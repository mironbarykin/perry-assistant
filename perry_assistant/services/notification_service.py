from __future__ import annotations

import datetime as dt
import re
from typing import Callable

from telegram.ext import Application

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import read_json, write_json


class NotificationService:
    def __init__(self, config: AppConfig) -> None:
        self._file = config.notification_file

    def load_notification_times(self) -> dict[str, str]:
        return read_json(self._file, {})

    def save_notification_times(self, values: dict[str, str]) -> None:
        write_json(self._file, values)

    def upsert_user_notification_time(self, user_id: int, time_text: str) -> str:
        normalized = normalize_time_text(time_text)
        data = self.load_notification_times()
        data[str(user_id)] = normalized
        self.save_notification_times(data)
        return normalized

    def schedule_user_notification(
        self,
        app: Application,
        user_id: int,
        time_text: str,
        callback: Callable,
    ) -> None:
        normalized = normalize_time_text(time_text)
        job_name = f"user_notification:{user_id}"
        for job in app.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()

        hour, minute = map(int, normalized.split(":"))
        target_time = dt.time(hour=hour, minute=minute, tzinfo=BERLIN_TZ)
        app.job_queue.run_daily(callback, time=target_time, chat_id=user_id, name=job_name)

    def schedule_all(
        self,
        app: Application,
        user_callback: Callable,
        morning_callback: Callable,
    ) -> None:
        for user_id, time_text in self.load_notification_times().items():
            self.schedule_user_notification(app, int(user_id), time_text, user_callback)

        for job in app.job_queue.get_jobs_by_name("morning_message"):
            job.schedule_removal()
        app.job_queue.run_daily(
            morning_callback,
            time=dt.time(hour=6, minute=0, tzinfo=BERLIN_TZ),
            name="morning_message",
        )


TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def normalize_time_text(time_text: str) -> str:
    match = TIME_RE.match(time_text.strip())
    if not match:
        raise ValueError("Invalid time format.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("Invalid time value.")
    return f"{hour:02d}:{minute:02d}"

