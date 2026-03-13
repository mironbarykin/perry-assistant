import asyncio
from types import SimpleNamespace
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


class _FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


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



def test_referee_notification_anderweitig_vergeben_is_quiet(app_config):
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient(), _FakeGymClient())
    assignment = RefereeAssignment(
        type="UMBESETZUNG_VERGEBEN",
        date="21.03.2026",
        time="10:00",
        liga="JOL1U10W",
        spielnummer="1051",
        teams="DJK TUSA 06 Düsseldorf - Citybasket Recklinghausen",
        hall_code="311C511",
    )

    bot = _FakeBot()
    context = SimpleNamespace(bot=bot)
    asyncio.run(service._handle_assignment(context, assignment, multiple=False))  # noqa: SLF001

    assert bot.messages
    payload = bot.messages[0]
    expected_url = f"https://maps.google.com/?q={quote_plus('Kopernikusstraße 20, 57413 Finnentrop')}"
    expected = (
        "\U0001F6AB UMBESETZUNG JOL1U10W #1051 wurde anderweitig vergeben\n"
        f'Saturday 21.03.2026 10:00 @ <a href="{expected_url}">Kopernikusstraße 20, 57413 Finnentrop (311C511)</a>\n'
        "DJK TUSA 06 Düsseldorf - Citybasket Recklinghausen"
    )
    assert payload["text"] == expected
    assert payload["kwargs"].get("disable_notification") is True
