"""Entrypoint for the Telegram Universal Media Downloader Bot.

Wires together configuration, database, cache, the yt-dlp service, the
download queue, and all Telegram handlers, then starts long polling.
"""

from __future__ import annotations

import asyncio
import shutil

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.cache.cache_manager import CacheManager
from bot.config.settings import get_settings_or_exit
from bot.database.db import Database
from bot.downloaders.ytdlp_service import YTDLPService
from bot.handlers.callback_handler import handle_callback
from bot.handlers.command_handler import cancel_command, help_command, start_command, stats_command
from bot.handlers.error_handler import handle_error
from bot.handlers.message_handler import handle_message
from bot.services.app_context import AppContext
from bot.services.queue_manager import DownloadQueueManager
from bot.services.session_store import SessionStore
from bot.utils.logger import get_logger, setup_logging


def check_binaries(ffmpeg_path: str, ytdlp_binary: str) -> None:
    """Fail fast with a clear message if ffmpeg isn't on PATH — a very common
    Railway deployment mistake when using a non-Docker builder."""
    if shutil.which(ffmpeg_path) is None:
        print(
            f"WARNING: '{ffmpeg_path}' was not found on PATH. Video/audio merging will fail. "
            "Make sure you're deploying with the provided Dockerfile, which installs ffmpeg."
        )


async def post_init(application: Application) -> None:
    app: AppContext = application.bot_data["app"]
    await app.db.connect()
    # Kick off background cache-expiry cleanup without blocking startup.
    asyncio.create_task(app.cache.periodic_cleanup())
    logger = get_logger("startup")
    logger.info("Bot started successfully and is now polling for updates.")


async def post_shutdown(application: Application) -> None:
    app: AppContext = application.bot_data["app"]
    await app.db.close()


def build_application() -> Application:
    settings = get_settings_or_exit()
    setup_logging(settings.log_level)
    check_binaries(settings.ffmpeg_path, settings.ytdlp_binary)

    db = Database(settings.db_path)
    cache = CacheManager(settings.cache_dir, settings.cache_expire_hours, settings.enable_cache)
    ytdlp = YTDLPService(
        ffmpeg_path=settings.ffmpeg_path,
        ytdlp_binary=settings.ytdlp_binary,
        proxy_url=settings.proxy_url,
        cookie_file=settings.cookie_file,
    )
    queue = DownloadQueueManager(settings.max_concurrent_downloads, settings.max_queue_size)
    sessions = SessionStore()

    app_context = AppContext(settings=settings, db=db, cache=cache, ytdlp=ytdlp, queue=queue, sessions=sessions)

    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["app"] = app_context

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(handle_error)

    return application


def main() -> None:
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
