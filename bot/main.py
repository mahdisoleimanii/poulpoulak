"""Entrypoint: build the PTB Application, register handlers, run polling."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import config
from .handlers.dong import (
    on_amount_callback,
    on_dong_keyword,
    on_group_message,
    on_more_callback,
    on_participant_callback,
    on_payer_callback,
)
from .handlers.membership import on_my_chat_member
from .handlers.reminders import reschedule_all
from .handlers.start import start
from .handlers.tabs import on_manual_settle_callback, on_paid_callback


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("poulpoulak")


def _build_application() -> Application:
    config.validate()
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(reschedule_all)
        .build()
    )

    # /start (private chat only; start.py ignores group calls).
    app.add_handler(CommandHandler("start", start))

    # Bot added/removed from a group (auth gate).
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Callback router for ALL inline-button clicks during the wizard.
    # We dispatch by inspecting the callback_data prefix inside each handler.
    cb_router = CallbackQueryHandler(_callback_dispatcher)
    app.add_handler(cb_router)

    # The "دنگ" keyword (entry). The same handler also covers any group message
    # that should be interpreted as a wizard reply (manual entry / amount).
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & (filters.TEXT | filters.COMMAND)
            & ~filters.COMMAND,
            on_group_message_or_keyword,
        )
    )

    # Catch-all: log any exception raised inside a handler (req: logging).
    app.add_error_handler(_on_error)

    return app


async def _on_error(update, context) -> None:
    """Log uncaught handler exceptions with a full traceback."""
    log.exception("unhandled error while processing update", exc_info=context.error)


async def _callback_dispatcher(
    update: Update, context
) -> None:
    """Route callback queries to the right wizard step.

    A single router keeps the prefix-handling logic in one place so each step's
    handler can stay focused.
    """
    query = update.callback_query
    if query is None:
        return
    data = query.data or ""

    # Filter by where the message lives (group vs. DM) — all wizard buttons are
    # sent to groups.
    if query.message is None or query.message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        try:
            await query.answer()
        except Exception:
            pass
        return

    # Step 9 (payer).
    if data.startswith("pay|") or data in {"pno", "pcancel"}:
        await on_payer_callback(update, context)
        return
    # Step 10 (amount).
    if data in {"achange", "acancel"}:
        await on_amount_callback(update, context)
        return
    # Step 11 (participants).
    if (
        data.startswith("ptog|")
        or data in {"pmanual", "pok", "pback", "ppcancel"}
    ):
        await on_participant_callback(update, context)
        return
    # Step 12 (more payers?).
    if data.startswith("more|") or data in {"done", "mcancel", "moreno"}:
        await on_more_callback(update, context)
        return
    # Debtor tab: real-user payment confirmation (two-step).
    if data.startswith("paid1|") or data.startswith("paid2|"):
        await on_paid_callback(update, context)
        return
    # Debtor tab: owner settling manual debtors.
    if data.startswith("mtog|") or data == "mconf":
        await on_manual_settle_callback(update, context)
        return

    # Unknown / no-op buttons (e.g. the expired "⏰ منقضی شد").
    try:
        await query.answer()
    except Exception:
        pass


async def on_group_message_or_keyword(
    update: Update, context
) -> None:
    """A group message arrived. Either it triggers the wizard (the bare keyword)
    or it is a wizard reply (manual entry / amount)."""
    message = update.effective_message
    if message is None or message.text is None:
        return
    if message.text.strip() == "دنگ":
        await on_dong_keyword(update, context)
        return
    await on_group_message(update, context)


def main() -> None:  # pragma: no cover - thin entrypoint
    app = _build_application()
    log.info("Poulpoulak (پول‌پولک) starting (long-polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":  # pragma: no cover
    main()
