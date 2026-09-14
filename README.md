# SK X TALHA PERIMUIM POST MAKER

A Python/aiogram Telegram bot with an original premium post-making workflow. It gates access behind required channels and a private group, builds posts through a guided wizard, supports photo/video attachments, logical premium-emoji decoration, Terminal/Card/Hacker layouts, inline URL buttons, multi-destination publishing, owner controls, and broadcast tooling.

## Persistence model

There is no SQLite database. The bot keeps a small local JSON cache for fast operation and mirrors durable state to a GitHub repository:

- `skx/users/<telegram_user_id>.json` — each user's profile, post history, destinations, and events.
- `skx/meta.json` — the active premium emoji pool and metadata.
- On startup, remote GitHub files are read first, so redeploys restore data.
- Writes use the GitHub Contents API with the current file SHA, preventing accidental overwrites in normal sequential operation.

## Setup

1. Install Python 3.11+ and dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Edit the single `config.py` file and set `BOT_TOKEN`, `DATA_REPO`, `DATA_BRANCH`, data paths, owners, and required destinations.
3. In Railway Variables, set only the GitHub token; do not commit it:

   ```bash
   export GITHUB_TOKEN='github_pat_...'
   ```

   The token needs repository Contents read/write permission for the configured data repository.

4. Add the bot to every required channel/group. For membership checks and publishing, grant administrator permissions where required. Private destinations must be added first and then supplied as chat IDs.
5. Run:

   ```bash
   python bot.py
   ```

## Important Telegram notes

Telegram custom emoji IDs are rendered in bot messages using `tg-emoji` entities. Bot API 10.3 supports inline button styles `primary`, `success`, and `danger`; those are used throughout the UI. The same custom emoji ID cannot universally be used as a button icon in every chat, so the implementation keeps buttons readable and uses custom emoji decoration in the message content.

The broadcast handler safely reports failures for users that blocked the bot. Channel/group broadcast requires the bot to be an administrator with posting permission in each destination; Telegram does not expose a way for a bot to broadcast to chats where it is not present.

## Security

- Keep `config.py` and `GITHUB_TOKEN` private.
- Use a fine-grained GitHub token scoped only to this repository.
- The two configured owner IDs are protected in `config.py`; runtime secondary owners can be added/removed from the owner panel.
- Rotate the bot token immediately if it is exposed.
