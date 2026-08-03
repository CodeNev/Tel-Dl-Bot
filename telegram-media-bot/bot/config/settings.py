"""
Application configuration.

Loads all runtime configuration from environment variables using python-dotenv,
validates required values at startup, and exposes a single immutable `settings`
object that the rest of the application imports.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _get(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        raise ConfigError(f"Environment variable {name} must be an integer, got: {val!r}")


def _get_list(name: str, default: str = "") -> List[str]:
    val = os.getenv(name, default)
    if not val or val.strip() == "*":
        return []
    return [item.strip() for item in val.split(",") if item.strip()]


# Placeholder values that must never be used in production. Startup validation
# rejects these so users can't accidentally deploy with the templates from
# railway.json / .env.example still in place.
_PLACEHOLDER_VALUES = {
    "YOUR_BOT_TOKEN",
    "YOUR_ADMIN_ID",
    "",
}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: List[int]

    log_level: str
    max_file_size_mb: int
    max_concurrent_downloads: int
    download_timeout: int

    cache_dir: Path
    temp_dir: Path
    enable_cache: bool
    cache_expire_hours: int

    enable_auto_detection: bool
    enable_private_chat: bool
    enable_groups: bool
    enable_supergroups: bool
    enable_progress_bar: bool

    max_queue_size: int
    rate_limit_per_user: int

    allowed_domains: List[str]
    blocked_domains: List[str]

    cookie_file: str | None
    cookies_content: str | None
    proxy_url: str | None
    ffmpeg_path: str
    ytdlp_binary: str

    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None

    db_path: Path = field(default_factory=lambda: Path("/tmp/cache/bot.sqlite3"))


def _parse_admin_ids(raw: str) -> List[int]:
    if not raw or raw in _PLACEHOLDER_VALUES:
        return []
    ids = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.lstrip("-").isdigit():
            raise ConfigError(f"ADMIN_IDS contains a non-numeric value: {chunk!r}")
        ids.append(int(chunk))
    return ids


def load_settings() -> Settings:
    """Load and validate settings, raising ConfigError with a clear message
    on the first problem found."""

    bot_token = _get("BOT_TOKEN")
    if not bot_token or bot_token in _PLACEHOLDER_VALUES:
        raise ConfigError(
            "BOT_TOKEN is not set. Open the Railway Variables page (or your .env file) "
            "and set BOT_TOKEN to the token you got from @BotFather."
        )

    admin_ids = _parse_admin_ids(_get("ADMIN_IDS", ""))

    cache_dir = Path(_get("CACHE_DIR", "/tmp/cache"))
    temp_dir = Path(_get("TEMP_DIR", "/tmp/downloads"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        bot_token=bot_token,
        admin_ids=admin_ids,
        log_level=_get("LOG_LEVEL", "INFO").upper(),
        max_file_size_mb=_get_int("MAX_FILE_SIZE", 2000),
        max_concurrent_downloads=_get_int("MAX_CONCURRENT_DOWNLOADS", 3),
        download_timeout=_get_int("DOWNLOAD_TIMEOUT", 600),
        cache_dir=cache_dir,
        temp_dir=temp_dir,
        enable_cache=_get_bool("ENABLE_CACHE", True),
        cache_expire_hours=_get_int("CACHE_EXPIRE_HOURS", 24),
        enable_auto_detection=_get_bool("ENABLE_AUTO_DETECTION", True),
        enable_private_chat=_get_bool("ENABLE_PRIVATE_CHAT", True),
        enable_groups=_get_bool("ENABLE_GROUPS", True),
        enable_supergroups=_get_bool("ENABLE_SUPERGROUPS", True),
        enable_progress_bar=_get_bool("ENABLE_PROGRESS_BAR", True),
        max_queue_size=_get_int("MAX_QUEUE_SIZE", 50),
        rate_limit_per_user=_get_int("RATE_LIMIT_PER_USER", 5),
        allowed_domains=_get_list("ALLOWED_DOMAINS", "*"),
        blocked_domains=_get_list("BLOCKED_DOMAINS", ""),
        cookie_file=_get("COOKIE_FILE") or None,
        cookies_content=_get("COOKIES_CONTENT") or None,
        proxy_url=_get("PROXY_URL") or None,
        ffmpeg_path=_get("FFMPEG_PATH", "ffmpeg"),
        ytdlp_binary=_get("YTDLP_BINARY", "yt-dlp"),
        telegram_api_id=_get("TELEGRAM_API_ID") or None,
        telegram_api_hash=_get("TELEGRAM_API_HASH") or None,
        db_path=cache_dir / "bot.sqlite3",
    )

    if settings.max_concurrent_downloads < 1:
        raise ConfigError("MAX_CONCURRENT_DOWNLOADS must be at least 1.")
    if settings.max_file_size_mb < 1:
        raise ConfigError("MAX_FILE_SIZE must be a positive number of megabytes.")
    if settings.download_timeout < 10:
        raise ConfigError("DOWNLOAD_TIMEOUT must be at least 10 seconds.")

    settings = _materialize_cookie_file(settings)
    return settings


def _materialize_cookie_file(settings: "Settings") -> "Settings":
    """If COOKIES_CONTENT was provided (needed on hosts like Railway where
    there's no way to upload a file directly), write it to disk as a real
    Netscape-format cookies file and point cookie_file at it. An explicit
    COOKIE_FILE path always takes priority if both are set."""
    if settings.cookie_file:
        return settings
    if not settings.cookies_content:
        return settings

    cookie_path = settings.cache_dir / "cookies.txt"
    content = settings.cookies_content
    # Support pasting the content with literal "\n" sequences (common when
    # copy-pasting a multi-line file into a single-line env var field).
    if "\\n" in content and "\n" not in content:
        content = content.replace("\\n", "\n")
    cookie_path.write_text(content, encoding="utf-8")

    from dataclasses import replace

    return replace(settings, cookie_file=str(cookie_path))


def get_settings_or_exit() -> Settings:
    """Convenience wrapper used by main.py: prints a friendly error and exits
    the process instead of raising a traceback if configuration is invalid."""
    try:
        return load_settings()
    except ConfigError as exc:
        print("=" * 70, file=sys.stderr)
        print("CONFIGURATION ERROR", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(1)
