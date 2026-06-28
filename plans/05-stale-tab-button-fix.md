# Plan 05 — Fix stale (superseded) tab buttons staying actionable

Source: `plans/bug.md`. Root cause confirmed by tracing + an offline repro
against the real `ledger`/`tabs` code.

## The problem (recap)

A debtor's pay-message carries only a stable key in its callback data
(`paid1|<src>` / `paid2|<src>`), and `on_paid_callback` acts on **whatever that
`src` currently owes** in the ledger. When a new invoice replaces the tab,
`tabs.deactivate_all` *tries* to disable the old messages, but that edit is
best-effort and silently swallowed (`try/except: pass`) — and Telegram refuses
to edit a message older than **48 h** (also possible: transient API error /
reminder-job race). If the disable doesn't land, the old button stays live and,
because it keys on `src`, it confirms the debtor's **current** obligation.

In the reported case: C's old "pay 50" button was never disabled; pressing it
settled the new 10‑toman tab, and the newer message then looked dead.

**Not a math bug** (totals were correct; no double payment). It is a
robustness/UX bug. The same latent flaw exists on the manual-settle message.

## The fix (guard the action, don't rely on the cosmetic disable)

The ledger already tracks the **current** message id per debtor
(`real_msgs[src].message_id`) and for the manual group (`manual_msg.message_id`).
Reject any button press that doesn't come from the currently-tracked message.

### 1. `bot/messages.py`
- Add a string:
  `TAB_MESSAGE_OUTDATED = "این پیام قدیمیه و دیگه معتبر نیست. از جدیدترین پیام ربات استفاده کن."`

### 2. `bot/handlers/tabs.py` — real-user confirm (`on_paid_callback`)
- After the existing user-lock check (the `NOT_YOUR_BUTTON` block) and **before**
  loading `src_obls`, add a staleness guard:
  - `entry = ledger.get_real_msg(chat_id, src)`
  - `current_mid = entry.get("message_id") if entry else None`
  - if `current_mid != query.message.message_id`:
    - `await query.answer(messages.TAB_MESSAGE_OUTDATED, show_alert=True)` (try/except)
    - disable this stale message:
      `await query.edit_message_reply_markup(reply_markup=keyboards.disabled_keyboard())`
      (try/except)
    - `return` (do **not** confirm anything)
- Net effect: only the latest tracked message for a debtor can confirm; any
  leftover/superseded message becomes inert even if its earlier disable failed.
- Existing behaviour is unchanged for the normal path: `paid1` edits the message
  in place (same `message_id`, still matches) and `paid2` confirms.

### 3. `bot/handlers/tabs.py` — manual settle (`on_manual_settle_callback`)
- Same class of bug. After the existing owner-lock check, add:
  - if `manual_msg.get("message_id") != query.message.message_id`:
    - `await query.answer(messages.TAB_MESSAGE_OUTDATED, show_alert=True)` (try/except)
    - disable the stale message via `query.edit_message_reply_markup(disabled_keyboard())`
      (try/except)
    - `return`
- Place it so it applies to both `mtog|` (toggle) and `mconf` (confirm).

> Note: `deactivate_all`'s `try/except: pass` stays — failing to edit a 48h-old
> message is expected and fine. The guard above is what actually makes stale
> messages safe, so no change is needed there.

## Tests (offline only — no live bot)

New file `tests/test_tabs_stale.py` driving the real handlers with fakes
(temp store + `job_queue=None`, mirroring `tests/test_wizard_flow.py`):

1. **Real-user stale press is rejected**: seed an obligation `u2→u1`, set the
   tracked message to id `500`; press `paid2|u2` from an **old** message id
   (`499`) as user `2` → obligation **unchanged**, an "outdated" alert was
   answered, and the old message was disabled (an `edit_message_reply_markup`
   happened).
2. **Current press still works**: press `paid2|u2` from id `500` → obligation
   removed (`confirm_real` ran).
3. **Manual stale press is rejected**: `set_manual_msg(message_id=600,
   owner_id=7)`; press `mconf` from old id `599` as user `7` → obligations
   unchanged, "outdated" alert answered.

Run: `.\.venv\Scripts\python.exe -m pytest -q` (expect the suite to grow from
24 to ~27 and stay green) and `python -m compileall bot`.

## Docs

### `CHANGELOG.md`
- Add a new section at the top:
  ```
  ## [1.1.1] — 2026-06-28
  ### Fixes
  - Stale/superseded debtor tab buttons are now ignored. A pay-message from a
    previous invoice (whose disable edit didn't land — e.g. Telegram's 48h edit
    limit) could still confirm the debtor's *current* tab; pressing it now shows
    "this message is outdated" and disables it instead. Only the latest message
    per debtor (and the latest manual-settle message) is actionable. No amounts
    were ever miscalculated.
  ```
- If `1.1.0` has not been tagged yet, this may instead be folded into the
  existing `1.1.0` "Fixes" — developer's call at tag time.

### `README.md`
- Add one bullet under **Known limitations** (or the persistent-tabs feature
  list) noting: "Only the most recent pay-message per debtor is actionable;
  older/superseded ones are rejected if pressed (the bot can't always delete or
  disable a message older than 48h, so it guards the action instead)."
- Bump the **Tests** count to the new total.

## Out of scope
- No change to the settlement algorithm, ledger schema, callback-data format, or
  reminder scheduling. (A callback-data generation nonce was considered but is
  more invasive than the message-id guard and unnecessary.)
- No version bump in `bot/__init__.py` unless you want it aligned now (left to
  the tagging step, as before).
