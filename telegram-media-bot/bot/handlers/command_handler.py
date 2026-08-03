"""Basic bot commands: /start, /help, /stats, /cancel."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.app_context import AppContext

WELCOME_TEXT = (
    "👋 *Welcome to the Universal Media Downloader Bot!*\n\n"
    "Just send me a link from YouTube, TikTok, Instagram, X/Twitter, Facebook, "
    "Reddit, Vimeo, Twitch, SoundCloud, Dailymotion, or any site supported by "
    "yt\\-dlp, and I'll fetch a preview with quality options.\n\n"
    "Use /help to see all commands."
)

HELP_TEXT = (
    "*Available commands*\n\n"
    "/start \\- Show the welcome message\n"
    "/help \\- Show this help message\n"
    "/stats \\- Show download statistics \\(admins only\\)\n"
    "/cancel \\- Cancel your most recent pending download\n\n"
    "Just paste a supported link into the chat to get started\\!"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(WELCOME_TEXT, parse_mode="MarkdownV2")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode="MarkdownV2")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app: AppContext = context.application.bot_data["app"]
    user = update.effective_user
    if not user or user.id not in app.settings.admin_ids:
        await update.effective_message.reply_text("⛔ This command is restricted to admins.")
        return

    summary = await app.db.stats_summary()
    active = app.queue.active_count()
    lines = ["📊 *Bot Statistics*", ""]
    lines.append(f"Active jobs: {active}")
    for status, count in summary.items():
        lines.append(f"{status.capitalize()}: {count}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "To cancel a download, tap the ❌ Cancel button under the relevant preview message."
    )
