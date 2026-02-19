from __future__ import annotations

import datetime as dt

from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.storage.bootstrap import bootstrap_data
from perry_assistant.storage.json_store import write_json


def test_add_list_and_excuse_absence(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    created = service.add_absence("2026-02-19", ["M", "E"])
    assert len(created) == 2

    unexcused = service.get_unexcused_absences()
    assert len(unexcused) == 2

    assert service.mark_absence_excused("2026-02-19", "M") is True
    remaining = service.get_unexcused_absences()
    assert len(remaining) == 1
    assert remaining[0].subject == "E"


def test_excusable_absences_today(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    monday = dt.datetime(2026, 2, 16, 10, 0)  # Monday
    service.add_absence("2026-02-09", ["M"])  # also Monday
    service.add_absence("2026-02-10", ["PH"])  # Tuesday
    write_json(app_config.school_timetable_file, {"0": ["M"], "1": ["PH"]})

    excusable = service.get_excusable_absences_today(now=monday)
    assert len(excusable) == 1
    assert excusable[0].subject == "M"


def test_excusable_absences_today_or_logic(app_config):
    bootstrap_data(app_config)
    service = AbsenceService(app_config)

    monday = dt.datetime(2026, 2, 16, 10, 0)  # Monday
    service.add_absence("2026-02-09", ["SW"])  # same weekday, not in Monday timetable
    service.add_absence("2026-02-10", ["M"])  # different weekday, but subject in Monday timetable
    service.add_absence("2026-02-10", ["PH"])  # different weekday and subject not in Monday timetable

    write_json(app_config.school_timetable_file, {"0": ["M"], "1": ["PH"]})

    excusable = service.get_excusable_absences_today(now=monday)
    subjects = sorted(item.subject for item in excusable)
    assert subjects == ["SW", "M"]
