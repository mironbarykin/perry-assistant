from helpers import clean_text
from datetime import datetime
from urllib.parse import quote_plus

def check_school_practice_gap(events):
    """Check if there is a short gap between school and practice."""
    # Extract end times of school events
    school_end_times = [
        e[4] for e in events
        if e[4] is not None and "school" in clean_text(e[1])
    ]
    # Extract start times of basketball/practice events
    practice_start_times = [
        e[0] for e in events
        if e[0] is not None and "practice" in clean_text(e[1])
    ]

    if not school_end_times or not practice_start_times:
        return None

    school_end = max(school_end_times)
    practice_start = min(practice_start_times)
    gap_hours = (practice_start - school_end).total_seconds() / 3600

    if gap_hours < 2:
        return "⚠️ <b>Little time between school and basketball — plan ahead!</b>"
    return None

def format_event(event, cal_symbol, is_basketball):
    """Format a single calendar event for display."""
    summary = event.get("summary", "No Title")
    start_raw = event["start"].get("dateTime", event["start"].get("date"))
    end_raw = event["end"].get("dateTime", event["end"].get("date"))
    location = event.get("location")

    all_day = "date" in event["start"]

    def parse_time(raw):
        if not raw:
            return None
        try:
            if len(raw) == 10:
                return datetime.datetime.fromisoformat(raw + "T00:00:00+00:00")
            return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    start_dt = parse_time(start_raw)
    end_dt = parse_time(end_raw)

    if all_day:
        time_str = ""
    else:
        start_time = start_dt.strftime("%H:%M") if start_dt else "??:??"
        end_time = end_dt.strftime("%H:%M") if end_dt else "??:??"
        time_str = f"<b>{start_time}-{end_time}</b>"

    address = ""
    if is_basketball and location:
        loc_lower = location.lower()
        if "görresstraße" in loc_lower or "rso" in loc_lower:
            address = " (RSO Osterath)"
        elif "mönkesweg" in loc_lower or "smg" in loc_lower:
            address = " (SMG Strümp)"
        else:
            gmaps_url = f"https://maps.google.com/?q={quote_plus(location)}"
            address = f"<a href='{gmaps_url}'>{location}</a>"

    prefix = "📌 " if all_day else ""

    if all_day:
        line = f"{prefix}{summary}"
    else:
        line = f"{prefix}{cal_symbol} {time_str} — {summary} {address}".strip()

    return start_dt, line, is_basketball, all_day, end_dt
