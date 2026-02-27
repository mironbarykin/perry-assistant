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

    def yesterday_usage_counts(self) -> tuple[int, int]:
        target_day = (dt.datetime.now(BERLIN_TZ) - dt.timedelta(days=1)).date()
        target_prefix = target_day.isoformat()
        parent_ids = self._parent_ids()
        total = 0
        parent_total = 0
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
                user_id = self._extract_user_id(line)
                if user_id is not None and user_id in parent_ids:
                    parent_total += 1
        return total, parent_total

    def yesterday_usage_line(self) -> str:
        total, parent_total = self.yesterday_usage_counts()
        return f"📊 Yesterday Perry was used {total} times, {parent_total} of those by parents!"

    def _parent_ids(self) -> set[int]:
        raw = read_json(self._parents_file, [])
        if not isinstance(raw, list):
            return set()
        output: set[int] = set()
        for item in raw:
            if isinstance(item, int):
                output.add(item)
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

