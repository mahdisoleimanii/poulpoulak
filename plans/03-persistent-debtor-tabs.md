# Plan 03 — Persistent debtor tabs with confirmation buttons

## Goal
Replace the one-shot "who owes whom" settlement summary with a **persistent,
per-debtor tab system**:

- After the session owner finishes (`done`), instead of one summary message, the
  bot messages **each person who must pay** (the `src` of every settlement
  transaction).
- **Real Telegram users** get a tagged message + a two-step confirm button
  (anti-misclick), locked to that user, re-sent every 6 hours until confirmed.
- **Manually-added debtors** can't be tagged, so they're grouped into one message
  tagging the **session owner**, who toggles who has paid and confirms.
- Unpaid tabs **persist across invoices**: a new invoice adds to the outstanding
  balance and the bot always recomputes the most-efficient split (each debtor
  pays once), then re-sends with the new amount.

This builds on the existing pure settlement algorithm (`bot/settle.py`,
unchanged) and the current key-based session payments (`payer_key`,
`participant_keys` already exist on `state.Payment`).

---

## Key design decisions (please review these first)

1. **Source of truth = persisted outstanding transactions** (not net balances).
   On each new invoice we reconstruct net balances from the outstanding
   transactions, add the new invoice's balance delta, then `simplify()` again.
   Confirming a payment simply removes that transaction. This avoids the
   net-balance/residual-confirmation paradox and keeps "each debtor pays once".

2. **No need to re-persist the manual roster.** Each stored obligation carries
   its own `src_label`/`dst_label`, and real users are already persisted in the
   `users` blob (for tagging). So manual debtors survive across invoices via the
   obligation labels — **plan-02 (session-scoped manual names) stays as-is**, and
   the suggested `git restore` is **not** needed. (If you'd rather I restore
   global manual persistence instead, say so — but it isn't required.)

3. **"Debtor" = `src` of any settlement transaction.** Genuine debtors have one
   transaction; over-funded creditors can have residual `creditor→creditor`
   transfers. We **group transactions by `src`** and send one message per `src`
   (one confirm clears all of that src's lines). For real groups this is almost
   always a single line. This keeps the full settlement correct, not just the
   "pure debtor" subset. (If you want residual creditors excluded from messaging,
   tell me — but then money wouldn't fully settle.)

4. **On a new invoice we refresh everything**: disable the buttons on all
   previous tab messages, cancel their reminder jobs, recompute, and send fresh
   messages to all current debtors. Simpler and matches "re-send with the new
   amount" + "disable previous reminder buttons".

5. **Reminders use `JobQueue.run_repeating`** (6h). Because PTB jobs are
   in-memory, we persist `last_sent` per real debtor and **reschedule on startup**
   via an Application `post_init` hook.

---

## Data model (persisted in `data/rosters.json`)

Add a `tabs` object under each chat alongside `users`/`manual`:

```jsonc
rosters["<chat_id>"] = {
  "users": { ... },          // unchanged (seen users, for tagging)
  "manual": [ ... ],         // unchanged (plan-02 leaves this empty)
  "tabs": {
    "obligations": [
      { "src": "u123", "src_label": "Ali",
        "dst": "u456", "dst_label": "@sara", "amount": "150.00" }
    ],
    "real_msgs": {                       // one entry per REAL-user src
      "u123": { "message_id": 789, "stage": "prompt", "last_sent": 1690000000.0 }
    },
    "manual_msg": {                      // single owner-facing message, or null
      "message_id": 555, "owner_id": 111, "selected": ["mBob"]
    }
  }
}
```

- `stage` ∈ `"prompt"` (showing "دنگمو دادم") | `"confirm"` (showing
  "تایید میکنم دنگمو دادم").
- `amount` stored as a string (Decimal-safe), like nothing else here needs.
- Keys (`u<id>` / `m<name>`) are the existing `roster.user_key` / `manual_key`.

---

## Steps

### 1. `bot/config.py`
- Add `REMINDER_INTERVAL_SECONDS = int(os.environ.get("REMINDER_INTERVAL_SECONDS", "21600"))`
  (6 hours) and document it in the module docstring.

### 2. `bot/store.py`
- In `load()` defaults / docstring, note the new `tabs` sub-object. No structural
  migration needed — readers use `.get("tabs", {...})` defensively.

### 3. `bot/ledger.py` (NEW — pure-ish persistence + logic, no Telegram imports)
Encapsulates all tab bookkeeping so handlers stay thin and it's unit-testable.

- `@dataclass Obligation(src, src_label, dst, dst_label, amount: Decimal)`.
- `_tabs_blob(data, chat_id)` → ensures `{obligations, real_msgs, manual_msg}`.
- `load_obligations(chat_id) -> list[Obligation]`.
- `balances_from_obligations(obls) -> dict[str, Decimal]`
  (`src -= amount`, `dst += amount`).
- `merge_invoice(chat_id, new_payments: list[settle.Payment], label_map) -> list[Obligation]`:
  1. reconstruct balances from current outstanding obligations,
  2. add `compute_balances(new_payments)` (computed over **keys**),
  3. `simplify()` → transactions,
  4. wrap as `Obligation`s using `label_map` (key→label), filtering zero amounts,
  5. **persist** as the new `obligations`, reset `real_msgs`/`manual_msg`,
  6. return the new obligations.
- `group_by_src(obls) -> dict[str, list[Obligation]]`.
- `confirm_real(chat_id, src_key)`: remove all obligations with that `src`,
  drop `real_msgs[src]`, persist.
- `set_real_msg(chat_id, src_key, message_id, stage, last_sent)` / getters.
- `toggle_manual_selected(chat_id, src_key)` / `set_manual_msg(...)`.
- `confirm_manual(chat_id) -> (settled: list[Obligation], remaining_srcs: list[str])`:
  remove obligations whose `src` is in `manual_msg.selected`; return what was
  settled and which manual srcs remain unpaid; persist.
- `active_real_srcs(chat_id)` (for startup rescheduling).
- Helpers to classify a key as real vs manual: `is_real_key(k) = k.startswith("u")`.

### 4. `bot/messages.py`
Add strings:
- `def debtor_tab(src_tag, amount, dst_tag)` → e.g.
  `"{src_tag} 👋\nسهم تو از دنگ: {amount} تومن\nباید بدی به: {dst_tag}"`.
- `DOUBLE_CONFIRM_SUFFIX = "\n\n⚠️ دوباره تایید کن"` (appended on first press).
- `def debtor_paid(src_tag, dst_tag, amount)` → settled-state text.
- `def manual_settle(owner_tag, lines: list[str])` + `manual_line(label, amount, dst)`.
- `def manual_settled_summary(lines)` (post-confirm "who paid whom").
- `TAB_ALL_SETTLED = "همه دنگا تسویه شد! 🎉"`.
- `NOT_YOUR_BUTTON = "این دکمه مال تو نیست 🙂"` (lock alert).
- Button labels: `BTN_PAID = "دنگمو دادم"`,
  `BTN_PAID_CONFIRM = "تایید میکنم دنگمو دادم"`,
  `BTN_MANUAL_CONFIRM = "✅ تایید"`, `BTN_EXPIRED = "⏰ غیرفعال"`.
- Keep existing `SETTLEMENT_HEADER`/`settlement_line` (reused for manual summary).

### 5. `bot/keyboards.py`
New builders + callback scheme (documented in the header):
- `paid1|<srckey>` → `debtor_prompt_keyboard(src_key)`: one button `BTN_PAID`.
- `paid2|<srckey>` → `debtor_confirm_keyboard(src_key)`: one button
  `BTN_PAID_CONFIRM`.
- `mtog|<srckey>` + `mconf` → `manual_settle_keyboard(srcs, selected)`: a toggle
  per manual src (✓ marker reuse `SELECTED`/`UNSELECTED`) and a `BTN_MANUAL_CONFIRM`.
- `disabled_keyboard()` → single inert `BTN_EXPIRED` button with `callback_data="noop"`.

### 6. `bot/handlers/dong.py`
- **Replace `_settle`** with logic that:
  1. builds `settle.Payment` list from `session.payments` using **keys**
     (`payer=p.payer_key`, `participants=tuple(p.participant_keys)`),
  2. builds a `label_map` from current session members + existing obligation
     labels + (for real users) roster `users` data,
  3. calls `ledger.merge_invoice(...)`,
  4. **disables old tab messages** (edit markup → `disabled_keyboard()`) and
     cancels old reminder jobs (via `reminders.cancel_all(context, chat_id)`),
  5. if no obligations → send `TAB_ALL_SETTLED`, clear tabs, end session,
  6. else `await _dispatch_tabs(context, chat_id)` and end session.
- New `_dispatch_tabs(context, chat_id)`:
  - `groups = ledger.group_by_src(load_obligations)`.
  - For each **real** src: `await _send_debtor_message(...)` (sends the prompt,
    stores `real_msgs[src]` with `last_sent=now`, schedules a 6h repeating job).
  - For all **manual** srcs together: `await _send_manual_message(...)` to the
    session owner (stores `manual_msg`).
- New callbacks (wired through `main._callback_dispatcher`):
  - `on_paid_callback` for `paid1|` / `paid2|`:
    - lock: `query.from_user.id == int(src[1:])` else alert `NOT_YOUR_BUTTON`.
    - `paid1` → edit text (+suffix) & markup→confirm keyboard, set stage.
    - `paid2` → `ledger.confirm_real`, edit message → `debtor_paid(...)` (no
      buttons), `reminders.cancel(context, chat_id, src)`, and if no obligations
      remain post-removal, optionally post `TAB_ALL_SETTLED`.
  - `on_manual_settle_callback` for `mtog|` / `mconf`:
    - lock to `manual_msg.owner_id`.
    - `mtog` → `ledger.toggle_manual_selected`, edit markup.
    - `mconf` → `ledger.confirm_manual` → edit current message to remove buttons
      and show settled summary; if `remaining_srcs`, send a NEW manual message for
      them (update `manual_msg`); else clear `manual_msg`.
- `_tag_for_key(chat_id, key, label)` helper: real → `mention_user` via roster
  `users` lookup; manual → plain `label`. Replaces `_tag_member`.

### 7. `bot/handlers/reminders.py` (NEW)
- `JOB_PREFIX = "dong-remind"`; `job_name(chat_id, src) -> str`.
- `async def reminder_job(context)`: data=`(chat_id, src)`. If the obligation for
  `src` is gone → remove job & return. Else: disable the previous message's markup
  (`disabled_keyboard()`), re-send the same debtor prompt (fresh message_id),
  update `real_msgs[src].last_sent`/`message_id`/`stage="prompt"`, persist.
  (`run_repeating` keeps the 6h cadence automatically.)
- `schedule(context, chat_id, src, first)` / `cancel(context, chat_id, src)` /
  `cancel_all(context, chat_id)`.
- `async def reschedule_all(app)`: startup hook — for every chat's active
  `real_msgs`, compute `first = max(0, interval - (now - last_sent))` and
  `run_repeating`. Used as `post_init`.

### 8. `bot/main.py`
- Import the new callbacks; extend `_callback_dispatcher` with prefixes
  `paid1|`, `paid2|`, `mtog|`, `mconf` (and keep `noop` → silent answer).
- Add `.post_init(reminders.reschedule_all)` to the Application builder so
  reminders survive restarts.

### 9. `CHANGELOG.md`
- Document the new persistent-tabs flow, the 6h reminders, the manual owner-driven
  settlement, and that settlement summaries were replaced.

### 10. Tests (`tests/`)
- `tests/test_ledger.py` (pure, no Telegram):
  - merge of a single invoice yields one obligation per debtor;
  - a second invoice on top of an unpaid first **accumulates** and still yields
    one payment per debtor (key invariant);
  - `confirm_real` removes the obligation and zeroes that debtor's effect;
  - `confirm_manual` settles selected and returns the remaining srcs;
  - `balances_from_obligations` round-trips with `simplify`.
- Keep the existing 8 `settle` tests untouched.

---

## Flow summaries

**Real debtor:** message (tag + amount + "دنگمو دادم") → press → same message gains
"دوباره تایید کن" + "تایید میکنم دنگمو دادم" → press → "✅ پرداخت شد", tab cleared,
reminder stopped. Every 6h until confirmed: old message buttons disabled, new
identical message sent.

**Manual debtors:** one message to the owner listing each manual debtor's
obligation + a toggle each + "✅ تایید". Owner toggles the paid ones → confirm →
buttons removed, settled ones summarised; if any remain, a fresh message is sent
for the remaining ones.

**New invoice with old unpaid tabs:** balances reconstructed from outstanding +
new delta → re-`simplify()` (one payment per debtor) → all old tab messages
disabled & reminder jobs cancelled → fresh messages with the new totals.

---

## Verification (offline only — DO NOT live bot test)
1. `python -m compileall bot` clean; `import bot.main` OK.
2. `.venv` `pytest -q` — existing 8 settle tests pass + new ledger tests pass.
3. Targeted offline checks of `bot/ledger.py`:
   - two stacked invoices → each debtor still appears as `src` at most once;
   - `confirm_real` / `confirm_manual` mutate `obligations` and persist;
   - a temp `DATA_DIR` shows `tabs` written and read back correctly.
4. Static check that `_callback_dispatcher` routes every new prefix.

## Notes / open questions for you
- **Residual creditors** (decision #3): include them in messaging (correct, may
  occasionally ask a net-creditor to forward surplus) — confirm you're OK with
  this, or I'll restrict messaging to genuine debtors only.
- **6h cadence** is configurable via `REMINDER_INTERVAL_SECONDS` for testing.
- No reminders for manual debtors (owner-driven), per the spec.
