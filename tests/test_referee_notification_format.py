from urllib.parse import quote_plus

from perry_assistant.domain.models import RefereeAssignment
from perry_assistant.services.referee_service import ICON_BUSY, RefereeService


class _FakeGmailClient:
    pass


class _FakeCalendarClient:
    def get_future_referee_game_events(self, start_time=None):
        return []

    def get_referee_events_for_day(self, target_date):
        return []

    def get_events_for_date(self, target_date):
        return []


class _FakeGymClient:
    def get_gym_address(self, hall_code: str):
        if hall_code == "311C511":
            return "Kopernikusstraße 20, 57413 Finnentrop"
        return None


def test_referee_notification_format_with_clickable_maps_link(app_config):
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient(), _FakeGymClient())
    assignment = RefereeAssignment(
        type="ANSETZUNG",
        date="28.02.2026",
        time="16:00",
        liga="BeL12H",
        spielnummer="61",
        teams="FC Finnentrop - TuS Fellinghausen 2",
        hall_code="311C511",
    )

    when_where = service._when_where_line(assignment)  # noqa: SLF001
    text = service._notification_text(  # noqa: SLF001
        icon=ICON_BUSY,
        assignment=assignment,
        assignment_type="ANSETZUNG",
        when_where_line=when_where,
    )

    expected_url = f"https://maps.google.com/?q={quote_plus('Kopernikusstraße 20, 57413 Finnentrop')}"
    expected = (
        "🙅‍♂️ ANSETZUNG @ BeL12H #61\n"
        f'Saturday 28.02.2026 16:00 @ <a href="{expected_url}">Kopernikusstraße 20, 57413 Finnentrop (311C511)</a>\n'
        "FC Finnentrop - TuS Fellinghausen 2"
    )
    assert text == expected
