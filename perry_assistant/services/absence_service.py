from __future__ import annotations

import datetime as dt
import re

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import AbsenceRecord
from perry_assistant.storage.json_store import read_json, write_json


MM_DD_RE = re.compile(r"^\d{2}-\d{2}$")


class AbsenceService:
    def __init__(self, config: AppConfig) -> None:
        self._absence_file = config.school_absence_file
        self._timetable_file = config.school_timetable_file

    def add_absence(self, date: str, subjects: list[str]) -> list[AbsenceRecord]:
        normalized_date = self._normalize_date(date)
        records = self._load_absences()
        existing_unexcused = {
            (item.date, item.subject.strip().lower())
            for item in records
            if not item.excused
        }
        added: list[AbsenceRecord] = []
        for subject in subjects:
            cleaned_subject = subject.strip()
            if not cleaned_subject:
                continue
            key = (normalized_date, cleaned_subject.lower())
            if key in existing_unexcused:
                continue
            record = AbsenceRecord(date=normalized_date, subject=cleaned_subject, excused=False)
            records.append(record)
            added.append(record)
            existing_unexcused.add(key)
        self._save_absences(records)
        return added

    def get_unexcused_absences(self) -> list[AbsenceRecord]:
        return sorted(
            [item for item in self._load_absences() if not item.excused],
            key=lambda item: (item.date, item.subject.lower()),
        )

    def get_excused_absences(self) -> list[AbsenceRecord]:
        return sorted(
            [item for item in self._load_absences() if item.excused],
            key=lambda item: (item.date, item.subject.lower()),
        )

    def get_excusable_absences_today(self, now: dt.datetime | None = None) -> list[AbsenceRecord]:
        now = now or dt.datetime.now()
        weekday = now.weekday()
        timetable = self.get_school_timetable()
        today_subjects = {subject.strip().lower() for subject in timetable.get(weekday, [])}

        excusable: list[AbsenceRecord] = []
        for item in self.get_unexcused_absences():
            absence_weekday = self._weekday_for_year(item.date, now.year)
            subject_match = item.subject.strip().lower() in today_subjects
            if absence_weekday == weekday or subject_match:
                excusable.append(item)
        return excusable

    def mark_absence_excused(self, date: str, subject: str | None = None) -> bool:
        normalized_date = self._normalize_date(date)
        subjects = [subject] if subject else []
        changed = self.mark_absences_excused([(normalized_date, subjects)])
        return changed > 0

    def mark_absences_excused(self, groups: list[tuple[str, list[str]]]) -> int:
        records = self._load_absences()
        total_changed = 0

        normalized_groups: list[tuple[str, set[str]]] = []
        for date, subjects in groups:
            normalized_date = self._normalize_date(date)
            normalized_subjects = {subject.strip().lower() for subject in subjects if subject.strip()}
            normalized_groups.append((normalized_date, normalized_subjects))

        for date, subjects in normalized_groups:
            for item in records:
                if item.date != date or item.excused:
                    continue
                if subjects and item.subject.strip().lower() not in subjects:
                    continue
                item.excused = True
                total_changed += 1

        self._save_absences(records)
        return total_changed

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
            try:
                normalized_date = self._normalize_date(str(item["date"]))
            except ValueError:
                continue
            output.append(
                AbsenceRecord(
                    date=normalized_date,
                    subject=str(item["subject"]),
                    excused=bool(item.get("excused", False)),
                )
            )
        return output

    def _save_absences(self, records: list[AbsenceRecord]) -> None:
        payload = [{"date": item.date, "subject": item.subject, "excused": item.excused} for item in records]
        write_json(self._absence_file, payload)

    @staticmethod
    def _normalize_date(date: str) -> str:
        value = date.strip()

        if MM_DD_RE.fullmatch(value):
            dt.datetime.strptime(f"2000-{value}", "%Y-%m-%d")
            return value

        try:
            parsed = dt.datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Date must be MM-DD.") from exc
        return parsed.strftime("%m-%d")

    @staticmethod
    def _weekday_for_year(date_mmdd: str, year: int) -> int | None:
        try:
            parsed = dt.datetime.strptime(f"{year}-{date_mmdd}", "%Y-%m-%d")
        except ValueError:
            return None
        return parsed.weekday()
