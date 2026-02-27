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
from perry_assistant.bot.handlers import absences, admin, common, referee, schedule, stats, uportal, weather
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
    app.add_handler(CommandHandler("uportal", uportal.uportal))
    app.add_handler(CommandHandler("uportal_ignored", uportal.uportal_ignored))
    app.add_handler(CommandHandler("parents", admin.parents))

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

    app.add_handler(MessageHandler(filters.Regex(r"^4/.*"), referee.handle_auth_code))
    app.add_handler(MessageHandler(filters.LOCATION, weather.receive_weather_location))
    app.add_handler(CallbackQueryHandler(uportal.ignore_uportal_game, pattern=r"^uio:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, common.button_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(referee.process_basketball_emails_job, interval=300, first=0)
    app.job_queue.run_repeating(uportal.process_uportal_schedule_tick_job, interval=60, first=0)
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
    return app
