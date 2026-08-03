"""Handles inline keyboard button presses: quality selection and cancellation."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from bot.downloaders.ytdlp_service import ExtractionError
from bot.services.app_context import AppContext
from bot.services.progress import ProgressReporter
from bot.services.queue_manager import QueueFullError
from bot.utils.formatting import human_size
from bot.utils.logger import get_logger

logger = get_logger(__name__)

MAX_TELEGRAM_UPLOAD_MB = 2000  # Telegram Bot API hard limit for bot uploads.


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    app: AppContext = context.application.bot_data["app"]

    await query.answer()

    if query.data.startswith("cancel:"):
        token = query.data.split(":", 1)[1]
        app.queue.cancel(token)
        app.sessions.drop(token)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Cancelled.")
        return

    if not query.data.startswith("dl:"):
        return

    _, token, format_id = query.data.split(":", 2)
    session = app.sessions.get(token)
    if session is None:
        await query.message.reply_text("⚠️ This request has expired. Please send the link again.")
        return

    fmt = session.formats.get(format_id)
    if fmt is None:
        await query.message.reply_text("⚠️ That format is no longer available. Please send the link again.")
        return

    max_bytes = app.settings.max_file_size_mb * 1024 * 1024
    if fmt.filesize and fmt.filesize > max_bytes:
        await query.message.reply_text(
            f"⚠️ This file (~{human_size(fmt.filesize)}) exceeds the configured limit of "
            f"{app.settings.max_file_size_mb} MB (MAX_FILE_SIZE)."
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    progress_msg = await query.message.reply_text("📥 Queued for download...")
    reporter = ProgressReporter(message=progress_msg)

    job_id = uuid.uuid4().hex[:10]

    async def _job() -> None:
        await _run_download_job(app, session, fmt, reporter, query.message.chat_id, query.from_user.id)

    try:
        await app.queue.submit(job_id, query.from_user.id, _job)
    except QueueFullError as exc:
        await progress_msg.edit_text(f"⚠️ {exc}")


async def _run_download_job(app: AppContext, session, fmt, reporter: ProgressReporter, chat_id: int, user_id: int) -> None:
    work_dir = app.settings.temp_dir / f"job_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    final_path: Path | None = None

    try:
        await reporter.set_stage("⬇️ Downloading...", force=True)

        # yt-dlp progress hooks are synchronous and run in a worker thread, so
        # we bridge them back to the event loop using call_soon_threadsafe.
        import asyncio

        loop = asyncio.get_running_loop()

        def sync_hook(d: dict) -> None:
            if d.get("status") in {"downloading", "finished"}:
                loop.call_soon_threadsafe(asyncio.create_task, reporter.report_download_progress(d))

        final_path = await app.ytdlp.download(
            url=session.url,
            format_id=fmt.format_id,
            is_audio_only=fmt.is_audio_only,
            dest_dir=work_dir,
            title_hint=session.title,
            progress_hook=sync_hook,
        )

        if not fmt.is_audio_only:
            await reporter.set_stage("🎞 Merging audio and video...", force=True)

        size_bytes = final_path.stat().st_size
        max_bytes = app.settings.max_file_size_mb * 1024 * 1024
        if size_bytes > max_bytes:
            await reporter.set_stage(
                f"⚠️ The downloaded file ({human_size(size_bytes)}) exceeds the "
                f"{app.settings.max_file_size_mb} MB limit and can't be uploaded.",
                force=True,
            )
            await app.db.log_download(user_id, chat_id, session.url, session.title, "too_large")
            return

        await reporter.set_stage("☁️ Uploading to Telegram...", force=True)

        bot = reporter.message.get_bot()
        with open(final_path, "rb") as fh:
            if fmt.is_audio_only:
                await bot.send_audio(chat_id=chat_id, audio=fh, title=session.title, filename=final_path.name)
            else:
                await bot.send_video(
                    chat_id=chat_id, video=fh, caption=session.title[:1024], filename=final_path.name, supports_streaming=True
                )

        await reporter.set_stage("✅ Finished.", force=True)
        await app.db.log_download(user_id, chat_id, session.url, session.title, "success")

    except ExtractionError as exc:
        await reporter.set_stage(str(exc), force=True)
        await app.db.log_download(user_id, chat_id, session.url, session.title, "failed", exc.category)
    except Exception as exc:
        logger.exception(f"Download job failed for {session.url}")
        await reporter.set_stage("⚠️ An unexpected error occurred during download.", force=True)
        await app.db.log_download(user_id, chat_id, session.url, session.title, "failed", str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        app.sessions.drop(session.token)
