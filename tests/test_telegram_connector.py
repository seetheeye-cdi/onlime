from __future__ import annotations

from types import SimpleNamespace

import pytest

import onlime.connectors.telegram as telegram_connector
from onlime.config import Settings
from onlime.connectors.telegram import TelegramConnector


class FakeChat:
    def __init__(self, chat_id: int = 1, chat_type: str = "private") -> None:
        self.id = chat_id
        self.type = chat_type
        self.actions: list[str] = []

    async def send_action(self, action: str) -> None:
        self.actions.append(action)


class FakeMessage:
    def __init__(self, text: str, chat: FakeChat | None = None) -> None:
        self.text = text
        self.chat = chat or FakeChat()
        self.chat_id = self.chat.id
        self.message_id = 99
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def _settings(*, allowed_user_ids: list[int]) -> Settings:
    settings = Settings()
    settings.telegram_bot.allowed_user_ids = allowed_user_ids
    return settings


@pytest.mark.asyncio
async def test_handle_text_replies_for_unauthorized_user(monkeypatch):
    monkeypatch.setattr(telegram_connector, "get_settings", lambda: _settings(allowed_user_ids=[123]))

    connector = TelegramConnector()
    message = FakeMessage("안녕")
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=999, username="blocked"),
        message=message,
    )

    await connector._handle_text(update, context=None)

    assert message.replies == ["인증되지 않은 사용자입니다."]
    assert message.chat.actions == []


@pytest.mark.asyncio
async def test_handle_text_runs_assistant_for_authorized_user(monkeypatch):
    monkeypatch.setattr(telegram_connector, "get_settings", lambda: _settings(allowed_user_ids=[123]))

    async def fake_handle_assistant_message(**kwargs):
        assert kwargs["chat_id"] == 123
        assert kwargs["text"] == "안녕"
        return "응답입니다."

    import onlime.assistant as assistant

    monkeypatch.setattr(assistant, "handle_assistant_message", fake_handle_assistant_message)

    connector = TelegramConnector()
    message = FakeMessage("안녕")
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123, username="allowed"),
        message=message,
    )

    await connector._handle_text(update, context=None)

    assert message.chat.actions == ["typing"]
    assert message.replies == ["응답입니다."]
