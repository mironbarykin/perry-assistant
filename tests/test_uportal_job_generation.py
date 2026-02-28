from __future__ import annotations

import datetime as dt
import random

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.services.uportal_service import (
    GENERATED_JOB_EVENING,
    GENERATED_JOB_MIDNIGHT,
    GENERATED_JOB_MORNING,
    UportalService,
)


class _FakeUportalClient:
    def fetch_open_games(self):
        return []


class _FakeCalendarClient:
    def get_future_referee_game_events(self, start_time=None):
        return []

    def get_events_for_date(self, target_date):
        return []


class _FakeJob:
    def __init__(self, queue, name: str) -> None:
        self._queue = queue
        self.name = name

    def schedule_removal(self) -> None:
        self._queue.jobs[self.name] = []


class _FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, list[_FakeJob]] = {}
        self.run_once_calls: list[dict] = []

    def get_jobs_by_name(self, name: str):
        return list(self.jobs.get(name, []))

    def run_once(self, callback, when, name: str, data=None):  # noqa: ANN001
        del callback
        job = _FakeJob(self, name)
        self.jobs.setdefault(name, []).append(job)
        self.run_once_calls.append({"name": name, "when": when, "data": data})
        return job


class _FakeApp:
    def __init__(self) -> None:
        self.job_queue = _FakeJobQueue()


def test_generate_daily_scan_jobs_creates_three_one_off_jobs(app_config):
    service = UportalService(
        app_config,
        _FakeUportalClient(),
        _FakeCalendarClient(),
        rng=random.Random(7),
    )
    app = _FakeApp()

    targets = service.generate_daily_scan_jobs(app, callback=lambda ctx: ctx)

    names = [item["name"] for item in app.job_queue.run_once_calls]
    assert names == [GENERATED_JOB_MORNING, GENERATED_JOB_EVENING, GENERATED_JOB_MIDNIGHT]
    assert set(targets.keys()) == {"morning", "evening", "midnight"}

    morning = dt.datetime.fromisoformat(targets["morning"]).astimezone(BERLIN_TZ)
    evening = dt.datetime.fromisoformat(targets["evening"]).astimezone(BERLIN_TZ)
    midnight = dt.datetime.fromisoformat(targets["midnight"]).astimezone(BERLIN_TZ)
    assert morning.hour == 10
    assert evening.hour == 20
    assert midnight.hour == 0
    assert midnight.date() >= (dt.datetime.now(BERLIN_TZ).date() + dt.timedelta(days=1))

