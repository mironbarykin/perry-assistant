import datetime as dt

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.domain.models import EventView, RefereeAssignment
from perry_assistant.services.referee_service import ICON_BUSY, ICON_CLOSE, ICON_FREE, RefereeService


class _FakeGmailClient:
    pass


class _FakeGymClient:
    def get_gym_address(self, hall_code: str) -> str | None:
        return None


class _FakeCalendarClient:
    def __init__(self, referee_events: list[dict] | None = None, day_events: list[EventView] | None = None) -> None:
        self._referee_events = referee_events or []
        self._day_events = day_events or []

    def get_future_referee_game_events(self, start_time=None) -> list[dict]:
        return self._referee_events

    def get_referee_events_for_day(self, target_date) -> list[dict]:
        return []

    def get_events_for_date(self, target_date):
        return self._day_events


def _referee_event(start: dt.datetime, end: dt.datetime) -> dict:
    return {
        "id": "event-id",
        "summary": "BEL12H Referee Game",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }


def _timed_event(start: dt.datetime, end: dt.datetime, title: str) -> EventView:
    return EventView(start=start, end=end, line=title, is_basketball=False, is_all_day=False)


def test_umbesetzung_availability_busy_under_one_hour(app_config):
    assignment = RefereeAssignment(type="UMBESETZUNG", date="28.02.2026", time="16:00")
    candidate_start = dt.datetime(2026, 2, 28, 16, 0, tzinfo=BERLIN_TZ)
    existing = _referee_event(candidate_start - dt.timedelta(hours=2), candidate_start - dt.timedelta(minutes=30))
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient([existing]), _FakeGymClient())
    icon, _, available = service._umbesetzung_availability(assignment)  # noqa: SLF001
    assert icon == ICON_BUSY
    assert available is False


def test_umbesetzung_availability_close_between_one_and_two_hours(app_config):
    assignment = RefereeAssignment(type="UMBESETZUNG", date="28.02.2026", time="16:00")
    candidate_start = dt.datetime(2026, 2, 28, 16, 0, tzinfo=BERLIN_TZ)
    existing = _referee_event(candidate_start - dt.timedelta(hours=3), candidate_start - dt.timedelta(hours=1, minutes=30))
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient([existing]), _FakeGymClient())
    icon, _, available = service._umbesetzung_availability(assignment)  # noqa: SLF001
    assert icon == ICON_CLOSE
    assert available is True


def test_umbesetzung_availability_free_two_hours_or_more(app_config):
    assignment = RefereeAssignment(type="UMBESETZUNG", date="28.02.2026", time="16:00")
    candidate_start = dt.datetime(2026, 2, 28, 16, 0, tzinfo=BERLIN_TZ)
    existing = _referee_event(candidate_start - dt.timedelta(hours=4), candidate_start - dt.timedelta(hours=2))
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient([existing]), _FakeGymClient())
    icon, _, available = service._umbesetzung_availability(assignment)  # noqa: SLF001
    assert icon == ICON_FREE
    assert available is True


def test_umbesetzung_availability_busy_with_parallel_non_referee_event(app_config):
    assignment = RefereeAssignment(type="UMBESETZUNG", date="22.02.2026", time="14:00")
    start = dt.datetime(2026, 2, 22, 14, 0, tzinfo=BERLIN_TZ)
    end = dt.datetime(2026, 2, 22, 16, 0, tzinfo=BERLIN_TZ)
    day_event = _timed_event(start, end, "Coach Game HOME (U12-2)")
    calendar = _FakeCalendarClient(referee_events=[], day_events=[day_event])
    service = RefereeService(app_config, _FakeGmailClient(), calendar, _FakeGymClient())

    icon, _, available = service._umbesetzung_availability(assignment)  # noqa: SLF001
    assert icon == ICON_BUSY
    assert available is False
