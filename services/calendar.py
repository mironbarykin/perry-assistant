import datetime
import pickle
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from consts import TOKEN_PICKLE, REFEREE_EVENTS_FILE
from helpers import load_json, save_json, clean_text
from gyms import get_gym_address
from events import format_event

BERLIN_TZ = ZoneInfo("Europe/Berlin")
DEFAULT_DURATION_HOURS = 2
REFEREE_CALENDAR_NAME = "Basketball"
CANCEL_COLOR_ID = "11"


def get_calendar_service():
    """Getting Google Calendar API service."""
    creds = None
    if TOKEN_PICKLE and TOKEN_PICKLE:
        try:
            with open(TOKEN_PICKLE, "rb") as token:
                creds = pickle.load(token)
        except Exception:
            creds = None
    return build("calendar", "v3", credentials=creds)


def get_all_calendars(service):
    """Get all calendars from the Google Calendar API."""
    return service.calendarList().list().execute().get("items", [])


def get_calendar_id_by_name(service, name: str = REFEREE_CALENDAR_NAME) -> str:
    calendars = get_all_calendars(service)
    for cal in calendars:
        if cal.get("summary", "").lower() == name.lower():
            return cal["id"]
    for cal in calendars:
        if cal.get("primary"):
            return cal["id"]
    return "primary"


def get_events_for_date(target_date: datetime.datetime):
    """Get all events for a specific date across all calendars."""
    service = get_calendar_service()
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.UTC).isoformat()
    end = target_date.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=datetime.UTC).isoformat()

    events_all = []
    for cal in get_all_calendars(service):
        cal_symbol = cal.get("summary", "?")[0]
        is_basketball = "basketball" in cal.get("summary", "").lower()

        events = service.events().list(
            calendarId=cal["id"], timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute().get("items", [])

        for e in events:
            event_tuple = format_event(e, cal_symbol, is_basketball)
            if event_tuple[3]:
                if event_tuple[0] and event_tuple[0].date() == target_date.date():
                    events_all.append(event_tuple)
            else:
                events_all.append(event_tuple)

    return sorted(events_all, key=lambda x: (not x[3], x[0] is None, x[0]))


def _build_event_key(date: Optional[str], time: Optional[str], teams: Optional[str], hall_code: Optional[str]) -> Optional[str]:
    if not date or not time or not teams or not hall_code:
        return None
    key = f"{date}|{time}|{teams}|{hall_code}"
    return clean_text(key)


def _load_event_map() -> Dict[str, str]:
    return load_json(REFEREE_EVENTS_FILE, {})


def _save_event_map(data: Dict[str, str]) -> None:
    save_json(REFEREE_EVENTS_FILE, data)


def get_event_id_from_map(assignment: Dict, use_old: bool = False) -> Optional[str]:
    data = _load_event_map()
    if use_old:
        key = _build_event_key(
            assignment.get("old_date"),
            assignment.get("old_time"),
            assignment.get("teams"),
            assignment.get("old_hall_code") or assignment.get("hall_code"),
        )
    else:
        key = _build_event_key(
            assignment.get("date"),
            assignment.get("time"),
            assignment.get("teams"),
            assignment.get("hall_code"),
        )
    if not key:
        return None
    return data.get(key)


def update_event_map(old_assignment: Optional[Dict], new_assignment: Dict, event_id: str) -> None:
    data = _load_event_map()
    if old_assignment:
        old_key = _build_event_key(
            old_assignment.get("date"),
            old_assignment.get("time"),
            old_assignment.get("teams"),
            old_assignment.get("hall_code"),
        )
        if old_key and old_key in data:
            data.pop(old_key, None)
    new_key = _build_event_key(
        new_assignment.get("date"),
        new_assignment.get("time"),
        new_assignment.get("teams"),
        new_assignment.get("hall_code"),
    )
    if new_key:
        data[new_key] = event_id
    _save_event_map(data)


def _build_event_description(assignment: Dict) -> str:
    lines = []
    if assignment.get("type"):
        lines.append(f"Type: {assignment['type']}")
    if assignment.get("liga"):
        lines.append(f"Liga: {assignment['liga']}")
    if assignment.get("spielnummer"):
        lines.append(f"Spielnummer: {assignment['spielnummer']}")
    if assignment.get("hall_code"):
        lines.append(f"Halle: {assignment['hall_code']}")
    if assignment.get("referees"):
        refs = assignment["referees"]
        if isinstance(refs, list):
            lines.append("Referees: " + ", ".join(refs))
        else:
            lines.append(f"Referees: {refs}")
    return "\n".join(lines)


def _build_event_location(assignment: Dict) -> Optional[str]:
    hall_code = assignment.get("hall_code")
    location = assignment.get("location")
    address = assignment.get("address")

    if hall_code:
        try:
            gym_addr = get_gym_address(hall_code)
            if gym_addr:
                return f"{gym_addr} ({hall_code})"
        except Exception:
            pass
        if location:
            return f"{location} ({hall_code})"
        return hall_code
    if address:
        return address
    return location


def _assignment_datetime(assignment: Dict) -> Optional[datetime.datetime]:
    if not assignment.get("date") or not assignment.get("time"):
        return None
    return datetime.datetime.strptime(
        f"{assignment['date']} {assignment['time']}",
        "%d.%m.%Y %H:%M",
    ).replace(tzinfo=BERLIN_TZ)


def create_referee_event(assignment: Dict) -> Optional[str]:
    service = get_calendar_service()
    calendar_id = get_calendar_id_by_name(service, REFEREE_CALENDAR_NAME)

    start_dt = _assignment_datetime(assignment)
    if not start_dt:
        return None
    end_dt = start_dt + datetime.timedelta(hours=DEFAULT_DURATION_HOURS)

    summary = f"Game: {assignment.get('teams')}" if assignment.get("teams") else "Game"
    event = {
        "summary": summary,
        "description": _build_event_description(assignment),
        "location": _build_event_location(assignment),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"},
    }

    created = service.events().insert(calendarId=calendar_id, body=event).execute()
    event_id = created.get("id")
    if event_id:
        update_event_map(None, assignment, event_id)
    return event_id


def update_referee_event(event_id: str, assignment: Dict) -> Optional[str]:
    service = get_calendar_service()
    calendar_id = get_calendar_id_by_name(service, REFEREE_CALENDAR_NAME)

    start_dt = _assignment_datetime(assignment)
    if not start_dt:
        start_dt = None
    end_dt = start_dt + datetime.timedelta(hours=DEFAULT_DURATION_HOURS) if start_dt else None

    summary = f"Game: {assignment.get('teams')}" if assignment.get("teams") else "Game"
    patch = {
        "summary": summary,
        "description": _build_event_description(assignment),
        "location": _build_event_location(assignment),
    }
    if start_dt and end_dt:
        patch["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"}
        patch["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"}

    updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
    return updated.get("id")


def cancel_referee_event(event_id: str, assignment: Dict) -> Optional[str]:
    service = get_calendar_service()
    calendar_id = get_calendar_id_by_name(service, REFEREE_CALENDAR_NAME)

    summary = f"Game: {assignment.get('teams')}" if assignment.get("teams") else "Game"
    if not summary.startswith("CANCELLED:"):
        summary = f"CANCELLED: {summary}"
    patch = {
        "summary": summary,
        "colorId": CANCEL_COLOR_ID,
    }
    updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
    return updated.get("id")


def _get_referee_calendar_events(target_date: datetime.datetime) -> List[Dict]:
    service = get_calendar_service()
    calendar_id = get_calendar_id_by_name(service, REFEREE_CALENDAR_NAME)
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.UTC).isoformat()
    end = target_date.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=datetime.UTC).isoformat()
    events = service.events().list(
        calendarId=calendar_id, timeMin=start, timeMax=end,
        singleEvents=True, orderBy="startTime"
    ).execute().get("items", [])
    return events


def check_availability(assignment: Dict) -> Tuple[bool, Optional[str]]:
    target_dt = _assignment_datetime(assignment)
    if not target_dt:
        return True, None

    events = _get_referee_calendar_events(target_dt)

    new_loc = assignment.get("hall_code") or assignment.get("location") or ""
    for event in events:
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue
        try:
            event_start = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        event_location = event.get("location", "") or ""
        same_location = clean_text(new_loc) in clean_text(event_location) or clean_text(event_location) in clean_text(new_loc)

        buffer_hours = 2 if same_location else 3
        diff_hours = abs((event_start - target_dt).total_seconds()) / 3600

        if diff_hours < buffer_hours:
            return False, f"Conflict within {buffer_hours}h of another game/practice."

    return True, None


def check_game_conflict(new_game_dt: datetime.datetime) -> str:
    """Check schedule for conflicts with a new game on the same day."""
    events = get_events_for_date(new_game_dt)
    game_times = [e[0] for e in events if e[0] and ("game" in e[1].lower() or "practice" in e[1].lower())]

    def to_naive(dt):
        if dt.tzinfo is not None:
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt

    new_game_dt_naive = to_naive(new_game_dt)
    game_times_naive = [to_naive(dt) for dt in game_times]

    if not game_times_naive:
        return "✅"

    min_diff = None
    for dt in game_times_naive:
        diff_hours = abs((dt - new_game_dt_naive).total_seconds()) / 3600
        if min_diff is None or diff_hours < min_diff:
            min_diff = diff_hours

    if min_diff is not None:
        if min_diff < 2:
            return "⛔"
        if 2 <= min_diff < 3:
            return "⚠️"
        return "🟢"
    return "❔"


def find_existing_event(assignment: Dict) -> Tuple[Optional[str], Optional[Dict]]:
    service = get_calendar_service()
    calendar_id = get_calendar_id_by_name(service, REFEREE_CALENDAR_NAME)

    event_id = get_event_id_from_map(assignment, use_old=True) or get_event_id_from_map(assignment, use_old=False)
    if event_id:
        try:
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            return event_id, event
        except Exception:
            pass

    # Fallback: match by teams + date/time in referee calendar
    target_dt = _assignment_datetime(assignment)
    if not target_dt:
        return None, None
    events = _get_referee_calendar_events(target_dt)
    teams = clean_text(assignment.get("teams") or "")
    for event in events:
        summary = clean_text(event.get("summary", ""))
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue
        try:
            event_start = datetime.datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if teams and teams in summary and abs((event_start - target_dt).total_seconds()) < 3600:
            return event.get("id"), event

    return None, None
