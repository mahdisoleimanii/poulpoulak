# Changelog

## [Unreleased] — fixes

- **Stop responding to every message**: while a wizard session is active, the bot now reacts only to the owner's *reply to its current prompt*. All other group chatter (and non-owner replies) is ignored silently instead of being answered with "only the owner can use me" / "please reply". Removed the `REPLY_REQUIRED`/`ONLY_OWNER` nags from the text path; button clicks still get an owner-only toast.
- **`.env` now authoritative**: `load_dotenv(override=True)` so added `SUPER_ADMINS` (or any var) take effect even if a stale value lingers in the shell/OS environment from an earlier run.
- **Roster bug**: normal messages were recorded with `is_bot=True` and silently dropped, so the roster never grew from chat. Fixed; `remember_user` also skips the disk write when the entry is unchanged (called per message now).
- **Logging**: per-module loggers in `dong`/`membership`/`start`, a global `add_error_handler` that logs any uncaught handler exception with traceback, and INFO logs at session start, payment recorded, settlement, cancel, timeout, busy, and authorize/reject.
- **Bug fix**: `my_chat_member` was registered via a non-existent message filter; switched to `ChatMemberHandler`.

## [Unreleased] — initial implementation

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