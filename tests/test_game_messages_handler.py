from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

from perry_assistant.bot.handlers.game_messages import PICKER_STATE_KEY, games, select_game
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.services.game_message_service import ParsedGameEvent


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append({"text": text, "kwargs": kwargs})


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        del chat_id, kwargs
        self.messages.append(text)


class _FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


class _FakeGameMessageService:
    def __init__(self, events: list[ParsedGameEvent], drafts: list[str]) -> None:
        self._events = events
        self._drafts = drafts
        self.selected_args: tuple[str, str] | None = None

    def list_upcoming_games(self, days: int = 7, now=None):  # noqa: ANN001
        del days, now
        return list(self._events)

    def build_drafts_for_selected_game(self, event_id: str, start_iso: str, now=None):  # noqa: ANN001
        del now
        self.selected_args = (event_id, start_iso)
        return [SimpleNamespace(text=item) for item in self._drafts]


def test_games_command_shows_picker_buttons():
    start = dt.datetime(2026, 3, 4, 18, 0, tzinfo=BERLIN_TZ)
    events = [
        ParsedGameEvent(
            event_id="e1",
            summary="2RLU16W Referee Game",
            description="Referees: A, B",
            location="Gym",
            start=start,
            end=start + dt.timedelta(hours=2),
            category="referee",
            league="2RLU16W",
            team="",
            team_bucket="",
            home_or_guest="guest",
            referees=["A", "B"],
        )
    ]
    message = _FakeMessage()
    service = _FakeGameMessageService(events, drafts=[])
    services = SimpleNamespace(config=SimpleNamespace(miron_id=42), game_message_service=service)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"services": services}))
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))

    asyncio.run(games(update, context))

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "Choose a game" in reply["text"]
    markup = reply["kwargs"]["reply_markup"]
    assert markup.inline_keyboard
    assert markup.inline_keyboard[0][0].callback_data.startswith("gmsg:")
    picker_state = context.application.bot_data[PICKER_STATE_KEY]
    assert picker_state


def test_select_game_generates_separate_draft_messages():
    fake_picker_id = "abcd1234"
    start_iso = dt.datetime(2026, 3, 4, 18, 0, tzinfo=BERLIN_TZ).isoformat()
    service = _FakeGameMessageService(events=[], drafts=["ref draft", "parents draft", "players draft"])
    services = SimpleNamespace(config=SimpleNamespace(miron_id=42), game_message_service=service)
    bot_data = {
        "services": services,
        PICKER_STATE_KEY: {
            fake_picker_id: {
                "owner_id": 42,
                "created_at": dt.datetime.now(dt.UTC).isoformat(),
                "events": [{"event_id": "ev1", "start": start_iso, "label": "Wed 04.03 18:00 Ref 2RLU16W"}],
            }
        },
    }
    context = SimpleNamespace(application=SimpleNamespace(bot_data=bot_data), bot=_FakeBot())
    query = _FakeQuery(data=f"gmsg:{fake_picker_id}:0")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=42),
    )

    asyncio.run(select_game(update, context))

    assert service.selected_args == ("ev1", start_iso)
    assert context.bot.messages[0].startswith("Drafts for Wed 04.03 18:00 Ref 2RLU16W")
    assert context.bot.messages[1:] == ["ref draft", "parents draft", "players draft"]
