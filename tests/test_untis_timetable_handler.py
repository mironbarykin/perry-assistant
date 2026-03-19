from __future__ import annotations

import asyncio
from pathlib import Path
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
        self.answered_text: str = ""

    async def answer(self, text: str = "", **kwargs) -> None:
        self.answered = True
        self.answered_text = text


def _make_services(parents_file: Path) -> object:
    """Build a minimal services stub with a config pointing to a parents file."""
    config = SimpleNamespace(parents_file=parents_file)
    return SimpleNamespace(config=config)


def _make_context(services: object, user_data: dict | None = None) -> object:
    bot_data = {"services": services}
    application = SimpleNamespace(bot_data=bot_data)
    return SimpleNamespace(application=application, user_data=user_data if user_data is not None else {})


def test_untis_setup_returns_ask_username_state(tmp_path):
    services = _make_services(tmp_path / "parents.json")
    context = _make_context(services)
    message = _FakeMessage()
    user = SimpleNamespace(id=9999)
    update = SimpleNamespace(message=message, effective_user=user)

    result = asyncio.run(untis_setup(update, context))

    assert result == UNTIS_ASK_USERNAME
    assert len(message.replies) == 1
    assert "Benutzernamen" in message.replies[0]


def test_untis_setup_blocked_for_parent(tmp_path):
    import json

    parents_file = tmp_path / "parents.json"
    parents_file.write_text(json.dumps([42]))
    services = _make_services(parents_file)
    context = _make_context(services)
    message = _FakeMessage()
    user = SimpleNamespace(id=42)
    update = SimpleNamespace(message=message, effective_user=user)

    result = asyncio.run(untis_setup(update, context))

    assert result == ConversationHandler.END
    assert any("not available" in r for r in message.replies)


def test_untis_setup_callback_returns_ask_username_state(tmp_path):
    """Inline-button entry must return UNTIS_ASK_USERNAME so the
    ConversationHandler transitions to the username-input state."""
    services = _make_services(tmp_path / "parents.json")
    context = _make_context(services)
    query = _FakeQuery()
    user = SimpleNamespace(id=9999)
    update = SimpleNamespace(callback_query=query, effective_user=user)

    result = asyncio.run(untis_setup_callback(update, context))

    assert result == UNTIS_ASK_USERNAME
    assert query.answered
    assert len(query.message.replies) == 1
    assert "Benutzernamen" in query.message.replies[0]


def test_untis_setup_callback_blocked_for_parent(tmp_path):
    import json

    parents_file = tmp_path / "parents.json"
    parents_file.write_text(json.dumps([42]))
    services = _make_services(parents_file)
    context = _make_context(services)
    query = _FakeQuery()
    user = SimpleNamespace(id=42)
    update = SimpleNamespace(callback_query=query, effective_user=user)

    result = asyncio.run(untis_setup_callback(update, context))

    assert result == ConversationHandler.END
    assert query.answered
    assert "not available" in query.answered_text.lower()


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
