---
description: "Telegram messaging: check inbox, reply, write to outbox. Polls every 30s, idles after 10 empty checks."
---

Data directory: use $TELEGRAM_DATA_DIR if set, otherwise ./data relative to this project root.

Check if <data_dir>/telegram_inbox.json exists and has content.

If there are messages:
1. **IMPORTANT**: First rename inbox to inbox.processing to prevent the watcher from overwriting it while you work:
   - Rename <data_dir>/telegram_inbox.json to <data_dir>/telegram_inbox.processing.json
   - Read from the .processing file, not the original
2. Read <data_dir>/telegram_conversation.json for conversation history. If it's large, only use the last 50 entries for context — do NOT read the entire file into your response
3. Reply as yourself, using the full context of your current session
4. If a message has a `media_path` field, use the Read tool on that path to see the image before replying
5. Write replies to <data_dir>/telegram_outbox.json, format: [{"chat_id": <from inbox>, "text": "your reply"}]
6. Delete the .processing file (NOT the original inbox — it may have new messages by now)
7. Update telegram_conversation.json (append this round's user + assistant messages)
8. Append transcript to <data_dir>/telegram_transcripts/telegram_<today>.jsonl

If no messages: do nothing, output nothing.

Note: You are the primary responder. Use your full session context to reply. This is not a proxy — you are replying directly.
