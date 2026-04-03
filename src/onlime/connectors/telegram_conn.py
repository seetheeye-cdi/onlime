"""Telegram connector via Pyrogram — fetches full chat history.

File named telegram_conn.py to avoid collision with the `telegram` package.
First run requires interactive phone verification; subsequent runs reuse
the session file stored in session_dir.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)

# Pyrogram media type enum names → human-readable labels
_MEDIA_LABELS = {
    "photo": "photo",
    "video": "video",
    "document": "document",
    "voice": "voice",
    "audio": "audio",
    "sticker": "sticker",
    "animation": "animation",
    "video_note": "video_note",
    "contact": "contact",
    "location": "location",
}


def _sender_name(message) -> str:
    """Extract a display name from a Pyrogram message."""
    user = message.from_user
    if user:
        if user.first_name:
            name = user.first_name
            if user.last_name:
                name += f" {user.last_name}"
            return name
        return user.username or str(user.id)
    # Channel or group with no from_user
    chat = message.chat
    if chat and chat.title:
        return chat.title
    return "unknown"


def _chat_display_name(dialog) -> tuple[str, bool]:
    """Return (display_name, is_group) from a Pyrogram dialog."""
    from pyrogram import enums

    chat = dialog.chat
    if chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return chat.title or str(chat.id), True
    if chat.type == enums.ChatType.CHANNEL:
        return chat.title or str(chat.id), True
    # Private chat
    name_parts = []
    if chat.first_name:
        name_parts.append(chat.first_name)
    if chat.last_name:
        name_parts.append(chat.last_name)
    return " ".join(name_parts) if name_parts else (chat.username or str(chat.id)), False


def _media_type(message) -> str | None:
    """Return a human-readable media type string, or None."""
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.voice:
        return "voice"
    if message.audio:
        return "audio"
    if message.sticker:
        return "sticker"
    if message.animation:
        return "animation"
    if message.video_note:
        return "video_note"
    return None


@register
class TelegramConnector(BaseConnector):
    """Connector that pulls messages from Telegram via Pyrogram."""

    name = "telegram"

    def is_available(self) -> bool:
        settings = get_settings()
        return bool(settings.telegram.api_id and settings.telegram.api_hash)

    def fetch(self, **kwargs) -> list[ConnectorResult]:
        settings = get_settings()
        if not self.is_available():
            logger.warning("Telegram api_id/api_hash not configured, skipping")
            return []

        from pyrogram import Client

        tg = settings.telegram
        session_dir = tg.resolved_session_dir
        session_dir.mkdir(parents=True, exist_ok=True)
        session_path = str(session_dir / "onlime_telegram")

        tz = ZoneInfo(settings.general.timezone)
        cutoff = datetime.now(tz) - timedelta(days=tg.sync_days_back)

        results: list[ConnectorResult] = []

        client = Client(
            session_path,
            api_id=tg.api_id,
            api_hash=tg.api_hash,
            phone_number=tg.phone or None,
        )

        with client:
            dialogs = []
            for dialog in client.get_dialogs():
                dialogs.append(dialog)

            # Filter to sync_chats if specified
            if tg.sync_chats:
                sync_set = set(tg.sync_chats)
                dialogs = [
                    d for d in dialogs
                    if (d.chat.title or d.chat.first_name or "") in sync_set
                    or str(d.chat.id) in sync_set
                    or (d.chat.username or "") in sync_set
                ]

            logger.info("Telegram: syncing %d chats", len(dialogs))

            for dialog in dialogs:
                chat_id = dialog.chat.id
                room_name, is_group = _chat_display_name(dialog)

                for message in client.get_chat_history(chat_id):
                    msg_date = message.date
                    if msg_date is None:
                        continue

                    # Pyrogram returns UTC-aware or naive datetimes
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=ZoneInfo("UTC"))
                    msg_local = msg_date.astimezone(tz)

                    if msg_local < cutoff:
                        break  # Messages are in reverse chronological order

                    text = message.text or message.caption or ""
                    media = _media_type(message)

                    if not text and not media:
                        continue

                    sender = _sender_name(message)
                    msg_id = f"tg_{hashlib.sha256(f'{chat_id}_{message.id}'.encode()).hexdigest()[:16]}"

                    content = text
                    if media and not text:
                        content = f"[{media}]"

                    metadata: dict = {
                        "app": "telegram",
                        "room": room_name,
                        "is_group": is_group,
                        "raw_sender": sender,
                    }
                    if media:
                        metadata["media_type"] = media

                    results.append(ConnectorResult(
                        source_id=msg_id,
                        source_type="message",
                        connector_name="telegram",
                        timestamp=msg_local,
                        title=room_name,
                        content=content,
                        participants=[sender],
                        metadata=metadata,
                        raw={
                            "chat_id": chat_id,
                            "message_id": message.id,
                        },
                    ))

        logger.info("Telegram: fetched %d messages from %d chats", len(results), len(dialogs))
        return results
