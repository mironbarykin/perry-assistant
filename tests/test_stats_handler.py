from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from perry_assistant.bot.handlers import stats


def _make_update(**message_extras):
    """Build a minimal fake Update SimpleNamespace for testing."""
    msg_defaults = dict(
        message_id=1001,
        text=None,
        caption=None,
        location=None,
        photo=None,
        voice=None,
        video=None,
        audio=None,
        document=None,
        sticker=None,
        animation=None,
        video_note=None,
        contact=None,
        poll=None,
        dice=None,
        venue=None,
    )
    msg_defaults.update(message_extras)
    return SimpleNamespace(
        update_id=99,
        effective_user=SimpleNamespace(
            id=123, username="test_user", full_name="Test User", is_bot=False
        ),
        effective_chat=SimpleNamespace(id=555, type="private"),
        message=SimpleNamespace(**msg_defaults),
        edited_message=None,
        channel_post=None,
        edited_channel_post=None,
        callback_query=None,
        inline_query=None,
        poll=None,
        poll_answer=None,
        my_chat_member=None,
        chat_member=None,
        chat_join_request=None,
    )


def test_log_incoming_update_logs_command(monkeypatch):
    captured: list[str] = []

    def _fake_statistic(message, value):  # noqa: ANN001
        captured.append(value)

    monkeypatch.setattr(stats.logger, "statistic", _fake_statistic, raising=False)

    update = _make_update(text="/today")
    context = SimpleNamespace()

    asyncio.run(stats.log_incoming_update(update, context))

    assert captured
    payload = json.loads(captured[0])
    assert payload["command"] == "/today"
    assert payload["user_id"] == 123
    assert payload["update_type"] == "text_message"


def test_log_incoming_update_location(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(stats.logger, "statistic", lambda m, v: captured.append(v), raising=False)

    update = _make_update(
        location=SimpleNamespace(latitude=51.26, longitude=6.68),
    )
    context = SimpleNamespace()

    asyncio.run(stats.log_incoming_update(update, context))

    payload = json.loads(captured[0])
    assert payload["update_type"] == "location_message"
    assert payload["location"] == {"lat": 51.26, "lon": 6.68}


def test_log_incoming_update_callback_query(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(stats.logger, "statistic", lambda m, v: captured.append(v), raising=False)

    update = _make_update()
    update.message = None
    update.callback_query = SimpleNamespace(
        data="gmsg:abc:0",
        message=SimpleNamespace(message_id=200),
    )

    context = SimpleNamespace()
    asyncio.run(stats.log_incoming_update(update, context))

    payload = json.loads(captured[0])
    assert payload["update_type"] == "callback_query"
    assert payload["callback_data"] == "gmsg:abc:0"


def test_log_incoming_update_sticker(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(stats.logger, "statistic", lambda m, v: captured.append(v), raising=False)

    update = _make_update(
        sticker=SimpleNamespace(emoji="👍", set_name="Animals"),
    )
    context = SimpleNamespace()
    asyncio.run(stats.log_incoming_update(update, context))

    payload = json.loads(captured[0])
    assert payload["update_type"] == "sticker_message"
    assert payload["content_type"] == "sticker"
    assert payload["sticker_emoji"] == "👍"


def test_log_incoming_update_edited_message(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(stats.logger, "statistic", lambda m, v: captured.append(v), raising=False)

    update = _make_update(text="edited text")
    update.message = None
    update.edited_message = SimpleNamespace(
        message_id=1002,
        text="edited text",
        caption=None,
        location=None,
        photo=None, voice=None, video=None, audio=None, document=None,
        sticker=None, animation=None, video_note=None, contact=None,
        poll=None, dice=None, venue=None,
    )

    context = SimpleNamespace()
    asyncio.run(stats.log_incoming_update(update, context))

    payload = json.loads(captured[0])
    assert payload["update_type"] == "edited_message"
    assert payload["is_edited"] is True


def test_log_outgoing_emits_stat(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(stats.logger, "statistic", lambda m, v: captured.append(v), raising=False)

    stats.log_outgoing(
        "sendMessage",
        {"chat_id": 123, "text": "Hello world", "parse_mode": "Markdown"},
        "handlers.schedule.today",
    )

    assert captured
    payload = json.loads(captured[0])
    assert payload["endpoint"] == "sendMessage"
    assert payload["chat_id"] == 123
    assert payload["text_preview"] == "Hello world"
    assert payload["function"] == "handlers.schedule.today"
    assert payload["parse_mode"] == "Markdown"

