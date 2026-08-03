"""Wraps yt-dlp for metadata extraction and format-specific downloads.

All yt-dlp calls run in a thread executor since yt-dlp itself is synchronous;
this keeps the bot's asyncio event loop free to handle other users.
"""

from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp

from bot.utils.logger import get_logger
from bot.utils.validators import sanitize_filename

logger = get_logger(__name__)


class UnsupportedURLError(Exception):
    pass


class ExtractionError(Exception):
    """Wraps a yt-dlp error with a user-friendly category."""

    def __init__(self, message: str, category: str = "unknown"):
        super().__init__(message)
        self.category = category


@dataclass
class FormatOption:
    format_id: str
    label: str
    ext: str
    height: Optional[int]
    filesize: Optional[int]
    is_audio_only: bool = False


@dataclass
class MediaInfo:
    url: str
    id: str
    title: str
    thumbnail: Optional[str]
    duration: Optional[float]
    uploader: Optional[str]
    upload_date: Optional[str]
    extractor_key: str
    resolution: Optional[str]
    filesize_approx: Optional[int]
    formats: list[FormatOption] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "private video" in msg or "private" in msg:
        return "private"
    if "age" in msg and "restrict" in msg:
        return "age_restricted"
    if "not available in your country" in msg or "geo" in msg:
        return "geo_blocked"
    if "video unavailable" in msg or "has been removed" in msg or "deleted" in msg:
        return "deleted"
    if "unsupported url" in msg or "no extractor" in msg:
        return "unsupported"
    if "timed out" in msg or "timeout" in msg:
        return "timeout"
    if "network" in msg or "connection" in msg or "resolve host" in msg:
        return "network"
    return "unknown"


FRIENDLY_ERRORS = {
    "private": "🔒 This video is private and can't be accessed.",
    "age_restricted": "🔞 This video is age-restricted and requires authentication (try setting COOKIE_FILE).",
    "geo_blocked": "🌍 This video is geo-blocked and unavailable in the bot's region.",
    "deleted": "🗑 This video has been deleted or is no longer available.",
    "unsupported": "❓ This link isn't supported by yt-dlp.",
    "timeout": "⏱ The request timed out. Please try again.",
    "network": "📡 A network error occurred while contacting the source. Please try again.",
    "unknown": "⚠️ Something went wrong while processing this link.",
}


class YTDLPService:
    def __init__(self, ffmpeg_path: str, ytdlp_binary: str, proxy_url: str | None, cookie_file: str | None):
        self.ffmpeg_path = ffmpeg_path
        self.ytdlp_binary = ytdlp_binary
        self.proxy_url = proxy_url
        self.cookie_file = cookie_file

    def _base_opts(self) -> dict:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "ffmpeg_location": self.ffmpeg_path,
            "socket_timeout": 30,
        }
        if self.proxy_url:
            opts["proxy"] = self.proxy_url
        if self.cookie_file:
            opts["cookiefile"] = self.cookie_file
        return opts

    async def extract_info(self, url: str) -> MediaInfo:
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(None, functools.partial(self._extract_sync, url))
        except yt_dlp.utils.DownloadError as exc:
            category = _classify_error(exc)
            raise ExtractionError(FRIENDLY_ERRORS.get(category, FRIENDLY_ERRORS["unknown"]), category) from exc
        return self._to_media_info(url, raw)

    def _extract_sync(self, url: str) -> dict:
        opts = self._base_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ExtractionError(FRIENDLY_ERRORS["unsupported"], "unsupported")
            return info

    def _to_media_info(self, url: str, raw: dict) -> MediaInfo:
        formats = self._collect_formats(raw.get("formats") or [])
        height = raw.get("height")
        resolution = f"{height}p" if height else None

        return MediaInfo(
            url=url,
            id=str(raw.get("id", "")),
            title=raw.get("title") or "Untitled",
            thumbnail=raw.get("thumbnail"),
            duration=raw.get("duration"),
            uploader=raw.get("uploader") or raw.get("channel"),
            upload_date=raw.get("upload_date"),
            extractor_key=raw.get("extractor_key") or raw.get("extractor") or "Unknown",
            resolution=resolution,
            filesize_approx=raw.get("filesize_approx") or raw.get("filesize"),
            formats=formats,
            raw=raw,
        )

    def _collect_formats(self, raw_formats: list[dict]) -> list[FormatOption]:
        """Reduce yt-dlp's full format list down to one entry per common
        resolution tier, plus an audio-only option, matching the buttons the
        product spec asks for (2160p/1440p/1080p/720p/480p/360p/audio)."""
        tiers = [2160, 1440, 1080, 720, 480, 360]
        best_per_tier: dict[int, dict] = {}
        best_audio: Optional[dict] = None

        for f in raw_formats:
            height = f.get("height")
            vcodec = f.get("vcodec")
            acodec = f.get("acodec")

            if height and vcodec and vcodec != "none":
                tier = min(tiers, key=lambda t: abs(t - height)) if height not in tiers else height
                # Only bucket into a tier if reasonably close, to avoid mislabeling.
                if abs(tier - height) <= 140 and tier in tiers:
                    current = best_per_tier.get(tier)
                    if current is None or (f.get("tbr") or 0) > (current.get("tbr") or 0):
                        best_per_tier[tier] = f

            if (not vcodec or vcodec == "none") and acodec and acodec != "none":
                if best_audio is None or (f.get("abr") or 0) > (best_audio.get("abr") or 0):
                    best_audio = f

        options: list[FormatOption] = []
        for tier in tiers:
            f = best_per_tier.get(tier)
            if f:
                options.append(
                    FormatOption(
                        format_id=f["format_id"],
                        label=f"{tier}p",
                        ext=f.get("ext", "mp4"),
                        height=tier,
                        filesize=f.get("filesize") or f.get("filesize_approx"),
                    )
                )

        if best_audio:
            options.append(
                FormatOption(
                    format_id=best_audio["format_id"],
                    label="🎵 Audio Only (MP3)",
                    ext="mp3",
                    height=None,
                    filesize=best_audio.get("filesize") or best_audio.get("filesize_approx"),
                    is_audio_only=True,
                )
            )

        return options

    async def download(
        self,
        url: str,
        format_id: str,
        is_audio_only: bool,
        dest_dir: Path,
        title_hint: str,
        progress_hook: Optional[Callable[[dict], None]] = None,
    ) -> Path:
        """Downloads (and merges if necessary) the requested format, returning
        the path to the final file on disk."""
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(
                None,
                functools.partial(
                    self._download_sync, url, format_id, is_audio_only, dest_dir, title_hint, progress_hook
                ),
            )
        except yt_dlp.utils.DownloadError as exc:
            category = _classify_error(exc)
            raise ExtractionError(FRIENDLY_ERRORS.get(category, FRIENDLY_ERRORS["unknown"]), category) from exc
        return path

    def _download_sync(
        self,
        url: str,
        format_id: str,
        is_audio_only: bool,
        dest_dir: Path,
        title_hint: str,
        progress_hook: Optional[Callable[[dict], None]],
    ) -> Path:
        safe_name = sanitize_filename(title_hint) or f"media_{int(time.time())}"
        outtmpl = str(dest_dir / f"{safe_name}.%(ext)s")

        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": outtmpl,
            "ffmpeg_location": self.ffmpeg_path,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
        }
        if self.proxy_url:
            opts["proxy"] = self.proxy_url
        if self.cookie_file:
            opts["cookiefile"] = self.cookie_file
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]

        if is_audio_only:
            opts["format"] = format_id
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        else:
            # Merge with best audio, prefer mp4 container per spec.
            opts["format"] = f"{format_id}+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_path = ydl.prepare_filename(info)
            if is_audio_only:
                final_path = str(Path(final_path).with_suffix(".mp3"))
            elif not final_path.endswith(".mp4"):
                candidate = Path(final_path).with_suffix(".mp4")
                if candidate.exists():
                    final_path = str(candidate)
            return Path(final_path)
