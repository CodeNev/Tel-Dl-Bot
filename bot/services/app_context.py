"""Bundles every shared service so handlers can access them via
`context.application.bot_data["app"]` without a tangle of globals."""

from __future__ import annotations

from dataclasses import dataclass

from bot.cache.cache_manager import CacheManager
from bot.config.settings import Settings
from bot.database.db import Database
from bot.downloaders.ytdlp_service import YTDLPService
from bot.services.queue_manager import DownloadQueueManager
from bot.services.session_store import SessionStore


@dataclass
class AppContext:
    settings: Settings
    db: Database
    cache: CacheManager
    ytdlp: YTDLPService
    queue: DownloadQueueManager
    sessions: SessionStore
