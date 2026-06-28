"""Sending and confirming persistent debtor tabs (post-settlement).

After the wizard finishes (:func:`bot.handlers.dong._settle`), this module turns
the outstanding :mod:`bot.ledger` obligations into messages:

* **Real users** get a tagged pay-message with a two-step confirm button, locked
  to that user, plus a 6-hourly reminder (see :mod:`bot.handlers.reminders`).
* **Manual debtors** (no Telegram id) are grouped into one owner-facing message
  with a toggle per debtor and a confirm button; the owner marks who has paid.

The confirm callbacks are routed here from :mod:`bot.main`.
"""

from __future__ import annotations

import html
import logging
import time
from decimal import Decimal

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import config, keyboards, ledger, messages, roster as roster_mod
from . import reminders

log = logging.getLogger(__name__)


# ---------- formatting helpers ---------------------------------------------

def _format_amount(amount: Decimal) -> str:
    q = amount.quantize(Decimal("0.01"))
    s = format(q, "f")
    if "." in s:
        int_part, dec_part = s.split(".")
        dec_part = dec_part.rstrip("0").rstrip(".") or "00"
        s = f"{int_part}.{dec_part}"
    return s


def _tag_for_key(chat_id: int, key: str, fallback_label: str) -> str:
    """HTML mention for a roster key; real users get a real tag/notification."""
    member = roster_mod.find(chat_id, key)
    if member is not None:
        return roster_mod.mention_html(member)
    return html.escape(fallback_label)


def _plain_label(chat_id: int, key: str, fallback_label: str) -> str:
    """Plain (un-escaped) label, for button captions (not HTML-parsed)."""
    member = roster_mod.find(chat_id, key)
    return member.label if member is not None else fallback_label


def _owner_mention(chat_id: int, owner_id: int) -> str:
    member = roster_mod.find(chat_id, roster_mod.user_key(owner_id))
    if member is not None:
        return roster_mod.mention_html(member)
    return roster_mod.mention_html_user(owner_id, None, None)


def _render_debtor(chat_id: int, src: str, src_obls: list[ledger.Obligation]):
    """Build (text, keyboard) for a real debtor's pay-message."""
    src_tag = _tag_for_key(chat_id, src, src_obls[0].src_label)
    if len(src_obls) == 1:
        o = src_obls[0]
        text = messages.debtor_tab(
            src_tag,
            _format_amount(o.amount),
            _tag_for_key(chat_id, o.dst, o.dst_label),
        )
    else:
        lines = [
            messages.debtor_tab_line(
                _format_amount(o.amount),
                _tag_for_key(chat_id, o.dst, o.dst_label),
            )
            for o in src_obls
        ]
        text = messages.debtor_tab_multi(src_tag, lines)
    return text, keyboards.debtor_prompt_keyboard(src)


# ---------- sending --------------------------------------------------------

async def send_debtor_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    src: str,
    src_obls: list[ledger.Obligation],
) -> None:
    """Send a fresh pay-message to a real debtor and start their reminder."""
    text, keyboard = _render_debtor(chat_id, src, src_obls)
    sent = await context.bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
    ledger.set_real_msg(chat_id, src, sent.message_id, "prompt", time.time())
    reminders.schedule(
        context, chat_id, src, first=config.REMINDER_INTERVAL_SECONDS
    )


async def refresh_debtor_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    src: str,
    src_obls: list[ledger.Obligation],
) -> None:
    """Reminder tick: disable the previous message and post a fresh one."""
    prev = ledger.get_real_msg(chat_id, src)
    if prev and prev.get("message_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=prev["message_id"],
                reply_markup=keyboards.disabled_keyboard(),
            )
        except Exception:
            pass
    text, keyboard = _render_debtor(chat_id, src, src_obls)
    sent = await context.bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
    ledger.set_real_msg(chat_id, src, sent.message_id, "prompt", time.time())


async def _send_manual_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    owner_id: int,
    owner_mention: str,
    only_srcs: list[str] | None = None,
) -> None:
    """Send (or resend) the owner-facing settlement message for manual debtors."""
    obls = ledger.load_obligations(chat_id)
    groups = ledger.group_by_src(obls)
    m_srcs = ledger.manual_srcs(obls)
    if only_srcs is not None:
        m_srcs = [s for s in m_srcs if s in only_srcs]
    if not m_srcs:
        return

    lines: list[str] = []
    btn_srcs: list[tuple[str, str]] = []
    for src in m_srcs:
        label = _plain_label(chat_id, src, groups[src][0].src_label)
        btn_srcs.append((src, label))
        for o in groups[src]:
            lines.append(
                messages.manual_line(
                    html.escape(label),
                    _format_amount(o.amount),
                    _tag_for_key(chat_id, o.dst, o.dst_label),
                )
            )

    text = messages.manual_settle(owner_mention, lines)
    sent = await context.bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.manual_settle_keyboard(btn_srcs, set()),
    )
    ledger.set_manual_msg(chat_id, sent.message_id, owner_id, selected=[])


async def dispatch(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    owner_id: int,
    owner_mention: str,
) -> None:
    """Send messages for the current outstanding obligations."""
    obls = ledger.load_obligations(chat_id)
    groups = ledger.group_by_src(obls)
    for src in ledger.real_srcs(obls):
        await send_debtor_message(context, chat_id, src, groups[src])
    await _send_manual_message(context, chat_id, owner_id, owner_mention)


async def deactivate_all(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Disable buttons on all current tab messages and cancel reminder jobs.

    Called before a new invoice replaces the outstanding tab, so superseded
    messages can no longer be acted on (prevents conflicting confirmations).
    """
    for src, entry in ledger.all_real_msgs(chat_id).items():
        mid = entry.get("message_id")
        if mid:
            try:
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=mid,
                    reply_markup=keyboards.disabled_keyboard(),
                )
            except Exception:
                pass
    manual_msg = ledger.get_manual_msg(chat_id)
    if manual_msg and manual_msg.get("message_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=manual_msg["message_id"],
                reply_markup=keyboards.disabled_keyboard(),
            )
        except Exception:
            pass
    reminders.cancel_all(context, chat_id)


# ---------- callbacks: real-user confirm -----------------------------------

async def on_paid_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle paid1| (first press -> re-confirm) and paid2| (final confirm)."""
    query = update.callback_query
    if query is None or query.message is None:
        return
    chat_id = query.message.chat_id
    data = query.data or ""
    src = data.split("|", 1)[1] if "|" in data else ""

    # Lock the button to the tagged debtor.
    debtor_id = ledger.user_id_of(src)
    if debtor_id is None or query.from_user.id != debtor_id:
        try:
            await query.answer(messages.NOT_YOUR_BUTTON, show_alert=True)
        except Exception:
            pass
        return

    # Reject presses from a superseded message. Only the latest tracked message
    # per debtor is actionable; an older one (whose disabling edit never landed —
    # e.g. Telegram's 48h edit limit) must not confirm the *current* tab.
    entry = ledger.get_real_msg(chat_id, src)
    current_mid = entry.get("message_id") if entry else None
    if current_mid != query.message.message_id:
        try:
            await query.answer(messages.TAB_MESSAGE_OUTDATED, show_alert=True)
        except Exception:
            pass
        try:
            await query.edit_message_reply_markup(
                reply_markup=keyboards.disabled_keyboard()
            )
        except Exception:
            pass
        return

    src_obls = [o for o in ledger.load_obligations(chat_id) if o.src == src]
    if not src_obls:
        # Already settled / superseded.
        try:
            await query.answer()
        except Exception:
            pass
        return

    if data.startswith("paid1|"):
        try:
            await query.answer()
        except Exception:
            pass
        text, _ = _render_debtor(chat_id, src, src_obls)
        try:
            await query.edit_message_text(
                text + messages.DOUBLE_CONFIRM_SUFFIX,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboards.debtor_confirm_keyboard(src),
            )
        except Exception:
            pass
        ledger.set_real_stage(chat_id, src, "confirm")
        return

    if data.startswith("paid2|"):
        if len(src_obls) == 1:
            o = src_obls[0]
            settled_text = messages.debtor_paid(
                _tag_for_key(chat_id, src, o.src_label),
                _tag_for_key(chat_id, o.dst, o.dst_label),
                _format_amount(o.amount),
            )
        else:
            settled_text = messages.debtor_paid_generic(
                _tag_for_key(chat_id, src, src_obls[0].src_label)
            )
        remaining = ledger.confirm_real(chat_id, src)
        reminders.cancel(context, chat_id, src)
        log.info("chat %s: debtor %s confirmed payment", chat_id, src)
        try:
            await query.answer()
        except Exception:
            pass
        try:
            await query.edit_message_text(settled_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        if not remaining:
            try:
                await context.bot.send_message(chat_id, messages.TAB_ALL_SETTLED)
            except Exception:
                pass


# ---------- callbacks: manual (owner) settle -------------------------------

async def on_manual_settle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle mtog| (owner toggles a manual debtor) and mconf (owner confirms)."""
    query = update.callback_query
    if query is None or query.message is None:
        return
    chat_id = query.message.chat_id
    data = query.data or ""

    manual_msg = ledger.get_manual_msg(chat_id)
    if manual_msg is None:
        try:
            await query.answer()
        except Exception:
            pass
        return

    # Lock to the session owner who created the manual message.
    if query.from_user.id != manual_msg.get("owner_id"):
        try:
            await query.answer(messages.NOT_YOUR_BUTTON, show_alert=True)
        except Exception:
            pass
        return

    # Reject presses from a superseded manual-settle message (same guard as the
    # real-user tabs above): only the latest tracked one is actionable.
    if manual_msg.get("message_id") != query.message.message_id:
        try:
            await query.answer(messages.TAB_MESSAGE_OUTDATED, show_alert=True)
        except Exception:
            pass
        try:
            await query.edit_message_reply_markup(
                reply_markup=keyboards.disabled_keyboard()
            )
        except Exception:
            pass
        return

    if data.startswith("mtog|"):
        src = data.split("|", 1)[1]
        selected = ledger.toggle_manual_selected(chat_id, src)
        try:
            await query.answer()
        except Exception:
            pass
        obls = ledger.load_obligations(chat_id)
        groups = ledger.group_by_src(obls)
        btn_srcs = [
            (s, _plain_label(chat_id, s, groups[s][0].src_label))
            for s in ledger.manual_srcs(obls)
        ]
        try:
            await query.edit_message_reply_markup(
                reply_markup=keyboards.manual_settle_keyboard(btn_srcs, set(selected))
            )
        except Exception:
            pass
        return

    if data == "mconf":
        owner_id = manual_msg.get("owner_id")
        settled, remaining_manual = ledger.confirm_manual(chat_id)
        try:
            await query.answer()
        except Exception:
            pass
        summary_lines = [
            messages.manual_line(
                html.escape(_plain_label(chat_id, o.src, o.src_label)),
                _format_amount(o.amount),
                _tag_for_key(chat_id, o.dst, o.dst_label),
            )
            for o in settled
        ]
        try:
            await query.edit_message_text(
                messages.manual_settled_summary(summary_lines),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        log.info(
            "chat %s: owner settled %d manual debtor line(s); %d still unpaid",
            chat_id, len(settled), len(remaining_manual),
        )
        if remaining_manual:
            await _send_manual_message(
                context,
                chat_id,
                owner_id,
                _owner_mention(chat_id, owner_id),
                only_srcs=remaining_manual,
            )
        else:
            ledger.clear_manual_msg(chat_id)
            if not ledger.load_obligations(chat_id):
                try:
                    await context.bot.send_message(chat_id, messages.TAB_ALL_SETTLED)
                except Exception:
                    pass
