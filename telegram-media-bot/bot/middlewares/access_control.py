"""Guard functions applied to every incoming update before processing.

These aren't true PTB middlewares (python-telegram-bot doesn't have a formal
middleware chain the way aiogram does), but plain async predicate functions
called at the top of the message handler, which achieves the same effect.
"""

from __future__ import annotations

from telegram import Update

from bot.config.settings import Settings
from bot.database.db import Database
from bot.utils.logger import get_logger

logger = get_logger(__name__)


async def is_duplicate(update: Update, db: Database) -> bool:
    """Returns True if this exact message has already been processed."""
    if not update.effective_chat or not update.effective_message:
        return False
    first_time = await db.mark_processed(update.effective_chat.id, update.effective_message.message_id)
    return not first_time


def is_from_bot(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.is_bot)


def is_chat_type_enabled(update: Update, settings: Settings) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    if chat.type == "private":
        return settings.enable_private_chat
    if chat.type == "group":
        return settings.enable_groups
    if chat.type == "supergroup":
        return settings.enable_supergroups
    return False


async def check_rate_limit(update: Update, db: Database, settings: Settings) -> bool:
    """Returns True if the user may proceed, False if rate-limited."""
    user = update.effective_user
    if user is None:
        return True
    if user.id in settings.admin_ids:
        return True  # Admins are exempt from rate limiting.
    return await db.check_rate_limit(user.id, settings.rate_limit_per_user)
