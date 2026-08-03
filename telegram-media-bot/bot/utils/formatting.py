"""Formatting helpers for user-facing Telegram messages."""

from __future__ import annotations

from datetime import datetime


def human_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "Unknown"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def human_size(num_bytes: float | None) -> str:
    if not num_bytes or num_bytes <= 0:
        return "Unknown"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_upload_date(date_str: str | None) -> str:
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return date_str


def escape_markdown_v2(text: str | None) -> str:
    """Escape text for Telegram's MarkdownV2 parse mode."""
    if not text:
        return ""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{ch}" if ch in special else ch for ch in text)


def truncate(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def build_metadata_caption(info: dict) -> str:
    """Build the formatted caption shown under the preview thumbnail."""
    title = escape_markdown_v2(truncate(info.get("title") or "Untitled", 150))
    uploader = escape_markdown_v2(info.get("uploader") or "Unknown")
    platform = escape_markdown_v2((info.get("extractor_key") or info.get("platform") or "Unknown"))
    duration = escape_markdown_v2(human_duration(info.get("duration")))
    upload_date = escape_markdown_v2(human_upload_date(info.get("upload_date")))
    resolution = escape_markdown_v2(info.get("resolution") or "Unknown")
    filesize = escape_markdown_v2(human_size(info.get("filesize_approx") or info.get("filesize")))

    lines = [
        f"🎬 *{title}*",
        "",
        f"📡 Platform: *{platform}*",
        f"👤 Uploader: {uploader}",
        f"📅 Uploaded: {upload_date}",
        f"⏱ Duration: {duration}",
        f"🖼 Resolution: {resolution}",
        f"💾 Est\\. size: {filesize}",
    ]
    return "\n".join(lines)
