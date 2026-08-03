"""Lightweight async SQLite persistence layer.

Used for:
 - deduplication of (chat_id, message_id) pairs already processed
 - per-user rate limiting counters
 - basic download history / stats for admins
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_messages (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    user_id INTEGER PRIMARY KEY,
    window_start REAL NOT NULL,
    request_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected yet")
        return self._conn

    # -- deduplication -----------------------------------------------------

    async def mark_processed(self, chat_id: int, message_id: int) -> bool:
        """Returns True if this is the first time we've seen this message."""
        try:
            await self.conn.execute(
                "INSERT INTO processed_messages (chat_id, message_id, created_at) VALUES (?, ?, ?)",
                (chat_id, message_id, time.time()),
            )
            await self.conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def prune_processed(self, older_than_seconds: int = 86400) -> None:
        cutoff = time.time() - older_than_seconds
        await self.conn.execute("DELETE FROM processed_messages WHERE created_at < ?", (cutoff,))
        await self.conn.commit()

    # -- rate limiting -------------------------------------------------------

    async def check_rate_limit(self, user_id: int, limit_per_minute: int) -> bool:
        """Returns True if the user is within their limit (and records the
        request), False if they've exceeded it."""
        now = time.time()
        window = 60.0
        cursor = await self.conn.execute(
            "SELECT window_start, request_count FROM rate_limits WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()

        if row is None or (now - row[0]) > window:
            await self.conn.execute(
                "INSERT INTO rate_limits (user_id, window_start, request_count) VALUES (?, ?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET window_start = excluded.window_start, request_count = 1",
                (user_id, now),
            )
            await self.conn.commit()
            return True

        window_start, count = row
        if count >= limit_per_minute:
            return False

        await self.conn.execute(
            "UPDATE rate_limits SET request_count = request_count + 1 WHERE user_id = ?",
            (user_id,),
        )
        await self.conn.commit()
        return True

    # -- history -------------------------------------------------------------

    async def log_download(
        self,
        user_id: int,
        chat_id: int,
        url: str,
        title: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO download_history (user_id, chat_id, url, title, status, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, url, title, status, error, time.time()),
        )
        await self.conn.commit()

    async def stats_summary(self) -> dict:
        cursor = await self.conn.execute(
            "SELECT status, COUNT(*) FROM download_history GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {status: count for status, count in rows}
