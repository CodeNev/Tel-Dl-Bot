"""Throttled progress updates for long-running downloads.

Telegram rate-limits message edits, so this wraps a bot message and only
pushes an update at most once every `min_interval` seconds, or when the
stage changes (e.g. "Downloading..." -> "Merging audio...").
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from telegram import Message

from bot.utils.formatting import human_size
from bot.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProgressReporter:
    message: Message
    min_interval: float = 3.0
    _last_update: float = 0.0
    _last_text: str = ""
    _lock: asyncio.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def set_stage(self, text: str, force: bool = False) -> None:
        await self._maybe_update(text, force=force)

    async def report_download_progress(self, d: dict) -> None:
        if d.get("status") != "downloading":
            return
        downloaded = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        percent = f"{(downloaded / total * 100):.0f}%" if total else "?"
        speed = d.get("speed")
        speed_str = f"{human_size(speed)}/s" if speed else "-"
        text = f"⬇️ Downloading... {percent} ({human_size(downloaded)} / {human_size(total)}) @ {speed_str}"
        await self._maybe_update(text)

    async def _maybe_update(self, text: str, force: bool = False) -> None:
        now = time.monotonic()
        if not force and text == self._last_text:
            return
        if not force and (now - self._last_update) < self.min_interval:
            return
        async with self._lock:
            self._last_update = now
            self._last_text = text
            try:
                await self.message.edit_text(text)
            except Exception as exc:  # Telegram raises if text is unchanged / message deleted
                logger.debug(f"Progress edit skipped: {exc}")
