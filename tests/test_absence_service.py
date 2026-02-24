from __future__ import annotations

import datetime as dt

from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.storage.bootstrap import bootstrap_data
from perry_assistant.storage.json_store import read_json, write_json


def test_add_list_and_excuse_absence_mmdd(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    created = service.add_absence("02-19", ["M", "E"])
    assert len(created) == 2

    unexcused = service.get_unexcused_absences()
    assert len(unexcused) == 2

    assert service.mark_absence_excused("02-19", "M") is True
    remaining = service.get_unexcused_absences()
    assert len(remaining) == 1
    assert remaining[0].subject == "E"


def test_legacy_yyyy_mm_dd_is_normalized_to_mm_dd(app_config):
    bootstrap_data(app_config)
    write_json(
        app_config.school_absence_file,
        [{"date": "2026-02-19", "subject": "M", "excused": False}],
    )

    service = AbsenceService(app_config)
    data = service.get_unexcused_absences()
    assert data[0].date == "02-19"

    service.add_absence("02-20", ["E"])
    persisted = read_json(app_config.school_absence_file, [])
    assert persisted[0]["date"] == "02-19"
    assert persisted[1]["date"] == "02-20"


def test_excusable_absences_today_or_logic(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    monday = dt.datetime(2026, 2, 16, 10, 0)  # Monday
    service.add_absence("02-09", ["SW"])  # same weekday, not in Monday timetable
    service.add_absence("02-10", ["M"])  # different weekday, but subject in Monday timetable
    service.add_absence("02-10", ["PH"])  # different weekday and subject not in Monday timetable

    write_json(app_config.school_timetable_file, {"0": ["M"], "1": ["PH"]})

    excusable = service.get_excusable_absences_today(now=monday)
    subjects = sorted(item.subject for item in excusable)
    assert subjects == ["M", "SW"]


def test_mark_absences_excused_multiple_groups(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    service.add_absence("02-24", ["M", "PH", "CH"])
    service.add_absence("02-25", ["M", "PH", "R"])

    changed = service.mark_absences_excused([("02-24", ["M", "PH", "CH"]), ("02-25", ["M", "R"])])
    assert changed == 5

    excused = service.get_excused_absences()
    assert len(excused) == 5
    unexcused = service.get_unexcused_absences()
    assert len(unexcused) == 1
    assert unexcused[0].date == "02-25"
    assert unexcused[0].subject == "PH"
