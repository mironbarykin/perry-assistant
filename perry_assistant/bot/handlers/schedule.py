from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import CallbackContext, ContextTypes
from telegram.constants import ParseMode

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.keyboards import build_schedule_keyboard


def _is_admin_user(update: Update, admin_id: int) -> bool:
    user = update.effective_user
    return bool(user and user.id == admin_id)


async def this_weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    is_admin = _is_admin_user(update, services.config.miron_id)
    now = dt.datetime.now(dt.UTC)
    saturday = now + dt.timedelta((5 - now.weekday()) % 7)
    sunday = saturday + dt.timedelta(days=1)

    sat_events = services.schedule_service.day_events_text(
        saturday,
        label="Saturday",
        is_admin=is_admin,
    )
    sun_events = services.schedule_service.day_events_text(
        sunday,
        label="Sunday",
        is_admin=is_admin,
    )
    await _reply_markdown(update, f"{sat_events}\n\n{sun_events}")


async def next_weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    is_admin = _is_admin_user(update, services.config.miron_id)
    now = dt.datetime.now(dt.UTC)
    saturday = now + dt.timedelta((5 - now.weekday()) % 7 + 7)
    sunday = saturday + dt.timedelta(days=1)

    sat_events = services.schedule_service.day_events_text(
        saturday,
        label="Saturday",
        is_admin=is_admin,
    )
    sun_events = services.schedule_service.day_events_text(
        sunday,
        label="Sunday",
        is_admin=is_admin,
    )
    await _reply_markdown(update, f"{sat_events}\n\n{sun_events}")


async def other_weekend(update: Update, context: CallbackContext) -> None:
    if update.message:
        await update.message.reply_text(
            "Please specify the date (feature not implemented yet).",
            reply_markup=build_schedule_keyboard(),
        )


async def today(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    is_admin = _is_admin_user(update, services.config.miron_id)
    await _reply_markdown(update, services.schedule_service.today_message(is_admin=is_admin))


async def tomorrow(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    is_admin = _is_admin_user(update, services.config.miron_id)
    await _reply_markdown(update, services.schedule_service.tomorrow_message(is_admin=is_admin))


async def weekend(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    is_admin = _is_admin_user(update, services.config.miron_id)
    await _reply_markdown(update, services.schedule_service.weekend_message(is_admin=is_admin))


async def morning(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    services = get_services(context)
    current_coords, _ = services.weather_location_service.resolve_current_location(services.config.home_coords)
    location_city_label = services.weather_location_service.location_city_label(fallback="home")
    usage_line = services.stats_service.yesterday_usage_line()
    digest = services.schedule_service.morning_digest(
        services.config.home_coords,
        services.config.school_coords,
        current_coords=current_coords,
        location_city_label=location_city_label,
        yesterday_usage_line=usage_line,
    )
    await _reply_markdown(update, digest)


async def send_daily_notification_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    chat_id = context.job.chat_id
    is_admin = chat_id == services.config.miron_id
    message = services.schedule_service.today_message(is_admin=is_admin)
    await _send_markdown(context, chat_id=chat_id, text=message)


async def send_morning_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    current_coords, _ = services.weather_location_service.resolve_current_location(services.config.home_coords)
    location_city_label = services.weather_location_service.location_city_label(fallback="home")
    usage_line = services.stats_service.yesterday_usage_line()
    digest = services.schedule_service.morning_digest(
        services.config.home_coords,
        services.config.school_coords,
        current_coords=current_coords,
        location_city_label=location_city_label,
        yesterday_usage_line=usage_line,
    )
    await _send_markdown(context, chat_id=services.config.miron_id, text=digest)


async def _reply_markdown(update: Update, text: str) -> None:
    if not update.message:
        return
    try:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(text)


async def _send_markdown(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=text)

