"""Retry failed pipeline events.

Periodically scans the state DB for events that failed processing
(e.g. transient network errors, LLM timeouts) and re-queues them
through the engine pipeline.

- Max 3 retries per event
- Only events younger than 24 hours
- 5-minute polling interval
"""

from __future__ import annotations

import asyncio
import json

import structlog

from onlime.maintenance.base import BackgroundTask

logger = structlog.get_logger()


class EventRetryTask(BackgroundTask):
    """Background task that retries failed events."""

    name = "event_retry"

    def __init__(self, interval_seconds: int, engine_queue: asyncio.Queue) -> None:
        super().__init__(interval_seconds)
        self._queue = engine_queue

    async def run_once(self) -> None:
        if self._store is None:
            return
        retryable = await self._store.get_retryable_events(max_retries=3, max_age_hours=24)
        for row in retryable:
            payload = json.loads(row["payload"])
            await self._store.increment_retry(row["id"])
            await self._queue.put(payload)
            logger.info(
                "event_retry.requeued",
                event_id=row["id"][:8],
                attempt=row["retry_count"] + 1,
            )
        if retryable:
            logger.info("event_retry.cycle", requeued=len(retryable))
