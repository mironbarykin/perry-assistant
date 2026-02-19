from __future__ import annotations

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from perry_assistant.bot.error_handler import error_handler
from perry_assistant.bot.handlers import absences, admin, common, referee, schedule
from perry_assistant.domain.types import AppServices


def build_application(services: AppServices) -> Application:
    app = ApplicationBuilder().token(services.config.tg_token).build()
    app.bot_data["services"] = services

    app.add_handler(CommandHandler("start", common.start))
    app.add_handler(CommandHandler("today", schedule.today))
    app.add_handler(CommandHandler("tomorrow", schedule.tomorrow))
    app.add_handler(CommandHandler("weekend", schedule.weekend))
    app.add_handler(CommandHandler("morning", schedule.morning))
    app.add_handler(CommandHandler("myid", common.myid))
    app.add_handler(CommandHandler("emails", referee.emails))
    app.add_handler(CommandHandler("parents", admin.parents))

    app.add_handler(CommandHandler("absence", absences.absence))
    app.add_handler(CommandHandler("absences", absences.absences_all))
    app.add_handler(CommandHandler("excuse", absences.excuse))

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, common.button_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(referee.process_basketball_emails_job, interval=300, first=0)
    services.notification_service.schedule_all(
        app=app,
        user_callback=schedule.send_daily_notification_job,
        morning_callback=schedule.send_morning_message_job,
    )
    return app
