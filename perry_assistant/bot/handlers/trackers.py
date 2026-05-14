from __future__ import annotations

import csv
import datetime as dt
import json
import logging
from enum import IntEnum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.constants import BERLIN_TZ


logger = logging.getLogger(__name__)

TRACKER_DATA_KEY = "tracker_data"
TRACKER_STATE_KEY = "tracker_state"

CSV_FAP_COLUMNS = [
    "captured_at_utc",
    "happened_at_utc",
    "duration_min",
    "location_label",
    "sources_json",
]

CSV_SHOWER_COLUMNS = [
    "captured_at_utc",
    "happened_at_utc",
    "duration_min",
    "location_label",
    "temperature_label",
    "products_used_json",
]

WHEN_LABELS = {
    "now": "Just now",
    "today": "Today",
    "other": "Other",
}

FAP_LOCATION_LABELS = {
    "bedroom": "Bedroom",
    "bathroom": "Bathroom",
    "other": "Other",
}

FAP_SOURCES_OPTIONS = {
    "none": "None",
    "device": "Device",
    "lubricant": "Lubricant",
    "videos": "Videos",
    "social media": "Social Media",
    "written_stories": "Written Stories",
    "other": "Other",
}

SHOWER_LOCATION_LABELS = {
    "home": "Home",
    "school": "School",
    "gym": "Gym",
    "other": "Other",
}

SHOWER_TEMPERATURE_LABELS = {
    "cold": "Cold",
    "warm": "Warm",
    "contrast": "Contrast",
    "other": "Other",
}

SHOWER_PRODUCTS_OPTIONS = {
    "shampoo": "Shampoo",
    "conditioner": "Conditioner",
    "gel": "Gel",
    "face_cleanser": "Face Cleanser",
    "other": "Other",
}


class TrackerState(IntEnum):
    CHOOSE_TYPE = 1
    CHOOSE_WHEN = 2
    CHOOSE_LOCATION = 3
    INPUT_DURATION = 4
    CHOOSE_TEMPERATURE = 5
    CHOOSE_SOURCES = 7


def _is_admin(update: Update, admin_id: int) -> bool:
    user = update.effective_user
    return bool(user and user.id == admin_id)


def _tracker_data(context: CallbackContext) -> dict[str, object]:
    if context.user_data is None:
        context.user_data = {}
    data = context.user_data.get(TRACKER_DATA_KEY)
    if not isinstance(data, dict):
        data = {}
        context.user_data[TRACKER_DATA_KEY] = data
    return data


def _tracker_state(context: CallbackContext) -> int | None:
    if context.user_data is None:
        return None
    state = context.user_data.get(TRACKER_STATE_KEY)
    return int(state) if isinstance(state, int) else None


def _set_tracker_state(context: CallbackContext, state: int | None) -> None:
    if context.user_data is None:
        context.user_data = {}
    if state is None:
        context.user_data.pop(TRACKER_STATE_KEY, None)
    else:
        context.user_data[TRACKER_STATE_KEY] = state


async def _clear_tracker(context: CallbackContext) -> None:
    if context.user_data is None:
        return
    data = context.user_data.pop(TRACKER_DATA_KEY, None)
    _set_tracker_state(context, None)
    if isinstance(data, dict):
        for key in (
            "when_prompt_message",
            "location_prompt_message",
            "duration_prompt_message",
            "temperature_prompt_message",
            "products_prompt_message",
        ):
            await _delete_message(data.get(key))

@require_admin
async def shower(update: Update, context: CallbackContext) -> int:
    services = get_services(context)

    data = _tracker_data(context)
    data.clear()
    data["type"] = "shower"
    data["products"] = []
    _set_tracker_state(context, TrackerState.CHOOSE_WHEN.value)

    if update.message:
        prompt = await update.message.reply_text(
            "When did you do it?",
            reply_markup=_build_when_keyboard(),
        )
        data["when_prompt_message"] = prompt
    return TrackerState.CHOOSE_WHEN.value


@require_admin
async def fap(update: Update, context: CallbackContext) -> int:
    services = get_services(context)

    data = _tracker_data(context)
    data.clear()
    data["type"] = "fap"
    data["products"] = []
    _set_tracker_state(context, TrackerState.CHOOSE_WHEN.value)

    if update.message:
        prompt = await update.message.reply_text(
            "When did you do it?",
            reply_markup=_build_when_keyboard(),
        )
        data["when_prompt_message"] = prompt
    return TrackerState.CHOOSE_WHEN.value


async def cancel_tracker(update: Update, context: CallbackContext) -> int:
    await _clear_tracker(context)
    return TrackerState.CHOOSE_WHEN.value


async def dispatch_text(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    state = _tracker_state(context)
    if state == TrackerState.INPUT_DURATION.value:
        await _input_duration(update, context)
        return

    text = update.message.text.strip().upper()
    if text == "SHOWER":
        await shower(update, context)
        return
    if text == "FAP":
        await fap(update, context)
        return

    if state is not None:
        await update.message.reply_text("Use the buttons below or /cancel.")
        return

    from perry_assistant.bot.handlers.common import button_handler

    await button_handler(update, context)


async def dispatch_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    if query.data.startswith("when_"):
        await _choose_when(update, context)
        return
    if query.data.startswith("loc_"):
        await _choose_location(update, context)
        return
    if query.data.startswith("temp_"):
        await _choose_temperature(update, context)
        return
    if query.data.startswith("prod_"):
        await _choose_sources(update, context)


async def _choose_when(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if not query or not query.data:
        return TrackerState.CHOOSE_WHEN.value

    services = get_services(context)
    if update.effective_user and not _is_admin(update, services.config.miron_id):
        await query.answer("Admin only.", show_alert=True)
        return TrackerState.CHOOSE_WHEN.value

    if _tracker_state(context) != TrackerState.CHOOSE_WHEN.value:
        await query.answer()
        return TrackerState.CHOOSE_WHEN.value

    await query.answer()
    when_key = query.data.removeprefix("when_")
    data = _tracker_data(context)
    data["when"] = when_key
    await _delete_message(query.message)
    if query.message:
        tracker_type = str(data.get("type", "shower"))
        prompt = await query.message.reply_text(
            "Where?",
            reply_markup=_build_location_keyboard(tracker_type),
        )
        data["location_prompt_message"] = prompt
    _set_tracker_state(context, TrackerState.CHOOSE_LOCATION.value)
    return TrackerState.CHOOSE_LOCATION.value


async def _choose_location(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if not query or not query.data:
        return TrackerState.CHOOSE_LOCATION.value

    services = get_services(context)
    if update.effective_user and not _is_admin(update, services.config.miron_id):
        await query.answer("Admin only.", show_alert=True)
        return TrackerState.CHOOSE_LOCATION.value

    if _tracker_state(context) != TrackerState.CHOOSE_LOCATION.value:
        await query.answer()
        return TrackerState.CHOOSE_LOCATION.value

    await query.answer()
    location_key = query.data.removeprefix("loc_")
    data = _tracker_data(context)
    data["location"] = location_key
    await _delete_message(query.message)
    if query.message:
        prompt = await query.message.reply_text("How long? (minutes)")
        data["duration_prompt_message"] = prompt
    _set_tracker_state(context, TrackerState.INPUT_DURATION.value)
    return TrackerState.INPUT_DURATION.value


async def _input_duration(update: Update, context: CallbackContext) -> int:
    if not update.message or not update.effective_user:
        return TrackerState.INPUT_DURATION.value

    services = get_services(context)
    if not _is_admin(update, services.config.miron_id):
        await update.message.reply_text("Admin only.")
        await _clear_tracker(context)
        return TrackerState.INPUT_DURATION.value

    if _tracker_state(context) != TrackerState.INPUT_DURATION.value:
        return TrackerState.INPUT_DURATION.value

    try:
        duration_min = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send the duration in minutes as a number.")
        return TrackerState.INPUT_DURATION.value

    if duration_min <= 0:
        await update.message.reply_text("Please send the duration in minutes as a positive number.")
        return TrackerState.INPUT_DURATION.value

    data = _tracker_data(context)
    await _delete_message(data.pop("duration_prompt_message", None))
    data["duration_min"] = duration_min
    tracker_type = str(data.get("type", "shower"))

    if tracker_type == "shower":
        _set_tracker_state(context, TrackerState.CHOOSE_TEMPERATURE.value)
        if update.message:
            prompt = await update.message.reply_text(
                "Select temperature:",
                reply_markup=_build_temperature_keyboard(),
            )
            data["temperature_prompt_message"] = prompt
        return TrackerState.CHOOSE_TEMPERATURE.value

    _set_tracker_state(context, TrackerState.CHOOSE_SOURCES.value)
    if update.message:
        prompt = await update.message.reply_text(
            "Select sources:",
            reply_markup=_build_sources_keyboard([], tracker_type),
        )
        data["products_prompt_message"] = prompt
    return TrackerState.CHOOSE_SOURCES.value


async def _choose_temperature(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if not query or not query.data:
        return TrackerState.CHOOSE_TEMPERATURE.value

    services = get_services(context)
    if update.effective_user and not _is_admin(update, services.config.miron_id):
        await query.answer("Admin only.", show_alert=True)
        return TrackerState.CHOOSE_TEMPERATURE.value

    if _tracker_state(context) != TrackerState.CHOOSE_TEMPERATURE.value:
        await query.answer()
        return TrackerState.CHOOSE_TEMPERATURE.value

    await query.answer()
    temperature_key = query.data.removeprefix("temp_")
    if temperature_key not in SHOWER_TEMPERATURE_LABELS:
        await query.answer("Invalid selection.", show_alert=True)
        return TrackerState.CHOOSE_TEMPERATURE.value

    data = _tracker_data(context)
    data["temperature"] = temperature_key
    await _delete_message(query.message)
    _set_tracker_state(context, TrackerState.CHOOSE_SOURCES.value)
    if query.message:
        tracker_type = "shower"
        prompt = await query.message.reply_text(
            "Select products:",
            reply_markup=_build_sources_keyboard(_selected_products(data), tracker_type),
        )
        data["products_prompt_message"] = prompt
    return TrackerState.CHOOSE_SOURCES.value


async def _choose_sources(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    if not query or not query.data:
        return TrackerState.CHOOSE_SOURCES.value

    services = get_services(context)
    if update.effective_user and not _is_admin(update, services.config.miron_id):
        await query.answer("Admin only.", show_alert=True)
        return TrackerState.CHOOSE_SOURCES.value

    if _tracker_state(context) != TrackerState.CHOOSE_SOURCES.value:
        await query.answer()
        return TrackerState.CHOOSE_SOURCES.value

    data = _tracker_data(context)
    tracker_type = str(data.get("type", "shower"))
    if query.data == "prod_done":
        await query.answer()
        await _delete_message(query.message)
        await _save_entry(update, context)
        await _clear_tracker(context)
        return TrackerState.CHOOSE_SOURCES.value

    product_key = query.data.removeprefix("prod_")
    valid_keys = SHOWER_PRODUCTS_OPTIONS if tracker_type == "shower" else FAP_SOURCES_OPTIONS
    if product_key not in valid_keys:
        await query.answer("Invalid selection.", show_alert=False)
        return TrackerState.CHOOSE_SOURCES.value

    products = _selected_products(data)
    if product_key in products:
        products.remove(product_key)
    else:
        products.append(product_key)
    data["products"] = products

    await query.answer()
    prompt_message = query.message
    if prompt_message and hasattr(prompt_message, "edit_text"):
        await prompt_message.edit_text(
            _products_prompt_text(products, tracker_type),
            reply_markup=_build_sources_keyboard(products, tracker_type),
        )
    elif prompt_message:
        await _delete_message(prompt_message)
        new_prompt = await prompt_message.reply_text(
            _products_prompt_text(products, tracker_type),
            reply_markup=_build_sources_keyboard(products, tracker_type),
        )
        data["products_prompt_message"] = new_prompt
    return TrackerState.CHOOSE_SOURCES.value


async def _save_entry(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    data = _tracker_data(context)
    now_local = dt.datetime.now(BERLIN_TZ)
    now_utc = now_local.astimezone(dt.UTC)
    tracker_type = str(data.get("type", "shower"))
    products = _selected_products(data)

    if tracker_type == "shower":
        location_key = str(data.get("location", "other"))
        location_label = SHOWER_LOCATION_LABELS.get(location_key, location_key.title())
        temperature_key = str(data.get("temperature", ""))
        temperature_label = SHOWER_TEMPERATURE_LABELS.get(temperature_key, "")
        row = {
            "captured_at_utc": now_utc.isoformat(),
            "happened_at_utc": now_utc.isoformat(),
            "duration_min": str(int(data.get("duration_min", 0))),
            "location_label": location_label,
            "temperature_label": temperature_label,
            "products_used_json": json.dumps(products, ensure_ascii=False),
        }
        csv_columns = CSV_SHOWER_COLUMNS
    else:
        location_key = str(data.get("location", "other"))
        location_label = FAP_LOCATION_LABELS.get(location_key, location_key.title())
        row = {
            "captured_at_utc": now_utc.isoformat(),
            "happened_at_utc": now_utc.isoformat(),
            "duration_min": str(int(data.get("duration_min", 0))),
            "location_label": location_label,
            "sources_json": json.dumps(products, ensure_ascii=False),
        }
        csv_columns = CSV_FAP_COLUMNS

    csv_filename = f"tracker_{tracker_type}_entries.csv"
    csv_path = services.config.data_dir / csv_filename
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        if is_new_file:
            writer.writeheader()
        writer.writerow(row)

    reply_message = getattr(update, "message", None)
    if reply_message is None and update.callback_query:
        reply_message = update.callback_query.message

    if reply_message:
        if tracker_type == "shower":
            location_label = SHOWER_LOCATION_LABELS.get(str(data.get("location", "other")), "Unknown")
            temperature_label = SHOWER_TEMPERATURE_LABELS.get(str(data.get("temperature", "")), "")
            lines = [
                f"✅ Logged - Shower",
                f"📍 {location_label}",
                f"⏰ {now_local.strftime('%H:%M')}",
                f"⌛ {row['duration_min']} min",
            ]
            if temperature_label:
                lines.append(f"🌡️ {temperature_label}")
            if products:
                lines.append(f"📝 {', '.join(products)}")
        else:
            location_label = FAP_LOCATION_LABELS.get(str(data.get("location", "other")), "Unknown")
            lines = [
                f"✅ Logged - Fap",
                f"📍 {location_label}",
                f"⏰ {now_local.strftime('%H:%M')}",
                f"⌛ {row['duration_min']} min",
            ]
            if products:
                lines.append(f"📝 {', '.join(products)}")
        await reply_message.reply_text("\n".join(lines))


def _selected_products(data: dict[str, object]) -> list[str]:
    products = data.get("products", [])
    if not isinstance(products, list):
        return []
    tracker_type = data.get("type", "shower")
    valid_keys = SHOWER_PRODUCTS_OPTIONS if tracker_type == "shower" else FAP_SOURCES_OPTIONS
    return [str(item) for item in products if str(item) in valid_keys]


def _build_when_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(WHEN_LABELS["now"], callback_data="when_now")],
            [InlineKeyboardButton(WHEN_LABELS["today"], callback_data="when_today")],
            [InlineKeyboardButton(WHEN_LABELS["other"], callback_data="when_other")],
        ]
    )


def _build_location_keyboard(tracker_type: str = "shower") -> InlineKeyboardMarkup:
    if tracker_type == "fap":
        locations = FAP_LOCATION_LABELS
        keys = ["bedroom", "bathroom", "other"]
    else:
        locations = SHOWER_LOCATION_LABELS
        keys = ["home", "school", "gym", "other"]
    
    rows = [[InlineKeyboardButton(locations[key], callback_data=f"loc_{key}")] for key in keys]
    return InlineKeyboardMarkup(rows)


def _build_temperature_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(SHOWER_TEMPERATURE_LABELS["cold"], callback_data="temp_cold")],
            [InlineKeyboardButton(SHOWER_TEMPERATURE_LABELS["warm"], callback_data="temp_warm")],
            [InlineKeyboardButton(SHOWER_TEMPERATURE_LABELS["contrast"], callback_data="temp_contrast")],
            [InlineKeyboardButton(SHOWER_TEMPERATURE_LABELS["other"], callback_data="temp_other")],
        ]
    )


def _build_sources_keyboard(selected: list[str], tracker_type: str = "shower") -> InlineKeyboardMarkup:
    selected_set = set(selected)
    rows = []
    options = SHOWER_PRODUCTS_OPTIONS if tracker_type == "shower" else FAP_SOURCES_OPTIONS
    for key, label in options.items():
        display = f"✅ {label}" if key in selected_set else label
        rows.append([InlineKeyboardButton(display, callback_data=f"prod_{key}")])
    rows.append([InlineKeyboardButton("✅ Done", callback_data="prod_done")])
    return InlineKeyboardMarkup(rows)


def _products_prompt_text(selected: list[str], tracker_type: str = "shower") -> str:
    if not selected:
        prompt = "Select products:" if tracker_type == "shower" else "Select sources:"
        return prompt
    options = SHOWER_PRODUCTS_OPTIONS if tracker_type == "shower" else FAP_SOURCES_OPTIONS
    labels = [options[key] for key in selected if key in options]
    prompt_prefix = "Select products:" if tracker_type == "shower" else "Select sources:"
    return f"{prompt_prefix} {', '.join(labels)}"


async def _delete_message(message: object | None) -> None:
    if not message or not hasattr(message, "delete"):
        return
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        logger.debug("Could not delete tracker message", exc_info=True)

