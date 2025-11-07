import os
import logging
from logging.handlers import TimedRotatingFileHandler

import datetime
import re
import pickle
import traceback
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus
import requests
import telegram
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler, filters, CallbackContext, ContextTypes
from googleapiclient.discovery import build
import json
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
import html
import shutil

# -- LOGGING SETUP --
LOG_DIR = "/data/logs/"
LOG_PATH = os.path.join(LOG_DIR, "logs.log")

os.makedirs(LOG_DIR, exist_ok=True)

file_handler = TimedRotatingFileHandler(LOG_PATH, when="midnight", encoding="utf-8")
file_handler.suffix = "%Y-%m-%d"
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        file_handler,
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# -- CONFIG SETUP --

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

# Use DATA_DIR (mounted volume) for all persistent files
DATA_DIR = os.getenv("DATA_DIR", "/data")

PEOPLE = ['@barykinmiron', '@barykinamarina', '@bar_and_bar']
MIRON_ID = 1955285579

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/gmail.readonly"]
# paths now point into DATA_DIR so files survive rebuilds
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'google_calendar_benny_access.json')
TOKEN_PICKLE = os.path.join(DATA_DIR, 'token.pickle')

NOTIFICATION_FILE = os.path.join(DATA_DIR, 'notification_times.json')
PARENTS_FILE = os.path.join(DATA_DIR, 'parents.json')

HOME = {"lat": 51.261838, "lon": 6.677088}
SCHOOL = {"lat": 51.305463, "lon": 6.743720}

SET_TIME = range(1)

BASKETBALL_EMAILS = ["*@uportal-wbv.de", "noreply@basketball-bund.net", "bekettgregory@gmail.com"]
STORED_EMAIL_IDS_FILE = os.path.join(DATA_DIR, 'processed_emails.json')
LOG_DIR = os.path.join(DATA_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "logs.log")

## -- JSON FUNCTIONS --

def load_json(file: str, default: Any) -> Any:
    """Load JSON from file, return default if file does not exist."""
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return default

def save_json(file: str, data: Any) -> None:
    """Save data as JSON to file."""
    with open(file, "w") as f:
        json.dump(data, f)

def clean_text(text: str) -> str:
    """Remove emojis and special symbols for easier matching."""
    return re.sub(r"[^\w\s]", "", text).lower() if text else ""

# -- WEATHER FUNCTIONS --

def get_weather(location: dict, target_dt: datetime.datetime) -> dict:
    """Fetch weather data for a location and time."""
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast?"
        f"lat={location['lat']}&lon={location['lon']}"
        f"&appid={OPENWEATHER_API_KEY}&units=metric"
    )
    data = requests.get(url).json()

    if "list" not in data:
        logger.error(f"OpenWeather error: {data}")
        return {
            "temp": None,
            "wind_speed": None,
            "wind_deg": None,
            "rain": False,
            "desc": f"API error: {data.get('message', 'unknown')}"
        }

    forecasts = data["list"]
    target_ts = int(target_dt.timestamp())
    chosen = min(forecasts, key=lambda f: abs(int(f["dt"]) - target_ts))

    main = chosen["main"]
    wind = chosen["wind"]
    weather_desc = chosen["weather"][0]["description"].lower()

    return {
        "temp": main["temp"],
        "wind_speed": wind["speed"],
        "wind_deg": wind["deg"],
        "rain": "rain" in weather_desc,
        "desc": weather_desc,
    }

def wind_direction_effect(wind_deg: float, route_angle: int = 30) -> str:
    """Return tailwind/headwind/crosswind based on wind coming from wind_deg."""
    blow_to = (wind_deg + 180) % 360
    diff = abs(blow_to - route_angle)
    diff = min(diff, 360 - diff)

    if diff <= 45:
        return "tailwind"
    elif diff >= 135:
        return "headwind"
    else:
        return "crosswind"

def bike_advice(weather: dict, wind_deg=None, route_angle=30) -> str:
    """Evaluate biking conditions and return advice."""


    if not weather or weather.get("temp") is None:
        return "⚫ Weather data unavailable, impossible to use bike 🚲"

    temp = weather.get("temp")
    wind = weather.get("wind_speed")
    rain = weather.get("rain")

    score = 0  # lower is better

    # --- Temperature evaluation ---
    if temp < 0:
        score += 3
        temp_msg = "Too cold ❄️"
    elif temp > 35:
        score += 3
        temp_msg = "Too hot 🔥"
    elif 0 <= temp < 10 or 30 < temp <= 35:
        score += 1
        temp_msg = "Temperature is a bit extreme 🌡️"
    else:
        temp_msg = "Temperature is good 👍"

    temp_msg += f" ({temp}°C)"

    # --- Wind direction evaluation ---
    if wind is None:
        wind_msg = "Wind data unavailable 🌬️"
    else:            
        if wind_deg is not None:
            effect = wind_direction_effect(wind_deg, route_angle)
            if effect == "tailwind":
                score -= 1  # makes biking easier
                wind_msg = "👍 Tailwind"
            elif effect == "headwind":
                score += 1  # makes biking harder
                wind_msg = "<b>👎 Headwind</b>"
            else:
                wind_msg = "👈 Crosswind"
        else:
            wind_msg = "💨 Wind"

        if wind > 25:
            score += 3
        elif 15 < wind <= 25:
            score += 2
        elif 5 < wind <= 15:
            score += 1

        wind_msg += f" ({wind} m/s)"

    # --- Rain evaluation ---
    if rain:
        score += 2
        rain_msg = "🌧️ Rainy, <b>take rain gear ☔</b>"
    else:
        rain_msg = "☀️ No rain"

    # --- Overall emoji based on score ---
    if score <= 0:
        emoji = "🟢"
    elif 1 <= score <= 2:
        emoji = "🟡"
    elif 3 <= score <= 4:
        emoji = "🟠"
    elif 5 <= score <= 6:
        emoji = "🔴"
    else:  # score >= 7
        emoji = "⚫"

    return f"{emoji} {temp_msg} {wind_msg} {rain_msg}"

## -- GOOGLE API FUNCTIONS --

def get_calendar_service():
    """Getting Google Calendar API service."""
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as token:
            creds = pickle.load(token)
    return build("calendar", "v3", credentials=creds)

def get_gmail_service():
    """Getting Gmail API service."""
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as token:
            creds = pickle.load(token)
    return build("gmail", "v1", credentials=creds)

## -- GOOGLE CALENDAR FUNCTIONS --

def get_all_calendars(service):
    """Get all calendars from the Google Calendar API."""
    return service.calendarList().list().execute().get("items", [])

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

def get_events_for_date(target_date: datetime.datetime):
    """Get all events for a specific date."""
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
            events_all.append(format_event(e, cal_symbol, is_basketball))

    return sorted(events_all, key=lambda x: (not x[3], x[0] is None, x[0]))

def get_day_events_text(date: datetime.datetime, label="Events") -> str:
    """Format events for a given day as text."""
    events = get_events_for_date(date)
    if not events:
        return f"No {label.lower()} found."
    return "\n".join(e[1] for e in events)

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

## -- NOTIFICATIONS --

def load_notification_times():
    """Load notification times from file."""
    return load_json(NOTIFICATION_FILE, {})

def save_notification_times(times):
    """Save notification times to file."""
    save_json(NOTIFICATION_FILE, times)

def schedule_user_notification(app, user_id: int, time_str: str):
    """Schedule daily notification for a user."""
    hour, minute = map(int, time_str.split(":"))
    berlin_time = datetime.time(hour, minute, tzinfo=ZoneInfo("Europe/Berlin"))
    app.job_queue.run_daily(send_daily_notification, time=berlin_time, chat_id=user_id)

def schedule_notifications(app):
    """Schedule notifications for all users and morning message."""
    for user_id, t in load_notification_times().items():
        schedule_user_notification(app, int(user_id), t)
    app.job_queue.run_daily(send_morning_message, time=datetime.time(6, 0, tzinfo=ZoneInfo("Europe/Berlin")))

async def send_daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Send daily notification to user."""
    chat_id = context.job.chat_id
    try:
        events_text = get_day_events_text(datetime.datetime.now(datetime.UTC), "today's events")
        await context.bot.send_message(chat_id, f"Today's events:\n{events_text}", parse_mode=telegram.constants.ParseMode.HTML)
    except Exception as e:
        await global_error_notify(None, context, e)

async def send_morning_message(context: ContextTypes.DEFAULT_TYPE):
    """Send morning message to Miron."""
    chat_id = 1955285579
    today = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    try:
        events = get_events_for_date(today)

        school_events = [e for e in events if "school" in e[1].lower()]
        school_end = max((e[0] for e in school_events if e[0]), default=None)

        target_home = today.replace(hour=7, minute=0, second=0, microsecond=0)
        home_weather = get_weather(HOME, target_home)
        school_weather = get_weather(SCHOOL, school_end) if school_end else None

        home_advice = bike_advice(home_weather)
        school_advice = bike_advice(school_weather) if school_weather else "No school today."

        gap_warning = check_school_practice_gap(events)

        msg_lines = [
            f"☀️ Good morning, Miron! \n Here is your schedule for today:\n{get_day_events_text(today)}",
        ]

        if any("school" in event[1].lower() for event in events):    
            if home_weather.get("temp") is not None:
                msg_lines.append(
                    f"🏠{home_advice}"
                )
            else:
                msg_lines.append(f"⁉️🏠 Weather on the way in — Weather unavailable 🚲")

            if school_weather:
                if school_weather.get("temp") is not None:
                    msg_lines.append(
                        f"🏫{school_advice}"
                    )
                else:
                    msg_lines.append(f"⁉️🏫 Weather at school end — Weather unavailable 🚲")

            if gap_warning:
                msg_lines.append(gap_warning)

        msg = "\n\n".join(msg_lines)
        await context.bot.send_message(chat_id, msg, parse_mode=telegram.constants.ParseMode.HTML)
    except Exception as e:
        await global_error_notify(None, context, e)


# -- COMMANDS --

async def start(update: Update, context: CallbackContext):
    """Handle /start command."""
    is_miron = update.effective_user.username == "barykinmiron"
    if not is_miron:
        save_parent(update.effective_user.id)

    keyboard = (
        [[KeyboardButton("BIKE"), KeyboardButton("TRAIN"), KeyboardButton("PRACTICE")]]
        if is_miron else
        [[KeyboardButton("TODAY"), KeyboardButton("WEEKEND")]]
    )
    await update.message.reply_text(
        "Welcome! Use /settime to set daily notification time. Use /today, /tomorrow, or /weekend to get the events.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def settime(update: Update, context: CallbackContext):
    """Handle /settime command."""
    # Ask user to send the notification time
    await update.message.reply_text("Send time as HH:MM (24h). Example: 08:30")
    return SET_TIME

async def handle_time_message(update: Update, context: CallbackContext):
    """Handle time message for notification setup."""
    user_id, text = update.effective_user.id, update.message.text.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)

    if not match or not (0 <= int(match[1]) < 24 and 0 <= int(match[2]) < 60):
        await update.message.reply_text("Invalid format. Use HH:MM (24h).")
        return SET_TIME

    times = load_notification_times()
    times[str(user_id)] = f"{int(match[1]):02d}:{int(match[2]):02d}"
    save_notification_times(times)
    schedule_user_notification(context.application, user_id, times[str(user_id)])
    await update.message.reply_text(f"Notification time set to {times[str(user_id)]}.")
    return ConversationHandler.END

async def today(update: Update, context: CallbackContext):
    """Send today's events."""
    msg = get_day_events_text(datetime.datetime.now(datetime.UTC), "today's events")
    await update.message.reply_text(f"Today's events:\n{msg}", parse_mode=telegram.constants.ParseMode.HTML)

async def tomorrow(update: Update, context: CallbackContext):
    """Send tomorrow's events."""
    msg = get_day_events_text(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1), "tomorrow's events")
    await update.message.reply_text(f"Tomorrow's events:\n{msg}", parse_mode=telegram.constants.ParseMode.HTML)

async def weekend(update: Update, context: CallbackContext):
    """Send weekend basketball events."""
    now = datetime.datetime.now(datetime.UTC)
    saturday = now + datetime.timedelta((5 - now.weekday()) % 7)
    sunday = saturday + datetime.timedelta(days=1)

    sat_events = [e[1] for e in get_events_for_date(saturday) if e[2]]
    sun_events = [e[1] for e in get_events_for_date(sunday) if e[2]]

    sat_events_str = '\n'.join(sat_events) if sat_events else 'No events'
    sun_events_str = '\n'.join(sun_events) if sun_events else 'No events'

    msg = (
        f"This weekend {saturday.day} - {sunday.day} basketball events:\n"
        f"Saturday:\n{sat_events_str}\n"
        f"Sunday:\n{sun_events_str}"
    )
    await update.message.reply_text(msg, parse_mode=telegram.constants.ParseMode.HTML)

async def morning(update: Update, context: CallbackContext):
    """Send the morning message manually."""
    # Send the morning message manually
    fake_context = type("obj", (), {"bot": context.bot})
    await send_morning_message(fake_context)


async def myid(update: Update, context: CallbackContext):
    """Send user's chat ID."""
    # Send user's chat ID
    await update.message.reply_text(f"Your ID is {update.effective_chat.id}")

# -- PARENTS --

def load_parents():
    """Load parent chat IDs from file."""
    return load_json(PARENTS_FILE, [])

def save_parent(chat_id):
    """Save parent chat ID to file."""
    parents = load_parents()
    if chat_id not in parents:
        parents.append(chat_id)
        save_json(PARENTS_FILE, parents)

async def leftschool(update: Update, context: CallbackContext):
    """Notify parents when Miron leaves school."""
    if update.effective_user.username != "barykinmiron":
        await update.message.reply_text("Only Miron can use this.")
        return

    if not context.args or context.args[0].lower() not in ["bike", "train", "practice"]:
        await update.message.reply_text("Usage: /leftschool [bike|train|practice]")
        return

    method = context.args[0].lower()
    eta = {
        "bike": "by bike <i>(ETA 33 minutes)</i>",
        "train": "by train <i>(ETA 60 minutes)</i>",
        "practice": "for practice <i>(ETA 20 minutes after practice)</i>"
    }[method]

    msg = f"Miron has left school {eta}."
    for pid in load_parents():
        try:
            await context.bot.send_message(pid, msg)
        except Exception:
            pass
    await update.message.reply_text(f"Notifications sent.\nMessage: {msg}")

# -- BUTTON HANDLER --

async def button_handler(update: Update, context: CallbackContext):
    """Handle button presses."""
    text, user = update.message.text.strip().upper(), update.effective_user.username
    if user == "barykinmiron":
        if text in ["BIKE", "TRAIN", "PRACTICE"]:
            context.args = [text.lower()]
            await leftschool(update, context)
    else:
        if text == "TODAY":
            await today(update, context)
        elif text == "WEEKEND":
            await weekend(update, context)

# -- ERROR HANDLER --

async def send_auth_link_to_miron(context, reason="Google token expired"):
    """Send Google reauthorization link to Miron and set bot_data for code awaiting."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob"
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )
    context.bot_data["pending_auth"] = {
        "flow": flow,
        "awaiting_code": True
    }
    await context.bot.send_message(
        chat_id=MIRON_ID,
        text=(
            f"⚠️ {reason}.\n\n"
            f"Please reauthorize the bot by clicking the link below:\n\n"
            f"{auth_url}\n\n"
            f"After logging in, send me the code you receive here."
        )
    )
    logger.warning(f"Authorization required — sent link to Miron (job context)")

async def handle_auth_code(update: Update, context: CallbackContext):
    """Handle OAuth code sent by Miron."""
    logger.debug("Received potential auth code message.")
    if update.effective_user.id != MIRON_ID:
        return
    code = update.message.text.strip()
    if not code.startswith("4/"):
        return
    pending = context.bot_data.get("pending_auth")
    if not pending or not pending.get("awaiting_code"):
        return
    flow = pending["flow"]
    try:
        logger.debug("Attempting to fetch token with provided code.")
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(TOKEN_PICKLE, "wb") as token:
            pickle.dump(creds, token)
        context.bot_data["pending_auth"] = None
        await update.message.reply_text("✅ Google authentication updated! You can use calendar features again.")
        logger.info("Google authentication updated successfully.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to authenticate: {e}")
        logger.error(f"Failed to authenticate with code: {e}")

async def auth_error_notify(update, context, error):
    """Notify user about expired authentication and send Miron the auth link."""
    # Notify the user who triggered the action
    if update and update.effective_chat:
        await context.bot.send_message(
            update.effective_chat.id,
            "❗ Google Calendar authentication expired. Miron has been notified to update it. Please try again later."
        )
    # Notify Miron with the auth link
    await send_auth_link_to_miron(context, reason="Google token expired (RefreshError)")

async def global_error_notify(update, context, error):
    """Send error details to Miron and log."""
    # Handle google.auth.exceptions.RefreshError
    if isinstance(error, RefreshError):
        await auth_error_notify(update, context, error)
        return
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(tb)
    timestamp = datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")
    user = None
    chat_id = None
    if update:
        user = getattr(getattr(update, "effective_user", None), "username", "Unknown")
        chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
    else:
        user = "JobQueue"
    admin_chat_id = MIRON_ID

    # Escape the traceback to avoid Telegram HTML parse errors
    safe_tb = html.escape(tb)
    msg_admin = (
        f"⚠️ Error during {user}'s usage\n"
        f"Timestamp: {timestamp}\n"
        f"Details:\n<pre>{safe_tb}</pre>"
    )
    try:
        # send as HTML (traceback is escaped so HTML parsing won't fail)
        await context.bot.send_message(chat_id=admin_chat_id, text=msg_admin, parse_mode=telegram.constants.ParseMode.HTML)
    except Exception as e:
        logger.error(f"Failed to send error to Miron: {e}")
    if chat_id and user != "barykinmiron":
        try:
            # simple plain-text notification to the user who triggered the error
            await context.bot.send_message(
                chat_id,
                "🚨 Your request caused an error. Miron has been notified to review it."
            )
        except Exception as e:
            logger.error(f"Failed to notify user about the error: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors and notify admin/user."""
    error = getattr(context, "error", None)
    await global_error_notify(update, context, error if error else Exception("Unknown error"))

# -- EMAIL FUNCTIONS --

def get_basketball_emails(service, max_results=10):
    """Get basketball-related emails from Gmail."""
    query = " OR ".join(f"from:{email}" for email in BASKETBALL_EMAILS)
    results = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()
    return results.get('messages', [])

def get_email_content(service, msg_id):
    """Get full email content."""
    message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = message['payload']
    headers = {header['name']: header['value'] for header in payload.get('headers', [])}
    
    if 'parts' in payload:
        parts = payload['parts']
        data = parts[0]['body'].get('data', '')
    else:
        data = payload['body'].get('data', '')
    
    if data:
        import base64
        text = base64.urlsafe_b64decode(data).decode()
    else:
        text = ""
    
    return {
        'subject': headers.get('Subject', ''),
        'from': headers.get('From', ''),
        'date': headers.get('Date', ''),
        'content': text
    }

def parse_basketball_email(content):
    """Parse basketball email content."""
    subject = content['subject']
    body = content['content']
    
    # Determine email type
    email_type = None
    if "offene Umbesetzung" in subject:
        email_type = "Umbesetzung"
    elif "SR-Ansetzung" in subject:
        email_type = "Ansetzung"
    elif "Spieländerung" in subject:
        email_type = "Spieländerung"
    elif "Spielverlegung" in subject:
        email_type = "Spielverlegung"
    
    if not email_type:
        return None

    # For double Umbesetzung, find all assignments
    assignments = []
    if "1. Ansetzung:" in body:
        # Split by numbered assignments
        parts = re.split(r'\d+\.\s*Ansetzung:', body)[1:]  # Skip text before first assignment
        for part in parts:
            info = {
                'type': email_type,
                'date': None,
                'time': None,
                'liga': None,
                'location': None,
                'teams': None,
                'hall_code': None
            }
            
            # Parse date
            date_match = re.search(r'Datum:\s*\w+,\s*(\d{2}\.\d{2}\.\d{4})', part)
            if date_match:
                info['date'] = date_match.group(1)
            
            # Parse time
            time_match = re.search(r'Zeit:\s*(\d{2}:\d{2})', part)
            if time_match:
                info['time'] = time_match.group(1)
            
            # Parse liga
            liga_match = re.search(r'Liga:\s*([^\n]+)', part)
            if liga_match:
                info['liga'] = liga_match.group(1).strip()
            
            # Parse teams and location
            teams_match = re.search(r'Begegnung:\s*([^\n]+)', part)
            hall_match = re.search(r'Halle:\s*([^\n]+)', part)
            
            if teams_match:
                info['teams'] = teams_match.group(1).strip()
            if hall_match:
                hall_text = hall_match.group(1).strip()
                # Extract hall code if present (format: XXXYZZZ)
                hall_code_match = re.search(r'\d{3}[A-Z]\d{3}', hall_text)
                if hall_code_match:
                    info['hall_code'] = hall_code_match.group(0)
                info['location'] = hall_text
            
            if info['date'] and info['time']:  # Only add if we have at least date and time
                assignments.append(info)
    else:
        # Single assignment (SR-Ansetzung format)
        info = {
            'type': email_type,
            'date': None,
            'time': None,
            'liga': None,
            'location': None,
            'teams': None,
            'hall_code': None
        }
        
        # Parse date and time from SR-Ansetzung format
        datetime_match = re.search(r'Spielbeginn:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})', body)
        if datetime_match:
            info['date'] = datetime_match.group(1)
            info['time'] = datetime_match.group(2)
        
        # Parse liga
        liga_match = re.search(r'Liga:\s*([^\n]+)', body)
        if liga_match:
            info['liga'] = liga_match.group(1).strip()
        
        # Parse location with hall code
        location_match = re.search(r'Spielhalle:\s*([^\n]+)\s+\((\d{3}[A-Z]\d{3})\)', body)
        if location_match:
            info['location'] = location_match.group(1).strip()
            info['hall_code'] = location_match.group(2)
        
        # Parse teams
        home_match = re.search(r'Heimmannschaft:\s*([^\n]+)', body)
        away_match = re.search(r'Gastmannschaft:\s*([^\n]+)', body)
        if home_match and away_match:
            info['teams'] = f"{home_match.group(1).strip()} - {away_match.group(1).strip()}"
        
        if info['date'] and info['time']:
            assignments.append(info)
    
    return assignments if assignments else None

async def check_calendar_availability(date_str, time_str):
    """Check calendar availability for a given date and time."""
    try:
        date_parts = date_str.split('.')
        date = datetime.datetime.strptime(f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]} {time_str}", "%Y-%m-%d %H:%M")
        events = get_events_for_date(date)
        return events, any(
            e[0] and abs((e[0] - date).total_seconds()) < 7200  # 2 hours
            for e in events
        )
    except Exception as e:
        logger.error(f"Error checking availability: {e}")
        return [], False

async def process_basketball_emails(context: ContextTypes.DEFAULT_TYPE):
    """Process new basketball emails and send notifications."""
    try:
        service = get_gmail_service()
        processed_ids = load_json(STORED_EMAIL_IDS_FILE, [])
        
        try:
            messages = get_basketball_emails(service)
        except HttpError as he:
            # Handle Gmail API disabled / project not configured
            try:
                err_text = ""
                try:
                    # attempt to extract message from HttpError content
                    err_text = he.error_details if hasattr(he, "error_details") else str(he)
                except Exception:
                    err_text = str(he)
                logger.warning(f"Gmail API HttpError while fetching messages: {err_text}")
                # Inform Miron in plain text (avoid HTML parsing issues)
                await context.bot.send_message(
                    chat_id=MIRON_ID,
                    text=(
                        "⚠️ Gmail API error while checking for basketball emails.\n\n"
                        "Reason: Gmail API is not enabled for the Google project or access is not configured.\n"
                        "Please enable the Gmail API in the Google Cloud Console for the project used by the bot.\n"
                        "Error: " + err_text
                    )
                )
            except Exception as e:
                # If notifying fails, log it via global_error_notify
                await global_error_notify(None, context, he)
            return

        for message_meta in messages:
            msg_id = message_meta.get('id')
            if not msg_id or msg_id in processed_ids:
                continue
                
            content = get_email_content(service, msg_id)
            assignments = parse_basketball_email(content)
            
            if not assignments:
                processed_ids.append(msg_id)
                continue

            is_multiple = len(assignments) > 1
            prefix = "🏀 DOUBLE" if is_multiple else "🏀"
            
            for assignment in assignments:
                # Check calendar availability
                events, conflict = await check_calendar_availability(assignment['date'], assignment['time'])
                schedule_text = get_day_events_text(
                    datetime.datetime.strptime(assignment['date'], '%d.%m.%Y')
                )
                
                # Format location string
                location_str = ""
                if assignment['location']:
                    if assignment['hall_code']:
                        location_str = f" @ {assignment['location']} ({assignment['hall_code']})"
                    else:
                        location_str = f" @ {assignment['location']}"

                # Build concise message
                msg = (
                    f"{prefix} <b>{assignment['type']}</b>: "
                    f"{assignment['liga']} {assignment['date']} {assignment['time']} "
                    f"{assignment['teams']}{location_str}\n\n"
                    f"{'⚠️ Schedule conflicts!' if conflict else '✅ Schedule is free!'}\n"
                    f"Your schedule:\n{schedule_text}"
                )
                
                await context.bot.send_message(
                    chat_id=MIRON_ID,
                    text=msg,
                    parse_mode=telegram.constants.ParseMode.HTML
                )
            
            processed_ids.append(msg_id)
            save_json(STORED_EMAIL_IDS_FILE, processed_ids)
            
    except Exception as e:
        await global_error_notify(None, context, e)

def ensure_persistent_files():
    """Ensure DATA_DIR exists and copy default files from app dir into DATA_DIR only if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    defaults = {
        'google_calendar_benny_access.json': './google_calendar_benny_access.json',
        'token.pickle': './token.pickle',
        'notification_times.json': './notification_times.json',
        'parents.json': './parents.json',
        'processed_emails.json': './processed_emails.json'
    }
    for dst_name, src_path in defaults.items():
        dst_path = os.path.join(DATA_DIR, dst_name)
        if not os.path.exists(dst_path) and os.path.exists(src_path):
            try:
                shutil.copy(src_path, dst_path)
                logger.info(f"Copied default {src_path} -> {dst_path}")
            except Exception as e:
                logger.error(f"Failed to copy default {src_path} -> {dst_path}: {e}")

# -- MAIN FUNCTION --

def main():
    # ensure persistent folder and default files are present before app starts
    ensure_persistent_files()

    app = ApplicationBuilder().token(TG_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("weekend", weekend))
    app.add_handler(CommandHandler("leftschool", leftschool))
    app.add_handler(CommandHandler("morning", morning))
    app.add_handler(CommandHandler("myid", myid))

    conv = ConversationHandler(
        entry_points=[CommandHandler("settime", settime)],
        states={SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_message)]},
        fallbacks=[]
    )
    app.add_handler(conv)

    # Register handle_auth_code BEFORE button_handler!
    app.add_handler(MessageHandler(filters.Regex(r"^4/.*"), handle_auth_code))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(process_basketball_emails, interval=300)
    
    schedule_notifications(app)
    app.run_polling()

if __name__ == "__main__":
    main()
