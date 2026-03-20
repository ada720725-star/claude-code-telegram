# Security

## Threat model

This tool is designed for **single-user operation on a personal machine**. The trust boundary assumes:

- You are the only user on the machine (or the only user with access to the data directory).
- Your Telegram bot token and user ID are kept secret.
- The machine itself is not compromised.

**If you run this on a shared machine**, anyone with filesystem access to the data directory can: read all your messages, steal your bot token, inject messages into the inbox, and effectively hijack your Claude Code session. If you must run on a shared machine, at minimum restrict the data directory (`chmod 700`) and token files (`chmod 600`).

## Authentication

- **Single-user design**: Only one Telegram user ID is allowed. All messages from other users are silently dropped.
- **Token storage**: Bot tokens can be stored in environment variables or files. If using files, ensure restrictive permissions (`chmod 600`).
- **No cloud auth**: Unlike Claude Code Channels, this project requires no cloud login. The watcher runs locally, but messages processed by Claude Code are sent to Anthropic's model API as part of the normal Claude Code workflow.

## Prompt injection

This tool bridges Telegram messages into a Claude Code session via file-based IPC. This creates an inherent prompt injection surface: a crafted Telegram message could attempt to manipulate Claude Code's behavior.

Mitigations in place:
- The Claude Code skill (`commands/telegram-watch.md`) instructs Claude to treat inbox content as untrusted external input, wrapped in `<telegram_message>` tags.
- Only messages from your authorized Telegram user ID reach the inbox.

Mitigations **not** in place (by design):
- There is no input sanitization or filtering. Claude Code receives the raw message text.
- There is no secondary confirmation step before Claude acts on messages.

This is an inherent limitation of any system that passes external text to an LLM. The single-user auth reduces the attack surface to: someone who has access to your Telegram account, or someone who can write to your inbox file.

## Data handling

- **Messages are stored in plaintext** JSON files on disk. Anyone with filesystem access can read them.
- **Media files** (photos) are saved unencrypted in the `data/media/` directory.
- **Transcripts** contain full conversation history in JSONL format.
- `run.sh` automatically sets `chmod 700` on the data directory at startup.

## Network

- **Outbound only**: The watcher makes outbound HTTPS requests to `api.telegram.org`. No inbound ports are opened.
- **No webhook mode**: Long-polling is used instead of webhooks, so no publicly accessible endpoint is needed.
- **Token masking**: Error messages redact the bot token to prevent accidental exposure in logs.

## Nudge command

- `TELEGRAM_NUDGE_CMD` runs via `subprocess.run(cmd, shell=True)`. This is intentional — the nudge command needs to support arbitrary shell expressions (pipes, redirects, etc.). Only set this to commands you trust. Do not set this from untrusted input.

## Reporting

If you find a security issue, please open a private issue or contact the maintainer directly.
