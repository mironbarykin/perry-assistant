import asyncio
from types import SimpleNamespace
from urllib.parse import quote_plus

from perry_assistant.domain.models import RefereeAssignment
from perry_assistant.constants import ICON_GREEN, ICON_ORANGE, ICON_RED
from perry_assistant.services.referee_service import ICON_BUSY, ICON_CLOSE, RefereeService


class _FakeGmailClient:
    pass


class _FakeCalendarClient:
    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.updated: list[tuple] = []

    def get_future_referee_game_events(self, start_time=None):
        return []

    def get_referee_events_for_day(self, target_date):
        return []

    def get_events_for_date(self, target_date):
        return []

    def create_referee_event(self, assignment, location):
        self.created.append((assignment, location))
        return "new-event-id"

    def update_referee_event(self, event_id, assignment, location):
        self.updated.append((event_id, assignment, location))
        return event_id


class _FakeCalendarClientWithExistingEvent(_FakeCalendarClient):
    """Calendar client that pretends an event already exists."""

    def get_event(self, event_id: str) -> dict:
        return {"id": event_id}


class _FakeCalendarClientNoEvent(_FakeCalendarClient):
    """Calendar client where no existing event can be found."""


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
        f"{ICON_RED} ANSETZUNG @ BeL12H #61\n"
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


def test_aenderung_creates_event_when_not_found(app_config):
    """AENDERUNG with no existing event must create one, not just report 'event not found'."""
    calendar = _FakeCalendarClientNoEvent()
    service = RefereeService(app_config, _FakeGmailClient(), calendar, _FakeGymClient())
    assignment = RefereeAssignment(
        type="AENDERUNG",
        date="17.03.2026",
        time="20:30",
        liga="KLH 1",
        spielnummer="87",
        teams="SG ART Giants Düsseldorf 5 - NEW Elephants Grevenbroich 3",
        hall_code="201A712",
        referees=["Grütter, Alexander (53775)", "Barykin, Miron (60180)"],
    )

    bot = _FakeBot()
    context = SimpleNamespace(bot=bot)
    asyncio.run(service._handle_assignment(context, assignment, multiple=False))  # noqa: SLF001

    # The calendar must have been asked to create the event.
    assert len(calendar.created) == 1
    assert len(calendar.updated) == 0

    # Notification should use the ICON_CLOSE icon (👌) and say "(created)".
    assert bot.messages
    text = bot.messages[0]["text"]
    assert ICON_CLOSE in text
    assert "(created)" in text
    assert "event not found" not in text


def test_aenderung_updates_event_when_found(app_config):
    """AENDERUNG with an existing mapped event must update it without an availability check."""
    calendar = _FakeCalendarClientWithExistingEvent()
    service = RefereeService(app_config, _FakeGmailClient(), calendar, _FakeGymClient())

    # Pre-populate the event map so _find_existing_event returns the id immediately.
    assignment = RefereeAssignment(
        type="AENDERUNG",
        date="17.03.2026",
        time="20:30",
        liga="KLH 1",
        spielnummer="87",
        teams="SG ART Giants Düsseldorf 5 - NEW Elephants Grevenbroich 3",
        hall_code="201A712",
        referees=["Grütter, Alexander (53775)", "Barykin, Miron (60180)"],
    )
    service._update_event_map(None, assignment, "existing-event-id")  # noqa: SLF001

    bot = _FakeBot()
    context = SimpleNamespace(bot=bot)
    asyncio.run(service._handle_assignment(context, assignment, multiple=False))  # noqa: SLF001

    # The existing event must have been updated (not re-created).
    assert len(calendar.updated) == 1
    assert calendar.updated[0][0] == "existing-event-id"
    assert len(calendar.created) == 0

    # Notification should use the ICON_CLOSE icon (👌) with no suffix.
    assert bot.messages
    text = bot.messages[0]["text"]
    assert ICON_CLOSE in text
    assert "event not found" not in text
    assert "(created)" not in text


def test_aenderung_ignores_conflict_no_availability_check(app_config):
    """AENDERUNG must not call _check_availability; conflicts on the same slot are ignored."""

    class _ConflictingCalendar(_FakeCalendarClientNoEvent):
        """Reports a referee event right at the same time (which would be a false conflict)."""

        def get_referee_events_for_day(self, target_date):
            return [
                {
                    "id": "other-event",
                    "summary": "KLH Referee Game",
                    "start": {"dateTime": "2026-03-17T20:30:00+01:00"},
                    "end": {"dateTime": "2026-03-17T22:30:00+01:00"},
                    "location": "201A712",
                }
            ]

    calendar = _ConflictingCalendar()
    service = RefereeService(app_config, _FakeGmailClient(), calendar, _FakeGymClient())
    assignment = RefereeAssignment(
        type="AENDERUNG",
        date="17.03.2026",
        time="20:30",
        liga="KLH 1",
        spielnummer="87",
        teams="SG ART Giants Düsseldorf 5 - NEW Elephants Grevenbroich 3",
        hall_code="201A712",
    )

    bot = _FakeBot()
    context = SimpleNamespace(bot=bot)
    asyncio.run(service._handle_assignment(context, assignment, multiple=False))  # noqa: SLF001

    # Even with a "conflicting" event, the calendar action must still happen.
    assert len(calendar.created) + len(calendar.updated) == 1

    # Notification must use ICON_CLOSE, not ICON_BUSY.
    assert bot.messages
    text = bot.messages[0]["text"]
    assert ICON_CLOSE in text
    assert ICON_BUSY not in text


def test_unified_icons_are_colored_circles():
    """ICON_FREE/CLOSE/BUSY aliases now map to the unified 🟢/🟠/🔴 icons."""
    from perry_assistant.services.referee_service import ICON_FREE
    assert ICON_FREE == ICON_GREEN
    assert ICON_CLOSE == ICON_ORANGE
    assert ICON_BUSY == ICON_RED


def test_double_umbesetzung_sends_single_combined_notification(app_config):
    """Two UMBESETZUNG in one email must produce exactly one combined message."""
    service = RefereeService(app_config, _FakeGmailClient(), _FakeCalendarClient(), _FakeGymClient())
    a1 = RefereeAssignment(
        type="UMBESETZUNG",
        date="21.03.2026",
        time="12:00",
        liga="JOL3U16M",
        spielnummer="111",
        teams="SV Haspe 70 - TuS Iserlohn Kangaroos",
        hall_code="311C511",
    )
    a2 = RefereeAssignment(
        type="UMBESETZUNG",
        date="21.03.2026",
        time="14:00",
        liga="JOL2U14O",
        spielnummer="222",
        teams="SV Haspe 70 - Witten Baskets",
        hall_code="311C511",
    )

    bot = _FakeBot()
    context = SimpleNamespace(bot=bot)
    import asyncio
    asyncio.run(service._handle_double_umbesetzung(context, [a1, a2]))  # noqa: SLF001

    assert len(bot.messages) == 1
    text = bot.messages[0]["text"]
    assert "2x UMBESETZUNG" in text
    assert "12:00" in text
    assert "14:00" in text
    assert "JOL3U16M" in text
    assert "JOL2U14O" in text
    assert "SV Haspe 70 - TuS Iserlohn Kangaroos" in text
    assert "SV Haspe 70 - Witten Baskets" in text
