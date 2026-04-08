"""Telegram edit_message based pipeline progress reporter."""

from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger()

# Minimum interval between edits to avoid Telegram rate limits
_MIN_EDIT_INTERVAL = 2.0


class ProgressReporter:
    """Show pipeline progress by editing a single Telegram message.

    If chat_id is None or telegram_app is missing, all methods are no-ops.
    """

    def __init__(
        self, telegram_app: Any, chat_id: int | None, reply_to: int | None,
    ) -> None:
        self._app = telegram_app
        self._chat_id = chat_id
        self._reply_to = reply_to
        self._msg_id: int | None = None
        self._last_edit: float = 0.0
        self._enabled = bool(telegram_app and chat_id)

    @classmethod
    async def create(
        cls, telegram_app: Any, chat_id: int | None, reply_to: int | None,
    ) -> ProgressReporter:
        """Send initial progress message and return bound reporter."""
        reporter = cls(telegram_app, chat_id, reply_to)
        if reporter._enabled:
            try:
                msg = await telegram_app.bot.send_message(
                    chat_id=chat_id,
                    text="⏳ 처리 시작...",
                    reply_to_message_id=reply_to,
                )
                reporter._msg_id = msg.message_id
                reporter._last_edit = time.monotonic()
            except Exception:
                logger.debug("progress.create_failed")
                reporter._enabled = False
        return reporter

    async def update(self, text: str) -> None:
        """Edit the progress message. Rate-limited to avoid Telegram 429s."""
        if not self._enabled or not self._msg_id:
            return
        now = time.monotonic()
        if now - self._last_edit < _MIN_EDIT_INTERVAL:
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=self._msg_id,
                text=text,
            )
            self._last_edit = now
        except Exception:
            # Silently ignore edit failures (message deleted, etc.)
            pass

    async def delete(self) -> None:
        """Delete the progress message before sending final confirmation."""
        if not self._enabled or not self._msg_id:
            return
        try:
            await self._app.bot.delete_message(
                chat_id=self._chat_id,
                message_id=self._msg_id,
            )
        except Exception:
            pass
        self._msg_id = None
