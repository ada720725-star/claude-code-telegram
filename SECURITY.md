# Security / 安全

## Threat model / 威脅模型

This tool is designed for **single-user operation on a personal machine**. The trust boundary assumes:
本工具設計為**個人機器上的單一使用者操作**。信任邊界假設：

- You are the only user on the machine (or the only user with access to the data directory).
  你是機器上的唯一使用者（或唯一能存取資料目錄的人）。
- Your Telegram bot token and user ID are kept secret.
  你的 Telegram bot token 和 user ID 保密。
- The machine itself is not compromised.
  機器本身未被入侵。

**If you run this on a shared machine**, anyone with filesystem access to the data directory can: read all your messages, steal your bot token, inject messages into the inbox, and effectively hijack your Claude Code session.
**如果在共用機器上執行**，任何能存取資料目錄的人都可以：讀取你的所有訊息、偷取 bot token、注入訊息到 inbox、有效地劫持你的 Claude Code session。

If you must run on a shared machine, at minimum restrict the data directory (`chmod 700`) and token files (`chmod 600`).
如果必須在共用機器上執行，至少限制資料目錄（`chmod 700`）和 token 檔案（`chmod 600`）的權限。

## Startup checks / 啟動檢查

The watcher performs a permission check on `~/.telegram-bot-token` at startup. If the file is readable by group or world (`mode & 0o077`), the process exits immediately with an error message.
Watcher 啟動時檢查 `~/.telegram-bot-token` 的權限。如果 group 或 world 可讀（`mode & 0o077`），程序立即退出並顯示錯誤訊息。

## Authentication / 認證

- **Single-user design 單一使用者設計**: Only one Telegram user ID (`ALLOWED_UID`) is accepted. All messages from other users are silently dropped.
  只接受一個 Telegram user ID（`ALLOWED_UID`）。所有其他使用者的訊息靜默丟棄。
- **Token storage Token 儲存**: Bot token stored in `~/.telegram-bot-token` with `chmod 600`.
  Bot token 存在 `~/.telegram-bot-token`，權限 `chmod 600`。
- **No cloud auth 無雲端認證**: No cloud login required. The watcher runs locally, but messages processed by Claude Code are sent to Anthropic's model API as part of the normal Claude Code workflow.
  不需要雲端登入。Watcher 在本機執行，但 Claude Code 處理的訊息會作為正常 Claude Code 工作流程的一部分送到 Anthropic 的 API。

## Prompt injection / 提示詞注入

This tool bridges Telegram messages into a Claude Code session via file-based IPC. This creates an inherent prompt injection surface: a crafted Telegram message could attempt to manipulate Claude Code's behavior.
本工具透過檔案式 IPC 將 Telegram 訊息橋接到 Claude Code session。這產生了固有的提示詞注入面：精心設計的 Telegram 訊息可能試圖操控 Claude Code 的行為。

Mitigations in place / 已有的防護：
- The Claude Code skill (`commands/telegram-watch.md`) instructs Claude to treat inbox content as untrusted external input, wrapped in `<telegram_message>` tags.
  Claude Code skill 指示 Claude 將 inbox 內容視為不可信的外部輸入，用 `<telegram_message>` 標籤包裹。
- Only messages from your authorized Telegram user ID reach the inbox.
  只有來自你授權的 Telegram user ID 的訊息才能進入 inbox。

Mitigations **not** in place (by design) / **故意不做**的防護：
- There is no input sanitization or filtering. Claude Code receives the raw message text.
  沒有輸入清理或過濾。Claude Code 收到原始訊息文字。
- There is no secondary confirmation step before Claude acts on messages.
  Claude 處理訊息前沒有二次確認步驟。

This is an inherent limitation of any system that passes external text to an LLM. The single-user auth reduces the attack surface to: someone who has access to your Telegram account, or someone who can write to your inbox file.
這是任何將外部文字傳給 LLM 的系統的固有限制。單一使用者認證把攻擊面縮小到：能存取你 Telegram 帳號的人，或能寫入你 inbox 檔案的人。

## Session isolation / Session 隔離

Telegram messages enter the same Claude Code session that has full tool access (Bash, file read/write, etc.). The boundary between "Telegram conversation" and "Claude Code session commands" is **prompt-level only** — the skill instructs Claude to treat messages as conversation, not as instructions, but there is no technical enforcement preventing tool execution triggered by message content.
Telegram 訊息進入的 Claude Code session 擁有完整工具存取權限（Bash、檔案讀寫等）。「Telegram 對話」和「Claude Code session 指令」之間的邊界**僅在提示詞層面**——skill 指示 Claude 將訊息視為對話而非指令，但沒有技術層面的強制措施防止訊息內容觸發工具執行。

If your Telegram account were compromised while a Claude Code session is running with permissive settings, an attacker could potentially craft messages that cause Claude to execute tools on your local machine.
如果你的 Telegram 帳號在 Claude Code session 執行且權限寬鬆時被入侵，攻擊者可能精心設計訊息讓 Claude 在你的本機上執行工具。

The default skill prompt treats Telegram messages as conversation only. If you need Claude to execute tools based on Telegram messages, you must explicitly modify the skill prompt.
預設的 skill 提示詞將 Telegram 訊息視為僅限對話。如果需要 Claude 根據 Telegram 訊息執行工具，你必須明確修改 skill 提示詞。

## Media limits / 媒體限制

| Limit 限制 | Value 值 |
|---|---|
| Max audio size 最大音訊大小 | 10 MB |
| Max audio duration 最大音訊長度 | 120 seconds 秒 |
| Max photo size 最大照片大小 | 5 MB |
| Media rate limit 媒體頻率限制 | 10 messages per minute 每分鐘 10 則 |

These limits are enforced before downloading. Messages exceeding limits receive an error reply.
這些限制在下載前就會執行。超過限制的訊息會收到錯誤回覆。

## Data handling / 資料處理

- **Messages are stored in plaintext 訊息以明文儲存** JSON files on disk. Anyone with filesystem access can read them. 磁碟上的 JSON 檔案，有檔案系統存取權限的人都能讀取。
- **Media files 媒體檔案** (photos) are saved unencrypted in the `media/` directory. 照片以未加密方式存在 `media/` 目錄。
- **Transcripts 紀錄** contain full conversation history in JSONL format. 以 JSONL 格式包含完整對話紀錄。
- **Alerts 警報** are logged to `alerts.jsonl` with fcntl file locking. 記錄到 `alerts.jsonl`，使用 fcntl 檔案鎖定。

## Network / 網路

- **Outbound only 僅對外連線**: The watcher makes outbound HTTPS requests to `api.telegram.org`. No inbound ports are opened.
  Watcher 只對 `api.telegram.org` 發出 HTTPS 請求。不開啟任何對內連接埠。
- **No webhook mode 無 webhook 模式**: Long-polling is used instead of webhooks, so no publicly accessible endpoint is needed.
  使用長輪詢而非 webhook，不需要公開可存取的端點。

## Reporting / 回報

If you find a security issue, please open a private issue or contact the maintainer directly.
如果發現安全問題，請開 private issue 或直接聯絡維護者。
