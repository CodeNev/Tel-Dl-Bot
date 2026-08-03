"""Global error handler registered with `application.add_error_handler`."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.utils.logger import get_logger

logger = get_logger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred. Please try again in a moment."
            )
        except Exception:
            pass
