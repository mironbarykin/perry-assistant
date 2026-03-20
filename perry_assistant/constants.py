from zoneinfo import ZoneInfo


BERLIN_TZ = ZoneInfo("Europe/Berlin")
REFEREE_CALENDAR_NAME = "Basketball"
CANCEL_COLOR_ID = "11"
DEFAULT_GAME_DURATION_HOURS = 2

# Unified availability icons used in both email (referee_service) and
# uportal contexts so that the same status always shows the same emoji.
ICON_GREEN = "\U0001F7E2"   # 🟢 free  (≥ 2 h gap)
ICON_ORANGE = "\U0001F7E0"  # 🟠 close (≥ 1 h gap)
ICON_RED = "\U0001F534"     # 🔴 busy  (< 1 h gap)
ICON_UNKNOWN = "\u2754"     # ❔ unknown

# Distance badges appended to availability icons in uportal messages.
ICON_STAR = "\u2B50"   # ⭐ gym within 20 km
ICON_PLANE = "\u2708\uFE0F"  # ✈️ gym more than 40 km away

