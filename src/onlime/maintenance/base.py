"""Base class for all periodic background tasks."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import structlog

from onlime.state.store import StateStore

logger = structlog.get_logger()


class BackgroundTask(ABC):
    """Common base for periodic background tasks.

    Provides:
    - Unified start/stop/status interface
    - Resilient sleep with macOS sleep-gap detection
    - Automatic connector_state tracking (cursor + failure count)
    """

    name: str  # subclass must set: "kakao_sync", "vault_janitor", etc.

    def __init__(self, interval_seconds: int) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._store: StateStore | None = None
        self._consecutive_failures: int = 0
        self._last_run_at: float = 0.0

    async def start(self, store: StateStore | None = None) -> None:
        self._store = store
        self._task = asyncio.create_task(self._loop())
        logger.info(f"{self.name}.started", interval=self.interval_seconds)

    async def _loop(self) -> None:
        while True:
            loop_start = time.monotonic()
            try:
                await self.run_once()
                self._consecutive_failures = 0
                self._last_run_at = time.monotonic()
                if self._store:
                    await self._store.set_cursor(self.name, datetime.now().isoformat())
            except asyncio.CancelledError:
                raise
            except Exception:
                self._consecutive_failures += 1
                if self._store:
                    await self._store.record_failure(self.name)
                logger.exception(
                    f"{self.name}.run_failed",
                    failures=self._consecutive_failures,
                )
            await self._resilient_sleep(loop_start)

    async def _resilient_sleep(self, loop_started: float) -> None:
        try:
            await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            raise
        elapsed = time.monotonic() - loop_started
        if elapsed > self.interval_seconds * 2:
            logger.warning(
                f"{self.name}.sleep_gap_detected",
                expected=self.interval_seconds,
                actual=int(elapsed),
            )

    @abstractmethod
    async def run_once(self) -> None: ...

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"{self.name}.stopped")

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "running": self._task is not None and not self._task.done(),
            "failures": self._consecutive_failures,
            "last_run": self._last_run_at,
        }
