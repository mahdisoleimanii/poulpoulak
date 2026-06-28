"""The "دنگ" keyword conversation wizard (reqs 7-18).

Concurrency: per-chat lock. First "دنگ" acquires the lock; others are ignored
(req 8/18). Only the lock owner can drive the wizard (req 14).

The wizard is implemented directly with ``update`` callbacks rather than via
``ConversationHandler``: per-chat (not per-user) state, an in-memory lock, and
owner-only enforcement are simpler to express with explicit dispatch.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from .. import access, config, ledger, messages, roster as roster_mod, settle, state
from ..keyboards import (
    amount_keyboard,
    more_payers_keyboard,
    participants_keyboard,
    payer_keyboard,
    split_keyboard,
    uneven_keyboard,
)
from ..roster import find, members, mention_user
from ..settle import Payment as SettlePayment
from . import tabs


log = logging.getLogger(__name__)

KEYWORD = "دنگ"
DECIMAL_RE = re.compile(r"^\s*-?\d+(?:[.,]\d+)?\s*$")


# ---------- helpers --------------------------------------------------------

def _is_group(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def _owner_only(session: state.Session, user_id: int | None) -> bool:
    return user_id is not None and session.owner_id == user_id


async def _disable_markup(context, chat_id: int, message_id: int | None) -> None:
    """Strip the inline buttons off a message without touching its text.

    This is the "good practice" the developer asked for: instead of editing a
    prompt's text to repurpose it, we just disable its buttons and send a fresh
    message for the next step. No-op on failure (message gone / no markup).
    """
    if message_id is None:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except Exception:
        pass


def _fmt_amount(value) -> str:
    """Render a Decimal amount without a needless ``.00`` tail."""
    d = Decimal(str(value))
    if d == d.to_integral_value():
        return str(int(d))
    return str(settle.quantize_down(d))


def _strip_at(label: str) -> str:
    """Drop a leading ``@`` so summary labels do not ping anyone."""
    return label[1:] if label.startswith("@") else label


def _summary_blocks(session: state.Session) -> list[tuple[str, str, str]]:
    """Build the (payer, amount, participants) blocks for ``messages.summary``."""
    blocks: list[tuple[str, str, str]] = []
    for p in session.payments:
        payer = _strip_at(p.payer_label)
        if p.shares:
            people = " - ".join(
                f"{_strip_at(label)} ({_fmt_amount(p.shares[key])})"
                for key, label in zip(p.participant_keys, p.participant_labels)
            )
        else:
            people = " - ".join(_strip_at(label) for label in p.participant_labels)
        blocks.append((payer, _fmt_amount(p.amount), people))
    return blocks


def _schedule_timeout(
    context: ContextTypes.DEFAULT_TYPE, session: state.Session
) -> None:
    if context.job_queue is None:
        return
    if session.timeout_job is not None:
        try:
            session.timeout_job.schedule_removal()
        except Exception:
            pass
        session.timeout_job = None
    session.timeout_job = context.job_queue.run_once(
        _on_timeout,
        when=config.SESSION_TIMEOUT_SECONDS,
        data=session.chat_id,
        name=f"dong-timeout:{session.chat_id}",
    )


def _end_session(chat_id: int, owner_id: int | None) -> None:
    session = state.get_session(chat_id)
    if session is None:
        return
    if owner_id is not None and session.owner_id != owner_id:
        return
    if session.timeout_job is not None:
        try:
            session.timeout_job.schedule_removal()
        except Exception:
            pass
    state.end_session(chat_id)


async def _on_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data
    session = state.get_session(chat_id)
    if session is None:
        return
    log.info("chat %s: session timed out after inactivity", chat_id)
    if session.menu_message_id is not None:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=session.menu_message_id,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⏰ منقضی شد", callback_data="noop")]]
                ),
            )
        except Exception:
            pass
    try:
        await context.bot.send_message(chat_id, messages.TIMEOUT)
    except Exception:
        pass
    _end_session(chat_id, owner_id=None)


# ---------- universal owner guard (callback + message) ----------------------

async def _guard_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> state.Session | None:
    """Return the active session if the callback is from the owner, else None."""
    query = update.callback_query
    if query is None:
        return None
    chat = query.message.chat_id if query.message else None
    session = state.get_session(chat) if chat is not None else None
    if session is None:
        try:
            await query.answer()
        except Exception:
            pass
        return None
    if not _owner_only(session, query.from_user.id):
        try:
            await query.answer(messages.ONLY_OWNER, show_alert=True)
        except Exception:
            pass
        return None
    return session


async def _guard_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> state.Session | None:
    """Return the active session if the message is from the owner, else None."""
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return None
    session = state.get_session(chat.id)
    if session is None:
        return None
    # Non-owners are filtered (silently) by the router; no nagging here.
    if not _owner_only(session, message.from_user.id if message.from_user else None):
        return None
    return session


# ---------- router for group messages while a session is active ------------

async def on_group_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a non-keyword group message.

    The bot stays silent on ordinary chatter. It only acts when the message is
    a *reply to its current prompt*, sent by the session owner (req 14). Every
    other message is ignored — we just quietly learn the sender into the roster.
    """
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None or not _is_group(update):
        return

    # Learn anyone who speaks, with or without an active session (0.1).
    user = message.from_user
    if user is not None and not user.is_bot:
        roster_mod.remember_user(
            chat.id, user.id, user.username, user.first_name, bool(user.is_bot)
        )

    session = state.get_session(chat.id)
    if session is None:
        return

    expected = session.awaiting_reply
    if expected is None:
        return  # waiting on a button press, not text

    # Only a reply to our prompt counts — ignore all other messages silently.
    if (
        message.reply_to_message is None
        or session.prompt_message_id is None
        or message.reply_to_message.message_id != session.prompt_message_id
    ):
        return
    # Only the owner drives the wizard; ignore everyone else silently.
    if not _owner_only(session, user.id if user else None):
        return

    log.info("chat %s: owner reply for step '%s'", chat.id, expected)
    if expected == "manual_payer":
        await on_manual_payer_message(update, context)
    elif expected == "amount":
        await on_amount_message(update, context)
    elif expected == "manual_participants":
        await on_manual_participants_message(update, context)
    elif expected == "uneven_shares":
        await on_uneven_shares_message(update, context)


# ---------- entry: the "دنگ" keyword ----------------------------------------

async def on_dong_keyword(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Triggered by a group message whose text is exactly "دنگ"."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None or not _is_group(update):
        return

    if (message.text or "").strip() != KEYWORD:
        return

    if not access.is_authorized_chat(chat.id):
        log.info("keyword in unauthorized chat %s — ignored", chat.id)
        return

    roster_mod.remember_user(
        chat.id, user.id, user.username, user.first_name, bool(user.is_bot)
    )

    if state.is_locked(chat.id):
        log.info("chat %s busy; keyword from %s ignored", chat.id, user.id)
        try:
            await message.reply_text(messages.BUSY)
        except Exception:
            pass
        return

    session = state.start_session(
        chat_id=chat.id,
        owner_id=user.id,
        owner_username=user.username,
        owner_first_name=user.first_name,
    )
    log.info("chat %s: session started by owner %s", chat.id, user.id)
    _schedule_timeout(context, session)
    await _show_payer_prompt(context, session)


# ---------- step: pick payer ------------------------------------------------

async def _show_payer_prompt(context, session) -> None:
    chat_members = members(session.chat_id)
    mention = mention_user(
        session.owner_id, session.owner_username, session.owner_first_name
    )
    text = messages.greeting(mention)
    if not chat_members:
        text += "\n\n" + messages.NO_ROSTER
    sent = await context.bot.send_message(
        session.chat_id, text, reply_markup=payer_keyboard(chat_members)
    )
    session.menu_message_id = sent.message_id
    session.prompt_message_id = sent.message_id
    session.awaiting_reply = None
    _schedule_timeout(context, session)


async def on_payer_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    session = await _guard_callback(update, context)
    if session is None:
        return
    await query.answer()

    data = query.data or ""
    if data == "pcancel":
        await _cancel(context, session)
        return
    if data == "pno":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _ask_manual_payer(context, session)
        return
    if data.startswith("pay|"):
        key = data[len("pay|"):]
        member = find(session.chat_id, key)
        if member is None:
            return
        session.draft_payer_key = member.key
        session.draft_payer_label = member.label
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _show_amount_prompt(context, session)
        return


async def _ask_manual_payer(context, session) -> None:
    prompt = await context.bot.send_message(
        session.chat_id, messages.ASK_MANUAL_PAYER
    )
    session.menu_message_id = prompt.message_id
    session.prompt_message_id = prompt.message_id
    session.awaiting_reply = "manual_payer"
    _schedule_timeout(context, session)


async def on_manual_payer_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    session = await _guard_message(update, context)
    if session is None or message is None:
        return
    if session.awaiting_reply != "manual_payer":
        return
    name = (message.text or "").strip()
    if not name:
        try:
            await message.reply_text(messages.ASK_MANUAL_PAYER)
        except Exception:
            pass
        return

    roster_mod.add_manual_name(session.chat_id, name)
    member = find(session.chat_id, f"m{name.strip()}")
    if member is None:
        return
    session.draft_payer_key = member.key
    session.draft_payer_label = member.label
    session.awaiting_reply = None
    await _disable_markup(context, session.chat_id, session.menu_message_id)
    await _show_amount_prompt(context, session, reply_to=message.message_id)


# ---------- step: amount ----------------------------------------------------

async def _show_amount_prompt(context, session, reply_to=None) -> None:
    # Show the payer's name, not the session owner — so it is clear who paid.
    # Always send a NEW message (never edit a previous prompt's text).
    payer_tag = session.draft_payer_label or "?"
    if session.draft_payer_key and session.draft_payer_key.startswith("u"):
        member = find(session.chat_id, session.draft_payer_key)
        if member is not None and member.user_id is not None:
            payer_tag = mention_user(
                member.user_id, member.username, member.first_name
            )
    text = messages.ask_amount(payer_tag)
    sent = await context.bot.send_message(
        session.chat_id,
        text,
        reply_markup=amount_keyboard(),
        reply_to_message_id=reply_to,
    )
    session.menu_message_id = sent.message_id
    session.prompt_message_id = sent.message_id
    session.awaiting_reply = "amount"
    _schedule_timeout(context, session)


async def on_amount_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    session = await _guard_callback(update, context)
    if session is None:
        return
    await query.answer()
    data = query.data or ""
    if data == "acancel":
        await _cancel(context, session)
        return
    if data == "achange":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _show_payer_prompt(context, session)
        return


async def on_amount_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    session = await _guard_message(update, context)
    if session is None or message is None:
        return
    if session.awaiting_reply != "amount":
        return

    raw = (message.text or "").strip().replace(",", ".")
    if not raw or not DECIMAL_RE.match(raw):
        try:
            await message.reply_text(messages.INVALID_AMOUNT)
        except Exception:
            pass
        return
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        try:
            await message.reply_text(messages.INVALID_AMOUNT)
        except Exception:
            pass
        return
    if amount <= 0:
        try:
            await message.reply_text(messages.INVALID_AMOUNT)
        except Exception:
            pass
        return

    session.draft_amount = amount
    session.awaiting_reply = None
    await _disable_markup(context, session.chat_id, session.menu_message_id)
    await _show_participants_prompt(context, session, reply_to=message.message_id)


# ---------- step: pick participants -----------------------------------------

async def _show_participants_prompt(context, session, reply_to=None) -> None:
    chat_members = members(session.chat_id)
    sent = await context.bot.send_message(
        session.chat_id,
        messages.ASK_PARTICIPANTS,
        reply_markup=participants_keyboard(chat_members, session.draft_participants),
        reply_to_message_id=reply_to,
    )
    session.menu_message_id = sent.message_id
    session.prompt_message_id = sent.message_id
    session.awaiting_reply = None
    _schedule_timeout(context, session)


async def on_participant_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    session = await _guard_callback(update, context)
    if session is None:
        return
    await query.answer()
    data = query.data or ""

    if data == "ppcancel":
        await _cancel(context, session)
        return
    if data == "pback":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _show_amount_prompt(context, session)
        return
    if data == "pmanual":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _ask_manual_participants(context, session)
        return
    if data.startswith("ptog|"):
        key = data[len("ptog|"):]
        if key in session.draft_participants:
            session.draft_participants.discard(key)
        else:
            session.draft_participants.add(key)
        chat_members = members(session.chat_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=participants_keyboard(
                    chat_members, session.draft_participants
                )
            )
        except Exception:
            pass
        _schedule_timeout(context, session)
        return
    if data == "pok":
        if not session.draft_participants:
            try:
                await query.answer(messages.NO_PARTICIPANTS_SELECTED, show_alert=True)
            except Exception:
                pass
            return
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _show_split_prompt(context, session)
        return


async def _ask_manual_participants(context, session) -> None:
    prompt = await context.bot.send_message(
        session.chat_id, messages.ASK_MANUAL_PARTICIPANTS
    )
    session.menu_message_id = prompt.message_id
    session.prompt_message_id = prompt.message_id
    session.awaiting_reply = "manual_participants"
    _schedule_timeout(context, session)


async def on_manual_participants_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    session = await _guard_message(update, context)
    if session is None or message is None:
        return
    if session.awaiting_reply != "manual_participants":
        return
    names = [n.strip() for n in re.split(r"[،,\n]", message.text or "") if n.strip()]
    if not names:
        try:
            await message.reply_text(messages.ASK_MANUAL_PARTICIPANTS)
        except Exception:
            pass
        return
    for n in names:
        roster_mod.add_manual_name(session.chat_id, n)
        session.draft_participants.add(f"m{n}")
    chat_members = members(session.chat_id)
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=session.chat_id,
            message_id=session.menu_message_id,
            reply_markup=participants_keyboard(
                chat_members, session.draft_participants
            ),
        )
    except Exception:
        pass
    _schedule_timeout(context, session)


# ---------- step: choose split (even / uneven) ------------------------------

async def _show_split_prompt(context, session) -> None:
    """After participants are picked, ask how to split this payment."""
    sent = await context.bot.send_message(
        session.chat_id, messages.ASK_SPLIT_MODE, reply_markup=split_keyboard()
    )
    session.menu_message_id = sent.message_id
    session.prompt_message_id = sent.message_id
    session.awaiting_reply = None
    _schedule_timeout(context, session)


def _ordered_participants(session) -> list:
    """Selected participants in stable roster order (for prompts + commit)."""
    return [m for m in members(session.chat_id) if m.key in session.draft_participants]


async def on_split_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    session = await _guard_callback(update, context)
    if session is None:
        return
    await query.answer()
    data = query.data or ""

    if data == "scancel":
        await _cancel(context, session)
        return
    if data == "sback":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        session.draft_split_order = []
        session.draft_shares = None
        await _show_participants_prompt(context, session)
        return
    if data == "sev":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        _commit_payment(session, shares=None)
        await _show_summary_and_more(context, session)
        return
    if data == "sun":
        ordered = _ordered_participants(session)
        if not ordered:
            return
        session.draft_split_order = [m.key for m in ordered]
        labels = [m.label for m in ordered]
        await _disable_markup(context, session.chat_id, query.message.message_id)
        sent = await context.bot.send_message(
            session.chat_id,
            messages.ask_uneven_shares(labels, _fmt_amount(session.draft_amount)),
            reply_markup=uneven_keyboard(),
        )
        session.menu_message_id = sent.message_id
        session.prompt_message_id = sent.message_id
        session.awaiting_reply = "uneven_shares"
        _schedule_timeout(context, session)
        return


async def on_uneven_shares_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    session = await _guard_message(update, context)
    if session is None or message is None:
        return
    if session.awaiting_reply != "uneven_shares":
        return

    order = session.draft_split_order
    tokens = [t.strip() for t in (message.text or "").split("\n") if t.strip()]
    if len(tokens) != len(order):
        try:
            await message.reply_text(messages.uneven_count_mismatch(len(order)))
        except Exception:
            pass
        return

    shares_list: list[Decimal] = []
    for tok in tokens:
        raw = tok.replace(",", ".")
        if not DECIMAL_RE.match(raw):
            try:
                await message.reply_text(messages.INVALID_AMOUNT)
            except Exception:
                pass
            return
        try:
            val = Decimal(raw)
        except InvalidOperation:
            try:
                await message.reply_text(messages.INVALID_AMOUNT)
            except Exception:
                pass
            return
        if val < 0:
            try:
                await message.reply_text(messages.INVALID_AMOUNT)
            except Exception:
                pass
            return
        shares_list.append(settle.quantize_down(val))

    total = sum(shares_list, Decimal("0"))
    expected = settle.quantize_down(session.draft_amount or Decimal("0"))
    if total != expected:
        try:
            await message.reply_text(
                messages.uneven_sum_mismatch(_fmt_amount(expected))
            )
        except Exception:
            pass
        return

    session.draft_shares = {key: val for key, val in zip(order, shares_list)}
    _commit_payment(session, shares=session.draft_shares)
    await _show_summary_and_more(context, session)


# ---------- commit + "more payers?" -----------------------------------------

def _commit_payment(session, shares) -> None:
    """Record the drafted payment and reset the draft. Pure state mutation."""
    ordered = _ordered_participants(session)
    participant_keys = [m.key for m in ordered]
    participant_labels = [m.label for m in ordered]
    payer_label = session.draft_payer_label or "?"
    session.payments.append(
        state.Payment(
            payer_key=session.draft_payer_key or "?",
            payer_label=payer_label,
            amount=session.draft_amount or Decimal("0"),
            participant_keys=participant_keys,
            participant_labels=participant_labels,
            shares=shares,
        )
    )
    log.info(
        "chat %s: recorded payment %s paid %s for %d people, %s split "
        "(total %d so far)",
        session.chat_id, payer_label, session.draft_amount,
        len(participant_keys), "uneven" if shares else "even",
        len(session.payments),
    )
    session.draft_payer_key = None
    session.draft_payer_label = None
    session.draft_amount = None
    session.draft_participants = set()
    session.draft_shares = None
    session.draft_split_order = []
    session.awaiting_reply = None


async def _show_summary_and_more(context, session) -> None:
    """Send the running summary plus the 'another payer?' menu as one message."""
    chat_members = members(session.chat_id)
    text = (
        messages.summary(_summary_blocks(session))
        + "\n\n"
        + messages.ASK_MORE_PAYERS
    )
    sent = await context.bot.send_message(
        session.chat_id, text, reply_markup=more_payers_keyboard(chat_members)
    )
    session.menu_message_id = sent.message_id
    session.prompt_message_id = sent.message_id
    session.awaiting_reply = None
    _schedule_timeout(context, session)


# ---------- step: more payers? ---------------------------------------------

async def on_more_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    session = await _guard_callback(update, context)
    if session is None:
        return
    await query.answer()
    data = query.data or ""

    if data == "mcancel":
        await _cancel(context, session)
        return
    if data == "done":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        # Re-send the summary as its own message before settling (req: don't
        # repurpose the menu message).
        try:
            await context.bot.send_message(
                session.chat_id, messages.summary(_summary_blocks(session))
            )
        except Exception:
            pass
        await _settle(context, session)
        return
    if data == "moreno":
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _ask_manual_payer(context, session)
        return
    if data.startswith("more|"):
        key = data[len("more|"):]
        member = find(session.chat_id, key)
        if member is None:
            return
        session.draft_payer_key = member.key
        session.draft_payer_label = member.label
        await _disable_markup(context, session.chat_id, query.message.message_id)
        await _show_amount_prompt(context, session)
        return


# ---------- settlement ------------------------------------------------------

def _build_label_map(chat_id: int) -> dict[str, str]:
    """key -> display label, from the current roster plus carried tab labels."""
    label_map = {m.key: m.label for m in members(chat_id)}
    for o in ledger.load_obligations(chat_id):
        label_map.setdefault(o.src, o.src_label)
        label_map.setdefault(o.dst, o.dst_label)
    return label_map


async def _settle(context, session) -> None:
    """Finish the wizard: fold this invoice into the persistent tab and message
    each debtor (replacing the old one-shot summary)."""
    chat_id = session.chat_id
    settle_payments = [
        SettlePayment(
            payer=p.payer_key,
            amount=p.amount,
            participants=tuple(p.participant_keys),
            shares=(
                tuple((k, p.shares[k]) for k in p.participant_keys)
                if p.shares
                else None
            ),
        )
        for p in session.payments
        if p.participant_keys
    ]
    if not settle_payments:
        try:
            await context.bot.send_message(chat_id, messages.NOTHING_TO_SETTLE)
        except Exception:
            pass
        _end_session(chat_id, session.owner_id)
        return

    # Neutralise any previous tab messages/reminders before replacing the tab.
    await tabs.deactivate_all(context, chat_id)

    label_map = _build_label_map(chat_id)
    obligations = ledger.merge_invoice(chat_id, settle_payments, label_map)
    log.info(
        "chat %s: merged %d payment(s) -> %d outstanding obligation(s)",
        chat_id, len(settle_payments), len(obligations),
    )

    if not obligations:
        try:
            await context.bot.send_message(chat_id, messages.TAB_ALL_SETTLED)
        except Exception:
            pass
        _end_session(chat_id, session.owner_id)
        return

    owner_mention = roster_mod.mention_html_user(
        session.owner_id, session.owner_username, session.owner_first_name
    )
    try:
        await tabs.dispatch(context, chat_id, session.owner_id, owner_mention)
    except Exception:
        log.exception("chat %s: failed to dispatch debtor tabs", chat_id)
    _end_session(chat_id, session.owner_id)


async def _cancel(context, session) -> None:
    log.info("chat %s: cancelled by owner %s", session.chat_id, session.owner_id)
    try:
        await context.bot.send_message(session.chat_id, messages.CANCELLED)
    except Exception:
        pass
    _end_session(session.chat_id, session.owner_id)