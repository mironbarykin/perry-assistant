from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.bot.error_handler import error_handler
from perry_assistant.bot.handlers import absences, admin, common, game_messages, referee, schedule, stats, uportal, weather
from perry_assistant.bot.handlers import untis_timetable
from perry_assistant.domain.types import AppServices


def build_application(services: AppServices) -> Application:
    app = ApplicationBuilder().token(services.config.tg_token).build()
    app.bot_data["services"] = services

    app.add_handler(TypeHandler(Update, stats.log_incoming_update, block=False), group=-1)

    app.add_handler(CommandHandler("start", common.start))
    app.add_handler(CommandHandler("today", schedule.today))
    app.add_handler(CommandHandler("tomorrow", schedule.tomorrow))
    app.add_handler(CommandHandler("weekend", schedule.weekend))
    app.add_handler(CommandHandler("morning", schedule.morning))
    app.add_handler(CommandHandler("setweatherloc", weather.setweatherloc))
    app.add_handler(CommandHandler("weatherloc", weather.weatherloc))
    app.add_handler(CommandHandler("myid", common.myid))
    app.add_handler(CommandHandler("emails", referee.emails))
    app.add_handler(CommandHandler("games", game_messages.games))
    app.add_handler(CommandHandler("uportal", uportal.uportal))
    app.add_handler(CommandHandler("uportal_ignored", uportal.uportal_ignored))
    app.add_handler(CommandHandler("parents", admin.parents))
    app.add_handler(CommandHandler("untis_status", untis_timetable.untis_status))
    app.add_handler(CommandHandler("untis_disconnect", untis_timetable.untis_disconnect))

    app.add_handler(CommandHandler("absence", absences.absence))
    app.add_handler(CommandHandler("absences", absences.absences_all))
    app.add_handler(CommandHandler("excused", absences.absences_excused))
    app.add_handler(CommandHandler("excuse", absences.excuse))

    published_conv = ConversationHandler(
        entry_points=[CommandHandler("published", admin.published_start)],
        states={
            admin.PUBLISH_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin.published_send),
            ]
        },
        fallbacks=[],
    )
    app.add_handler(published_conv)

    set_time_conv = ConversationHandler(
        entry_points=[CommandHandler("settime", common.settime)],
        states={
            common.SET_TIME_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, common.handle_time_message),
            ]
        },
        fallbacks=[],
    )
    app.add_handler(set_time_conv)

    untis_setup_conv = ConversationHandler(
        entry_points=[
            CommandHandler("untis_setup", untis_timetable.untis_setup),
            CallbackQueryHandler(untis_timetable.untis_setup_callback, pattern=r"^untis_setup$"),
        ],
        states={
            untis_timetable.UNTIS_ASK_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, untis_timetable.untis_setup_username),
            ],
            untis_timetable.UNTIS_ASK_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, untis_timetable.untis_setup_password),
            ],
        },
        fallbacks=[],
    )
    app.add_handler(untis_setup_conv)

    app.add_handler(MessageHandler(filters.Regex(r"^4/.*"), referee.handle_auth_code))
    app.add_handler(MessageHandler(filters.LOCATION, weather.receive_weather_location))
    app.add_handler(CallbackQueryHandler(uportal.ignore_uportal_game, pattern=r"^uio:"))
    app.add_handler(CallbackQueryHandler(game_messages.select_game, pattern=r"^gmsg:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, common.button_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(referee.process_basketball_emails_job, interval=300, first=0)
    app.job_queue.run_daily(
        services.weather_archive_service.process_scheduled_capture,
        time=dt.time(hour=8, minute=0, tzinfo=BERLIN_TZ),
        name="weather_archive_08",
    )
    app.job_queue.run_daily(
        services.weather_archive_service.process_scheduled_capture,
        time=dt.time(hour=16, minute=0, tzinfo=BERLIN_TZ),
        name="weather_archive_16",
    )
    app.job_queue.run_daily(
        services.weather_archive_service.process_scheduled_capture,
        time=dt.time(hour=22, minute=0, tzinfo=BERLIN_TZ),
        name="weather_archive_22",
    )
    services.notification_service.schedule_all(
        app=app,
        user_callback=schedule.send_daily_notification_job,
        morning_callback=schedule.send_morning_message_job,
    )

    # Adaptive Untis timetable polling jobs
    # Morning window 06:00–08:00: every 10 minutes
    for minute in range(0, 120, 10):
        h, m = divmod(minute, 60)
        run_time = dt.time(hour=6 + h, minute=m, tzinfo=BERLIN_TZ)
        app.job_queue.run_daily(
            untis_timetable.check_timetable_changes_job,
            time=run_time,
            name=f"untis_morning_{minute:03d}",
        )

    # Evening window 18:00–21:00: every 15 minutes
    for minute in range(0, 180, 15):
        h, m = divmod(minute, 60)
        run_time = dt.time(hour=18 + h, minute=m, tzinfo=BERLIN_TZ)
        app.job_queue.run_daily(
            untis_timetable.check_timetable_changes_job,
            time=run_time,
            name=f"untis_evening_{minute:03d}",
        )

    # Off-peak: every 30 minutes during the rest of the day
    # 08:30–17:30 and 21:30–05:30 (covers the remainder via run_repeating with a filter)
    _schedule_off_peak_untis_checks(app)

    return app


def _schedule_off_peak_untis_checks(app: Application) -> None:
    """Schedule Untis checks every 30 min outside morning (06-08) and evening (18-21) windows."""
    # Build a list of 30-min slots not covered by the dense windows
    dense_slots: set[tuple[int, int]] = set()
    for minute in range(0, 120, 10):
        h, m = divmod(minute, 60)
        dense_slots.add((6 + h, m))
    for minute in range(0, 180, 15):
        h, m = divmod(minute, 60)
        dense_slots.add((18 + h, m))

    for total_minutes in range(0, 24 * 60, 30):
        h, m = divmod(total_minutes, 60)
        if (h, m) in dense_slots:
            continue
        run_time = dt.time(hour=h, minute=m, tzinfo=BERLIN_TZ)
        app.job_queue.run_daily(
            untis_timetable.check_timetable_changes_job,
            time=run_time,
            name=f"untis_offpeak_{total_minutes:04d}",
        )
