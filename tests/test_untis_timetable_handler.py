from __future__ import annotations

import asyncio
from types import SimpleNamespace

from telegram.ext import ConversationHandler

from perry_assistant.bot.handlers.untis_timetable import (
    UNTIS_ASK_PASSWORD,
    UNTIS_ASK_USERNAME,
    untis_setup,
    untis_setup_callback,
    untis_setup_username,
)


class _FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class _FakeQuery:
    def __init__(self) -> None:
        self.data = "untis_setup"
        self.message = _FakeMessage()
        self.answered = False

    async def answer(self, **kwargs) -> None:
        self.answered = True


def test_untis_setup_returns_ask_username_state():
    message = _FakeMessage()
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(user_data={})

    result = asyncio.run(untis_setup(update, context))

    assert result == UNTIS_ASK_USERNAME
    assert len(message.replies) == 1
    assert "Benutzernamen" in message.replies[0]


def test_untis_setup_callback_returns_ask_username_state():
    """Inline-button entry must return UNTIS_ASK_USERNAME so the
    ConversationHandler transitions to the username-input state."""
    query = _FakeQuery()
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(user_data={})

    result = asyncio.run(untis_setup_callback(update, context))

    assert result == UNTIS_ASK_USERNAME
    assert query.answered
    assert len(query.message.replies) == 1
    assert "Benutzernamen" in query.message.replies[0]


def test_untis_setup_callback_ends_without_query():
    update = SimpleNamespace(callback_query=None)
    context = SimpleNamespace(user_data={})

    result = asyncio.run(untis_setup_callback(update, context))

    assert result == ConversationHandler.END


def test_untis_setup_username_stores_name_and_returns_password_state():
    message = _FakeMessage(text="  max.mueller  ")
    update = SimpleNamespace(message=message)
    user_data: dict[str, str] = {}
    context = SimpleNamespace(user_data=user_data)

    result = asyncio.run(untis_setup_username(update, context))

    assert result == UNTIS_ASK_PASSWORD
    assert user_data["untis_username"] == "max.mueller"
    assert len(message.replies) == 1
    assert "Passwort" in message.replies[0]
