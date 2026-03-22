#!/usr/bin/env python3
"""Telegram watcher for Claude Code.

Polls Telegram for messages, writes them to an inbox file for Claude Code
to read and respond via the companion skill. Sends replies from outbox back
to Telegram. Supports voice (mlx-whisper) and photo messages.

Configuration (environment variables):
    TELEGRAM_BOT_TOKEN      Bot token (or path in TELEGRAM_TOKEN_FILE)
    TELEGRAM_ALLOWED_USER   Allowed user ID (or path in TELEGRAM_USER_FILE)
    TELEGRAM_DATA_DIR       Base directory for data files (default: ./data)
    TELEGRAM_WHISPER_MODEL  HuggingFace model for voice transcription
    TELEGRAM_WHISPER_LANG   Language for voice transcription (default: auto-detect)
    TELEGRAM_NUDGE_CMD      Optional shell command to run when new message arrives
    TELEGRAM_DEBOUNCE_SECS  Seconds to wait for more messages before nudging (default: 2)
    TELEGRAM_TOKEN_FILE     File containing bot token (default: ~/.telegram-bot-token)
    TELEGRAM_USER_FILE      File containing user ID (default: ~/.telegram-user-id)
"""
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _read_file_stripped(path):
    try:
        with open(os.path.expanduser(path)) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _get_token():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if token:
        return token
    path = os.environ.get('TELEGRAM_TOKEN_FILE', '~/.telegram-bot-token')
    token = _read_file_stripped(path)
    if not token:
        print(f"Error: set TELEGRAM_BOT_TOKEN or create {path}", file=sys.stderr)
        sys.exit(1)
    return token


def _get_allowed_user():
    uid = os.environ.get('TELEGRAM_ALLOWED_USER')
    if uid:
        return int(uid)
    path = os.environ.get('TELEGRAM_USER_FILE', '~/.telegram-user-id')
    uid = _read_file_stripped(path)
    if not uid:
        print(f"Error: set TELEGRAM_ALLOWED_USER or create {path}", file=sys.stderr)
        sys.exit(1)
    return int(uid)


TOKEN = _get_token()
ALLOWED_UID = _get_allowed_user()

DATA_DIR = os.environ.get('TELEGRAM_DATA_DIR', os.path.join(os.getcwd(), 'data'))
INBOX = os.path.join(DATA_DIR, 'telegram_inbox.json')
INBOX_TMP = os.path.join(DATA_DIR, 'telegram_inbox.tmp.json')
OUTBOX = os.path.join(DATA_DIR, 'telegram_outbox.json')
OFFSET_FILE = os.path.join(DATA_DIR, 'telegram_offset')
TRANSCRIPT_DIR = os.path.join(DATA_DIR, 'telegram_transcripts')
MEDIA_DIR = os.path.join(DATA_DIR, 'media')
CONVERSATION_FILE = os.path.join(DATA_DIR, 'telegram_conversation.json')
WHISPER_MODEL = os.environ.get('TELEGRAM_WHISPER_MODEL', 'mlx-community/whisper-small')
WHISPER_LANG = os.environ.get('TELEGRAM_WHISPER_LANG')  # None = auto-detect
NUDGE_CMD = os.environ.get('TELEGRAM_NUDGE_CMD')
DEBOUNCE_SECS = float(os.environ.get('TELEGRAM_DEBOUNCE_SECS', '2'))
BRAKE_FILE = os.path.join(DATA_DIR, 'BRAKE.flag')
CONVERSATION_MAX_MESSAGES = 100

# ---------------------------------------------------------------------------
# Security limits (media size, rate, token permissions)
# ---------------------------------------------------------------------------

MAX_AUDIO_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_PHOTO_SIZE = 5 * 1024 * 1024    # 5 MB
MAX_AUDIO_DURATION = 120            # seconds
MEDIA_RATE_LIMIT = 10               # max media messages per minute
ALLOWED_AUDIO_MIME = {'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/x-wav', 'audio/wav'}
_media_timestamps: list[float] = []


def _check_token_file_permissions():
    """Refuse to start if token file is readable by group/world."""
    path = os.environ.get('TELEGRAM_TOKEN_FILE', '~/.telegram-bot-token')
    resolved = os.path.expanduser(path)
    if not os.path.exists(resolved):
        return  # using env var, no file to check
    mode = os.stat(resolved).st_mode & 0o777
    if mode & 0o077:
        print(
            f"FATAL: {resolved} has permissions {oct(mode)}. "
            f"Group/world can read your bot token. Run: chmod 600 {resolved}",
            file=sys.stderr,
        )
        sys.exit(1)


def _check_media_rate() -> bool:
    """Return False if media rate limit exceeded (per-minute window)."""
    now = time.time()
    _media_timestamps[:] = [t for t in _media_timestamps if now - t < 60]
    if len(_media_timestamps) >= MEDIA_RATE_LIMIT:
        return False
    _media_timestamps.append(now)
    return True


os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
os.makedirs(TRANSCRIPT_DIR, mode=0o700, exist_ok=True)
os.makedirs(MEDIA_DIR, mode=0o700, exist_ok=True)

# ---------------------------------------------------------------------------
# Whisper (lazy load)
# ---------------------------------------------------------------------------

_whisper = None
_whisper_checked = False

def _get_whisper():
    global _whisper, _whisper_checked
    if not _whisper_checked:
        _whisper_checked = True
        try:
            import mlx_whisper
            _whisper = mlx_whisper
            print("mlx-whisper loaded", flush=True)
        except ImportError:
            print("mlx-whisper not installed, voice messages disabled", file=sys.stderr)
    return _whisper


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

def _today_transcript_path():
    return os.path.join(TRANSCRIPT_DIR, f'telegram_{datetime.now():%Y-%m-%d}.jsonl')


def _write_transcript(role, text):
    entry = {
        "type": "message",
        "timestamp": datetime.now().isoformat(),
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}]
        },
        "source": "telegram"
    }
    with open(_today_transcript_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------------------
# Conversation history (with truncation)
# ---------------------------------------------------------------------------

def _truncate_conversation():
    """Keep only the most recent CONVERSATION_MAX_MESSAGES entries."""
    if not os.path.exists(CONVERSATION_FILE):
        return
    try:
        with open(CONVERSATION_FILE) as f:
            history = json.loads(f.read())
        if len(history) > CONVERSATION_MAX_MESSAGES:
            history = history[-CONVERSATION_MAX_MESSAGES:]
            with open(CONVERSATION_FILE, 'w') as f:
                json.dump(history, f, ensure_ascii=False)
    except Exception as e:
        print(f"Conversation truncation failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def api(method, data=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    try:
        if data:
            req = urllib.request.Request(url, json.dumps(data).encode(), {'Content-Type': 'application/json'})
        else:
            req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(str(e).replace(TOKEN, TOKEN[:8] + '...')) from None


def _download_file(file_id, dest_dir=None):
    """Download a Telegram file. Returns local path or None.

    If dest_dir is given, saves there with a stable name (for media).
    Otherwise uses a temp file (for voice transcription).
    """
    try:
        result = api('getFile', {'file_id': file_id})
    except Exception as e:
        print(f"getFile failed: {e}", file=sys.stderr)
        return None
    if not result or not result.get('ok'):
        return None
    file_path = result['result']['file_path']
    download_url = f'https://api.telegram.org/file/bot{TOKEN}/{file_path}'
    ext = os.path.splitext(file_path)[1] or '.ogg'

    if dest_dir:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_path = os.path.join(dest_dir, f'{ts}_{file_id[:8]}{ext}')
        try:
            resp = urllib.request.urlopen(download_url, timeout=30)
            with open(local_path, 'wb') as f:
                f.write(resp.read())
            return local_path
        except Exception as e:
            print(f"Download failed: {str(e).replace(TOKEN, TOKEN[:8] + '...')}", file=sys.stderr)
            return None
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            resp = urllib.request.urlopen(download_url, timeout=30)
            tmp.write(resp.read())
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"Download failed: {str(e).replace(TOKEN, TOKEN[:8] + '...')}", file=sys.stderr)
            tmp.close()
            os.unlink(tmp.name)
            return None


# ---------------------------------------------------------------------------
# Voice transcription
# ---------------------------------------------------------------------------

def _transcribe_voice(file_path):
    """Transcribe audio using mlx-whisper. Returns text or None."""
    whisper = _get_whisper()
    if not whisper:
        return None
    try:
        kwargs = {
            'path_or_hf_repo': WHISPER_MODEL,
        }
        if WHISPER_LANG:
            kwargs['language'] = WHISPER_LANG
        result = whisper.transcribe(file_path, **kwargs)
        text = result.get("text", "").strip()
        return text if text else None
    except Exception as e:
        print(f"Transcription failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Inbox (atomic write via rename)
# ---------------------------------------------------------------------------

def _write_inbox(text, chat_id, timestamp, message_id, media_path=None):
    """Write message to inbox for Claude Code to pick up.

    Uses atomic write (write to tmp, then rename) to prevent race conditions
    with the Claude Code skill that reads and deletes the inbox.
    """
    inbox = []
    if os.path.exists(INBOX):
        try:
            with open(INBOX) as f:
                inbox = json.loads(f.read())
        except Exception:
            inbox = []
    entry = {
        'text': text,
        'chat_id': chat_id,
        'timestamp': timestamp,
        'message_id': message_id,
    }
    if media_path:
        entry['media_path'] = media_path
    inbox.append(entry)

    # Atomic write: write to tmp file, then rename
    with open(INBOX_TMP, 'w') as f:
        json.dump(inbox, f, ensure_ascii=False)
    os.replace(INBOX_TMP, INBOX)

    print("NEW message received", flush=True)


# ---------------------------------------------------------------------------
# Nudge
# ---------------------------------------------------------------------------

def _nudge():
    """Run optional nudge command to wake up the Claude Code session."""
    if not NUDGE_CMD:
        return
    import subprocess
    try:
        subprocess.run(NUDGE_CMD, shell=True, timeout=5, capture_output=True)
        print("Nudge sent", flush=True)
    except Exception as e:
        print(f"Nudge failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Offset persistence
# ---------------------------------------------------------------------------

def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    return 0


def save_offset(o):
    with open(OFFSET_FILE, 'w') as f:
        f.write(str(o))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

STOP_WORDS = {'stop', '/stop'}

def main():
    _check_token_file_permissions()
    print(f"Telegram watcher started. Data dir: {DATA_DIR}", flush=True)
    offset = load_offset()
    _last_msg_time = 0.0  # timestamp of last received message
    _pending_nudge = False  # whether we have un-nudged messages

    # Truncate conversation history on startup
    _truncate_conversation()

    while True:
        try:
            # Debounce: nudge only after DEBOUNCE_SECS of silence
            if _pending_nudge and (time.time() - _last_msg_time) >= DEBOUNCE_SECS:
                _nudge()
                _pending_nudge = False
            # Send outbox replies (rename-then-process to avoid race with skill)
            if os.path.exists(OUTBOX):
                outbox_processing = OUTBOX + '.sending'
                try:
                    os.replace(OUTBOX, outbox_processing)
                    with open(outbox_processing) as f:
                        out = json.loads(f.read())
                    failed = []
                    for msg in out:
                        try:
                            api('sendMessage', {'chat_id': msg['chat_id'], 'text': msg['text']})
                            _write_transcript('assistant', msg['text'])
                        except Exception as e:
                            print(f"Send failed: {e}", file=sys.stderr)
                            failed.append(msg)
                    os.remove(outbox_processing)
                    if failed:
                        _outbox_tmp = OUTBOX + '.tmp'
                        with open(_outbox_tmp, 'w') as f:
                            json.dump(failed, f, ensure_ascii=False)
                        os.replace(_outbox_tmp, OUTBOX)
                        print(f"{len(failed)} message(s) failed, written back to outbox for retry", file=sys.stderr)
                    _truncate_conversation()
                except Exception as e:
                    print(f"Outbox error: {e}", file=sys.stderr)

            # Poll for new messages
            result = api('getUpdates', {'offset': offset, 'timeout': 20})
            if not result.get('ok'):
                time.sleep(2)
                continue

            for update in result.get('result', []):
                offset = update['update_id'] + 1
                save_offset(offset)

                msg = update.get('message')
                if not msg:
                    continue
                uid = msg.get('from', {}).get('id')
                if uid != ALLOWED_UID:
                    continue

                chat_id = msg['chat']['id']
                timestamp = msg.get('date', 0)
                message_id = msg.get('message_id', 0)

                # Voice
                voice = msg.get('voice') or msg.get('audio')
                if voice:
                    file_size = voice.get('file_size', 0)
                    duration = voice.get('duration', 0)
                    mime = voice.get('mime_type', '')
                    if file_size > MAX_AUDIO_SIZE:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Audio too large ({file_size // 1024 // 1024}MB > {MAX_AUDIO_SIZE // 1024 // 1024}MB)'})
                        continue
                    if duration > MAX_AUDIO_DURATION:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Audio too long ({duration}s > {MAX_AUDIO_DURATION}s)'})
                        continue
                    if mime and mime not in ALLOWED_AUDIO_MIME:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Unsupported audio format: {mime}'})
                        continue
                    if not _check_media_rate():
                        api('sendMessage', {'chat_id': chat_id, 'text': 'Too many media messages. Try again shortly.'})
                        continue
                    api('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
                    local_path = _download_file(voice['file_id'])
                    if local_path:
                        text = _transcribe_voice(local_path)
                        os.unlink(local_path)
                        if text:
                            text = f"[voice] {text}"
                            _write_transcript('user', text)
                            _write_inbox(text, chat_id, timestamp, message_id)
                            _last_msg_time = time.time()
                            _pending_nudge = True
                        else:
                            api('sendMessage', {'chat_id': chat_id, 'text': 'Voice transcription failed. Try again?'})
                    continue

                # Photo — save to media dir, pass path to Claude Code
                photo = msg.get('photo')
                if photo:
                    best = photo[-1]
                    file_size = best.get('file_size', 0)
                    if file_size > MAX_PHOTO_SIZE:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Photo too large ({file_size // 1024 // 1024}MB > {MAX_PHOTO_SIZE // 1024 // 1024}MB)'})
                        continue
                    if not _check_media_rate():
                        api('sendMessage', {'chat_id': chat_id, 'text': 'Too many media messages. Try again shortly.'})
                        continue
                    api('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
                    local_path = _download_file(best['file_id'], dest_dir=MEDIA_DIR)
                    if local_path:
                        caption = msg.get('caption', '') or ''
                        text = f"[photo] {caption}".strip() if caption else "[photo]"
                        _write_transcript('user', text)
                        _write_inbox(text, chat_id, timestamp, message_id, media_path=local_path)
                        _last_msg_time = time.time()
                        _pending_nudge = True
                    continue

                # Text
                text = msg.get('text', '').strip()
                if not text:
                    continue

                # Brake
                if text.lower() in STOP_WORDS:
                    _write_transcript('user', f'[brake] {text}')
                    open(BRAKE_FILE, 'w').close()
                    api('sendMessage', {'chat_id': chat_id, 'text': 'Stopped.'})
                    continue

                api('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
                _write_transcript('user', text)
                _write_inbox(text, chat_id, timestamp, message_id)
                _last_msg_time = time.time()
                _pending_nudge = True

        except Exception as e:
            print(f"Poll error: {e}", file=sys.stderr)
            time.sleep(5)

        time.sleep(0.3)


if __name__ == '__main__':
    main()
