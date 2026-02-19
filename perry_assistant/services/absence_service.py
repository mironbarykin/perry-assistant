from __future__ import annotations

import datetime as dt

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import AbsenceRecord
from perry_assistant.storage.json_store import read_json, write_json


class AbsenceService:
    def __init__(self, config: AppConfig) -> None:
        self._absence_file = config.school_absence_file
        self._timetable_file = config.school_timetable_file

    def add_absence(self, date: str, subjects: list[str]) -> list[AbsenceRecord]:
        self._validate_date(date)
        records = self._load_absences()
        added: list[AbsenceRecord] = []
        for subject in subjects:
            cleaned_subject = subject.strip()
            if not cleaned_subject:
                continue
            record = AbsenceRecord(date=date, subject=cleaned_subject, excused=False)
            records.append(record)
            added.append(record)
        self._save_absences(records)
        return added

    def get_unexcused_absences(self) -> list[AbsenceRecord]:
        return [item for item in self._load_absences() if not item.excused]

    def get_excusable_absences_today(self, now: dt.datetime | None = None) -> list[AbsenceRecord]:
        now = now or dt.datetime.now()
        weekday = now.weekday()
        timetable = self.get_school_timetable()
        today_subjects = set(timetable.get(weekday, []))

        excusable: list[AbsenceRecord] = []
        for item in self.get_unexcused_absences():
            absence_date = dt.datetime.strptime(item.date, "%Y-%m-%d")
            if absence_date.weekday() == weekday and item.subject in today_subjects:
                excusable.append(item)
        return excusable

    def mark_absence_excused(self, date: str, subject: str | None = None) -> bool:
        self._validate_date(date)
        records = self._load_absences()
        updated = False
        for item in records:
            if item.date != date or item.excused:
                continue
            if subject and item.subject != subject:
                continue
            item.excused = True
            updated = True
        self._save_absences(records)
        return updated

    def get_school_timetable(self) -> dict[int, list[str]]:
        raw = read_json(self._timetable_file, {})
        parsed: dict[int, list[str]] = {}
        for day, subjects in raw.items():
            try:
                parsed[int(day)] = [str(subject) for subject in subjects]
            except (ValueError, TypeError):
                continue
        return parsed

    def _load_absences(self) -> list[AbsenceRecord]:
        raw = read_json(self._absence_file, [])
        output: list[AbsenceRecord] = []
        for item in raw:
            if "date" not in item or "subject" not in item:
                continue
            output.append(
                AbsenceRecord(
                    date=str(item["date"]),
                    subject=str(item["subject"]),
                    excused=bool(item.get("excused", False)),
                )
            )
        return output

    def _save_absences(self, records: list[AbsenceRecord]) -> None:
        payload = [{"date": item.date, "subject": item.subject, "excused": item.excused} for item in records]
        write_json(self._absence_file, payload)

    @staticmethod
    def _validate_date(date: str) -> None:
        dt.datetime.strptime(date, "%Y-%m-%d")

