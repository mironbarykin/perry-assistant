import os
import datetime
import re
import pickle
import traceback
from zoneinfo import ZoneInfo
import requests
import telegram
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler, filters, CallbackContext, ContextTypes
from googleapiclient.discovery import build
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
import html
import shutil

load_dotenv()

# -- CUSTOM IMPORTS --
from consts import *
from logs import logger, LOGS_DIR
from helpers import load_json, save_json
from gyms import get_gym_address
from emails import get_basketball_emails, get_email_content, parse_basketball_email
from services.weather import get_weather, bike_advice
from events import format_event, check_school_practice_gap

## -- APISERVICES FUNCTIONS --

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
            event_tuple = format_event(e, cal_symbol, is_basketball)
            if event_tuple[3]:
                if event_tuple[0] and event_tuple[0].date() == target_date.date():
                    events_all.append(event_tuple)
            else:
                events_all.append(event_tuple)

    return sorted(events_all, key=lambda x: (not x[3], x[0] is None, x[0]))

def get_day_events_text(date: datetime.datetime, label="Events") -> str:
    """Format events for a given day as text."""
    events = get_events_for_date(date)
    if not events:
        return f"No {label.lower()} found."
    return "\n".join(e[1] for e in events)


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

        home_advice = weather_message(home_weather)
        school_advice = weather_message(school_weather) if school_weather else "No school today."
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
        parents = load_json(PARENTS_FILE, [])
        if update.effective_user.id not in parents:
            parents.append(update.effective_user.id)
            save_json(PARENTS_FILE, parents)


    keyboard = (
        [[KeyboardButton("EMAILS"), KeyboardButton("TODAY"), KeyboardButton("WEEKEND")]]
        if is_miron else
        [[KeyboardButton("TODAY"), KeyboardButton("WEEKEND")]]
    )
    await update.message.reply_text(
        "Welcome! Use /settime to set daily notification time. Use /today, /tomorrow, or /weekend to get the events.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def settime(update: Update, context: CallbackContext):
    """Handle /settime command."""
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
    await update.message.reply_text(f"Your ID is {update.effective_chat.id}")

async def emails(update: Update, context: CallbackContext):
    """Manually trigger processing of basketball emails."""
    await update.message.reply_text("📩 Scanning your emails... ")
    await process_basketball_emails(context)
    await update.message.reply_text("👍 All of your emails have been scanned!")

# -- BUTTON HANDLER --

async def button_handler(update: Update, context: CallbackContext):
    """Handle button presses."""
    text, user = update.message.text.strip().upper(), update.effective_user.username
    if user == "barykinmiron":
        if text == "EMAILS":
            await emails(update, context)

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

def check_game_conflict(new_game_dt: datetime.datetime):
    """Check schedule for conflicts with a new game on the same day."""
    events = get_events_for_date(new_game_dt)
    game_times = [e[0] for e in events if e[0] and ("game" in e[1].lower() or "practice" in e[1].lower())]

    # Ensure all datetimes are naive or all are aware (convert to naive in UTC)
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
        elif 2 <= min_diff < 3:
            return "⚠️"
        else:
            return "🟢"
    return "❔"

async def process_basketball_emails(context: ContextTypes.DEFAULT_TYPE):
    """Process new basketball emails and send notifications."""
    try:
        service = get_gmail_service()
        processed_ids = load_json(STORED_EMAIL_IDS_FILE, [])
        processed_ids = processed_ids[-100:] if processed_ids else []

        try:
            messages = get_basketball_emails(service)
        except HttpError as he:
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
                await global_error_notify(None, context, e)
            return

        processed_set = set(processed_ids)

        for message_meta in messages:
            msg_id = message_meta.get('id')
            if not msg_id or msg_id in processed_set:
                continue
                
            content = get_email_content(service, msg_id)
            assignments = parse_basketball_email(content)
            
            if not assignments:
                processed_ids.append(msg_id)
                processed_ids = processed_ids[-100:]
                continue

            is_multiple = len(assignments) > 1
            prefix = "🏀 2x " if is_multiple else "🏀"
            
            for assignment in assignments:
                location_str = ""
                if assignment['hall_code'] == assignment['location']:
                    location_str = f" @ {get_gym_address(assignment['hall_code'])} ({assignment['hall_code']})"
                else:
                    location_str = f" @ {assignment['location']} ({assignment['hall_code']})"

                msg = (
                    f"{check_game_conflict(datetime.datetime.strptime(assignment['date'] + ' ' + assignment['time'], '%d.%m.%Y %H:%M'))} {prefix} <b>{assignment['type']}</b>: {assignment['liga']} \n"
                    f"{assignment['teams']} \n"
                    f"<b>{assignment['date']} {assignment['time']}</b> {location_str}\n"
                    f""
                )
                
                await context.bot.send_message(
                    chat_id=MIRON_ID,
                    text=msg,
                    disable_notification='⛔' in msg,
                    parse_mode=telegram.constants.ParseMode.HTML
                )
            
            processed_ids.append(msg_id)
            processed_set.add(msg_id)
            processed_ids = processed_ids[-100:]
            save_json(STORED_EMAIL_IDS_FILE, processed_ids)
            
    except Exception as e:
        await global_error_notify(None, context, e)

# -- MAIN FUNCTIONS --

def ensure_persistent_files():
    """Ensure DATA_DIR exists and copy default files from app dir into DATA_DIR only if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    defaults = {
        'google_calendar_benny_access.json': './google_calendar_benny_access.json',
        'token.pickle': './token.pickle',
        'notification_times.json': './notification_times.json',
        'parents.json': './parents.json',
        'processed_emails.json': './processed_emails.json',
        'gyms_cache.json': './gyms_cache.json',
        'school_timetable.json': './school_timetable.json',
        'school_absences.json': './school_absences.json',
    }

    for dst_name, src_path in defaults.items():
        dst_path = os.path.join(DATA_DIR, dst_name)
        if not os.path.exists(dst_path) and os.path.exists(src_path):
            try:
                shutil.copy(src_path, dst_path)
                logger.info(f"Copied default {src_path} -> {dst_path}")
            except Exception as e:
                logger.error(f"Failed to copy default {src_path} -> {dst_path}: {e}")

def main():
    ensure_persistent_files()

    app = ApplicationBuilder().token(TG_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("weekend", weekend))
    app.add_handler(CommandHandler("morning", morning))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("emails", emails))

    conv = ConversationHandler(
        entry_points=[CommandHandler("settime", settime)],
        states={SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_time_message)]},
        fallbacks=[]
    )
    app.add_handler(conv)

    app.add_handler(MessageHandler(filters.Regex(r"^4/.*"), handle_auth_code))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(process_basketball_emails, interval=300, first=0)
    
    schedule_notifications(app)
    app.run_polling()

if __name__ == "__main__":
    main()
