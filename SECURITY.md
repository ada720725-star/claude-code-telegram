# Security

## Authentication

- **Single-user design**: Only one Telegram user ID is allowed. All messages from other users are silently dropped.
- **Token storage**: Bot tokens can be stored in environment variables or files. If using files, ensure restrictive permissions (`chmod 600`).
- **No cloud auth**: Unlike Claude Code Channels, this project requires no cloud login. Everything runs locally.

## Data handling

- **Messages are stored in plaintext** JSON files on disk. Anyone with filesystem access can read them.
- **Media files** (photos) are saved unencrypted in the `data/media/` directory.
- **Transcripts** contain full conversation history in JSONL format.
- **Recommendation**: If your machine has multiple users, restrict the data directory permissions.

## Network

- **Outbound only**: The watcher makes outbound HTTPS requests to `api.telegram.org`. No inbound ports are opened.
- **No webhook mode**: Long-polling is used instead of webhooks, so no publicly accessible endpoint is needed.

## Nudge command

- `TELEGRAM_NUDGE_CMD` runs via `subprocess.run(cmd, shell=True)`. This is a user-configured environment variable — only set it to commands you trust. Do not set this from untrusted input.

## Reporting

If you find a security issue, please open a private issue or contact the maintainer directly.
