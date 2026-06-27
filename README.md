# Poulpoulak (پول‌پولک)

A small Persian Telegram bot that splits group expenses and reduces the number
of settle-up transactions using the rule **every debtor makes exactly one
payment**.

> کلمهٔ «دنگ» در فارسی به معنای سهم هر نفر از یک خرج مشترک است.

## Features

- Group-only: works inside a Telegram group; `/start` in private chats shows
  general info (or admin instructions).
- Super-admin gated: only people listed in `SUPER_ADMINS` can add the bot to a
  group. Other adders are rejected and the bot stays inert.
- Per-chat member roster: once any user sends a message in the group, the bot
  can pick them from a button list (Telegram doesn't expose the full member
  list). Names can also be entered manually and are remembered per group.
- Wizard flow in Persian with inline buttons, reply-only validation, and
  owner-only enforcement.
- 5-minute inactivity timeout that disables the active menu.
- Debt simplification: debtors make ONE payment each; any residual between
  creditors is settled with extra creditor→creditor transfers.
- Persists only the per-group roster and which groups are authorized — no
  database. Active conversation state (the lock, wizard selections, timer) is
  transient and lost on restart.

## Setup

1. Get a bot token from [@BotFather](https://t.me/BotFather).
2. Find your Telegram user ID via [@userinfobot](https://t.me/userinfobot).
3. Configure:

   ```bash
   cp .env.example .env
   # edit .env: set BOT_TOKEN and SUPER_ADMINS=<your-id>
   ```

4. Run with Docker (recommended):

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

5. Or run locally with the project's virtual environment:

   ```bash
   .venv/Scripts/python.exe -m bot.main   # PowerShell 7
   ```

## Usage

1. A super-admin adds the bot to a Telegram group. The bot posts a welcome
   message and the group is "authorized" for this instance.
2. Anyone in the group sends a message containing only the keyword **دنگ**.
3. The bot walks the owner through:

   1. Who paid? (pick from the roster or enter manually)
   2. How much? (positive integer/decimal, in تومان)
   3. Who is sharing it? (multi-select with 🟢/🔘 toggles)
   4. Anyone else paid? (loop back, or ✅ تموم to finish)

4. The bot posts a tagged summary like:

   ```
   @alice
   به: @bob
   مبلغ: 215.00 تومن

   @carol
   به: @bob
   مبلغ: 215.00 تومن
   ```

   Users without a Telegram `@username` are tagged using a clickable mention
   (`tg://user?id=...`) built from their first name.

## Known limitations

- Telegram does not let a bot enumerate the full member list of a group. The
  button list only contains people who have sent a message while the bot was
  present (plus any names manually entered). Use "هیچکدام" to add anyone else.
- Buttons are capped at `MAX_MEMBER_BUTTONS` (default 20) and laid out in 2
  columns. Groups with more than ~20 active members are not supported.
- Restart loses the active wizard (the lock, selections, timer). The roster and
  authorized-chats flags are persisted and survive restarts.

## Deployment to a VPS

The `.github/workflows/deploy.yml` workflow:

1. Triggers on **git tags** (`v*`) — push a tag like `v1.0.0` to deploy.
2. Builds the Docker image and pushes it to GHCR (tagged both `:latest` and `:vX.Y.Z`).
3. SSHes into the VPS, creates runtime `.env` from **GitHub Secrets**, pulls the
   fresh image, and restarts via Docker Compose.

Required GitHub repository secrets:

| Secret          | Purpose                           |
|-----------------|-----------------------------------|
| `VPS_HOST`      | hostname or IP of the VPS         |
| `VPS_USER`      | SSH username                      |
| `VPS_SSH_KEY`   | private SSH key for that user     |
| `BOT_TOKEN`     | Telegram bot token (required)     |
| `SUPER_ADMINS`  | comma/space separated Telegram IDs|
| `PROXY_URL`     | optional HTTP proxy for the bot   |

No `.env` file is needed on the VPS; the workflow writes one from secrets on
every deploy. For local development, copy `.env.example` to `.env` and fill it in.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ -q
```

The settlement algorithm has unit tests that encode both worked examples from
the requirements (500/450 and 400/600).

## Project layout

```
bot/
├── main.py            entrypoint, builds the PTB Application
├── config.py          env-var config
├── messages.py        all Persian strings
├── state.py           transient session/lock state
├── store.py           tiny JSON persistence (rosters + authorized chats)
├── roster.py          per-chat roster + manual names + mention helpers
├── access.py          super-admin / authorized-chat helpers
├── keyboards.py       inline-keyboard builders (2-col layout)
├── settle.py          debt-simplification (pure, unit-tested)
└── handlers/
    ├── start.py       /start (admin vs non-admin)
    ├── membership.py  my_chat_member (bot added/removed)
    └── dong.py        the دنگ wizard (keyword, callbacks, replies, timer)
```

## License

MIT — see `LICENSE` (add one before publishing).