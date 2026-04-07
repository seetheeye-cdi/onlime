"""Telegram bot connector using python-telegram-bot v21+ async."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector
from onlime.connectors.registry import register
from onlime.models import ContentType, RawEvent, SourceType
from onlime.processors.categorizer import extract_hashtags
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()


def _is_authorized(user_id: int) -> bool:
    """Check if user is in the allowed list. Empty list = allow all."""
    allowed = get_settings().telegram_bot.allowed_user_ids
    return not allowed or user_id in allowed


def _detect_content_type(text: str) -> ContentType:
    """Detect if message contains a URL."""
    import re
    url_pattern = re.compile(r"https?://\S+", re.IGNORECASE)
    if url_pattern.search(text):
        return ContentType.LINK
    return ContentType.MESSAGE


def _build_raw_event(
    text: str,
    content_type: ContentType,
    user_id: int,
    username: str | None = None,
    file_path: str | None = None,
) -> RawEvent:
    """Build a RawEvent from a Telegram message."""
    hashtags = extract_hashtags(text)
    return RawEvent(
        id=str(uuid.uuid4()),
        source=SourceType.TELEGRAM,
        content_type=content_type,
        raw_content=text,
        timestamp=datetime.now(),
        metadata={
            "telegram_user_id": user_id,
            "telegram_username": username or "",
            "hashtags": hashtags,
            "file_path": file_path,
        },
    )


@register
class TelegramConnector(BaseConnector):
    """Push-based Telegram bot connector."""

    name = "telegram"

    def __init__(self) -> None:
        self._app: Application | None = None  # type: ignore[type-arg]
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._reply_futures: dict[str, asyncio.Future[str]] = {}
        self._vault_search: Any = None

    def set_vault_search(self, search: Any) -> None:
        """Inject vault search instance (called from cli.py)."""
        self._vault_search = search

    def fetch(self, **kwargs: Any) -> list:
        """Not used for push-based connector."""
        return []

    async def start(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Start the Telegram bot polling."""
        self._queue = queue
        token = get_secret_or_env("telegram-bot-token", "TELEGRAM_BOT_TOKEN")

        self._app = Application.builder().token(token).build()
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("clear", self._handle_clear))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_voice))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        logger.info("telegram.started")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()  # type: ignore[union-attr]
            await self._app.stop()
            await self._app.shutdown()
            logger.info("telegram.stopped")

    # --- Handlers ---

    async def _handle_start(self, update: Update, context: Any) -> None:
        """Handle /start command."""
        if not update.effective_user or not update.message:
            return
        if not _is_authorized(update.effective_user.id):
            await update.message.reply_text("인증되지 않은 사용자입니다.")
            return
        await update.message.reply_text(
            "안녕하세요! Onlime AI 비서입니다.\n"
            "- 자연어로 대화하면 AI 비서가 응답합니다\n"
            "- URL을 보내면 Vault에 저장합니다\n"
            "- #해시태그로 분류할 수 있어요\n"
            "- /clear 로 대화 이력을 초기화합니다"
        )

    async def _handle_clear(self, update: Update, context: Any) -> None:
        """Handle /clear command — reset conversation history."""
        if not update.effective_user or not update.message:
            return
        if not _is_authorized(update.effective_user.id):
            return
        from onlime.assistant import clear_history
        clear_history(update.effective_user.id)
        await update.message.reply_text("대화 이력을 초기화했습니다.")

    async def _handle_text(self, update: Update, context: Any) -> None:
        """Route text messages: URL/hashtag → vault save, else → AI assistant."""
        if not update.effective_user or not update.message or not update.message.text:
            return
        if not _is_authorized(update.effective_user.id):
            return

        text = update.message.text
        content_type = _detect_content_type(text)
        hashtags = extract_hashtags(text)

        # Route: URL or hashtag-prefixed → vault save pipeline
        if content_type == ContentType.LINK or hashtags:
            await self._save_to_vault(update, text, content_type)
        else:
            # Natural language → AI assistant
            await self._handle_assistant(update, text)

    async def _save_to_vault(
        self, update: Update, text: str, content_type: ContentType
    ) -> None:
        """Save content to vault via the engine pipeline (existing behavior)."""
        event = _build_raw_event(
            text=text,
            content_type=content_type,
            user_id=update.effective_user.id,  # type: ignore[union-attr]
            username=update.effective_user.username if update.effective_user else None,
        )

        event_dict = _event_to_dict(event)
        event_dict["_telegram_chat_id"] = update.message.chat_id  # type: ignore[union-attr]
        event_dict["_telegram_message_id"] = update.message.message_id  # type: ignore[union-attr]

        if self._queue:
            await self.emit(event_dict, self._queue)

        type_label = "링크" if content_type == ContentType.LINK else "텍스트"
        hashtags = event.metadata.get("hashtags", [])
        tag_str = f" [{', '.join(hashtags)}]" if hashtags else ""
        await update.message.reply_text(f"접수했습니다 ({type_label}{tag_str}). 처리 중...")  # type: ignore[union-attr]
        logger.info("telegram.received", type=type_label, user=update.effective_user.id)  # type: ignore[union-attr]

    async def _handle_assistant(self, update: Update, text: str) -> None:
        """Handle natural language conversation via Claude tool-use."""
        from onlime.assistant import handle_assistant_message

        chat_id = update.message.chat_id  # type: ignore[union-attr]
        user_id = update.effective_user.id  # type: ignore[union-attr]

        # Send typing indicator
        await update.message.chat.send_action("typing")  # type: ignore[union-attr]

        try:
            reply = await handle_assistant_message(
                chat_id=user_id,
                text=text,
                vault_search=self._vault_search,
                engine_queue=self._queue,
            )
            if reply:
                # Split long messages (Telegram 4096 char limit)
                for chunk in _split_message(reply):
                    await update.message.reply_text(chunk)  # type: ignore[union-attr]
            else:
                await update.message.reply_text("응답을 생성할 수 없습니다.")  # type: ignore[union-attr]
        except Exception as exc:
            logger.exception("telegram.assistant_error", user=user_id)
            await update.message.reply_text(f"비서 응답 오류: {exc}")  # type: ignore[union-attr]

    async def _handle_voice(self, update: Update, context: Any) -> None:
        """Handle voice messages → download file → emit as VOICE event."""
        if not update.effective_user or not update.message:
            return
        if not _is_authorized(update.effective_user.id):
            return

        voice = update.message.voice or update.message.audio
        if not voice:
            return

        # Download the voice file
        file = await context.bot.get_file(voice.file_id)
        import tempfile
        from pathlib import Path

        tmp_dir = Path(tempfile.gettempdir()) / "onlime_voice"
        tmp_dir.mkdir(exist_ok=True)
        file_ext = ".ogg" if update.message.voice else ".mp3"
        local_path = tmp_dir / f"{voice.file_unique_id}{file_ext}"
        await file.download_to_drive(str(local_path))

        event = _build_raw_event(
            text=f"[음성 메모] {voice.duration}초",
            content_type=ContentType.VOICE,
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            file_path=str(local_path),
        )

        event_dict = _event_to_dict(event)
        event_dict["_telegram_chat_id"] = update.message.chat_id
        event_dict["_telegram_message_id"] = update.message.message_id

        if self._queue:
            await self.emit(event_dict, self._queue)

        await update.message.reply_text("음성 메모 접수했습니다. 처리 중... (STT는 다음 단계)")
        logger.info("telegram.voice_received", user=update.effective_user.id, duration=voice.duration)


def _event_to_dict(event: RawEvent) -> dict[str, Any]:
    """Serialize RawEvent to dict for the engine queue."""
    return {
        "id": event.id,
        "source": event.source.value,
        "content_type": event.content_type.value,
        "raw_content": event.raw_content,
        "timestamp": event.timestamp.isoformat(),
        "metadata": event.metadata,
    }


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split text into chunks that fit Telegram's message length limit."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline before limit
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks
