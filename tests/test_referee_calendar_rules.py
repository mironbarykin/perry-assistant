from perry_assistant.domain.models import RefereeAssignment
from perry_assistant.integrations.calendar_client import (
    league_short_name,
    referee_game_summary,
    sanitize_event_location,
    select_calendar_id,
)


def test_referee_game_summary_uses_liga_short_name_from_parentheses():
    assignment = RefereeAssignment(type="ANSETZUNG", liga="Bezirksliga 02 Damen - Aufstiegsrunde (BeL02D-AR)")
    assert league_short_name(assignment) == "BeL02D-AR"
    assert referee_game_summary(assignment) == "BeL02D-AR Referee Game"


def test_referee_game_summary_falls_back_to_spielnummer():
    assignment = RefereeAssignment(type="ANSETZUNG", liga=None, spielnummer="61")
    assert referee_game_summary(assignment) == "61 Referee Game"


def test_sanitize_event_location_removes_hall_code_suffix():
    value = "Mönkesweg 58, 40670 Meerbusch (202B551)"
    assert sanitize_event_location(value) == "Mönkesweg 58, 40670 Meerbusch"


def test_select_calendar_prefers_non_primary_basketball_match():
    calendars = [
        {"id": "primary-id", "summary": "My Calendar", "primary": True},
        {"id": "basketball-id", "summary": "🏀 Basketball"},
    ]
    selected = select_calendar_id(calendars, "Basketball")
    assert selected == "basketball-id"
