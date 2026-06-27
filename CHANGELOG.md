# Changelog

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