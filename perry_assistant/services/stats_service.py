from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.storage.json_store import read_json


class StatsService:
    def __init__(self, config: AppConfig) -> None:
        self._logs_dir = config.logs_dir
        self._parents_file = config.parents_file
        self._untis_users_file = config.untis_users_file
        self._untis_changes_file = config.untis_changes_file

    def yesterday_usage_counts(self) -> tuple[int, int, int]:
        """Return (total_incoming, parent_total, untis_total) for yesterday."""
        target_day = (dt.datetime.now(BERLIN_TZ) - dt.timedelta(days=1)).date()
        target_prefix = target_day.isoformat()
        parent_ids = self._parent_ids()
        untis_ids = self._untis_user_ids()
        total = 0
        parent_total = 0
        untis_total = 0
        seen_lines: set[str] = set()

        for path in self._log_candidates():
            for line in self._read_lines(path):
                if not line.startswith(target_prefix):
                    continue
                if " STATS " not in line or " incoming=" not in line:
                    continue
                signature = f"{path.name}:{line}"
                if signature in seen_lines:
                    continue
                seen_lines.add(signature)
                total += 1
                user_id = self._extract_json_field(line, "incoming=", "user_id")
                if user_id is not None and user_id in parent_ids:
                    parent_total += 1
                if user_id is not None and user_id in untis_ids:
                    untis_total += 1
        return total, parent_total, untis_total

    def yesterday_outgoing_counts(self) -> dict[str, int]:
        """Return a dict of {endpoint: count} for outgoing messages sent yesterday."""
        target_day = (dt.datetime.now(BERLIN_TZ) - dt.timedelta(days=1)).date()
        target_prefix = target_day.isoformat()
        counts: dict[str, int] = {}
        seen_lines: set[str] = set()

        for path in self._log_candidates():
            for line in self._read_lines(path):
                if not line.startswith(target_prefix):
                    continue
                if " STATS " not in line or " outgoing=" not in line:
                    continue
                signature = f"{path.name}:{line}"
                if signature in seen_lines:
                    continue
                seen_lines.add(signature)
                endpoint = self._extract_json_field(line, "outgoing=", "endpoint")
                if isinstance(endpoint, str):
                    counts[endpoint] = counts.get(endpoint, 0) + 1
        return counts

    def timetable_edits_count(self) -> int:
        """Return the total number of timetable changes currently tracked."""
        raw = read_json(self._untis_changes_file, {})
        if not isinstance(raw, dict):
            return 0
        total = 0
        for user_changes in raw.values():
            if isinstance(user_changes, list):
                total += len(user_changes)
        return total

    def yesterday_usage_line(self) -> str:
        total, parent_total, untis_total = self.yesterday_usage_counts()
        edits = self.timetable_edits_count()
        outgoing = self.yesterday_outgoing_counts()
        total_outgoing = sum(outgoing.values())
        return (
            f"📊 Yesterday Perry was used {total} times, "
            f"{parent_total} by parents and {untis_total} for untis. "
            f"It managed to inform about {edits} school timetable edits. "
            f"Perry sent {total_outgoing} message(s) in total."
        )

    def _parent_ids(self) -> set[int]:
        raw = read_json(self._parents_file, [])
        if not isinstance(raw, list):
            return set()
        output: set[int] = set()
        for item in raw:
            if isinstance(item, int):
                output.add(item)
        return output

    def _untis_user_ids(self) -> set[int]:
        raw = read_json(self._untis_users_file, {})
        if not isinstance(raw, dict):
            return set()
        output: set[int] = set()
        for key in raw:
            try:
                output.add(int(key))
            except (ValueError, TypeError):
                pass
        return output

    def _log_candidates(self) -> list[Path]:
        if not self._logs_dir.exists():
            return []
        return sorted(path for path in self._logs_dir.glob("perry.log*") if path.is_file())

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return []

    @staticmethod
    def _extract_json_field(line: str, marker: str, field: str):
        """Extract a single JSON field value from a log line.

        Splits on *marker* (e.g. ``"incoming="``), parses the remainder as
        JSON, and returns ``parsed[field]``.  Returns ``None`` on any error.
        """
        try:
            payload = line.split(marker, 1)[1]
        except IndexError:
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed.get(field)

    # Keep a backward-compatible alias used by the stats line builder
    @staticmethod
    def _extract_user_id(line: str) -> int | None:
        try:
            payload = line.split("incoming=", 1)[1]
        except IndexError:
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        user_id = parsed.get("user_id") if isinstance(parsed, dict) else None
        if isinstance(user_id, int):
            return user_id
        return None

