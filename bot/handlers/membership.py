"""my_chat_member handler (req 5): authorize the chat only if a super-admin adds the bot."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from .. import access, messages

log = logging.getLogger(__name__)

_PRESENT = {"member", "administrator"}
_ABSENT = {"left", "kicked"}


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """React to the bot's own membership changes in a chat."""
    cmu = update.my_chat_member
    if cmu is None:
        return

    chat = cmu.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    old_status = cmu.old_chat_member.status
    new_status = cmu.new_chat_member.status
    adder = cmu.from_user

    became_present = old_status in _ABSENT and new_status in _PRESENT
    became_absent = new_status in _ABSENT and old_status not in _ABSENT

    if became_present:
        adder_id = adder.id if adder else None
        if access.is_super_admin(adder_id):
            access.authorize_chat(chat.id)
            log.info("authorized chat %s (added by super-admin %s)", chat.id, adder_id)
            try:
                await context.bot.send_message(chat.id, messages.ADDED_BY_ADMIN)
            except Exception:
                log.exception("chat %s: failed to send welcome", chat.id)
        else:
            # Not a super-admin: stay inert in this chat (req 5).
            access.deauthorize_chat(chat.id)
            log.info("rejected chat %s (added by non-admin %s)", chat.id, adder_id)
            try:
                await context.bot.send_message(chat.id, messages.ADDED_BY_NON_ADMIN)
            except Exception:
                log.exception("chat %s: failed to send rejection", chat.id)
    elif became_absent:
        # Bot removed from the group -> drop its authorization flag.
        access.deauthorize_chat(chat.id)
        log.info("deauthorized chat %s (bot removed)", chat.id)
