from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.keyboards import build_main_keyboard, build_schedule_keyboard
from perry_assistant.domain.types import AppServices
from perry_assistant.storage.json_store import read_json, write_json


SET_TIME_STATE = 1


def get_services(context: CallbackContext) -> AppServices:
    return context.application.bot_data["services"]


async def start(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    user = update.effective_user
    if not user or not update.message:
        return

    is_admin = user.id == services.config.miron_id
    if not is_admin:
        parents = read_json(services.config.parents_file, [])
        if user.id not in parents:
            parents.append(user.id)
            write_json(services.config.parents_file, parents)

    command_text = "Commands: /today /tomorrow /weekend /absence /absences /excuse"
    if is_admin:
        command_text += " /published"

    await update.message.reply_text(
        (
            "Welcome to Perry.\n"
            "Use /settime to configure daily notifications.\n"
            f"{command_text}"
        ),
        reply_markup=build_main_keyboard(is_admin),
    )


async def settime(update: Update, context: CallbackContext) -> int:
    if update.message:
        await update.message.reply_text("Send time in HH:MM (24h). Example: 08:30")
    return SET_TIME_STATE


async def handle_time_message(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    services = get_services(context)
    user_id = update.effective_user.id
    try:
        normalized = services.notification_service.upsert_user_notification_time(
            user_id=user_id,
            time_text=update.message.text.strip(),
        )
        from perry_assistant.bot.handlers.schedule import send_daily_notification_job

        services.notification_service.schedule_user_notification(
            app=context.application,
            user_id=user_id,
            time_text=normalized,
            callback=send_daily_notification_job,
        )
    except ValueError:
        await update.message.reply_text("Invalid format. Use HH:MM (24h).")
        return SET_TIME_STATE

    await update.message.reply_text(f"Notification time saved: {normalized}")
    return ConversationHandler.END


async def myid(update: Update, context: CallbackContext) -> None:
    if update.message and update.effective_chat:
        await update.message.reply_text(f"Your ID is {update.effective_chat.id}")


async def button_handler(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    user = update.effective_user
    text = update.message.text.strip().upper()
    is_admin = bool(user and user.id == services.config.miron_id)

    if text in {"ABSENCES", "EXCUSABLE TODAY", "ALL ABSENCES", "I AM ABSENT"} and not is_admin:
        await update.message.reply_text("Access denied. Admin only.")
        return

    if text == "ABSENCES":
        from perry_assistant.bot.handlers.absences import absences_menu

        await absences_menu(update, context)
        return

    if text == "EXCUSABLE TODAY":
        from perry_assistant.bot.handlers.absences import absences_today

        await absences_today(update, context)
        return

    if text == "ALL ABSENCES":
        from perry_assistant.bot.handlers.absences import absences_all

        await absences_all(update, context)
        return

    if text == "I AM ABSENT":
        from perry_assistant.bot.handlers.absences import absences_absent

        await absences_absent(update, context)
        return

    if text == "SCHEDULE":
        await update.message.reply_text("Ok👌", reply_markup=build_schedule_keyboard())
        return
    
    if text == "TODAY":
        from perry_assistant.bot.handlers.schedule import today
        await today(update, context)
        return

    if text == "THIS WEEKEND":
        from perry_assistant.bot.handlers.schedule import this_weekend

        await this_weekend(update, context)
        return

    if text == "NEXT WEEKEND":
        from perry_assistant.bot.handlers.schedule import next_weekend

        await next_weekend(update, context)
        return

    if text == "OTHER":
        from perry_assistant.bot.handlers.schedule import other_weekend

        await other_weekend(update, context)
        return

    if text == "EMAILS":
        if not is_admin:
            await update.message.reply_text("Admin only.")
            return
        from perry_assistant.bot.handlers.referee import emails

        await emails(update, context)
        return

    if text == "BACK":
        await update.message.reply_text("Ok👌", reply_markup=build_main_keyboard(is_admin))
        return
