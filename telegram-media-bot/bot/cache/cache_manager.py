"""Simple TTL cache for extracted metadata, keyed by URL.

Kept intentionally lightweight (in-memory dict + optional disk spill) rather
than pulling in Redis, since Railway's free/hobby tiers favor low memory and
a single-process deployment. If the bot is later scaled horizontally, this
class is the seam to swap in a Redis-backed implementation.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional


class CacheManager:
    def __init__(self, cache_dir: Path, expire_hours: int, enabled: bool = True) -> None:
        self.cache_dir = cache_dir
        self.expire_seconds = expire_hours * 3600
        self.enabled = enabled
        self._mem: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _disk_path(self, key: str) -> Path:
        import hashlib

        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    async def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        async with self._lock:
            entry = self._mem.get(key)
            if entry is not None:
                ts, value = entry
                if time.time() - ts < self.expire_seconds:
                    return value
                del self._mem[key]

        path = self._disk_path(key)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if time.time() - data["ts"] < self.expire_seconds:
                    async with self._lock:
                        self._mem[key] = (data["ts"], data["value"])
                    return data["value"]
                path.unlink(missing_ok=True)
            except (json.JSONDecodeError, KeyError, OSError):
                path.unlink(missing_ok=True)
        return None

    async def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        ts = time.time()
        async with self._lock:
            self._mem[key] = (ts, value)
        path = self._disk_path(key)
        try:
            path.write_text(json.dumps({"ts": ts, "value": value}))
        except (OSError, TypeError):
            pass  # Non-serializable or disk issue: memory cache still works.

    async def clear_expired(self) -> int:
        """Removes expired entries from memory and disk. Returns count removed."""
        removed = 0
        now = time.time()
        async with self._lock:
            expired_keys = [k for k, (ts, _) in self._mem.items() if now - ts >= self.expire_seconds]
            for k in expired_keys:
                del self._mem[k]
                removed += 1

        if self.cache_dir.exists():
            for path in self.cache_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text())
                    if now - data.get("ts", 0) >= self.expire_seconds:
                        path.unlink(missing_ok=True)
                        removed += 1
                except (json.JSONDecodeError, OSError):
                    path.unlink(missing_ok=True)
                    removed += 1
        return removed

    async def periodic_cleanup(self, interval_seconds: int = 3600) -> None:
        """Run forever in the background, clearing expired entries periodically."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.clear_expired()
            except Exception:
                pass
