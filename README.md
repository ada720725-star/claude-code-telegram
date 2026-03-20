# claude-code-telegram

> **Security notice**: This is a personal tool designed for single-user use on a private machine. If you run it on a shared system, other users with filesystem access can read your messages, tokens, and session data. See [SECURITY.md](SECURITY.md) for the full threat model.

Async Telegram integration for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Message Claude from your phone, get replies from your running Claude Code session.

## How it works

```
You (Telegram) → telegram_watcher.py → inbox.json → Claude Code skill → outbox.json → telegram_watcher.py → You (Telegram)
```

Two components:

1. **`telegram_watcher.py`** — Long-polling bot that receives your Telegram messages and writes them to an inbox file. Picks up replies from an outbox file and sends them back.
2. **`commands/telegram-watch.md`** — Claude Code [custom slash command](https://docs.anthropic.com/en/docs/claude-code/slash-commands) that reads the inbox, replies using the full session context, and writes to the outbox.

Claude Code responds as itself — with full conversation context, memory, and tools. This is not a proxy to the API; it's your running session replying directly.

## Features

- Text, voice (mlx-whisper), and photo messages
- Photos saved locally and passed to Claude Code for visual understanding
- JSONL transcripts per day
- Conversation history with automatic truncation (keeps last 100 messages)
- Atomic file writes to prevent race conditions
- Brake command (`stop` / `/stop`) — creates a flag file to signal other processes
- Optional nudge command to wake up the Claude Code session
- Zero required dependencies (Python stdlib only)

## How it compares to Claude Code Channels

[Claude Code Channels](https://code.claude.com/docs/en/channels) (March 2026) is Anthropic's official Telegram/Discord integration built on MCP. Both solve the same problem — messaging Claude from your phone — but with fundamentally different approaches.

### Feature comparison

| | This project | Claude Code Channels |
|---|---|---|
| **Architecture** | Independent Python script + Claude Code skill, file-based IPC (inbox/outbox JSON) | MCP server as subprocess, direct notification injection into session |
| **Setup** | Clone repo + set env vars + run script | `/plugin install telegram` one-liner |
| **Latency** | 10–20s (file polling) | < 1s (MCP notification) |
| **Voice messages** | Built-in mlx-whisper, on-device transcription | Not available |
| **Photo handling** | Saved locally, Claude reads via Read tool | Discord attachments only, Telegram unclear |
| **Identity** | Fully customizable — edit the skill prompt to define who Claude is | Standard Claude, no identity layer |
| **Memory** | conversation.json + daily transcripts persist across sessions | Session-only — close the session, lose the context |
| **Offline buffering** | Messages wait in inbox until session picks them up | Events only arrive while session is open |
| **Quota usage** | You control when to process — batch messages, reply on your schedule | Every incoming message consumes quota immediately |
| **Platforms** | Telegram | Telegram + Discord (community can extend via MCP) |
| **Dependencies** | Python stdlib only | Claude Code v2.1.80+, claude.ai login, MCP plugin system |

### Where this project wins

- **Memory continuity** — Channels lose context when the session closes. This project keeps conversation history and daily transcripts across sessions.
- **Customizable identity** — The skill prompt is yours. Claude responds as whoever you've configured — a named persona, a domain expert, or just "you but with a specific tone."
- **Voice transcription** — On-device speech-to-text via mlx-whisper (Apple Silicon). Channels doesn't offer this.
- **Offline buffering** — Messages are stored in the inbox file until Claude Code is ready. Channels require an active session or messages are lost.
- **Quota efficiency** — You decide when to check and respond. Batch 10 messages and reply once, or check every 30 seconds. Channels process every message immediately, burning through Pro/Max quota faster.
- **Zero dependencies** — Pure Python stdlib. No plugin system, no minimum version requirement, no cloud login needed.

### Where Channels wins

- **Instant delivery** — MCP notification injection is near-instant. Our file-based polling has 10–20s latency.
- **Deeper integration** — Direct session injection means Claude has full tool access without file-based intermediation.
- **One-line setup** — `/plugin install telegram` vs. cloning a repo and configuring env vars.
- **Multi-platform** — Discord support and community-extensible via MCP standard.
- **Rich interactions** — Discord supports edits, reactions, and history retrieval.

### Different problems, different solutions

**Channels** = "I want to run Claude Code commands from my phone." The session is the center, Telegram is a remote input device.

**This project** = "I want an async communication channel with a Claude that remembers me." Identity and memory are the center, Telegram is the interface.

If you need instant code execution from your phone, use Channels. If you want a persistent, personalized AI assistant you can text anytime — as long as the watcher and Claude Code session are running on your machine — this project is for you.

### Quota impact for subscribers

| Plan | Channels cost | This project cost |
|---|---|---|
| Pro ($20/mo) | Every TG message = one interaction, quota runs out fast | You control frequency — batch replies save quota |
| Max $100/mo | 5x Pro quota, moderate usage OK | Same flexibility, lasts longer |
| Max $200/mo | 20x Pro + Opus, best fit for Channels | Overkill for this project's pattern |
| API key | Pay per token ($5/$25 per M for Opus) | Same — only the skill reply step costs tokens |

## Setup

### 1. Create a Telegram bot

Talk to [@BotFather](https://t.me/BotFather), create a bot, get the token.

### 2. Get your Telegram user ID

Send a message to your bot, then:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | python3 -m json.tool
```

Look for `message.from.id` — that's your user ID.

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your token and user ID
```

Or use files:

```bash
echo "your-bot-token" > ~/.telegram-bot-token && chmod 600 ~/.telegram-bot-token
echo "123456789" > ~/.telegram-user-id && chmod 600 ~/.telegram-user-id
```

### 4. Install the Claude Code skill

Copy the skill to your Claude Code commands directory:

```bash
cp commands/telegram-watch.md ~/.claude/commands/
```

### 5. Run

```bash
./run.sh
```

Or manually:

```bash
export $(grep -v '^#' .env | xargs)
python3 telegram_watcher.py
```

### 6. Use

In your Claude Code session, run `/telegram-watch` to check for and reply to messages.

For continuous monitoring, use the `/loop` skill if available:

```
/loop 30s /telegram-watch
```

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes* | — | Bot token from BotFather |
| `TELEGRAM_ALLOWED_USER` | Yes* | — | Your Telegram user ID |
| `TELEGRAM_DATA_DIR` | No | `./data` | Directory for all data files |
| `TELEGRAM_WHISPER_MODEL` | No | `mlx-community/whisper-small` | HuggingFace model for voice |
| `TELEGRAM_WHISPER_LANG` | No | auto-detect | Language code (en, zh, ja, etc.) |
| `TELEGRAM_NUDGE_CMD` | No | — | Shell command on new message |
| `TELEGRAM_DEBOUNCE_SECS` | No | `2` | Seconds to wait for more messages before nudging |
| `TELEGRAM_TOKEN_FILE` | No | `~/.telegram-bot-token` | File containing bot token |
| `TELEGRAM_USER_FILE` | No | `~/.telegram-user-id` | File containing user ID |

*Can use env var or file-based config.

## Data files

All stored in `$TELEGRAM_DATA_DIR` (default: `./data`):

```
data/
├── telegram_inbox.json          # Pending messages for Claude Code
├── telegram_outbox.json         # Replies waiting to be sent
├── telegram_offset              # Telegram update offset
├── telegram_conversation.json   # Conversation history (auto-truncated)
├── telegram_transcripts/        # Daily JSONL transcripts
│   └── telegram_YYYY-MM-DD.jsonl
├── media/                       # Downloaded photos
└── BRAKE.flag                   # Created on stop command
```

## Security

- **Single-user only** — Only your Telegram user ID is accepted. All other messages are silently dropped. No group chat support by design.
- **No inbound ports** — Long-polling only. No webhook, no publicly accessible endpoint.
- **No cloud login** — Unlike Channels, no claude.ai login required. Your bot token stays on your machine. Messages are sent to Telegram's API and, when processed by Claude Code, to Anthropic's API.
- **Local storage** — Messages, transcripts, and media are stored as plaintext JSON/files on disk. Protect your data directory accordingly.
- **Nudge command** — `TELEGRAM_NUDGE_CMD` uses `shell=True`. Only set this to commands you trust.
- **Session isolation** — By default, the skill treats Telegram messages as conversation only: no file writes, no tool execution, no system commands. If you need tool access from Telegram, you must explicitly modify `commands/telegram-watch.md`. See [SECURITY.md](SECURITY.md) for details on this architectural boundary.

See [SECURITY.md](SECURITY.md) for full details.

## Architecture notes

- **Atomic writes**: Inbox uses write-to-tmp-then-rename to prevent data loss when the watcher and Claude Code skill access the file concurrently. Outbox uses rename-then-process for the same reason.
- **Conversation truncation**: History is automatically trimmed to the last 100 messages on startup and after each reply cycle. Full history is preserved in daily transcript files.
- **Photo handling**: Images are saved to `data/media/` and their paths are included in inbox messages. Claude Code can read these files directly for visual understanding.
- **Voice language**: By default, whisper auto-detects the spoken language. Set `TELEGRAM_WHISPER_LANG` to force a specific language for better accuracy.

## License

MIT
