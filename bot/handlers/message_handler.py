"""Auto-detects supported links in incoming messages and replies with a
metadata preview + quality-selection keyboard."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.downloaders.ytdlp_service import ExtractionError
from bot.middlewares.access_control import (
    check_rate_limit,
    is_chat_type_enabled,
    is_duplicate,
    is_from_bot,
)
from bot.services.app_context import AppContext
from bot.utils.formatting import build_metadata_caption
from bot.utils.logger import get_logger
from bot.utils.validators import extract_urls, is_domain_allowed, is_valid_url

logger = get_logger(__name__)


def _build_keyboard(token: str, formats) -> InlineKeyboardMarkup:
    rows = []
    video_formats = [f for f in formats if not f.is_audio_only]
    audio_formats = [f for f in formats if f.is_audio_only]

    # Two buttons per row for compactness.
    row = []
    for fmt in video_formats:
        row.append(InlineKeyboardButton(f"🎥 {fmt.label}", callback_data=f"dl:{token}:{fmt.format_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    for fmt in audio_formats:
        rows.append([InlineKeyboardButton(fmt.label, callback_data=f"dl:{token}:{fmt.format_id}")])

    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{token}")])
    return InlineKeyboardMarkup(rows)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app: AppContext = context.application.bot_data["app"]
    settings = app.settings

    if not update.effective_message or not update.effective_message.text:
        return
    if is_from_bot(update):
        return
    if not is_chat_type_enabled(update, settings):
        return
    if not settings.enable_auto_detection:
        return
    if await is_duplicate(update, app.db):
        return

    urls = extract_urls(update.effective_message.text)
    if not urls:
        return

    if not await check_rate_limit(update, app.db, settings):
        await update.effective_message.reply_text(
            "⏳ You're sending links too quickly. Please wait a moment and try again."
        )
        return

    for url in urls[:3]:  # Cap to avoid abuse via messages stuffed with links.
        await _process_url(update, context, app, url)


async def _process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, app: AppContext, url: str) -> None:
    message = update.effective_message
    user = update.effective_user

    if not is_valid_url(url):
        return  # Silently ignore garbage/unsupported-looking links.

    if not is_domain_allowed(url, app.settings.allowed_domains, app.settings.blocked_domains):
        logger.info(f"Blocked domain rejected: {url}")
        return

    status_msg = await message.reply_text("🔎 Extracting metadata...")

    cached = await app.cache.get(url)
    try:
        if cached:
            info = cached
            from_cache = True
        else:
            info = await app.ytdlp.extract_info(url)
            from_cache = False
    except ExtractionError as exc:
        await status_msg.edit_text(str(exc))
        await app.db.log_download(user.id, message.chat_id, url, None, "failed", exc.category)
        return
    except Exception:
        logger.exception(f"Unexpected error extracting metadata for {url}")
        await status_msg.edit_text("⚠️ Something went wrong while processing this link.")
        await app.db.log_download(user.id, message.chat_id, url, None, "failed", "unexpected")
        return

    if not from_cache:
        # Cache a plain-dict snapshot (MediaInfo is a dataclass; store as dict).
        from dataclasses import asdict

        await app.cache.set(url, asdict(info))
    elif isinstance(info, dict):
        # Reconstruct dataclass-ish access from cached dict for downstream code.
        from bot.downloaders.ytdlp_service import FormatOption, MediaInfo

        info = MediaInfo(
            **{**info, "formats": [FormatOption(**f) for f in info.get("formats", [])]}
        )

    if not info.formats:
        await status_msg.edit_text("⚠️ No downloadable formats were found for this link.")
        return

    session = app.sessions.create(info, user.id, message.chat_id)
    caption = build_metadata_caption(
        {
            "title": info.title,
            "uploader": info.uploader,
            "extractor_key": info.extractor_key,
            "duration": info.duration,
            "upload_date": info.upload_date,
            "resolution": info.resolution,
            "filesize_approx": info.filesize_approx,
        }
    )
    keyboard = _build_keyboard(session.token, info.formats)

    await status_msg.delete()
    if info.thumbnail:
        try:
            await message.reply_photo(
                photo=info.thumbnail,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
            return
        except Exception:
            logger.warning("Failed to send thumbnail photo, falling back to text preview")

    await message.reply_text(caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard)
