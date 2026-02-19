from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.keyboards import build_main_keyboard
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

    await update.message.reply_text(
        (
            "Welcome to Perry.\n"
            "Use /settime to configure daily notifications.\n"
            "Commands: /today /tomorrow /weekend /absences /absence /excuse"
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

    text = update.message.text.strip().upper()
    if text == "TODAY":
        from perry_assistant.bot.handlers.schedule import today

        await today(update, context)
        return

    if text == "WEEKEND":
        from perry_assistant.bot.handlers.schedule import weekend

        await weekend(update, context)
        return

    if text == "EMAILS":
        from perry_assistant.bot.handlers.referee import emails

        await emails(update, context)
        return

    if text == "ABSENCES":
        from perry_assistant.bot.handlers.absences import absences

        await absences(update, context)

