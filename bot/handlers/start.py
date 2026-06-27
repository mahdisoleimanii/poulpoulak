"""/start handler (req 3, 4): private-chat info for users, instructions for admins."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from .. import access, config, messages


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None:
        return

    # The wizard lives in groups; /start is only meaningful in private chats.
    if chat.type != ChatType.PRIVATE:
        return

    if access.is_super_admin(user.id):
        await message.reply_text(messages.start_admin(config.REPO_URL))
    else:
        await message.reply_text(messages.start_non_admin(config.REPO_URL))
