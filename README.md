# Poulpoulak (پول‌پولک)

A Persian Telegram bot that splits group expenses and reduces the number of
settle-up transactions using the rule **every debtor makes exactly one payment**.

> پول‌پولک: سهم‌های کوچک پول تو خرج‌های گروهی رو برات حساب می‌کنه.

NOTE: This bot was written solely by AI agents.

## Features

- **Group-only**: works inside Telegram groups; `/start` in private chats shows
  info or admin instructions.
- **Super-admin gated**: only users listed in `SUPER_ADMINS` can add the bot to
  a group.
- **Per-chat member roster**: learns users as they speak. Manually-entered names
  are also persisted per group.
- **Wizard flow** in Persian with inline buttons, reply-only validation, and
  owner-only enforcement.
- **Visible conversation**: the bot never edits a prompt's text to repurpose it
  and never deletes the owner's replies. Each step disables the previous
  message's buttons and posts a new message, so the whole exchange stays
  readable by everyone in the group.
- **Running summary**: after each payment is recorded, the bot posts a
  `خلاصه تا الان 📝` block listing every payment so far (payer, amount, people),
  and re-sends it when the session is finished. Summary names are shown without
  a leading `@` so nobody gets pinged.
- **Even or uneven split**: by default a payment is split equally, but the owner
  can choose **نامساوی (دستی)** to give each person a custom share (e.g. one
  bill of 100 split 30 / 30 / 40). Shares are entered one-per-line and must sum
  exactly to the paid amount.
- **5-minute inactivity timeout** that disables the active menu.
- **Debt simplification**: debtors make **one payment each**; any residual
  between creditors is settled with extra creditor→creditor transfers. Amounts
  use `Decimal`, are rounded DOWN (never up), and never exceed 2 decimals.
- **Persistent debtor tabs**: after the wizard finishes, the bot sends a
  tagged pay-message to **each person who must pay** — a two-step confirm
  button (`دنگمو دادم` → `تایید میکنم دنگمو دادم`, anti-misclick) locked to
  that user.
- **6-hourly reminders**: unpaid debtors are re-pinged every 6 hours; each
  reminder disables the previous message's button so only the latest is
  actionable. Reminders survive restarts.
- **Tab accumulation across invoices**: a new "دنگ" run folds into outstanding
  balances and re-runs the minimal split, so every debtor still pays exactly
  once even with unpaid prior debt.
- **Manual debtors** (no Telegram ID): grouped into one owner-facing message
  with toggles and a confirm button. Persisted so identities are stable across
  invoices.
- **No database** — only the per-group roster, authorized chats, and outstanding
  tabs are persisted as a single JSON file. Wizard state (lock, selections,
  timer) is transient.

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
3. The bot walks the session owner through:

   1. **Who paid?** — pick from the roster or enter a name manually.
   2. **How much?** — enter a positive number in تومان. The prompt tags the
      named payer, not the session owner, so it's always clear who's being
      recorded.
   3. **Who is sharing it?** — multi-select with 🟢/🔘 toggles.
   4. **How to split?** — ➗ مساوی for an equal split, or ✏️ نامساوی to type
      each person's share (one number per line, in the listed order; they must
      add up to the amount).
   5. A **summary so far** is posted, then **Anyone else paid?** — loop back, or
      ✅ تموم to finish (which re-posts the final summary).

4. Instead of a one-shot settlement summary, the bot sends a **tagged
   pay-message** to each person who must pay:

   - **Real users** get a mention + the amount + who to pay + a
     `دنگمو دادم` button. Pressing it changes the same message to
     `⚠️ دوباره تایید کن` with a `تایید میکنم دنگمو دادم` button —
     an accidental press can't confirm. The button is locked to that user.
   - **Manually-added debtors** are grouped into one message tagging the
     session owner, who toggles who has paid and hits ✅ تایید.
   - Unconfirmed debtors are reminded every 6 hours with a fresh message
     (the old one's button is disabled).

5. If someone initiates a new "دنگ" while there are still unpaid tabs from a
   previous session, the amounts are **accumulated** and re-optimised — each
   debtor still pays exactly once, now with the combined total.

## Known limitations

- Telegram does not let a bot enumerate the full member list of a group. The
  button list only contains people who have sent a message while the bot was
  present (plus any names manually entered). Use "یکی دیگه" to add anyone else.
- Buttons are capped at `MAX_MEMBER_BUTTONS` (default 20) and laid out in 2
  columns. Groups with more than ~20 active members are not supported.
- Restart loses the active wizard (the lock, selections, timer). The roster,
  authorized-chats, and outstanding tabs are persisted.
- Reminder jobs (6h) are in-memory; on restart they are recreated from the
  persisted tab state via a `post_init` hook.
- The confirmation buttons use HTML `parse_mode` and a `tg://user?id=...`
  anchor for users without a username. All user-supplied text is HTML-escaped.
- Only the most recent pay-message per debtor (and the latest manual-settle
  message) is actionable; older/superseded ones are rejected if pressed. Telegram
  won't always let the bot disable a message older than 48 hours, so the bot
  guards the action itself rather than relying on the button being removed.

## Deployment to a VPS

The `.github/workflows/deploy.yml` workflow:

1. Triggers on **git tags** (`v*`) — push a tag like `v1.0.0` to deploy.
2. Builds the Docker image and pushes it to GHCR (tagged both `:latest` and
   `:vX.Y.Z`).
3. SSHes into the VPS, creates the runtime `.env` from **GitHub Secrets**,
   pulls the fresh image, and restarts via Docker Compose.

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

**27 tests** — debt-simplification (both PLAN.md examples, the
one-payment-per-debtor invariant, and explicit uneven shares), the persistent
tab ledger (merge, accumulation, uneven invoice, real/manual confirmation,
balance round-trip, message bookkeeping), an offline wizard-flow harness
(even/uneven end-to-end, share validation, no message editing/deletion), and the
stale-tab-button guard (superseded real/manual pay-messages are rejected).

## Project layout

```
bot/
├── main.py            entrypoint, builds the PTB Application
├── config.py          env-var config
├── messages.py        all Persian strings
├── state.py           transient session/lock state
├── store.py           tiny JSON persistence (rosters + auth + tabs)
├── roster.py          per-chat roster + manual names + mention helpers
├── access.py          super-admin / authorized-chat helpers
├── keyboards.py       inline-keyboard builders (2-col layout)
├── settle.py          debt-simplification (pure, unit-tested)
├── ledger.py          persistent debtor tabs (pure, unit-tested)
└── handlers/
    ├── start.py       /start (admin vs non-admin)
    ├── membership.py  my_chat_member (bot added/removed)
    ├── dong.py        the دنگ wizard (keyword, callbacks, replies, timer)
    ├── tabs.py        sending + confirming debtor tab messages
    └── reminders.py   6-hourly re-ping jobs, restart rescheduler
```

## License

MIT — see `LICENSE`.

## Attribution

Telegram Bot Profile Picture: <a href="https://www.flaticon.com/free-icons/coin" title="coin icons">Coin icons created by Shuvo.Das - Flaticon</a>
