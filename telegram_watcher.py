#!/usr/bin/env python3
"""Telegram watcher：收訊息 → 寫 inbox → nudge CLI → 讀 outbox → 發回去。
支援語音（mlx-whisper）和圖片。"""
import json, os, time, tempfile, urllib.request, urllib.error, sys, threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ALERTS_PATH = os.path.expanduser('~/claude-memory/status/alerts.jsonl')


def _write_tg_alert(severity, message):
    """寫一行到 alerts.jsonl。TG watcher 錯誤時呼叫。"""
    import fcntl
    entry = {
        'ts': datetime.now().isoformat(),
        'module': 'telegram_watcher',
        'severity': severity,
        'category': 'watcher_error',
        'message': message,
        'consumed': False,
        'consumed_at': None,
    }
    try:
        os.makedirs(os.path.dirname(_ALERTS_PATH), exist_ok=True)
        _lock = _ALERTS_PATH + '.lock'
        _lfd = open(_lock, 'w')
        try:
            fcntl.flock(_lfd, fcntl.LOCK_EX)
            with open(_ALERTS_PATH, 'a', encoding='utf-8') as _f:
                _f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        finally:
            fcntl.flock(_lfd, fcntl.LOCK_UN)
            _lfd.close()
    except Exception as _e:
        print(f'[tg_watcher] alert write failed: {_e}', file=sys.stderr)


TOKEN = open(os.path.expanduser('~/.telegram-bot-token')).read().strip()
ALLOWED_UID = int(open(os.path.expanduser('~/.telegram-user-id')).read().strip())
BASE = os.path.expanduser('~/claude-memory')
INBOX = os.path.expanduser('~/claude-memory/telegram_inbox.json')
OUTBOX = os.path.expanduser('~/claude-memory/telegram_outbox.json')
OFFSET_FILE = os.path.expanduser('~/claude-memory/telegram_offset')
TRANSCRIPT_DIR = os.path.expanduser('~/claude-memory/telegram_transcripts')
TG_RECENT = os.path.expanduser('~/claude-memory/tg_recent.json')
MEDIA_DIR = os.path.expanduser('~/claude-memory/media')
WHISPER_MODEL = "mlx-community/whisper-small"

# Security limits
MAX_AUDIO_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_PHOTO_SIZE = 5 * 1024 * 1024    # 5 MB
MAX_AUDIO_DURATION = 120            # seconds
MEDIA_RATE_LIMIT = 10               # max media messages per minute
ALLOWED_AUDIO_MIME = {'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/x-wav', 'audio/wav'}
_media_timestamps: list[float] = []

os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, 0o700, exist_ok=True)


def _check_token_file_permissions():
    """Refuse to start if token file is readable by group/world."""
    path = os.path.expanduser('~/.telegram-bot-token')
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode & 0o777
    if mode & 0o077:
        print(
            f"FATAL: {path} has permissions {oct(mode)}. "
            f"Group/world can read your bot token. Run: chmod 600 {path}",
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

_whisper = None

def _get_whisper():
    global _whisper
    if _whisper is None:
        try:
            import mlx_whisper
            _whisper = mlx_whisper
            print("mlx-whisper loaded", flush=True)
        except ImportError:
            print("mlx-whisper not installed, voice disabled", file=sys.stderr)
    return _whisper


def _today_transcript_path():
    today = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(TRANSCRIPT_DIR, f'telegram_{today}.jsonl')


def _write_transcript(role, text):
    entry = {
        "type": "message",
        "timestamp": datetime.now().isoformat(),
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
        "source": "telegram"
    }
    with open(_today_transcript_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    # ring buffer：最近 6 則
    try:
        recent = []
        if os.path.exists(TG_RECENT):
            recent = json.loads(open(TG_RECENT).read())
        recent.append({"role": role, "text": text, "ts": entry["timestamp"]})
        recent = recent[-6:]
        with open(TG_RECENT, 'w') as f:
            json.dump(recent, f, ensure_ascii=False)
    except Exception:
        pass


def api(method, data=None):
    url = f'https://api.telegram.org/bot{TOKEN}/{method}'
    if data:
        req = urllib.request.Request(url, json.dumps(data).encode(), {'Content-Type': 'application/json'})
    else:
        req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def _download_file(file_id, dest_dir=None):
    """Download a Telegram file. Returns local path or None.

    If dest_dir is given, saves there with a stable name (for media).
    Otherwise uses a temp file (for voice transcription).
    """
    result = api('getFile', {'file_id': file_id})
    if not result or not result.get('ok'):
        return None
    file_path = result['result']['file_path']
    url = f'https://api.telegram.org/file/bot{TOKEN}/{file_path}'
    ext = os.path.splitext(file_path)[1] or '.ogg'

    if dest_dir:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_path = os.path.join(dest_dir, f'{ts}_{file_id[:8]}{ext}')
        try:
            resp = urllib.request.urlopen(url, timeout=30)
            with open(local_path, 'wb') as f:
                f.write(resp.read())
            return local_path
        except Exception as e:
            print(f"download failed: {e}", file=sys.stderr)
            return None
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            resp = urllib.request.urlopen(url, timeout=30)
            tmp.write(resp.read())
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"download failed: {e}", file=sys.stderr)
            tmp.close()
            os.unlink(tmp.name)
            return None


def _transcribe_voice(file_path):
    whisper = _get_whisper()
    if not whisper:
        return None
    try:
        result = whisper.transcribe(file_path, path_or_hf_repo=WHISPER_MODEL, language="zh")
        text = result.get("text", "").strip()
        return text if text else None
    except Exception as e:
        print(f"transcribe failed: {e}", file=sys.stderr)
        return None


_last_nudge_time = 0
NUDGE_COOLDOWN = 10  # 秒：10 秒內只打一次 nudge

def _nudge_cli(text="0"):
    """osascript do script 送文字。長文字（>512 bytes）補一次空 do script 確保 Enter 到達。"""
    global _last_nudge_time
    import subprocess
    now = time.time()
    if now - _last_nudge_time < NUDGE_COOLDOWN:
        print(f"CLI nudge skipped (cooldown {int(NUDGE_COOLDOWN - (now - _last_nudge_time))}s)", flush=True)
        return
    try:
        escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        text_bytes = len(escaped.encode('utf-8'))
        # 長文字：先送文字，delay 後補 Enter
        if text_bytes > 512:
            script = f'''
            tell application "Terminal"
                if it is running then
                    repeat with w in every window
                        try
                            if name of w contains "claude" then
                                do script "{escaped}" in w
                                delay 1
                                do script "" in w
                                return "ok-long:" & (id of w as text)
                            end if
                        end try
                    end repeat
                    return "no claude window"
                end if
            end tell
            '''
        else:
            script = f'''
            tell application "Terminal"
                if it is running then
                    repeat with w in every window
                        try
                            if name of w contains "claude" then
                                do script "{escaped}" in w
                                return "ok:" & (id of w as text)
                            end if
                        end try
                    end repeat
                    return "no claude window"
                end if
            end tell
            '''
        result = subprocess.run(['osascript', '-e', script], timeout=10, capture_output=True, text=True)
        _last_nudge_time = now
        print(f"CLI nudge sent [{text[:40]}] ({text_bytes}B) -> {result.stdout.strip()}", flush=True)
    except Exception as e:
        print(f"CLI nudge failed: {e}", file=sys.stderr)


CHAT_INBOX = os.path.expanduser('~/claude-memory/chat/chat_inbox.json')


def _notify_chat(text, chat_id):
    """把 TG 訊息寫進聊天室 inbox，讓衡從聊天室統一收。"""
    try:
        existing = []
        if os.path.exists(CHAT_INBOX):
            try:
                existing = json.loads(open(CHAT_INBOX).read())
            except Exception:
                existing = []
        existing.append({
            'sender': '坤達',
            'content': f'[TG] {text}',
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'received_at': time.time(),
            'source': 'telegram',
            'chat_id': chat_id
        })
        with open(CHAT_INBOX, 'w') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"chat_inbox notify failed: {e}", file=sys.stderr)


def _restart_claude():
    """10 秒後重啟 Claude Code（工程模式，繞過選單）。"""
    import subprocess
    print("EXIT: waiting 10s before restart...", flush=True)
    time.sleep(10)

    settings_path = os.path.expanduser("~/.claude/settings.local.json")
    try:
        with open(settings_path) as f:
            d = json.load(f)
        d.pop('outputStyle', None)
        with open(settings_path, 'w') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"EXIT: settings update failed: {e}", flush=True)

    print("EXIT: restarting claude (工程模式)...", flush=True)
    script = '''
    tell application "Terminal"
        do script "cd ~ && command claude" in front window
    end tell
    '''
    subprocess.run(['osascript', '-e', script], timeout=10)
    print("EXIT: claude restarted", flush=True)


def _write_inbox(text, chat_id, timestamp, message_id, media_path=None):
    clean = text.strip().lstrip('/').upper()
    if clean == 'EXIT':
        _nudge_cli("/exit")
        threading.Thread(target=_restart_claude, daemon=True).start()
        return
    inbox = []
    if os.path.exists(INBOX):
        try:
            inbox = json.loads(open(INBOX).read())
        except Exception:
            inbox = []
    entry = {'text': text, 'chat_id': chat_id, 'timestamp': timestamp, 'message_id': message_id}
    if media_path:
        entry['media_path'] = media_path
    inbox.append(entry)
    with open(INBOX, 'w') as f:
        json.dump(inbox, f, ensure_ascii=False)
    print(f"NEW: {text[:60]}", flush=True)
    # _notify_chat(text, chat_id)  # 2026-04-03 停用：TG 跟聊天室是獨立通道，不轉發
    _nudge_cli(text)


def load_offset():
    if os.path.exists(OFFSET_FILE):
        return int(open(OFFSET_FILE).read().strip())
    return 0


def save_offset(o):
    with open(OFFSET_FILE, 'w') as f:
        f.write(str(o))


def main():
    offset = load_offset()
    while True:
        try:
            # check outbox
            if os.path.exists(OUTBOX):
                try:
                    out = json.loads(open(OUTBOX).read())
                    if out:
                        if isinstance(out, dict):
                            out = [out]
                        for msg in out:
                            api('sendMessage', {'chat_id': msg['chat_id'], 'text': msg['text']})
                            _write_transcript('assistant', msg['text'])
                    os.remove(OUTBOX)
                except json.JSONDecodeError as e:
                    print(f"outbox corrupt, deleting: {e}", file=sys.stderr)
                    _write_tg_alert('WARNING', f'telegram_outbox 格式錯誤，已刪除：{e}')
                    os.remove(OUTBOX)
                except Exception as e:
                    print(f"outbox error: {e}", file=sys.stderr)
                    _write_tg_alert('WARNING', f'telegram_outbox 發送失敗：{e}')

            # poll new messages
            result = api('getUpdates', {'offset': offset, 'timeout': 1})
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

                # voice
                voice = msg.get('voice') or msg.get('audio')
                if voice:
                    file_size = voice.get('file_size', 0)
                    duration = voice.get('duration', 0)
                    if file_size > MAX_AUDIO_SIZE:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Audio too large ({file_size // 1024 // 1024}MB > {MAX_AUDIO_SIZE // 1024 // 1024}MB)'})
                        continue
                    if duration > MAX_AUDIO_DURATION:
                        api('sendMessage', {'chat_id': chat_id, 'text': f'Audio too long ({duration}s > {MAX_AUDIO_DURATION}s)'})
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
                        else:
                            api('sendMessage', {'chat_id': chat_id, 'text': 'Voice transcription failed'})
                    continue

                # photo -- save to media dir, pass path to CLI
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
                    continue

                # text
                text = msg.get('text', '').strip()
                if not text:
                    continue

                # brake
                if text.lower() in ('停止', 'stop', '停', '/stop'):
                    _write_transcript('user', f'[brake] {text}')
                    open(os.path.join(BASE, 'BRAKE.flag'), 'w').close()
                    api('sendMessage', {'chat_id': chat_id, 'text': 'Braked'})
                    continue

                api('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
                _write_transcript('user', text)
                _write_inbox(text, chat_id, timestamp, message_id)

        except Exception as e:
            print(f"poll error: {e}", file=sys.stderr)
            _write_tg_alert('WARNING', f'telegram_watcher poll 錯誤：{e}')
            time.sleep(5)

        time.sleep(0.3)


if __name__ == '__main__':
    _check_token_file_permissions()
    main()
