from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import CallbackContext, ContextTypes
from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.keyboards import build_schedule_keyboard

async def schedule_menu(update: Update, context: CallbackContext) -> None:
    if update.message:
        await update.message.reply_text("Choose a weekend:", reply_markup=build_schedule_keyboard())

async def this_weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    user = update.effective_user
    is_admin = user and user.id == services.config.miron_id
    now = dt.datetime.now(dt.UTC)
    saturday = now + dt.timedelta((5 - now.weekday()) % 7)
    sunday = saturday + dt.timedelta(days=1)
    sat_events = services.schedule_service.today_message(user.id if user else 0, is_admin=is_admin)
    sun_events = services.schedule_service.today_message(user.id if user else 0, is_admin=is_admin)
    sat_events = services.schedule_service.day_events_text(saturday, label="Saturday")
    sun_events = services.schedule_service.day_events_text(sunday, label="Sunday")
    try:
        await update.message.reply_text(f"Saturday:\n{sat_events}\n\nSunday:\n{sun_events}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(f"Saturday:\n{sat_events}\n\nSunday:\n{sun_events}")

async def next_weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    user = update.effective_user
    is_admin = user and user.id == services.config.miron_id
    now = dt.datetime.now(dt.UTC)
    saturday = now + dt.timedelta((5 - now.weekday()) % 7 + 7)
    sunday = saturday + dt.timedelta(days=1)
    sat_events = services.schedule_service.day_events_text(saturday, label="Saturday")
    sun_events = services.schedule_service.day_events_text(sunday, label="Sunday")
    try:
        await update.message.reply_text(f"Saturday:\n{sat_events}\n\nSunday:\n{sun_events}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(f"Saturday:\n{sat_events}\n\nSunday:\n{sun_events}")

async def other_weekend(update: Update, context: CallbackContext) -> None:
    if update.message:
        await update.message.reply_text("Please specify the date (feature not implemented yet).", reply_markup=build_schedule_keyboard())

async def today(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    user = update.effective_user
    is_admin = user and user.id == services.config.miron_id
    text = services.schedule_service.today_message(user.id if user else 0, is_admin=is_admin)
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


async def tomorrow(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    text = services.schedule_service.tomorrow_message()
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


async def weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    text = services.schedule_service.weekend_message()
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


async def morning(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    digest = services.schedule_service.morning_digest(
        services.config.home_coords,
        services.config.school_coords,
    )
    if update.message:
        try:
            await update.message.reply_text(digest, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(digest)


async def send_daily_notification_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    chat_id = context.job.chat_id
    message = services.schedule_service.today_message()
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
        )
    except Exception:
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
    try:
        await context.bot.send_message(
            chat_id=services.config.miron_id,
            text=digest,
            parse_mode="Markdown",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=services.config.miron_id,
            text=digest,
        )
