# Changelog


## [1.1.0] — 2026-06-28

### Wizard conversation hygiene

The bot no longer edits a prompt's text to repurpose it, and no longer deletes
the owner's replies. Each step now **disables the previous message's buttons and
sends a new message**, so the whole bot↔owner exchange stays visible to the
group (`plans/04-wizard-ux-and-uneven-split.md`).

- Payer→amount and amount→participants send fresh messages; the participants
  question is sent as a reply to the owner's amount message.
- Dropped every `message.delete()` in the wizard.

### Running summary

- After each recorded payment the bot posts a `خلاصه تا الان 📝` block (payer,
  amount, people) combined with the "another payer?" menu, and re-posts the
  final summary when the session finishes.
- Summary names omit the leading `@` so the summary never pings anyone.

### Uneven (custom) splitting

- New split-choice step after participants: **مساوی** (equal) or **نامساوی**
  (manual). Uneven mode lists each participant numbered; the owner replies with
  one share per line, validated to sum exactly to the paid amount.
- `settle.Payment` gained an optional, hashable `shares` field; `compute_balances`
  charges explicit shares when present and falls back to the equal split
  otherwise — fully backward compatible. Shares flow through to the persistent
  tab ledger unchanged.

### Tests

- Added uneven-share unit tests for `settle` and `ledger`, plus an offline
  wizard-flow harness (even/uneven end-to-end, share validation, and assertions
  that no message text is edited or deleted). Suite is now **24 tests**.

---

## [1.0.4] — 2026-06-27

### Fixes

- Fixed repo url

---

## [1.0.3] — 2026-06-27

### Fixes 

- Removed leftover proxy from local run

---

## [1.0.2] — 2026-06-27

### Fixes

- Fixed the problem where the directory didn't exist on the server

---

## [1.0.1] — 2026-06-27

### Fixes

- Fixed a bug in deployment process

---

## [1.0.0] — 2026-06-27

### Initial implementation

Added the bot skeleton end-to-end:

- **Access control**: `/start` shows admin vs. non-admin messages; only super-admins can add the bot to a group (req 5); authorized chats are persisted.
- **Roster**: per-chat seen-users roster plus manual name entries, persisted in `data/rosters.json` (per developer answer to plan 0.1). Bots excluded.
- **Wizard**: "دنگ" keyword triggers the conversation. Steps 9–14 are implemented with inline buttons (2 columns, capped at 20 members), reply-only validation, and owner-only enforcement (req 14). Locking prevents concurrent use (req 8/18).
- **Inactivity timeout**: 5-minute `JobQueue` job that disables the active menu and posts a timeout note (req 17).
- **Settlement algorithm**: pure `Decimal` math with no rounding-up, max 2 decimal places (plan 0.3). Each debtor makes exactly one payment (req 15); creditor→creditor residual transfers are added on top.
- **Tests**: 8 unit tests covering both PLAN.md worked examples plus the one-payment-per-debtor invariant.
- **Docker**: multi-stage `Dockerfile` on `python:3.12-slim`, non-root user, `docker-compose.yml` with a named volume for `/data`.
- **CI/CD**: `.github/workflows/deploy.yml` builds & pushes to GHCR and SSH-deploys via `appleboy/ssh-action`.
- **Docs**: `README.md` and `.env.example` cover setup, usage, the Telegram member-list limitation, and deployment.

### Fixes

- **Stop responding to every message**: while a wizard session is active, the bot now reacts only to the owner's *reply to its current prompt*. All other group chatter (and non-owner replies) is ignored silently instead of being answered with "only the owner can use me" / "please reply". Removed the `REPLY_REQUIRED`/`ONLY_OWNER` nags from the text path; button clicks still get an owner-only toast.
- **`.env` now authoritative**: `load_dotenv(override=True)` so added `SUPER_ADMINS` (or any var) take effect even if a stale value lingers in the shell/OS environment from an earlier run.
- **Roster bug**: normal messages were recorded with `is_bot=True` and silently dropped, so the roster never grew from chat. Fixed; `remember_user` also skips the disk write when the entry is unchanged (called per message now).
- **Logging**: per-module loggers in `dong`/`membership`/`start`, a global `add_error_handler` that logs any uncaught handler exception with traceback, and INFO logs at session start, payment recorded, settlement, cancel, timeout, busy, and authorize/reject.
- **Bug fix**: `my_chat_member` was registered via a non-existent message filter; switched to `ChatMemberHandler`.

### Persistent debtor tabs

Replaced the one-shot "who owes whom" settlement summary with a persistent,
per-debtor **tab** system (see `plans/03-persistent-debtor-tabs.md`).

- **Per-debtor messages instead of a summary**: when the owner finishes, the bot
  messages every person who must pay. Real users are tagged with a two-step
  confirm button (`دنگمو دادم` → `تایید میکنم دنگمو دادم`, anti-misclick) that is
  **locked to that user**.
- **6-hourly reminders**: an unpaid debtor is re-pinged every
  `REMINDER_INTERVAL_SECONDS` (default 6h); each reminder disables the previous
  message's button so only the latest is actionable. Reminders survive restarts
  via an Application `post_init` rescheduler.
- **Tabs accumulate across invoices**: a new "دنگ" run folds into the outstanding
  balance and re-runs the minimal split, so every debtor still pays exactly once
  even with unpaid prior debt. Superseded messages are disabled and fresh ones
  sent with the new totals.
- **Manual debtors** (no Telegram id) are grouped into one message tagging the
  session owner, who toggles who has paid and confirms; any still-unpaid manual
  debtors get a fresh message. Manual names remain **persisted** so a debtor's
  identity is stable across invoices.
- **New code**: `bot/ledger.py` (durable tab bookkeeping, Telegram-free + unit
  tested) and `bot/handlers/{tabs,reminders}.py`. Tab messages are sent as HTML
  for robust tagging. Added `tests/test_ledger.py`.

### Project rename

Renamed from "dong-bot" to **Poulpoulak (پول‌پولک)**.

- All references updated (image names, config, docs, logger name, repo URL).
- **Amount prompt** now tags the actual **payer**, not the session owner.
- **Deploy**: trigger on git tags (`v*`) instead of push to `main`; action
  versions pinned to latest stable (`checkout@v4`, `buildx-action@v3`,
  `login-action@v3`, `build-push-action@v6`). Runtime env vars are injected
  from GitHub Secrets, removing the need for a `.env` file on the VPS.
- **docker-compose**: uses `${GITHUB_REPOSITORY_OWNER}` for the image tag.