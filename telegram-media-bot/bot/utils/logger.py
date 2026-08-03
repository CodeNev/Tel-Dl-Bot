"""Structured logging setup shared by the whole application."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Iterator


class _ContextFilter(logging.Filter):
    """Ensures every record has a `user_id` field even if not supplied."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "user_id"):
            record.user_id = "-"
        return True


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s | %(levelname)-8s | user=%(user_id)s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet down noisy third-party libraries unless we're debugging.
    if level != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("yt_dlp").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_duration(logger: logging.Logger, action: str, user_id: int | str = "-") -> Iterator[None]:
    """Logs how long a block of code took. Useful for download/upload timing."""
    start = time.monotonic()
    logger.info(f"{action} started", extra={"user_id": user_id})
    try:
        yield
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(f"{action} failed after {elapsed:.2f}s: {exc}", extra={"user_id": user_id})
        raise
    else:
        elapsed = time.monotonic() - start
        logger.info(f"{action} finished in {elapsed:.2f}s", extra={"user_id": user_id})
