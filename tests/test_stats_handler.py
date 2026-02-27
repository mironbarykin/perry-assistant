from __future__ import annotations

import asyncio
from types import SimpleNamespace

from perry_assistant.bot.handlers import stats


def test_log_incoming_update_logs_command(monkeypatch):
    captured: list[str] = []

    def _fake_statistic(message, value):  # noqa: ANN001
        captured.append(value)

    monkeypatch.setattr(stats.logger, "statistic", _fake_statistic, raising=False)

    update = SimpleNamespace(
        update_id=99,
        effective_user=SimpleNamespace(id=123, username="test_user", full_name="Test User"),
        effective_chat=SimpleNamespace(id=555),
        message=SimpleNamespace(
            message_id=1001,
            text="/today",
            caption=None,
            location=None,
        ),
        callback_query=None,
    )
    context = SimpleNamespace()

    asyncio.run(stats.log_incoming_update(update, context))

    assert captured
    assert '"command":"/today"' in captured[0]
    assert '"user_id":123' in captured[0]
