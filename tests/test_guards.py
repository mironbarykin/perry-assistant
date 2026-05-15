from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import asyncio
from telegram.ext import ConversationHandler

from perry_assistant.bot.handlers.guards import require_admin, require_family
from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import write_json


class _FakeMessage:
    def __init__(self, text: str = "", user_id: int = 123456) -> None:
        self.text = text
        self._user_id = user_id
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class _FakeCallbackQuery:
    def __init__(self, message: _FakeMessage | None = None) -> None:
        self.message = message or _FakeMessage()
        self.answered: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answered.append((text, show_alert))


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def _make_update_message(user_id: int, message: _FakeMessage) -> SimpleNamespace:
    user = SimpleNamespace(id=user_id)
    return SimpleNamespace(message=message, effective_user=user)


def _make_update_callback(user_id: int, query: _FakeCallbackQuery) -> SimpleNamespace:
    user = SimpleNamespace(id=user_id)
    return SimpleNamespace(callback_query=query, effective_user=user)


def _make_context(config: AppConfig, bot: _FakeBot | None = None) -> SimpleNamespace:
    services = SimpleNamespace(config=config)
    app = SimpleNamespace(bot_data={"services": services})
    return SimpleNamespace(bot=bot or _FakeBot(), application=app, user_data={}, args=[])


def cfg(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return AppConfig(
        tg_token="test-token",
        data_dir=data_dir,
        logs_dir=data_dir / "logs",
        miron_id=123456,
        debug_mode=False,
        credentials_file=data_dir / "creds.json",
        token_pickle_file=data_dir / "token.pickle",
        notification_file=data_dir / "notification_times.json",
        parents_file=data_dir / "parents.json",
        processed_emails_file=data_dir / "processed_emails.json",
        referee_events_file=data_dir / "referee_events.json",
        gyms_cache_file=data_dir / "gyms_cache.json",
        address_cache_file=data_dir / "address_cache.json",
        school_absence_file=data_dir / "school_absences.json",
        school_timetable_file=data_dir / "school_timetable.json",
        weather_location_file=data_dir / "weather_location.json",
        game_message_rules_file=data_dir / "game_message_rules.json",
        game_message_state_file=data_dir / "game_message_state.json",
        uportal_seen_rows_file=data_dir / "uportal_seen_rows.json",
        uportal_window_state_file=data_dir / "uportal_window_state.json",
        uportal_ignored_rows_file=data_dir / "uportal_ignored_rows.json",
        uportal_game_catalog_file=data_dir / "uportal_game_catalog.json",
        basketball_senders=("sender@example.com",),
        home_coords={"lat": 1.0, "lon": 2.0},
        school_coords={"lat": 3.0, "lon": 4.0},
        scopes=("scope1",),
        uportal_login_name="test-user",
        uportal_login_password="test-pass",
        uportal_login_url="https://example.com/login",
        michi_id=789012,
        untis_users_file=data_dir / "untis_users.json",
        untis_timetable_state_file=data_dir / "untis_timetable_state.json",
        untis_changes_file=data_dir / "untis_changes_state.json",
        untis_server="thalia.webuntis.com",
        untis_school="test-school",
        miron_school_calendar_id="cal-miron",
        michi_school_calendar_id="cal-michi",
        home_address="Test Address 123, Test City",
        ors_api_key="test-ors-api-key",
        google_api_key="test-google-api-key",
    )


def test_require_admin_allows_admin_message(tmp_path: Path) -> None:
    config = cfg(tmp_path)
    message = _FakeMessage()
    update = _make_update_message(123456, message)
    context = _make_context(config)

    called: dict[str, bool] = {"ok": False}

    @require_admin
    async def handler(u, c):
        called["ok"] = True
        return "done"

    result = asyncio.run(handler(update, context))
    assert result == "done"
    assert called["ok"]


def test_require_admin_denies_non_admin_message(tmp_path: Path) -> None:
    config = cfg(tmp_path)
    message = _FakeMessage(user_id=999)
    update = _make_update_message(999, message)
    context = _make_context(config)

    @require_admin
    async def handler(u, c):
        return "should not run"

    result = asyncio.run(handler(update, context))
    assert result == ConversationHandler.END
    assert any("🫸" in r for r in message.replies)


def test_require_admin_denies_callback_query(tmp_path: Path) -> None:
    config = cfg(tmp_path)
    query = _FakeCallbackQuery()
    update = _make_update_callback(999, query)
    context = _make_context(config)

    @require_admin
    async def handler(u, c):
        return "should not run"

    result = asyncio.run(handler(update, context))
    assert result == ConversationHandler.END
    assert query.answered and query.answered[0][1] is True


def test_require_family_allows_parent(tmp_path: Path) -> None:
    config = cfg(tmp_path)
    # write parent list to include user 555
    write_json(config.parents_file, [555])
    message = _FakeMessage(user_id=555)
    update = _make_update_message(555, message)
    context = _make_context(config)

    @require_family
    async def handler(u, c):
        return "ok"

    result = asyncio.run(handler(update, context))
    assert result == "ok"
