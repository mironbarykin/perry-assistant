from __future__ import annotations

import datetime as dt
import random
from dataclasses import asdict, replace
from pathlib import Path

from perry_assistant.domain.models import UportalGame
from perry_assistant.services.uportal_service import EvaluatedGame, UportalService
from perry_assistant.storage.json_store import read_json, write_json


class _FakeUportalClient:
    def __init__(self, rows: list[UportalGame] | None = None) -> None:
        self._rows = rows or []

    def fetch_open_games(self) -> list[UportalGame]:
        return self._rows


class _FakeCalendarClient:
    def get_future_referee_game_events(self, start_time=None) -> list[dict]:
        return []

    def get_events_for_date(self, target_date) -> list:
        return []


class _CountingCalendarClient(_FakeCalendarClient):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_events_for_date(self, target_date) -> list:
        self.calls.append(target_date.date().isoformat())
        return []


def _row(
    detail_id: str,
    number: str,
    date: str = "27.02.2026",
    time: str = "19:30",
    distance_km: float = 20.0,
) -> UportalGame:
    return UportalGame(
        detail_id=detail_id,
        liga="RE-KLH",
        number=number,
        home_team=f"Home-{number}",
        away_team=f"Away-{number}",
        date=date,
        time=time,
        hall="109N581",
        original_referee="N.B.(1)",
        ust="K02",
        distance_km=distance_km,
    )


def test_due_window_runs_once_inside_window_and_no_backfill(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    state = {
        "date": "2026-02-27",
        "targets": {"night": "00:03", "morning": "10:02", "evening": "20:04"},
        "executed": {"night": False, "morning": False, "evening": False},
    }

    now_due = dt.datetime(2026, 2, 27, 10, 5, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    assert service._due_window(state, now_due) == "morning"  # noqa: SLF001

    state["executed"]["morning"] = True
    assert service._due_window(state, now_due) is None  # noqa: SLF001

    state["executed"]["morning"] = False
    now_after_window = dt.datetime(2026, 2, 27, 10, 30, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    assert service._due_window(state, now_after_window) is None  # noqa: SLF001


def test_new_daily_window_state_has_three_random_targets(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(7))
    state = service._new_daily_window_state(dt.date(2026, 2, 27))  # noqa: SLF001

    assert state["date"] == "2026-02-27"
    assert set(state["targets"].keys()) == {"night", "morning", "evening"}
    assert state["executed"] == {"night": False, "morning": False, "evening": False}
    for key, expected_hour in (("night", "00"), ("morning", "10"), ("evening", "20")):
        hour, minute = state["targets"][key].split(":")
        assert hour == expected_hour
        assert 0 <= int(minute) <= 10


def test_evaluate_rows_includes_old_green_plus_new_and_updated(app_config, monkeypatch):
    row_green = _row("11", "11")
    row_red = _row("22", "22")
    row_updated = _row("33", "33")
    row_new = _row("44", "44")

    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    seen = {
        service._identity_key(row_green): {"fingerprint": service._fingerprint(row_green)},  # noqa: SLF001
        service._identity_key(row_red): {"fingerprint": service._fingerprint(row_red)},  # noqa: SLF001
        service._identity_key(row_updated): {"fingerprint": "old"},  # noqa: SLF001
    }
    write_json(app_config.uportal_seen_rows_file, seen)

    def fake_availability(game: UportalGame) -> tuple[str, str]:
        if game.detail_id == "11":
            return "green", "G"
        if game.detail_id == "22":
            return "red", "R"
        if game.detail_id == "33":
            return "orange", "O"
        return "green", "G"

    monkeypatch.setattr(service, "_availability", fake_availability)
    evaluated, counts = service._evaluate_rows([row_green, row_red, row_updated, row_new])  # noqa: SLF001

    by_id = {item.game.detail_id: item.kind for item in evaluated}
    assert by_id["11"] == "old_green"
    assert by_id["33"] == "updated"
    assert by_id["44"] == "new"
    assert "22" not in by_id
    assert counts["fetched"] == 4
    assert counts["new"] == 1
    assert counts["updated"] == 1
    assert counts["old_green"] == 1
    assert counts["hidden"] == 1

    stored = read_json(app_config.uportal_seen_rows_file, {})
    assert service._identity_key(row_new) in stored  # noqa: SLF001
    assert stored[service._identity_key(row_updated)]["fingerprint"] == service._fingerprint(row_updated)  # noqa: SLF001


def test_render_chunks_group_by_date_and_sort_by_time_then_distance(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    service._hall_address_cache["109N581"] = "Main Hall, 12345 City"  # noqa: SLF001
    items = [
        EvaluatedGame(game=_row("1", "1", date="28.02.2026", time="11:00", distance_km=20.0), status="green", icon="G", kind="new"),
        EvaluatedGame(game=_row("2", "2", date="27.02.2026", time="09:00", distance_km=12.0), status="green", icon="G", kind="new"),
        EvaluatedGame(game=_row("3", "3", date="27.02.2026", time="09:00", distance_km=9.0), status="green", icon="G", kind="new"),
    ]

    chunks = service._render_chunks(items, reason="manual")  # noqa: SLF001
    assert len(chunks) == 2
    text_day1 = chunks[0].text
    first_27 = text_day1.index("27.02.2026")
    first_id3 = text_day1.index("Home-3")
    first_id2 = text_day1.index("Home-2")

    assert "28.02.2026" in chunks[1].text
    assert first_id3 < first_id2
    assert chunks[0].buttons[0][0] == "👎 Ignore all"


def test_evaluate_rows_fetches_calendar_events_once_per_game_day(app_config):
    calendar = _CountingCalendarClient()
    rows = [
        _row("11", "11", date="27.02.2026", time="09:00"),
        _row("12", "12", date="27.02.2026", time="11:00"),
        _row("13", "13", date="28.02.2026", time="10:00"),
    ]
    service = UportalService(app_config, _FakeUportalClient([]), calendar, rng=random.Random(0))

    service._evaluate_rows(rows)  # noqa: SLF001

    assert sorted(calendar.calls) == ["2026-02-26", "2026-02-27", "2026-02-28", "2026-03-01"]


def test_dump_raw_rows_debug_writes_all_scraped_rows(app_config):
    debug_config = replace(app_config, debug_mode=True)
    service = UportalService(debug_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    rows = [
        _row("11", "11", date="27.02.2026", time="09:00", distance_km=12.5),
        _row("12", "12", date="28.02.2026", time="11:00", distance_km=30.0),
    ]

    path = service._dump_raw_rows_debug(rows, reason="manual")  # noqa: SLF001
    payload = read_json(Path(path), {})

    assert payload["reason"] == "manual"
    assert payload["total_rows"] == 2
    assert len(payload["rows"]) == 2
    assert payload["rows"][0]["detail_id"] == "11"
    assert payload["rows"][0]["date"] == "27.02.2026"
    assert payload["rows"][0]["time"] == "09:00"
    assert payload["rows"][0]["distance_km"] == 12.5


def test_dump_raw_rows_debug_disabled_when_not_in_debug_mode(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    rows = [_row("11", "11", date="27.02.2026", time="09:00", distance_km=12.5)]

    path = service._dump_raw_rows_debug(rows, reason="manual")  # noqa: SLF001

    assert path == ""


def test_row_line_uses_compact_format_and_kind_badge(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    service._hall_address_cache["109N581"] = "Main Hall, 12345 City"  # noqa: SLF001
    item = EvaluatedGame(
        game=_row("99", "93", date="01.03.2026", time="20:00", distance_km=75.0),
        status="green",
        icon="🟢",
        kind="new",
    )

    line = service._row_line(item)  # noqa: SLF001
    assert "🟢🆕 @ 20:00" in line
    assert "RE-KLH #93" in line
    assert "Home-93 - Away-93" in line
    assert "👎" not in line
    assert "maps.google.com" in line


def test_row_line_includes_clickable_link_when_detail_url_present(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    service._hall_address_cache["109N581"] = "Main Hall, 12345 City"  # noqa: SLF001
    game = _row("101", "101", date="01.03.2026", time="18:00", distance_km=10.0)
    game.detail_url = "https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&sm=offene_umbesetzungen&id=101"
    item = EvaluatedGame(game=game, status="green", icon="🟢", kind="new")

    line = service._row_line(item)  # noqa: SLF001
    assert '<a href="https://www.uportal-wbv.de/index.php?o=meine_ansetzungen&amp;sm=offene_umbesetzungen&amp;id=101">RE-KLH #101</a>' in line


def test_row_line_marks_umb_offen_with_salute(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    service._hall_address_cache["109N581"] = "Main Hall, 12345 City"  # noqa: SLF001
    game = _row("777", "777", date="01.03.2026", time="16:00", distance_km=12.0)
    game.is_umb_offen = True
    item = EvaluatedGame(game=game, status="green", icon="🟢", kind="new")

    line = service._row_line(item)  # noqa: SLF001
    assert "🫡" in line


def test_ignore_game_by_id_hides_row_from_report(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    game = _row("301", "301", date="01.03.2026", time="12:00", distance_km=22.0)
    ignore_id = service._ignore_id(game)  # noqa: SLF001

    write_json(app_config.uportal_game_catalog_file, {ignore_id: asdict(game)})
    ok, _ = service.ignore_game_by_id(ignore_id)
    assert ok is True

    evaluated, counts = service._evaluate_rows([game])  # noqa: SLF001
    assert evaluated == []
    assert counts["ignored"] == 1


def test_ignore_all_in_group_hides_only_group_games(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    row1 = _row("401", "401", date="01.03.2026", time="12:00")
    row2 = _row("402", "402", date="01.03.2026", time="14:00")
    row3 = _row("403", "403", date="02.03.2026", time="10:00")
    id1 = service._ignore_id(row1)  # noqa: SLF001
    id2 = service._ignore_id(row2)  # noqa: SLF001
    id3 = service._ignore_id(row3)  # noqa: SLF001

    write_json(
        app_config.uportal_game_catalog_file,
        {
            id1: asdict(row1),
            id2: asdict(row2),
            id3: asdict(row3),
        },
    )
    service._ignore_groups["grp1"] = [id1, id2]  # noqa: SLF001
    ok, _ = service.ignore_all_in_group("grp1")
    assert ok is True

    evaluated, counts = service._evaluate_rows([row1, row2, row3])  # noqa: SLF001
    assert len(evaluated) == 1
    assert evaluated[0].game.detail_id == "403"
    assert counts["ignored"] == 2


def test_dedupe_rows_merges_same_date_hall_number(app_config):
    service = UportalService(app_config, _FakeUportalClient([]), _FakeCalendarClient(), rng=random.Random(0))
    a = _row("a", "93", date="01.03.2026", time="12:00")
    b = _row("b", "93", date="01.03.2026", time="12:00")
    b.detail_url = "https://example.test/detail"
    b.is_umb_offen = True

    deduped = service._dedupe_rows([a, b])  # noqa: SLF001
    assert len(deduped) == 1
    assert deduped[0].detail_url == "https://example.test/detail"
    assert deduped[0].is_umb_offen is True

