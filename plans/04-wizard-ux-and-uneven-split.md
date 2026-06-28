# Plan 04 — Wizard UX cleanup + uneven bill splitting

Source: `plans/preplan.md`. Two independent feature groups:

- **Group A — Conversation hygiene:** stop editing/deleting messages; keep the
  whole bot↔owner exchange visible; show a running summary.
- **Group B — Uneven splitting:** let the owner give each debtor a custom share
  instead of an equal split.

Guiding constraints (from `CLAUDE.md` + memory): don't break the existing even
split path; verify **offline only** (compileall + pytest in `.venv`); **never**
live-bot-test. Keep current method signatures working where compatible.

---

## Background — current flow (for reference)

`payer → amount → participants → [✅ ادامه] → commit → more-payers menu (loop) → [✅ تموم] → settle/dispatch tabs`

Problems today (`bot/handlers/dong.py`):
- `_show_amount_prompt` **edits** the payer message into the amount question.
- `on_amount_message` **deletes** the owner's reply, then a new message is sent.
- `on_manual_payer_message` / `on_manual_participants_message` **delete** the
  owner's reply too.
- `_commit_and_ask_more` **edits** the participants message into the
  more-payers menu. No summary is ever shown.

---

## Group A — Conversation hygiene

### A1. Add a "disable buttons" helper
- In `bot/handlers/dong.py` add `async def _disable_markup(context, chat_id, message_id)`
  that calls `context.bot.edit_message_reply_markup(reply_markup=None)` inside a
  `try/except` (no-op on failure). This only strips buttons — it never rewrites
  message text, which is the practice the developer objects to.

### A2. Payer → amount: disable, don't edit
- In `on_payer_callback` (the `pay|` branch) and `on_more_callback` (the
  `more|` branch): call `_disable_markup(...)` on `query.message.message_id`,
  then call `_show_amount_prompt` to send a **new** message.
- Refactor `_show_amount_prompt(context, session, reply_to=None)` to **always**
  `send_message` (remove the `query.edit_message_text` path entirely). It keeps
  setting `menu_message_id`/`prompt_message_id`/`awaiting_reply="amount"`.

### A3. Amount reply → participants: don't delete, reply instead
- In `on_amount_message`: **remove** `message.delete()`. Disable the amount
  prompt's buttons (`_disable_markup` on `session.menu_message_id`), then call
  `_show_participants_prompt(context, session, reply_to=message.message_id)`.
- Refactor `_show_participants_prompt(context, session, reply_to=None)` to pass
  `reply_to_message_id=reply_to` to `send_message`, so the participants question
  visibly hangs off the owner's amount message (per ANSWER in preplan line 8).

### A4. Stop deleting the owner's other replies
- `on_manual_payer_message`: remove `message.delete()`; disable the manual-payer
  prompt's buttons (if any) before sending the amount prompt.
- `on_manual_participants_message`: remove `message.delete()`. Keep the existing
  in-place toggle re-render of the participants menu (that edits only the live
  menu's markup, which is allowed).

### A5. Participants confirm → summary + more-payers (new message)
- Replace the body of `_commit_and_ask_more` so it:
  1. commits the payment (factor the commit into `_commit_payment(session, shares)`,
     see B5),
  2. `_disable_markup` on the participants menu,
  3. sends a **new** message = `messages.summary(...)` **followed by** the
     more-payers prompt text, with `more_payers_keyboard(...)`.
- Decision: keep the summary and the "add another payer?" menu in **one**
  message (matches preplan: summary "and below this" the add-another control).

### A6. "✅ تموم" → send the summary, then settle
- In `on_more_callback` (`done` branch): `_disable_markup` on the menu, send the
  final `messages.summary(...)` as its own message, then call `_settle(...)`
  (which dispatches the per-debtor tabs as today).

### A7. Summary builder (messages.py)
- Add `messages.summary(blocks)` producing:
  ```
  خلاصه تا الان 📝

  پرداخت‌کننده: <payer>
  مبلغ: <amount> تومن
  افراد:
  <p1> - <p2> - <p3> ...

  پرداخت‌کننده: <payer2>
  ...
  ```
  where each `block = (payer_label, amount_str, participants_render)`.
- For an **even** split, `participants_render` = labels joined by `" - "`.
  For an **uneven** split, render `"<label> (<share>)"` per person so the custom
  shares are visible.
- Decision: render labels as **plain text** (`Member.label`, e.g. `@user` or the
  first name / manual name) — *not* HTML pings — so the summary informs without
  mass-notifying the group. (The actual tag/ping still happens later in the
  debtor-tab messages.)
- Build `blocks` from `session.payments` via a small `_summary_blocks(session)`
  helper in `dong.py`.

---

## Group B — Uneven splitting

New step inserted after participants are confirmed and **before** commit:
`participants → [✅ ادامه] → SPLIT CHOICE → commit`.

### B1. Settlement core supports explicit shares (`bot/settle.py`)
- Extend `Payment` with an optional, hashable shares field:
  ```python
  shares: tuple[tuple[str, Decimal], ...] | None = None
  ```
  (tuple-of-pairs keeps the frozen dataclass hashable).
- In `compute_balances`: if `pmt.shares` is set, credit the payer the full
  `amount` and charge each `(person, share)` its `quantize_down(share)`;
  otherwise keep the current equal-split path unchanged.
- Backward compatible: existing callers omit `shares` → identical behavior.
  Existing `tests/test_ledger.py` / settle tests keep passing untouched.

### B2. Session draft carries shares + a stable order (`bot/state.py`)
- Add to `Session`:
  - `draft_shares: dict[str, Decimal] | None = None`
  - `draft_split_order: list[str] = field(default_factory=list)` (participant
    keys in the order shown to the owner, so prompt and reply parsing agree).
- Add to `Payment`: `shares: dict[str, Decimal] | None = None`.

### B3. Split-choice step (keyboards + messages + handler)
- `bot/keyboards.py`: add `split_keyboard()` with buttons
  `BTN_SPLIT_EVEN` (`sev`), `BTN_SPLIT_UNEVEN` (`sun`), then
  `BTN_CHANGE_PARTICIPANTS` (`sback`) and `BTN_CANCEL` (`scancel`).
- `bot/messages.py`: add `ASK_SPLIT_MODE`, `BTN_SPLIT_EVEN` ("➗ مساوی"),
  `BTN_SPLIT_UNEVEN` ("✏️ دستی / نامساوی"), `BTN_CHANGE_PARTICIPANTS`,
  `ask_uneven_shares(ordered_labels, amount)`, `UNEVEN_COUNT_MISMATCH`,
  `UNEVEN_SUM_MISMATCH(expected)`.
- `bot/handlers/dong.py`: change the participants-confirm (`pok`) handler to,
  instead of committing directly, `_disable_markup` the participants menu and
  send the split-choice prompt (`_show_split_prompt`). Set `awaiting_reply=None`.
- Add `async def on_split_callback(update, context)`:
  - `scancel` → `_cancel`.
  - `sback` → disable, re-show participants (`_show_participants_prompt`).
  - `sev` → `_commit_payment(session, shares=None)` then the A5 summary+more flow.
  - `sun` → compute `draft_split_order = [m.key for m in members(chat) if m.key
    in draft_participants]`, send `ask_uneven_shares(...)`, set
    `awaiting_reply="uneven_shares"`.

### B4. Uneven-shares reply (`bot/handlers/dong.py`)
- Route `awaiting_reply == "uneven_shares"` in `on_group_message` to a new
  `on_uneven_shares_message`.
- Parse the reply by splitting on `،,\n` (reuse the manual-participants regex).
  Validate:
  - count == `len(draft_split_order)` → else reply `UNEVEN_COUNT_MISMATCH`.
  - each token matches `DECIMAL_RE`, parses to a `Decimal >= 0` → else
    `INVALID_AMOUNT`.
  - `sum(quantize_down(share)) == quantize_down(draft_amount)` → else
    `UNEVEN_SUM_MISMATCH(expected=draft_amount)`.
  - Decision: shares **must sum exactly to the amount** (clear and unambiguous;
    no rounding-up needed since the owner supplies exact figures).
- On success: build `draft_shares = {key: share}` zipping `draft_split_order`
  with the parsed values, then `_commit_payment(session, shares=draft_shares)`
  and run the A5 summary+more flow. **Do not** delete the owner's reply (A4).

### B5. Commit + settle wiring
- Factor `_commit_payment(session, shares)`:
  - Build participants in **stable** order:
    `ordered = [m for m in members(chat) if m.key in draft_participants]`
    → `participant_keys` / `participant_labels` from it (also fixes today's
    nondeterministic set-iteration order in the summary).
  - Append `state.Payment(..., shares=shares)`.
  - Reset all `draft_*` fields (payer, amount, participants, shares,
    split_order, awaiting_reply).
- In `_settle`, when converting to `SettlePayment`, pass
  `shares=tuple((k, p.shares[k]) for k in p.participant_keys) if p.shares else None`.
  The rest (`tabs.deactivate_all`, `ledger.merge_invoice`, `tabs.dispatch`)
  is unchanged — uneven shares flow through `compute_balances` transparently.

### B6. Callback router (`bot/main.py`)
- In `_callback_dispatcher` add a branch:
  `if data in {"sev", "sun", "sback", "scancel"}: await on_split_callback(...)`.

---

## Files touched

1. `bot/settle.py` — `Payment.shares`; `compute_balances` shares path. (B1)
2. `bot/state.py` — `Session.draft_shares`, `draft_split_order`;
   `Payment.shares`. (B2)
3. `bot/keyboards.py` — `split_keyboard()`. (B3)
4. `bot/messages.py` — summary + split-mode + uneven-share strings/buttons.
   (A7, B3)
5. `bot/handlers/dong.py` — `_disable_markup`, refactor amount/participants
   prompts to send-new + reply, `_commit_payment`, split step + uneven handler,
   summary on ادامه/تموم, drop all `message.delete()`. (A1–A6, B3–B5)
6. `bot/main.py` — route split callbacks. (B6)
7. `tests/` — see below.

---

## Verification (offline only — NO live bot test)

1. `.venv` Python: `python -m compileall bot` — syntax check.
2. `python -m pytest -q` — existing suite must stay green (settle/ledger
   unchanged for even splits).
3. **New unit tests** (`tests/`):
   - `settle.compute_balances` with explicit `shares` → correct per-person
     charges; payer credited full amount; even-split path unchanged when
     `shares=None`.
   - Worked example: A pays 100 for {A,B,C} with shares 30/30/40 → balances
     A=+70, B=−30, C=−40; `settle()` yields each debtor one payment to A.
   - `ledger.merge_invoice` folds an uneven invoice correctly (one obligation
     per debtor).
4. An async fake-driven harness check of the new flow (payer→amount→
   participants→split→commit) using `SimpleNamespace` fakes, mirroring the
   existing offline harness pattern — assert: no `edit_message_text` /
   `delete` on owner content, summary text built correctly, uneven shares
   reach `merge_invoice`.

---

## Decisions to confirm (defaults chosen; change at review if desired)

1. **Uneven entry UX:** owner replies with comma/newline-separated numbers in
   the displayed participant order (matches the existing manual-entry pattern).
   Alternative would be per-person button stepping (more taps, more messages).
   → Default: comma-separated reply.
   ANSWER: Accept newline-separated numbers only. Put a number next to each participant and the session starter will write these numbers in their message so the bot can process better which number is for which.
2. **Share validation:** shares must sum **exactly** to the paid amount.
   → Default: strict equality with a clear re-prompt on mismatch.
   ANSWER: This is acceptable
3. **Summary mentions:** plain labels, no group ping.
   → Default: plain text.
   ANSWER: Yes, in the summaries do not ping anyone. You can use the usernames and remove @ at the start so no one gets pinged. Prevent annoyance.
4. **Summary placement:** summary + "another payer?" control in one message.
   → Default: combined (per preplan wording).
   ANSWER: Go with default, as mentioned in preplan

---

## Out of scope
- No change to debtor-tab messages, reminders, persistence schema, or the
  settlement algorithm itself (only an additive shares input).
- No change to deploy/config/proxy.
