from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram.ext import ConversationHandler

from perry_assistant.bot.handlers.admin import (
    PUBLISH_STATE,
    PUBLISH_TARGET_PARENTS,
    PUBLISH_TARGET_UNTIS,
    published_send,
    published_start,
)
from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import write_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, text: str = "", user_id: int = 123456) -> None:
        self.text = text
        self._user_id = user_id
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)


def _make_update(message: _FakeMessage, user_id: int = 123456) -> SimpleNamespace:
    user = SimpleNamespace(id=user_id)
    return SimpleNamespace(message=message, effective_user=user)


def _make_context(
    config: AppConfig,
    args: list[str] | None = None,
    user_data: dict | None = None,
    bot: _FakeBot | None = None,
) -> SimpleNamespace:
    services = SimpleNamespace(config=config)
    app = SimpleNamespace(bot_data={"services": services})
    return SimpleNamespace(
        args=args or [],
        user_data=user_data if user_data is not None else {},
        bot=bot or _FakeBot(),
        application=app,
    )


@pytest.fixture
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


# ---------------------------------------------------------------------------
# published_start tests
# ---------------------------------------------------------------------------


class TestPublishedStart:
    def test_no_args_returns_end_with_usage(self, cfg: AppConfig) -> None:
        message = _FakeMessage()
        update = _make_update(message)
        context = _make_context(cfg, args=[])

        result = asyncio.run(published_start(update, context))

        assert result == ConversationHandler.END
        assert len(message.replies) == 1
        assert "Usage" in message.replies[0]

    def test_invalid_arg_returns_end_with_usage(self, cfg: AppConfig) -> None:
        message = _FakeMessage()
        update = _make_update(message)
        context = _make_context(cfg, args=["unknown"])

        result = asyncio.run(published_start(update, context))

        assert result == ConversationHandler.END
        assert "Usage" in message.replies[0]

    def test_parents_arg_returns_publish_state(self, cfg: AppConfig) -> None:
        message = _FakeMessage()
        update = _make_update(message)
        user_data: dict = {}
        context = _make_context(cfg, args=["parents"], user_data=user_data)

        result = asyncio.run(published_start(update, context))

        assert result == PUBLISH_STATE
        assert user_data["publish_target"] == PUBLISH_TARGET_PARENTS
        assert "parents" in message.replies[0]

    def test_untis_arg_returns_publish_state(self, cfg: AppConfig) -> None:
        message = _FakeMessage()
        update = _make_update(message)
        user_data: dict = {}
        context = _make_context(cfg, args=["untis"], user_data=user_data)

        result = asyncio.run(published_start(update, context))

        assert result == PUBLISH_STATE
        assert user_data["publish_target"] == PUBLISH_TARGET_UNTIS
        assert "untis" in message.replies[0]

    def test_non_admin_returns_end(self, cfg: AppConfig) -> None:
        message = _FakeMessage(user_id=999)
        update = _make_update(message, user_id=999)
        context = _make_context(cfg, args=["parents"])

        result = asyncio.run(published_start(update, context))

        assert result == ConversationHandler.END
        assert "Admin" in message.replies[0]

    def test_no_message_returns_end(self, cfg: AppConfig) -> None:
        update = SimpleNamespace(message=None, effective_user=SimpleNamespace(id=123456))
        context = _make_context(cfg)

        result = asyncio.run(published_start(update, context))

        assert result == ConversationHandler.END


# ---------------------------------------------------------------------------
# published_send tests
# ---------------------------------------------------------------------------


class TestPublishedSend:
    def test_send_to_parents(self, cfg: AppConfig) -> None:
        write_json(cfg.parents_file, [111, 222])
        message = _FakeMessage(text="Hello parents!")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_PARENTS},
            bot=bot,
        )

        result = asyncio.run(published_send(update, context))

        assert result == ConversationHandler.END
        assert len(bot.sent) == 2
        assert all(m["text"] == "Hello parents!" for m in bot.sent)
        assert "2 parents" in message.replies[0]

    def test_send_to_untis_users(self, cfg: AppConfig) -> None:
        write_json(cfg.untis_users_file, {
            "333": {"username": "u1", "password": "test-password"},
            "444": {"username": "u2", "password": "test-password"},
        })
        message = _FakeMessage(text="Timetable update!")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_UNTIS},
            bot=bot,
        )

        result = asyncio.run(published_send(update, context))

        assert result == ConversationHandler.END
        assert len(bot.sent) == 2
        assert all(m["text"] == "Timetable update!" for m in bot.sent)
        assert "2 untis" in message.replies[0]

    def test_no_parents_returns_end_with_message(self, cfg: AppConfig) -> None:
        message = _FakeMessage(text="Hello!")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_PARENTS},
            bot=bot,
        )

        result = asyncio.run(published_send(update, context))

        assert result == ConversationHandler.END
        assert len(bot.sent) == 0
        assert "parents" in message.replies[0]

    def test_no_untis_users_returns_end_with_message(self, cfg: AppConfig) -> None:
        message = _FakeMessage(text="Hello!")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_UNTIS},
            bot=bot,
        )

        result = asyncio.run(published_send(update, context))

        assert result == ConversationHandler.END
        assert len(bot.sent) == 0
        assert "untis" in message.replies[0]

    def test_admin_id_excluded_from_parents(self, cfg: AppConfig) -> None:
        # miron_id is 123456, also in parents list
        write_json(cfg.parents_file, [123456, 111])
        message = _FakeMessage(text="Broadcast")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_PARENTS},
            bot=bot,
        )

        asyncio.run(published_send(update, context))

        sent_ids = [m["chat_id"] for m in bot.sent]
        assert 123456 not in sent_ids
        assert 111 in sent_ids

    def test_admin_id_excluded_from_untis_users(self, cfg: AppConfig) -> None:
        # miron_id is 123456, also in untis users
        write_json(cfg.untis_users_file, {
            "123456": {"username": "admin", "password": "test-password"},
            "555": {"username": "u1", "password": "test-password"},
        })
        message = _FakeMessage(text="Change!")
        update = _make_update(message)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_UNTIS},
            bot=bot,
        )

        asyncio.run(published_send(update, context))

        sent_ids = [m["chat_id"] for m in bot.sent]
        assert 123456 not in sent_ids
        assert 555 in sent_ids

    def test_non_admin_returns_end_immediately(self, cfg: AppConfig) -> None:
        write_json(cfg.parents_file, [111])
        message = _FakeMessage(text="Hi", user_id=999)
        update = _make_update(message, user_id=999)
        bot = _FakeBot()
        context = _make_context(
            cfg,
            user_data={"publish_target": PUBLISH_TARGET_PARENTS},
            bot=bot,
        )

        result = asyncio.run(published_send(update, context))

        assert result == ConversationHandler.END
        assert len(bot.sent) == 0
