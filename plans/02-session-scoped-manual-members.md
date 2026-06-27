# Plan 02 — Session-scoped manual members

## Goal
Manually-added member names should live **only for the duration of the active
"دنگ" session**. Seen Telegram users keep being persisted permanently (unchanged).
Manual names must no longer be written to `data/rosters.json`.

## Current behavior (why this is needed)
- `roster.add_manual_name(chat_id, name)` writes the name into
  `rosters[chat].manual` on disk (`bot/roster.py:83`), so it survives restarts
  and leaks into every future session for that chat.
- `roster.members()` reads those persisted manual names back
  (`bot/roster.py:119`), so an old typo'd or one-off name shows up forever.
- Seen users are stored separately under `rosters[chat].users` via
  `remember_user` — that path stays exactly as-is.

## Design
Move manual names off disk and into the in-memory `Session`. Seen-user
persistence is untouched. `roster.members()` / `roster.find()` gain an optional
`manual_names` argument so callers can inject the current session's manual list;
the disk `manual` array is no longer read or written.

---

## Steps

1. **`bot/state.py` — add a session-scoped manual list.**
   - Add field to `Session`:
     ```python
     # Manual names typed during THIS session only (never persisted).
     manual_names: list[str] = field(default_factory=list)
     ```
   - Nothing else changes here; the field dies with the session (and the lock),
     satisfying "only for the duration of the session".

2. **`bot/roster.py` — read manual names from the caller, not disk.**
   - Change signature:
     `members(chat_id: int, manual_names: list[str] | None = None) -> list[Member]`.
     Build seen-user `Member`s from `blob["users"]` exactly as today, then build
     manual `Member`s from the passed `manual_names` list (default `[]`).
     **Remove** the loop over `blob.get("manual", [])`.
   - Change signature:
     `find(chat_id: int, key: str, manual_names: list[str] | None = None)` and
     forward `manual_names` to `members(...)`.
   - **Remove** `add_manual_name` (no longer needed — nothing persists manual
     names). Update the module docstring (lines 1–11) to say manual names are
     session-scoped and not persisted.
   - Leave `manual_key`, `Member`, `mention`, `_escape_md`, `mention_user`,
     `remember_user`, `_chat_blob` unchanged. `_chat_blob` may keep creating the
     `"manual"` key for backward compatibility, but it will simply stay empty.

3. **`bot/handlers/dong.py` — use the session list everywhere.**
   - Add a small helper:
     ```python
     def _add_session_manual(session, name) -> str | None:
         name = name.strip()
         if not name:
             return None
         if name not in session.manual_names:
             session.manual_names.append(name)
         return roster_mod.manual_key(name)
     ```
   - Replace the two `roster_mod.add_manual_name(...)` call sites:
     - `on_manual_payer_message` (line ~336): use `_add_session_manual` then
       `find(session.chat_id, key, session.manual_names)`.
     - `on_manual_participants_message` (line ~524): for each name call
       `_add_session_manual` and add the returned key to
       `session.draft_participants`.
   - Pass `session.manual_names` to **every** `members()` / `find()` call in this
     file so manual entries are visible in the keyboards and lookups:
     - `_show_payer_prompt`, `on_payer_callback`, `_show_participants_prompt`,
       `on_participant_callback` (both `members` and `find`),
       `on_manual_participants_message`, `_commit_and_ask_more`,
       `on_more_callback`.
   - `_tag_member(chat_id, label)` → add a `manual_names` param and forward it to
     `members(...)`. Update its only caller `_settle` to pass
     `session.manual_names`.

4. **Docs / changelog.**
   - `bot/store.py` docstring (lines 1–11): adjust the wording that says manual
     names are persisted — only seen users are now.
   - `CHANGELOG.md`: add a bullet under "[Unreleased]" describing that manual
     members are now session-scoped and no longer written to disk.

---

## Notes / decisions
- **Backward compatibility:** existing `rosters.json` files may still contain a
  `"manual": [...]` array. After this change it is simply ignored (never read,
  never written). No migration is required; it can be left in place harmlessly.
  (Optional follow-up: strip stale `manual` arrays on next save — not included
  here to keep the change minimal.)
- **No behavior change for seen users** — `remember_user` and the `users` blob
  are untouched, so permanent member memory still works.
- **No new persistence** — the only state added is in-memory on `Session`, which
  is already the home for all transient wizard data.

## Verification (offline only — DO NOT live bot test)
1. `python -m compileall bot` — compiles clean.
2. `python -m pytest` — existing 8 settlement tests still pass (unaffected).
3. Targeted offline check:
   - `members(chat, ["Ali"])` returns the seen users **plus** one manual
     `Member` with key `mAli`; `members(chat)` (no list) returns only seen users.
   - `find(chat, "mAli", ["Ali"])` resolves; `find(chat, "mAli")` returns `None`.
   - Confirm `data/rosters.json` is **not** modified when a manual name is added
     (only `Session.manual_names` grows).
