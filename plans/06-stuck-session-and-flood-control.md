# Plan 06 — Fix the permanently-stuck session (flood control + missing JobQueue)

Source: `bug.log` from the VPS. Two compounding bugs:

- **Trigger:** a wizard step's `send_message` hit Telegram flood control
  (`telegram.error.RetryAfter: Flood control exceeded`) and crashed mid-flow,
  leaving the per-chat session locked with no live menu.
- **Why it never recovered:** `JobQueue` is **not installed** in production
  (`requirements.txt` lacks the extra), so the 5-minute inactivity timeout never
  fires and the lock is never released. The bot reports "busy" forever.

Evidence: `bug.log` line 260 (`429 Too Many Requests`) → 301 (`RetryAfter`,
raised in `_show_split_prompt`, `dong.py:579`); repeated `busy; keyword ... ignored`
from line 307 on; `No JobQueue set up` warnings at lines 4-5, 27-28, 234-239.

Contributing factor: plan 04 changed each wizard step from one "edit in place"
call to two calls (disable old buttons **+** send new message), ~doubling the
per-group message rate and making flood control easy to hit with fast clicking.

Guiding constraints (`CLAUDE.md` + memory): don't break the even-split path;
verify **offline only** (compileall + pytest in `.venv`); **never** live-bot-test.

---

## Fix 1 — Install the missing PTB extras (root cause)

### 1.1 `requirements.txt`
- Change `python-telegram-bot==21.9` to:
  `python-telegram-bot[job-queue,rate-limiter]==21.9`
- `job-queue` (APScheduler) → restores the inactivity timeout **and** the
  6-hourly debtor reminders (both currently dead in prod).
- `rate-limiter` (aiolimiter) → enables `AIORateLimiter` (Fix 2).

> No Dockerfile change needed; it installs from `requirements.txt`.

---

## Fix 2 — Add `AIORateLimiter` so flood control never crashes a step

### 2.1 `bot/main.py`
- Import: `from telegram.ext import AIORateLimiter`.
- In `_build_application`, add `.rate_limiter(AIORateLimiter())` to the builder
  chain (alongside `.token(...)` / `.post_init(...)`).
- Effect: PTB transparently throttles outbound calls and **auto-retries on
  HTTP 429** instead of raising `RetryAfter` into the handler. The split-menu
  send that crashed would now simply wait and succeed.

---

## Fix 3 — Lazy lock expiry (defense-in-depth, independent of JobQueue)

Even with Fix 1, a stuck session should self-heal without relying on a job
firing. Make the lock expire by wall-clock time, checked on the next keyword.

### 3.1 `bot/state.py`
- `import time` and add to `Session`:
  `last_activity: float = field(default_factory=time.time)`
- Add a helper to refresh it, and set it on `start_session`.
- (Optional, low-risk) update `last_activity` wherever `_schedule_timeout` is
  already called, so an active session stays fresh; simplest is to stamp it in
  `_schedule_timeout` in `dong.py` (it already runs at every step).

### 3.2 `bot/handlers/dong.py` — `on_dong_keyword`
- Replace the `if state.is_locked(chat.id):` block with:
  - if a session exists **and** `now - session.last_activity >= SESSION_TIMEOUT_SECONDS`
    → it's stale: `_end_session(chat.id, owner_id=None)` and fall through to start
    a fresh session (log "released stale session").
  - else if locked → reply `BUSY` as today.
- Net: even if JobQueue were missing again or a job failed, the lock clears on
  the next keyword after the timeout window.

---

## Fix 4 — Explicit owner/admin escape hatch

A `/cancel` command so a stuck or unwanted session can always be killed
immediately (no waiting for the timeout, no message-volume risk).

### 4.1 `bot/handlers/dong.py`
- Add `async def on_cancel_command(update, context)`:
  - group chats only; look up the session for the chat.
  - allow if the caller is the **session owner** or a **super-admin**
    (`config.is_super_admin`).
  - `_end_session(...)` and reply `messages.CANCELLED`; if no session, reply a
    short "nothing to cancel" note.

### 4.2 `bot/main.py`
- Register `CommandHandler("cancel", on_cancel_command)` (groups).

---

## Files touched

1. `requirements.txt` — add `[job-queue,rate-limiter]` extras. (Fix 1)
2. `bot/main.py` — `AIORateLimiter`; register `/cancel`. (Fix 2, 4)
3. `bot/state.py` — `last_activity` timestamp + refresh helper. (Fix 3)
4. `bot/handlers/dong.py` — stale-lock expiry in `on_dong_keyword`; stamp
   activity; `on_cancel_command`. (Fix 3, 4)
5. Docs — `CHANGELOG.md`, `README.md`. (below)
6. `tests/` — see below.

---

## Verification (offline only — NO live bot test)

1. `.\.venv\Scripts\python.exe -m compileall bot` — syntax.
2. `python -c "import bot.main"` — import graph resolves (incl. `AIORateLimiter`,
   which needs the rate-limiter extra to be installed in `.venv`).
3. `python -m pytest -q` — full suite stays green.
4. **New tests** (extend `tests/test_wizard_flow.py` or a new file, using the
   existing fakes + `job_queue=None`):
   - **Stale lock auto-resets**: start a session, set `last_activity` to
     `now - (SESSION_TIMEOUT_SECONDS + 1)`, call `on_dong_keyword` → old session
     ended and a **new** session started (not `BUSY`).
   - **Fresh lock still busy**: a recent session + a different user's keyword →
     `BUSY`, original session intact.
   - **`/cancel` by owner / super-admin** ends the session; by an unrelated user
     it does not.

> Note: the rate-limiter / flood-control behaviour itself can't be unit-tested
> offline (it's PTB-internal); Fixes 1–2 are verified by import + the dependency
> change. Confirmed safe by design: `AIORateLimiter` only throttles/retries.

---

## Docs

### `CHANGELOG.md` — new `## [1.1.2] — 2026-06-28`, **Fixes**
- Installed the `job-queue` extra: the 5-minute inactivity timeout and the
  6-hourly debtor reminders now actually run on the server (they were silently
  disabled, which is why an interrupted session stayed "busy" forever).
- Added a rate limiter so Telegram flood control (HTTP 429) is retried instead
  of crashing a wizard step.
- The per-chat lock now self-heals: a session idle past the timeout is released
  on the next `دنگ`, and a new `/cancel` command lets the owner or a super-admin
  end a stuck session immediately.

### `README.md`
- Note that `/cancel` ends the current session.
- Update the inactivity-timeout / reminders wording to reflect that the
  `[job-queue]` extra is required (now in `requirements.txt`).
- Bump the Tests count.

---

## Out of scope (note, don't implement now)
- Re-evaluating plan 04's "send a new message every step" volume increase. The
  rate limiter (Fix 2) makes it safe; a later pass could reduce the number of
  sends, but that's a UX trade-off the developer chose and is not needed to fix
  the freeze.
- No change to settlement, ledger, or tab logic.
