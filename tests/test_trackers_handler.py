from __future__ import annotations

import asyncio
import csv
import json
from types import SimpleNamespace

from perry_assistant.bot.handlers.trackers import (
    dispatch_callback,
    dispatch_text,
    shower,
)


class _FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.deleted = False
        self.replies: list[dict] = []
        self.edits: list[dict] = []

    async def reply_text(self, text: str, **kwargs):
        message = _FakeMessage(text)
        self.replies.append({"text": text, "kwargs": kwargs, "message": message})
        return message

    async def delete(self) -> None:
        self.deleted = True

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edits.append({"text": text, "kwargs": kwargs})
        self.text = text


class _FakeQuery:
    def __init__(self, data: str, message: _FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


def _services(app_config):
    return SimpleNamespace(config=app_config)


def _context(app_config):
    services = _services(app_config)
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"services": services}),
        user_data={},
    )


def _message_update(message: _FakeMessage, user_id: int):
    return SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
    )


def _callback_update(query: _FakeQuery, user_id: int):
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
    )


def test_shower_flow_records_temperature_and_products(app_config):
    context = _context(app_config)
    user_id = app_config.miron_id

    start_message = _FakeMessage()
    asyncio.run(shower(_message_update(start_message, user_id), context))
    when_prompt = start_message.replies[0]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("when_now", when_prompt), user_id), context))
    location_prompt = when_prompt.replies[0]["message"]
    assert when_prompt.deleted is True

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("loc_home", location_prompt), user_id), context))
    duration_prompt = location_prompt.replies[0]["message"]
    assert location_prompt.deleted is True

    duration_message = _FakeMessage("15")
    asyncio.run(dispatch_text(_message_update(duration_message, user_id), context))
    temperature_prompt = duration_message.replies[0]["message"]
    assert duration_prompt.deleted is True
    assert context.user_data["tracker_data"]["duration_min"] == 15

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("temp_warm", temperature_prompt), user_id), context))
    products_prompt = temperature_prompt.replies[0]["message"]
    assert temperature_prompt.deleted is True
    assert context.user_data["tracker_data"]["temperature"] == "warm"

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_shampoo", products_prompt), user_id), context))
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_gel", products_prompt), user_id), context))
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_done", products_prompt), user_id), context))

    csv_path = app_config.data_dir / "tracker_shower_entries.csv"
    assert csv_path.exists()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["duration_min"] == "15"
    assert rows[0]["location_label"] == "🏠Home"
    assert rows[0]["temperature_label"] == "🔥Warm"
    assert json.loads(rows[0]["products_used_json"]) == ["shampoo", "gel"]
    assert "tracker_state" not in context.user_data
    assert "tracker_data" not in context.user_data


def test_cancel_clears_tracker_state(app_config):
    context = _context(app_config)
    user_id = app_config.miron_id

    start_message = _FakeMessage()
    asyncio.run(shower(_message_update(start_message, user_id), context))
    when_prompt = start_message.replies[0]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("when_now", when_prompt), user_id), context))
    location_prompt = when_prompt.replies[0]["message"]

    cancel_message = _FakeMessage("/cancel")
    from perry_assistant.bot.handlers.trackers import cancel_tracker

    asyncio.run(cancel_tracker(_message_update(cancel_message, user_id), context))

    assert when_prompt.deleted is True
    assert location_prompt.deleted is True
    assert context.user_data == {}


def test_fap_flow_records_sources(app_config):
    """Test fap tracker flow with sources selection and CSV writing."""
    from perry_assistant.bot.handlers.trackers import fap
    
    context = _context(app_config)
    user_id = app_config.miron_id

    start_message = _FakeMessage()
    asyncio.run(fap(_message_update(start_message, user_id), context))
    when_prompt = start_message.replies[0]["message"]
    assert context.user_data["tracker_data"]["type"] == "fap"

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("when_now", when_prompt), user_id), context))
    location_prompt = when_prompt.replies[0]["message"]
    assert when_prompt.deleted is True

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("loc_bedroom", location_prompt), user_id), context))
    duration_prompt = location_prompt.replies[0]["message"]
    assert location_prompt.deleted is True

    duration_message = _FakeMessage("10")
    asyncio.run(dispatch_text(_message_update(duration_message, user_id), context))
    sources_prompt = duration_message.replies[0]["message"]
    assert duration_prompt.deleted is True
    assert context.user_data["tracker_data"]["duration_min"] == 10

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_videos", sources_prompt), user_id), context))
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_lubricant", sources_prompt), user_id), context))
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_done", sources_prompt), user_id), context))

    csv_path = app_config.data_dir / "tracker_fap_entries.csv"
    assert csv_path.exists()
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["duration_min"] == "10"
    assert rows[0]["location_label"] == "🛏️Bedroom"
    assert json.loads(rows[0]["sources_json"]) == ["videos", "lubricant"]
    assert "temperature_label" not in rows[0]
    assert "tracker_state" not in context.user_data
    assert "tracker_data" not in context.user_data


def test_when_today_prompts_for_time_and_uses_today_date(app_config):
    context = _context(app_config)
    user_id = app_config.miron_id

    start_message = _FakeMessage()
    asyncio.run(shower(_message_update(start_message, user_id), context))
    when_prompt = start_message.replies[0]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("when_today", when_prompt), user_id), context))
    assert context.user_data["tracker_state"] == 8

    time_message = _FakeMessage("18:30")
    asyncio.run(dispatch_text(_message_update(time_message, user_id), context))
    location_prompt = time_message.replies[0]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("loc_home", location_prompt), user_id), context))
    duration_message = _FakeMessage("7")
    asyncio.run(dispatch_text(_message_update(duration_message, user_id), context))
    temp_prompt = duration_message.replies[0]["message"]
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("temp_warm", temp_prompt), user_id), context))
    products_prompt = temp_prompt.replies[0]["message"]
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_done", products_prompt), user_id), context))

    csv_path = app_config.data_dir / "tracker_shower_entries.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    happened = rows[0]["happened_at_utc"]
    assert "T" in happened
    assert "+" in happened or happened.endswith("Z")


def test_when_other_requires_date_and_time_in_one_message(app_config):
    context = _context(app_config)
    user_id = app_config.miron_id

    start_message = _FakeMessage()
    asyncio.run(shower(_message_update(start_message, user_id), context))
    when_prompt = start_message.replies[0]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("when_other", when_prompt), user_id), context))
    assert context.user_data["tracker_state"] == 9

    invalid_message = _FakeMessage("19:30")
    asyncio.run(dispatch_text(_message_update(invalid_message, user_id), context))
    assert any("Invalid date/time" in item["text"] for item in invalid_message.replies)
    assert context.user_data["tracker_state"] == 9

    valid_message = _FakeMessage("2026-01-15 19:30")
    asyncio.run(dispatch_text(_message_update(valid_message, user_id), context))
    location_prompt = valid_message.replies[-1]["message"]

    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("loc_home", location_prompt), user_id), context))
    duration_message = _FakeMessage("9")
    asyncio.run(dispatch_text(_message_update(duration_message, user_id), context))
    temp_prompt = duration_message.replies[0]["message"]
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("temp_warm", temp_prompt), user_id), context))
    products_prompt = temp_prompt.replies[0]["message"]
    asyncio.run(dispatch_callback(_callback_update(_FakeQuery("prod_done", products_prompt), user_id), context))

    csv_path = app_config.data_dir / "tracker_shower_entries.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["happened_at_utc"].startswith("2026-01-15T")