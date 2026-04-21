# claude-code-telegram

> **Security notice**: This is a personal tool designed for single-user use on a private machine. If you run it on a shared system, other users with filesystem access can read your messages, tokens, and session data. See [SECURITY.md](SECURITY.md) for the full threat model.
>
> **安全提醒**：這是為個人機器上的單一使用者設計的工具。如果在共用系統上執行，其他使用者可以讀取你的訊息、token 和 session 資料。詳見 [SECURITY.md](SECURITY.md)。

Async Telegram integration for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Message Claude from your phone, get replies from your running Claude Code session.

非同步的 Telegram 整合，用於 [Claude Code](https://docs.anthropic.com/en/docs/claude-code)。從手機傳訊息給 Claude，由正在執行的 Claude Code session 回覆你。

## How it works / 運作方式

```
You (Telegram) → telegram_watcher.py → inbox.json → Claude Code skill → outbox.json → telegram_watcher.py → You (Telegram)
你（Telegram）→ telegram_watcher.py → inbox.json → Claude Code skill → outbox.json → telegram_watcher.py → 你（Telegram）
```

Two components:
兩個元件：

1. **`telegram_watcher.py`** — Long-polling bot that receives your Telegram messages, writes them to an inbox file, and nudges Claude Code via `osascript do script`. Picks up replies from an outbox file and sends them back.
   長輪詢 bot，接收你的 Telegram 訊息，寫入 inbox 檔案，並透過 `osascript do script` 喚醒 Claude Code。從 outbox 檔案讀取回覆送回 Telegram。

2. **`commands/telegram-watch.md`** — Claude Code [custom slash command](https://docs.anthropic.com/en/docs/claude-code/slash-commands) that reads the inbox, replies using the full session context, and writes to the outbox.
   Claude Code [自訂斜線指令](https://docs.anthropic.com/en/docs/claude-code/slash-commands)，讀取 inbox，用完整的 session 上下文回覆，並寫入 outbox。

Claude Code responds as itself — with full conversation context, memory, and tools. This is not a proxy to the API; it's your running session replying directly.

Claude Code 用自身身份回覆——帶有完整的對話上下文、記憶和工具。這不是 API 代理，是你正在跑的 session 直接回覆。

## Features / 功能

- Text, voice (mlx-whisper on-device), and photo messages
  文字、語音（mlx-whisper 裝置端轉錄）和照片訊息
- EXIT command: `/exit` from Telegram triggers CLI exit + auto-restart Claude Code
  EXIT 指令：在 Telegram 打 `/exit`，觸發 CLI 退出並自動重啟 Claude Code
- BRAKE command: `stop` / `停止` creates a flag file to halt other processes
  煞車指令：`stop` / `停止` 建立 flag 檔案，停止其他程序
- Long text handling: dual `do script` with delay for texts > 512 bytes, prevents Enter key loss
  長文字處理：超過 512 bytes 的文字用兩次 `do script`，中間加延遲，防止 Enter 鍵遺失
- Nudge with cooldown (10s) to prevent spam
  Nudge 有冷卻（10 秒）防止重複觸發
- JSONL transcripts per day + recent message ring buffer (last 6)
  每日 JSONL 紀錄 + 最近訊息環形緩衝（最近 6 則）
- Alert system: errors written to `alerts.jsonl` with file locking
  警報系統：錯誤寫入 `alerts.jsonl`，帶檔案鎖定
- Photos saved locally and passed to Claude Code for visual understanding
  照片存在本機，傳給 Claude Code 做圖像理解
- Media rate limiting (10/min) and size limits (10MB audio, 5MB photo)
  媒體頻率限制（每分鐘 10 則）和大小限制（音訊 10MB、照片 5MB）
- Token file permission check: refuses to start if group/world readable
  Token 檔案權限檢查：如果 group/world 可讀，拒絕啟動
- Zero required dependencies (Python stdlib only; mlx-whisper optional for voice)
  零必要依賴（僅需 Python 標準函式庫；語音需選裝 mlx-whisper）

## How it compares to Claude Code Channels / 與 Claude Code Channels 比較

[Claude Code Channels](https://code.claude.com/docs/en/channels) (March 2026) is Anthropic's official Telegram/Discord integration built on MCP. Both solve the same problem — messaging Claude from your phone — but with fundamentally different approaches.

[Claude Code Channels](https://code.claude.com/docs/en/channels)（2026 年 3 月）是 Anthropic 官方基於 MCP 的 Telegram/Discord 整合。兩者解決同一個問題——從手機傳訊息給 Claude——但方法根本不同。

### Feature comparison / 功能比較

| | This project 本專案 | Claude Code Channels |
|---|---|---|
| **Architecture 架構** | Python script + skill, file-based IPC (inbox/outbox JSON) Python 腳本 + skill，檔案式 IPC | MCP server, direct session injection MCP 伺服器，直接注入 session |
| **Setup 設定** | Clone repo + configure + run 複製 repo + 設定 + 執行 | `/plugin install telegram` one-liner 一行指令 |
| **CLI control CLI 操控** | Direct Terminal injection via `do script` — restart session, brake, full text in CLI input 透過 `do script` 直接注入 Terminal——重啟 session、煞車、完整文字在 CLI 輸入中 | No CLI access, notification only 無法操控 CLI，僅通知 |
| **Latency 延遲** | Depends on nudge method 取決於 nudge 方式 | < 1s |
| **Voice 語音** | Built-in mlx-whisper, on-device 內建 mlx-whisper，裝置端執行 | Not available 無 |
| **Photo 照片** | Saved locally, Claude reads via Read tool 存本機，Claude 用 Read 工具讀 | Discord attachments only 僅 Discord 附件 |
| **Identity 身份** | Fully customizable skill prompt 可完全自訂 skill 提示詞 | Standard Claude 標準 Claude |
| **Memory 記憶** | conversation.json + daily transcripts persist across sessions 對話紀錄跨 session 保存 | Session-only 僅限單次 session |
| **Offline buffering 離線緩衝** | Messages wait in inbox until session picks them up 訊息在 inbox 等待直到 session 讀取 | Requires active session 需要活躍的 session |
| **Quota 用量** | You control when to process 你控制處理時機 | Every message consumes quota immediately 每則訊息立即消耗用量 |

### Where this project wins / 本專案優勢

- **Memory continuity 記憶延續** — Channels lose context when the session closes. This project keeps conversation history across sessions. Channels 關閉 session 就失去上下文。本專案跨 session 保存對話紀錄。
- **Customizable identity 可自訂身份** — The skill prompt is yours. Claude responds as whoever you've configured. Skill 提示詞由你定義。Claude 用你設定的身份回覆。
- **Voice transcription 語音轉錄** — On-device speech-to-text via mlx-whisper (Apple Silicon). 裝置端語音轉文字（Apple Silicon）。
- **Offline buffering 離線緩衝** — Messages stored until Claude Code is ready. 訊息會存著直到 Claude Code 準備好。
- **Direct CLI control 直接 CLI 操控** — Messages are injected directly into the Terminal running Claude Code via `osascript do script`. You can restart the session (`/exit`), brake all processes (`stop`), and see the full message text in CLI input. Channels can only send notifications — it cannot control the CLI or restart sessions. 訊息透過 `osascript do script` 直接注入正在執行 Claude Code 的 Terminal。你可以重啟 session（`/exit`）、煞停所有程序（`stop`），且完整訊息文字會出現在 CLI 輸入中。Channels 只能送通知——無法操控 CLI ��重啟 session。

### Where Channels wins / Channels 優勢

- **Instant delivery 即時送達** — MCP notification injection is near-instant. MCP 通知注入幾乎即時。
- **One-line setup 一行設定** — `/plugin install telegram` vs. cloning a repo. 安裝只要一行指令。
- **Multi-platform 多平台** — Discord support and community-extensible via MCP. 支援 Discord，可透過 MCP 擴充。

## Setup / 設定

### 1. Create a Telegram bot / 建立 Telegram bot

Talk to [@BotFather](https://t.me/BotFather), create a bot, get the token.
跟 [@BotFather](https://t.me/BotFather) 對話，建立 bot，取得 token。

### 2. Get your Telegram user ID / 取得你的 Telegram user ID

Send a message to your bot, then:
傳一則訊息給你的 bot，然後：

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | python3 -m json.tool
```

Look for `message.from.id` — that's your user ID.
找到 `message.from.id`——那就是你的 user ID。

### 3. Store credentials / 儲存憑證

```bash
echo "your-bot-token" > ~/.telegram-bot-token && chmod 600 ~/.telegram-bot-token
echo "123456789" > ~/.telegram-user-id && chmod 600 ~/.telegram-user-id
```

The watcher reads these files on startup. `chmod 600` ensures only you can read them.
Watcher 啟動時讀取這些檔案。`chmod 600` 確保只有你能讀取。

### 4. Configure paths / 設定路徑

Edit `telegram_watcher.py` and update the path constants near the top of the file:
編輯 `telegram_watcher.py`，修改檔案頂部的路徑常數：

```python
BASE = os.path.expanduser('~/claude-memory')          # your data directory / 你的資料目錄
INBOX = os.path.expanduser('~/claude-memory/telegram_inbox.json')
OUTBOX = os.path.expanduser('~/claude-memory/telegram_outbox.json')
# ... etc
```

Change `~/claude-memory` to wherever you want to store data.
把 `~/claude-memory` 改成你想存放資料的路徑。

### 5. Install the Claude Code skill / 安裝 Claude Code skill

Copy the skill to your Claude Code commands directory:
把 skill 複製到 Claude Code 的 commands 目錄：

```bash
cp commands/telegram-watch.md ~/.claude/commands/
```

### 6. Run as launchd service (recommended for macOS) / 用 launchd 執行（macOS 建議）

Create a LaunchAgent plist:
建立 LaunchAgent plist：

```bash
cat > ~/Library/LaunchAgents/com.yourname.telegram-watcher.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.telegram-watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-u</string>
        <string>/path/to/telegram_watcher.py</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/logs/watcher-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/logs/watcher-stderr.log</string>
</dict>
</plist>
EOF
```

Load it:
載入：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yourname.telegram-watcher.plist
```

This ensures the watcher auto-starts on login and auto-restarts on crash.
這確保 watcher 在登入時自動啟動，crash 時自動重啟。

Or run manually / 或手動執行：

```bash
python3 -u telegram_watcher.py
```

### 7. Use / 使用

In your Claude Code session, run `/telegram-watch` to check for and reply to messages.
在 Claude Code session 中，執行 `/telegram-watch` 檢查並回覆訊息。

For continuous monitoring, use the `/loop` skill:
持續監控用 `/loop` skill：

```
/loop 30s /telegram-watch
```

## Telegram commands / Telegram 指令

| Command 指令 | Behavior 行為 |
|---|---|
| `/exit`, `exit`, `EXIT`, `/EXIT` | Sends `/exit` to CLI, waits 10s, restarts Claude Code in engineering mode. 送 `/exit` 給 CLI，等 10 秒，以工程模式重啟 Claude Code。 |
| `stop`, `/stop`, `停止`, `停` | Creates `BRAKE.flag` in data dir, signals other processes to halt. 在資料目錄建立 `BRAKE.flag`，通知其他程序停止。 |

## Nudge mechanism / Nudge 機制

The watcher uses macOS `osascript do script` to inject the message text directly into the Terminal window running Claude Code. This allows Claude to see the full message in its input.

Watcher 用 macOS `osascript do script` 把訊息文字直接注入到正在執行 Claude Code 的 Terminal 視窗。這讓 Claude 能在輸入中看到完整訊息。

**Short text (≤ 512 bytes)** — Single `do script` call. The text + Enter key arrive together.
**短文字（≤ 512 bytes）**——單次 `do script`。文字和 Enter 鍵一起到達。

**Long text (> 512 bytes)** — Two `do script` calls with 1-second delay. First sends the text, second sends an empty string (which acts as a backup Enter). This works around macOS pty buffer limits that can cause the trailing `\n` to be lost on long inputs.
**長文字（> 512 bytes）**——兩次 `do script`，中間延遲 1 秒。第一次送文字，第二次送空字串（作為備用 Enter）。這繞過了 macOS pty 緩衝區限制，長輸入時尾巴的 `\n` 可能會遺失。

**Cooldown**: 10 seconds between nudges to prevent spam.
**冷卻**：nudge 之間間隔 10 秒，防止重複觸發。

**Window detection**: Iterates all Terminal windows, finds the one with "claude" in its name. Protected with `try/end try` for windows without a name attribute.
**視窗偵測**：遍歷所有 Terminal 視窗，找到名稱含 "claude" 的。用 `try/end try` 保護沒有 name 屬性的視窗。

## Data files / 資料檔案

```
data/
├── telegram_inbox.json          # Pending messages / 待處理訊息
├── telegram_outbox.json         # Replies to send / 待發送回覆
├── telegram_offset              # Telegram update offset / Telegram 更新偏移量
├── telegram_conversation.json   # Conversation history / 對話紀錄
├── tg_recent.json               # Ring buffer, last 6 messages / 環形緩衝，最近 6 則
├── telegram_transcripts/        # Daily JSONL transcripts / 每日 JSONL 紀錄
│   └── telegram_YYYY-MM-DD.jsonl
├── media/                       # Downloaded photos / 下載的照片
├── status/
│   └── alerts.jsonl             # Error alerts with timestamps / 錯誤警報（帶時間戳記）
└── BRAKE.flag                   # Created on stop command / 煞車指令時建立
```

## Security / 安全

- **Single-user only 僅限單一使用者** — Only your Telegram user ID is accepted. All other messages are silently dropped. 只接受你的 Telegram user ID，其他訊息靜默丟棄。
- **Token file permission check Token 檔案權限檢查** — Refuses to start if `~/.telegram-bot-token` is readable by group/world. 如果 token 檔案的 group/world 可讀，拒絕啟動。
- **No inbound ports 無對內連接埠** — Long-polling only. No webhook, no publicly accessible endpoint. 只用長輪詢，沒有 webhook，沒有對外端點。
- **Media limits 媒體限制** — Audio: 10MB / 120s max. Photo: 5MB max. Rate: 10 media messages per minute. 音訊：最大 10MB / 120 秒。照片：最大 5MB。頻率：每分鐘 10 則。
- **Alert logging 警報記錄** — Errors are logged to `alerts.jsonl` with `fcntl` file locking for concurrent safety. 錯誤記錄到 `alerts.jsonl`，用 `fcntl` 檔案鎖定保證並行安全。
- **Session isolation 隔離** — The skill treats Telegram messages as conversation only by default. See [SECURITY.md](SECURITY.md). Skill 預設將 Telegram 訊息視為對話，不執行指令。

See [SECURITY.md](SECURITY.md) for full details.
詳見 [SECURITY.md](SECURITY.md)。

## Architecture notes / 架構筆記

- **Nudge via `do script`**: Injects text directly into Terminal's Claude Code window. Long text uses dual `do script` with delay. Requires Terminal.app to be running (not necessarily frontmost).
  **透過 `do script` 的 Nudge**：直接注入文字到 Terminal 的 Claude Code 視窗。長文字用兩次 `do script` 加延遲。需要 Terminal.app 在執行中（不需要在最前面）。
- **EXIT restart**: `_restart_claude()` waits 10s, cleans `outputStyle` from settings, then runs `command claude` in Terminal's front window.
  **EXIT 重啟**：`_restart_claude()` 等 10 秒，清除 settings 中的 `outputStyle`，然後在 Terminal 前景視窗執行 `command claude`。
- **Alert system**: Watcher errors are written to `alerts.jsonl` with fcntl locking, consumable by other monitoring processes.
  **警報系統**：Watcher 錯誤寫入 `alerts.jsonl`，用 fcntl 鎖定，可被其他監控程序消費。
- **Ring buffer**: `tg_recent.json` keeps the last 6 messages for quick context without reading full transcripts.
  **環形緩衝**：`tg_recent.json` 保存最近 6 則訊息，不用讀完整 transcript 就能快速取得上下文。

## License / 授權

MIT
