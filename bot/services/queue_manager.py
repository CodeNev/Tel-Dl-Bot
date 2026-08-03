"""Async job queue that limits concurrent downloads and supports cancellation.

Each job is a coroutine factory submitted along with a unique job_id. The
queue enforces `max_concurrent` running jobs at once and `max_queue_size`
pending jobs, matching MAX_CONCURRENT_DOWNLOADS / MAX_QUEUE_SIZE.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bot.utils.logger import get_logger

logger = get_logger(__name__)


class QueueFullError(Exception):
    pass


@dataclass
class Job:
    job_id: str
    user_id: int
    coro_factory: Callable[[], Awaitable[None]]
    task: Optional[asyncio.Task] = None
    cancelled: bool = False


class DownloadQueueManager:
    def __init__(self, max_concurrent: int, max_queue_size: int):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, Job] = {}
        self._pending_count = 0
        self._lock = asyncio.Lock()

    async def submit(self, job_id: str, user_id: int, coro_factory: Callable[[], Awaitable[None]]) -> Job:
        async with self._lock:
            if self._pending_count >= self.max_queue_size:
                raise QueueFullError("The download queue is full. Please try again shortly.")
            self._pending_count += 1

        job = Job(job_id=job_id, user_id=user_id, coro_factory=coro_factory)
        self._jobs[job_id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        try:
            async with self._semaphore:
                if job.cancelled:
                    return
                await job.coro_factory()
        except asyncio.CancelledError:
            logger.info(f"Job {job.job_id} was cancelled", extra={"user_id": job.user_id})
        except Exception:
            logger.exception(f"Job {job.job_id} raised an unhandled exception")
        finally:
            async with self._lock:
                self._pending_count = max(0, self._pending_count - 1)
            self._jobs.pop(job.job_id, None)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancelled = True
        if job.task and not job.task.done():
            job.task.cancel()
        return True

    def active_count(self) -> int:
        return len(self._jobs)
