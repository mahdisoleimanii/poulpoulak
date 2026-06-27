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

from .. import access, config, ledger, messages, roster as roster_mod, state
from ..keyboards import (
    amount_keyboard,
    more_payers_keyboard,
    participants_keyboard,
    payer_keyboard,
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
        await _ask_manual_payer(context, session)
        return
    if data.startswith("pay|"):
        key = data[len("pay|"):]
        member = find(session.chat_id, key)
        if member is None:
            return
        session.draft_payer_key = member.key
        session.draft_payer_label = member.label
        await _show_amount_prompt(context, session, query=query)
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
    try:
        await message.delete()
    except Exception:
        pass
    await _show_amount_prompt(context, session, query=None)


# ---------- step: amount ----------------------------------------------------

async def _show_amount_prompt(context, session, query=None) -> None:
    mention = mention_user(
        session.owner_id, session.owner_username, session.owner_first_name
    )
    text = messages.ask_amount(mention)
    sent = None
    if query is not None and query.message is not None:
        try:
            await query.edit_message_text(text, reply_markup=amount_keyboard())
            sent = query.message
        except Exception:
            pass
    if sent is None:
        sent = await context.bot.send_message(
            session.chat_id, text, reply_markup=amount_keyboard()
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
    try:
        await message.delete()
    except Exception:
        pass
    await _show_participants_prompt(context, session)


# ---------- step: pick participants -----------------------------------------

async def _show_participants_prompt(context, session) -> None:
    chat_members = members(session.chat_id)
    sent = await context.bot.send_message(
        session.chat_id,
        messages.ASK_PARTICIPANTS,
        reply_markup=participants_keyboard(chat_members, session.draft_participants),
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
        await _show_amount_prompt(context, session, query=query)
        return
    if data == "pmanual":
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
        await _commit_and_ask_more(query, context, session)
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
    try:
        await message.delete()
    except Exception:
        pass
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


async def _commit_and_ask_more(query, context, session) -> None:
    payer_label = session.draft_payer_label or "?"
    participants: list[str] = []
    for key in session.draft_participants:
        m = find(session.chat_id, key)
        if m is not None:
            participants.append(m.label)
    session.payments.append(
        state.Payment(
            payer_key=session.draft_payer_key or "?",
            payer_label=payer_label,
            amount=session.draft_amount or Decimal("0"),
            participant_keys=list(session.draft_participants),
            participant_labels=participants,
        )
    )
    log.info(
        "chat %s: recorded payment %s paid %s for %d people (total %d so far)",
        session.chat_id, payer_label, session.draft_amount,
        len(participants), len(session.payments),
    )
    session.draft_payer_key = None
    session.draft_payer_label = None
    session.draft_amount = None
    session.draft_participants = set()
    session.awaiting_reply = None

    chat_members = members(session.chat_id)
    try:
        await query.edit_message_text(
            messages.ASK_MORE_PAYERS,
            reply_markup=more_payers_keyboard(chat_members),
        )
    except Exception:
        sent = await context.bot.send_message(
            session.chat_id,
            messages.ASK_MORE_PAYERS,
            reply_markup=more_payers_keyboard(chat_members),
        )
        session.menu_message_id = sent.message_id
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
        await _settle(context, session)
        return
    if data == "moreno":
        await _ask_manual_payer(context, session)
        return
    if data.startswith("more|"):
        key = data[len("more|"):]
        member = find(session.chat_id, key)
        if member is None:
            return
        session.draft_payer_key = member.key
        session.draft_payer_label = member.label
        await _show_amount_prompt(context, session, query=query)
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