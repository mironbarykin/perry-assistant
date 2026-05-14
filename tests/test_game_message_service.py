from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.services.game_message_service import GameMessageService, ParsedGameEvent


class _FakeCalendarClient:
    def __init__(self, events: list[dict] | None = None) -> None:
        self._events = events or []

    def get_basketball_events_between(self, start_time: dt.datetime, end_time: dt.datetime) -> list[dict]:
        del start_time, end_time
        return list(self._events)


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        del chat_id, kwargs
        self.messages.append(text)


def _context(bot: _FakeBot):
    return SimpleNamespace(bot=bot)


def _next_weekday(base: dt.date, weekday: int) -> dt.date:
    delta = (weekday - base.weekday()) % 7
    if delta == 0:
        delta = 7
    return base + dt.timedelta(days=delta)


def _raw_event(
    *,
    event_id: str,
    summary: str,
    start: dt.datetime,
    end: dt.datetime,
    location: str,
    description: str = "",
) -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "location": location,
        "description": description,
    }


def test_referee_merge_same_gym_and_refs(app_config):
    service = GameMessageService(app_config, _FakeCalendarClient())
    day = dt.datetime(2026, 3, 7, 18, 0, tzinfo=BERLIN_TZ)
    refs = "Referees: Dorrani, Mehrdad, Barykin, Miron"
    events = [
        ParsedGameEvent(
            event_id="r1",
            summary="2JRLER16W Referee Game",
            description=refs,
            location="Gym A",
            start=day,
            end=day + dt.timedelta(hours=2),
            category="referee",
            league="2JRLER16W",
            team="",
            team_bucket="",
            home_or_guest="guest",
            referees=["Mehrdad", "Miron"],
        ),
        ParsedGameEvent(
            event_id="r2",
            summary="2RLU16W Referee Game",
            description=refs,
            location="Gym A",
            start=day.replace(hour=20),
            end=day.replace(hour=22),
            category="referee",
            league="2RLU16W",
            team="",
            team_bucket="",
            home_or_guest="guest",
            referees=["Mehrdad", "Miron"],
        ),
    ]
    rules = {"referee": {"arrival_minutes_by_league_regex": [{"pattern": ".*", "min": 30, "max": 40}]}}
    drafts = service._build_referee_drafts(events, rules)  # noqa: SLF001
    assert len(drafts) == 1
    assert "2JRLER16W" in drafts[0].text
    assert "2RLU16W" in drafts[0].text


def test_coach_team_rules_u12_parents_only_u16_parents_and_players(app_config):
    service = GameMessageService(app_config, _FakeCalendarClient())
    start = dt.datetime(2026, 3, 8, 10, 0, tzinfo=BERLIN_TZ)
    events = [
        ParsedGameEvent(
            event_id="c1",
            summary="Coach Game HOME (U12-2)",
            description="Osterather TV 2 - ART Giants Düsseldorf, 201B502",
            location="Görresstraße 6, 40670 Meerbusch",
            start=start,
            end=start + dt.timedelta(hours=2),
            category="coach",
            league="",
            team="U12-2",
            team_bucket="U12",
            home_or_guest="home",
            referees=[],
        ),
        ParsedGameEvent(
            event_id="c2",
            summary="Coach Game GUEST (U16-2)",
            description="Osterather TV 2 - ART Giants Düsseldorf, 201B502",
            location="Theodor-Litt-Straße 2, 40593 Düsseldorf",
            start=start.replace(hour=17, day=9),
            end=start.replace(hour=19, day=9),
            category="coach",
            league="",
            team="U16-2",
            team_bucket="U16",
            home_or_guest="guest",
            referees=[],
        ),
    ]
    rules = {
        "coach": {
            "team_rules": {
                "U16": {"meeting_minutes": 50, "send_parents": True, "send_players": True},
                "U12": {"meeting_minutes": 45, "send_parents": True, "send_players": False},
            },
            "home_10am_override_minutes": 60,
            "greetings_parents": ["Hallo zusammen!"],
            "greetings_players": ["Hi Jungs!"],
            "jersey_placeholders": {"U16": {"bring": "A", "wash": "B"}, "U12": {"bring": "C", "wash": "D"}},
        }
    }
    drafts = service._build_coach_drafts(events, rules)  # noqa: SLF001
    assert len(drafts) == 3
    u12_text = next(item.text for item in drafts if "c1" in item.key)
    assert "1 Stunde" in u12_text
    assert "Trikots bringt C" in u12_text
    u16_parent = next(item.text for item in drafts if item.key.startswith("coach:parents:c2"))
    assert "50 Minuten" in u16_parent
    u16_player = next(item.text for item in drafts if item.key.startswith("coach:players:c2"))
    assert "Hi Jungs!" in u16_player


def test_schedule_weekday_reminder_is_d_minus_3(app_config):
    service = GameMessageService(app_config, _FakeCalendarClient())
    today = dt.datetime.now(BERLIN_TZ).date()
    friday = _next_weekday(today, 4)
    if friday > (today - dt.timedelta(days=3)):
        friday += dt.timedelta(days=7)
    start = dt.datetime(friday.year, friday.month, friday.day, 18, 0, tzinfo=BERLIN_TZ)
    parsed = service._parse_events(  # noqa: SLF001
        [
            _raw_event(
                event_id="wk1",
                summary="Coach Game GUEST (U16-2)",
                start=start,
                end=start + dt.timedelta(hours=2),
                location="Gym B",
                description="Opponent Team, 201B502",
            )
        ]
    )
    state = {"scheduled_weekday": {}, "sent_keys": []}
    rules = {"coach": {"team_rules": {"U16": {"meeting_minutes": 50, "send_parents": True, "send_players": True}}}}
    service._schedule_weekday_drafts(state, parsed, rules, today)  # noqa: SLF001

    assert state["scheduled_weekday"]
    entry = next(iter(state["scheduled_weekday"].values()))
    assert entry["remind_on"] == (friday - dt.timedelta(days=3)).isoformat()


def test_daily_safety_sends_due_weekday_drafts_separately(app_config):
    service = GameMessageService(app_config, _FakeCalendarClient())
    today = dt.datetime.now(BERLIN_TZ).date().isoformat()
    state = {
        "scheduled_weekday": {
            "weekday:one": {"remind_on": today, "texts": ["A", "B"], "sent": False},
        },
        "sent_keys": [],
    }
    bot = _FakeBot()
    asyncio.run(service._send_due_weekday_drafts(_context(bot), state, dt.date.fromisoformat(today)))  # noqa: SLF001

    assert bot.messages == ["A", "B"]
    assert state["scheduled_weekday"]["weekday:one"]["sent"] is True


def test_wednesday_scan_sends_weekend_drafts(app_config, monkeypatch):
    today = dt.datetime.now(BERLIN_TZ).date()
    saturday = today + dt.timedelta((5 - today.weekday()) % 7)
    start = dt.datetime(saturday.year, saturday.month, saturday.day, 18, 0, tzinfo=BERLIN_TZ)
    event = _raw_event(
        event_id="wr1",
        summary="2JRLER16W Referee Game",
        start=start,
        end=start + dt.timedelta(hours=2),
        location="Gym Weekend",
        description="Referees: Dorrani, Sebastian, Barykin, Miron",
    )
    service = GameMessageService(app_config, _FakeCalendarClient([event]))
    monkeypatch.setattr("perry_assistant.services.game_message_service.WEDNESDAY_INDEX", today.weekday())

    bot = _FakeBot()
    asyncio.run(service.run_daily_scan(_context(bot)))

    assert any("Gym Weekend" in item for item in bot.messages)


def test_list_upcoming_games_filters_by_requested_range(app_config):
    now = dt.datetime(2026, 3, 3, 9, 0, tzinfo=BERLIN_TZ)
    within_start = now + dt.timedelta(days=2)
    outside_start = now + dt.timedelta(days=9)
    events = [
        _raw_event(
            event_id="in-range",
            summary="2JRLER16W Referee Game",
            start=within_start,
            end=within_start + dt.timedelta(hours=2),
            location="Gym A",
            description="Referees: Dorrani, Sebastian, Barykin, Miron",
        ),
        _raw_event(
            event_id="out-range",
            summary="Coach Game GUEST (U16-2)",
            start=outside_start,
            end=outside_start + dt.timedelta(hours=2),
            location="Gym B",
            description="TV - Gegner",
        ),
    ]
    service = GameMessageService(app_config, _FakeCalendarClient(events))

    upcoming = service.list_upcoming_games(days=7, now=now)

    assert [item.event_id for item in upcoming] == ["in-range"]


def test_build_drafts_for_selected_game_uses_event_id_and_start(app_config):
    now = dt.datetime(2026, 3, 3, 9, 0, tzinfo=BERLIN_TZ)
    start = now + dt.timedelta(days=1)
    events = [
        _raw_event(
            event_id="selected",
            summary="2JRLER16W Referee Game",
            start=start,
            end=start + dt.timedelta(hours=2),
            location="Gym C",
            description="Referees: Dorrani, Sebastian, Barykin, Miron",
        )
    ]
    service = GameMessageService(app_config, _FakeCalendarClient(events))

    drafts = service.build_drafts_for_selected_game(
        event_id="selected",
        start_iso=start.isoformat(),
        now=now,
    )

    assert drafts
    assert any("Gym C" in item.text for item in drafts)


def test_referee_draft_shows_street_in_city_and_shirt_line(app_config):
    now = dt.datetime(2026, 3, 3, 9, 0, tzinfo=BERLIN_TZ)
    start = now + dt.timedelta(days=1)
    events = [
        _raw_event(
            event_id="city1",
            summary="2JRLER16W Referee Game",
            start=start,
            end=start + dt.timedelta(hours=2),
            location="Goerresstrasse 6, 40670 Meerbusch",
            description="Referees: Dorrani, Sebastian, Barykin, Miron",
        ),
        _raw_event(
            event_id="city2",
            summary="2RLU16W Referee Game",
            start=start + dt.timedelta(days=1),
            end=start + dt.timedelta(days=1, hours=2),
            location="",
            description="Referees: Dorrani, Sebastian, Barykin, Miron",
        ),
    ]
    service = GameMessageService(app_config, _FakeCalendarClient(events))

    drafts_with_city = service.build_drafts_for_selected_game(
        event_id="city1",
        start_iso=start.isoformat(),
        now=now,
    )
    drafts_with_placeholder = service.build_drafts_for_selected_game(
        event_id="city2",
        start_iso=(start + dt.timedelta(days=1)).isoformat(),
        now=now,
    )

    assert drafts_with_city
    # Address is now formatted as "Street in City" (no postal code)
    assert "Goerresstrasse 6 in Meerbusch" in drafts_with_city[0].text
    assert "Habe neues Silber und Schwarz und altes Silber dabei!" in drafts_with_city[0].text
    assert drafts_with_placeholder
    assert " CITY " in f" {drafts_with_placeholder[0].text} "
    assert "Habe neues Silber und Schwarz und altes Silber dabei!" in drafts_with_placeholder[0].text


def test_referee_street_city_label_various_formats(app_config):
    svc = GameMessageService(app_config, _FakeCalendarClient())
    # Standard German address: "Street Number, Postal City"
    assert svc._referee_street_city_label("Bergheimer Straße 223, 41464 Neuss") == "Bergheimer Straße 223 in Neuss"  # noqa: SLF001
    # Address with trailing sub-city
    assert svc._referee_street_city_label("Goerresstrasse 6, 40670 Meerbusch") == "Goerresstrasse 6 in Meerbusch"  # noqa: SLF001
    # Empty / missing
    assert svc._referee_street_city_label("") == "CITY"  # noqa: SLF001
    # Single-part address (no comma) — return raw
    assert svc._referee_street_city_label("Gymnasium") == "Gymnasium"  # noqa: SLF001
