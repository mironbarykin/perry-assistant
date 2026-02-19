from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import CallbackContext, ContextTypes

from perry_assistant.bot.handlers.common import get_services


async def today(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    await update.message.reply_text(services.schedule_service.today_message())


async def tomorrow(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    await update.message.reply_text(services.schedule_service.tomorrow_message())


async def weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    await update.message.reply_text(services.schedule_service.weekend_message())


async def morning(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    digest = services.schedule_service.morning_digest(
        services.config.home_coords,
        services.config.school_coords,
    )
    if update.message:
        await update.message.reply_text(digest)


async def send_daily_notification_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    chat_id = context.job.chat_id
    message = services.schedule_service.today_message()
    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
    )


async def send_morning_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    digest = services.schedule_service.morning_digest(
        services.config.home_coords,
        services.config.school_coords,
    )
    await context.bot.send_message(
        chat_id=services.config.miron_id,
        text=digest,
    )
