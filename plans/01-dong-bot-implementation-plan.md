# Dong Bot — Implementation Plan

> Status: DRAFT — awaiting developer go-ahead. See "Open Questions / Blockers" (section 0) first; some answers may change later sections.

---

## 0. Open Questions / Blockers (READ FIRST)

### 0.1 BLOCKER: Telegram Bot API cannot list all group members
The requirements (parts 9, 11, 12) assume the bot can "show a list of inline buttons with the username of every group member in the chat." **This is not possible with the Telegram Bot API.** A bot can:
- Get the member *count* (`getChatMemberCount`).
- Get the list of *administrators* only (`getChatAdministrators`).
- Look up a *specific* user it already knows the ID of (`getChatMember`).

There is **no API to enumerate all members** of a group/supergroup. The bot only "knows" a user once that user has interacted (sent a message) in the chat while the bot was present and running.

This collides with requirement 20 ("the bot should not hold any data at all"). To show even a partial member list, the bot must remember users it has *seen* sending messages — which is in-memory state.

**Proposed resolution (assumed in this plan, please confirm):**
- The bot keeps an **in-memory, non-persistent** roster per chat, populated from users who send messages while the bot is running. This is transient (lost on restart) and never written to disk/DB, so it honors "no persistent data."
- The member-selection lists (parts 9, 11, 12) show **users from this in-memory roster**. The "هیچکدام / None of the above" + manual-entry path is the primary way to add anyone the bot hasn't seen.
- We clearly document this limitation in the README and the admin welcome message.

If you reject in-memory rosters entirely, the only fallback is: **no member buttons at all** — every payer/participant is entered by name manually. Please choose.

ANSWER: After the bot is added to a group, it can pick a up a list of the members after it sees a message from them. No special command or anything, just a simple message from a user after the bot is added is enough. It can save the members of that group so it always has them. It should also keep the names manually added, but only for that group. Each group has its own member data. I don't know how to approach this. If this requires the bot to save anything, so be it. If a user didn't have a username, when tagging them, create a link with their first name. This functionality exists in Telegram.

### 0.2 Clarify "no data at all" (req 20)
A conversation flow inherently needs transient in-memory state (the active lock, the wizard selections, the 5-minute timer). I'm assuming "no data" means **no persistent storage** (no database, no files, nothing surviving a restart). Confirm.

ANSWER: Refer to 0.1's ANSWER

### 0.3 Debt-simplification algorithm (req 15)
I believe I understand the rule: **every debtor makes exactly ONE payment** (their whole debt goes to a single creditor); creditors may receive from several debtors and may additionally settle residuals among themselves. Section 6 specifies the algorithm I'll implement. Please skim section 6 and confirm it matches your intent, especially tie-breaking when amounts don't divide evenly.

ANSWER: DO NOT EVER ROUND UP THE NUMBERS. Keep up to 2 decimal points. Rest is good. I confirm.

### 0.4 Usernames vs. users without a @username
Many Telegram users have no `@username`. Tagging by `@username` (req 16) fails for them. Proposed: when a user has no username, tag them with an inline text-mention link (`tg://user?id=...`) using their first name. Confirm acceptable.

ANSWER: Yes this is good.

### 0.5 Inline buttons & long member lists
Telegram inline keyboards are limited (~100 buttons, and practically far fewer for readability). For large groups the member list could be unwieldy. Proposed: cap buttons at a sane number (e.g. 30) with the rest reachable via manual entry. Confirm or specify paging.

ANSWER: For now let's say that the bot can only work with less than 20 members. To display the buttons, use 2 columns. So for 20 members there will be 10 rows.

---

## 1. Technology Stack

1. **Language:** Python 3.12 (use the provided `.venv`). Matches req 20 and gives the best Telegram library support.
2. **Library:** `python-telegram-bot` v21+ (async). Provides `ConversationHandler`, `InlineKeyboardMarkup`, `JobQueue` (for the 5-minute timeout), and `CallbackQueryHandler`.
3. **Config:** environment variables only (`BOT_TOKEN`, `SUPER_ADMINS`). Optional `.env` support via `python-dotenv` for local dev.
4. **No database.** All state in-memory (section 5).
5. **Packaging:** `requirements.txt` (pinned). Dockerized on `python:3.12-slim`.

---

## 2. Project Structure (proposed)

```
dong-bot/
├── bot/
│   ├── __init__.py
│   ├── main.py             # entrypoint: build Application, register handlers, run polling
│   ├── config.py           # load BOT_TOKEN, SUPER_ADMINS, constants
│   ├── messages.py         # all Persian strings in one place
│   ├── state.py            # in-memory session/lock/roster structures
│   ├── access.py           # super-admin checks, group-only checks, add-to-group handling
│   ├── roster.py           # in-memory per-chat seen-users roster (see 0.1)
│   ├── handlers/
│   │   ├── start.py        # /start (admin vs non-admin, group vs private)
│   │   ├── membership.py   # bot added/removed from group (my_chat_member)
│   │   └── dong.py         # the "دنگ" keyword conversation wizard
│   ├── keyboards.py        # inline keyboard builders (payer, participants, etc.)
│   └── settle.py           # debt-simplification algorithm (section 6) — pure, unit-tested
├── tests/
│   └── test_settle.py      # algorithm tests incl. the two PLAN.md examples
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .env.example
├── .github/workflows/deploy.yml
└── README.md
```

---

## 3. Access Control & Lifecycle

1. **Group-only enforcement (req 1):**
   - `/start` in a **private chat** from a **non-super-admin** → general info message + repo link (req 3).
   - `/start` in a **private chat** from a **super-admin** → welcome + usage instructions (req 4).
   - The "دنگ" wizard only runs in group/supergroup chats.
2. **Bot added to a group (req 5):** handle the `my_chat_member` update. Identify the user who added the bot (`update.my_chat_member.from_user`).
   - If adder is **not** a super-admin → post the error message that only super-admins may add the bot, then the bot stays inert in that chat (ignores "دنگ").
   - If adder **is** a super-admin → bot is active in that chat.
   - Because "active in this chat" is in-memory only, document that a bot restart loses this flag. Proposed handling: on restart, re-derive permission lazily — i.e., treat a chat as authorized only if a super-admin re-adds or we can confirm via `getChatAdministrators` that a super-admin is an admin of the chat. **(Confirm preferred behavior — this ties into 0.2.)**
3. **Super-admin list:** `SUPER_ADMINS` parsed as comma/space-separated integer user IDs from env.

---

## 4. The "دنگ" Conversation Wizard

State machine driven by `ConversationHandler` (per-chat, not per-user, because of the lock).

1. **Trigger (req 7):** a group message whose text, trimmed, is exactly `دنگ`.
2. **Concurrency lock (req 8, 18):** in-memory per-chat lock keyed by `chat_id`.
   - First "دنگ" acquires the lock and becomes the *owner* (the only user the wizard accepts input from, req 14).
   - While locked, any other "دنگ" is ignored (optionally a brief "someone is already using me" reply — confirm).
3. **Greeting + payer selection (req 9):** send the greeting message tagging the owner, with an inline keyboard of roster usernames + "هیچکدام" (manual entry) + "بیخیال ❌" (cancel → "هیچ خرجی ثبت نشد." + release lock).
4. **Amount entry (req 10):** ask the amount. Accept the value **only when sent as a reply** to the bot's question (req 14) and **only from the owner**.
   - Validate: positive number, allow very large values and decimals. Use `Decimal` for precision. Reject non-numeric / ≤0 with a re-prompt.
   - Buttons: "تغییر پرداخت کننده" (back to payer), "بیخیال ❌" (cancel).
5. **Participant multi-select (req 11):** "این خرج مال کیاست؟" with toggle buttons (`🔘` unselected / `🟢` selected) + "هیچکدام" (manual) + a confirm action + "تغییر مبلغ" (back) + "بیخیال ❌".
   - Manual entry path lets the owner type names (reply-based) for unlisted members.
6. **More payers? (req 12, 13):** "کس دیگه ای هم خرج کرده؟" with member buttons + "✅ تموم". Selecting a member loops back to step 4 for that payer; "✅ تموم" proceeds to settlement.
7. **Settlement (req 16):** run section 6 algorithm, post the tagged who-pays-whom summary, release the lock.
8. **5-minute inactivity timeout (req 17):** a `JobQueue` job per active session; on each owner interaction it is rescheduled. On expiry: edit the last menu to a disabled/expired state, post a timeout note, release the lock.
9. **All wizard prompts** are sent as replies to the owner's relevant message and only accept replies/callbacks from the owner (req 14). Callback queries are validated so only the owner's `from_user.id` is honored; others get an answer-callback toast and are ignored.

---

## 5. In-Memory State Design

1. `chat_sessions: dict[chat_id, Session]` — holds lock owner, wizard step, list of payments `[(payer, Decimal amount, [participants])]`, current selections, last message id, timeout job handle.
2. `chat_rosters: dict[chat_id, dict[user_id, DisplayUser]]` — seen users (see 0.1). Bots excluded (filter `is_bot`).
3. `authorized_chats: set[chat_id]` — chats where a super-admin added the bot (see 3.2).
4. All cleared on process exit; nothing persisted.

---

## 6. Debt-Simplification Algorithm (req 15)

**Rule:** each debtor makes **exactly one** outgoing payment; creditors may receive multiple payments and may pay each other to settle residuals.

1. **Per-payment shares:** for each payment `(payer, amount, participants)`, each participant's share = `amount / len(participants)` (use `Decimal`; define rounding policy — proposed: round to whole تومان with remainder absorbed by the payer, confirm).
2. **Net balance per person:** `balance[p] = sum(amounts they paid) - sum(shares they owe)`. Positive = creditor (owed), negative = debtor (owes).
3. **Debtors are indivisible:** each debtor `d` with debt `|balance[d]|` must pay that entire amount to **one** creditor.
4. **Assignment phase:** assign each debtor to a creditor. Greedy approach: sort debtors descending; for each, pick the creditor with the largest remaining "capacity" (remaining owed) that best fits, decrementing that creditor's remaining owed. (Confirm tie-break; this reproduces both PLAN.md examples.)
5. **Creditor residual phase:** after assignment, some creditors received more than owed (over-funded) and some less (under-funded). Settle these with creditor→creditor transfers (over-funded pays under-funded). These extra transactions are allowed because the constraint only restricts *debtors*.
6. **Output:** list of `(from, to, amount)` transactions → formatted per req 16.
7. **Unit tests:** encode both worked examples from PLAN.md (the 500/450 case and the 400/600 case) and assert the resulting transaction set matches, plus the invariant "every debtor appears as `from` in at most one transaction."

---

## 7. Persian Messages (req 6)
All user-facing strings centralized in `bot/messages.py`, exactly matching the wording in PLAN.md parts 9, 10, 11, 12, plus cancel/timeout/error strings. UI is Persian-only.

---

## 8. Dockerization (req 19)
1. `Dockerfile` on `python:3.12-slim`, multi-stage if it reduces size: build deps in a builder stage, copy only the venv/site-packages into a slim runtime stage. Run as non-root user. Default `CMD` runs `python -m bot.main` (long-polling).
2. `.dockerignore` excludes `.venv`, `.git`, `plans`, tests, caches.
3. Config strictly via env vars (`BOT_TOKEN`, `SUPER_ADMINS`).

---

## 9. CI/CD — `.github/workflows/deploy.yml` (req 21)
1. On push to `main`: build the Docker image (optionally push to GHCR).
2. Deploy to a VPS over SSH (using `appleboy/ssh-action` or equivalent): pull/build image, restart the container with the configured env vars.
3. Secrets used: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `BOT_TOKEN`, `SUPER_ADMINS`. Documented in README.
4. Keep it minimal and editable so each public-repo user can adapt it to their own VPS.

---

## 10. Documentation
`README.md` covering: what the bot does, the **member-list limitation (0.1)**, how to set `SUPER_ADMINS`/`BOT_TOKEN`, how to run via Docker, and how to configure the deploy workflow.

---

## 11. Implementation Order (once approved)
1. Scaffolding: `config.py`, `messages.py`, `state.py`, `main.py` skeleton.
2. `settle.py` + `tests/test_settle.py` (pure logic first; verify against PLAN.md examples).
3. Access control: `/start`, `my_chat_member` membership handling.
4. Roster tracking.
5. The "دنگ" `ConversationHandler` wizard (steps 9–14), lock, reply-only/owner-only enforcement.
6. 5-minute timeout via JobQueue.
7. Settlement output formatting (req 16).
8. Dockerfile + `.dockerignore` + `.env.example`.
9. `deploy.yml`.
10. README.

---

## 12. Risks / Notes
- Member enumeration limitation (0.1) is the biggest UX constraint; manual entry is the safety net.
- Long-polling assumed (simplest for self-hosting); webhooks can be added later if desired.
- Restart loses all in-memory state (active sessions, rosters, authorized-chat flags) — acceptable under "no persistent data," but worth stating to users.
