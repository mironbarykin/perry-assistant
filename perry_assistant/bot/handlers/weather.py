from __future__ import annotations

import datetime as dt

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.bot.handlers.helpers import parse_iso_datetime
from perry_assistant.bot.keyboards import build_main_keyboard
from perry_assistant.constants import BERLIN_TZ

@require_admin
async def setweatherloc(update: Update, context: CallbackContext) -> None:
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("Share current location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Share your current location. Perry will use the latest shared location until you update it again.",
        reply_markup=keyboard,
    )

@require_admin
async def weatherloc(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    location = services.weather_location_service.get_shared_location()
    if not location:
        await update.message.reply_text("No shared location saved yet. Use /setweatherloc.")
        return

    updated = _format_timestamp(location.updated_at)
    city_text = location.city or "-"
    await update.message.reply_text(
        (
            f"Current shared location:\n"
            f"lat={location.lat:.6f}, lon={location.lon:.6f}\n"
            f"City: {city_text}\n"
            f"Updated: {updated}"
        )
    )

@require_admin
async def receive_weather_location(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    loc = update.message.location
    city = services.weather_location_service.resolve_city_name(lat=loc.latitude, lon=loc.longitude)
    saved = services.weather_location_service.save_shared_location(
        lat=loc.latitude,
        lon=loc.longitude,
        user_id=update.effective_user.id,
        city=city,
    )
    await update.message.reply_text(
        (
            "Location updated.\n"
            f"lat={saved.lat:.6f}, lon={saved.lon:.6f}\n"
            f"City: {saved.city or '-'}\n"
            f"Updated: {_format_timestamp(saved.updated_at)}"
        ),
        reply_markup=build_main_keyboard(is_admin=True),
    )


def _format_timestamp(raw: str) -> str:
    parsed = parse_iso_datetime(raw, default_tz=dt.UTC)
    if parsed is None:
        return raw
    return parsed.astimezone(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
