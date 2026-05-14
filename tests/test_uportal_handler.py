from __future__ import annotations

import asyncio
from types import SimpleNamespace

from perry_assistant.bot.handlers.uportal import ignore_uportal_game, uportal, uportal_ignored


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class _FakeUportalService:
    def __init__(self) -> None:
        self.called = False
        self.ignored_called = False
        self.ignore_calls: list[str] = []
        self.ignore_all_calls: list[str] = []

    async def run_manual_scan(self, context) -> None:
        self.called = True

    async def run_show_ignored(self, context) -> None:
        self.ignored_called = True

    def ignore_game_by_id(self, ignore_id: str) -> tuple[bool, str]:
        self.ignore_calls.append(ignore_id)
        return True, f"Ignored: {ignore_id}"

    def ignore_all_in_group(self, group_id: str) -> tuple[bool, str]:
        self.ignore_all_calls.append(group_id)
        return True, f"Ignored group: {group_id}"


def _context_with_services(admin_id: int, service: _FakeUportalService):
    services = SimpleNamespace(
        config=SimpleNamespace(miron_id=admin_id),
        uportal_service=service,
    )
    return SimpleNamespace(application=SimpleNamespace(bot_data={"services": services}))


def test_uportal_handler_admin_only():
    message = _FakeMessage()
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=999))
    service = _FakeUportalService()
    context = _context_with_services(admin_id=123, service=service)

    asyncio.run(uportal(update, context))

    assert service.called is False
    assert '🫸' in ','.join(message.replies)


def test_uportal_handler_calls_service_for_admin():
    message = _FakeMessage()
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123))
    service = _FakeUportalService()
    context = _context_with_services(admin_id=123, service=service)

    asyncio.run(uportal(update, context))

    assert service.called is True
    assert message.replies == ["Running Uportal scan...", "Uportal scan finished."]


def test_uportal_ignored_handler_calls_service_for_admin():
    message = _FakeMessage()
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123))
    service = _FakeUportalService()
    context = _context_with_services(admin_id=123, service=service)

    asyncio.run(uportal_ignored(update, context))

    assert service.ignored_called is True


def test_ignore_uportal_game_callback_calls_service():
    query_message = _FakeMessage()

    class _FakeQuery:
        def __init__(self) -> None:
            self.data = "uio:g:abc123"
            self.message = query_message
            self.answers: list[str] = []

        async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
            if text:
                self.answers.append(text)

    query = _FakeQuery()
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=123))
    service = _FakeUportalService()
    context = _context_with_services(admin_id=123, service=service)

    asyncio.run(ignore_uportal_game(update, context))

    assert service.ignore_calls == ["abc123"]
    assert query_message.replies == ["Ignored: abc123"]


def test_ignore_uportal_all_callback_calls_service():
    query_message = _FakeMessage()

    class _FakeQuery:
        def __init__(self) -> None:
            self.data = "uio:a:grp123"
            self.message = query_message
            self.answers: list[str] = []

        async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
            if text:
                self.answers.append(text)

    query = _FakeQuery()
    update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=123))
    service = _FakeUportalService()
    context = _context_with_services(admin_id=123, service=service)

    asyncio.run(ignore_uportal_game(update, context))

    assert service.ignore_all_calls == ["grp123"]
    assert query_message.replies == ["Ignored group: grp123"]
