from __future__ import annotations

import datetime as dt
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.bot.handlers.helpers import parse_iso_datetime
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.services.game_message_service import ParsedGameEvent


PICKER_STATE_KEY = "game_message_picker"
PICKER_CALLBACK_PREFIX = "gmsg:"
PICKER_TTL_HOURS = 6

@require_admin 
async def games(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    user = update.effective_user
    
    _cleanup_picker_state(context.application.bot_data)
    events = services.game_message_service.list_upcoming_games(days=7)
    if not events:
        await update.message.reply_text("No games found for the next 7 days.")
        return

    picker_id = uuid.uuid4().hex[:8]
    state = context.application.bot_data.setdefault(PICKER_STATE_KEY, {})
    state[picker_id] = {
        "owner_id": user.id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "events": [
            {"event_id": event.event_id, "start": event.start.isoformat(), "label": _event_button_label(event)}
            for event in events
        ],
    }

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=item["label"], callback_data=f"{PICKER_CALLBACK_PREFIX}{picker_id}:{idx}")]
            for idx, item in enumerate(state[picker_id]["events"])
        ]
    )
    await update.message.reply_text("Choose a game to generate draft messages:", reply_markup=keyboard)


@require_admin
async def select_game(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query:
        return

    services = get_services(context)
    user = update.effective_user

    data = query.data or ""
    if not data.startswith(PICKER_CALLBACK_PREFIX):
        await query.answer()
        return

    _, _, payload = data.partition(PICKER_CALLBACK_PREFIX)
    picker_id, sep, index_raw = payload.partition(":")
    if not sep:
        await query.answer("Invalid selection.", show_alert=False)
        return

    state = context.application.bot_data.get(PICKER_STATE_KEY, {})
    entry = state.get(picker_id) if isinstance(state, dict) else None
    if not isinstance(entry, dict):
        await query.answer("Selection expired. Use /games again.", show_alert=True)
        return
    if int(entry.get("owner_id", 0)) != user.id:
        await query.answer("Selection not available.", show_alert=True)
        return

    events = entry.get("events", [])
    try:
        index = int(index_raw)
    except ValueError:
        await query.answer("Invalid selection.", show_alert=False)
        return
    if not isinstance(events, list) or index < 0 or index >= len(events):
        await query.answer("Game not found. Use /games again.", show_alert=True)
        return

    selected = events[index] if isinstance(events[index], dict) else {}
    event_id = str(selected.get("event_id", "")).strip()
    event_start = str(selected.get("start", "")).strip()
    label = str(selected.get("label", "selected game")).strip()
    if not event_id:
        await query.answer("Game not found. Use /games again.", show_alert=True)
        return

    drafts = services.game_message_service.build_drafts_for_selected_game(
        event_id=event_id,
        start_iso=event_start,
    )
    if not drafts:
        await query.answer("No draft messages could be generated.", show_alert=False)
        return

    chat_id = update.effective_chat.id if update.effective_chat else services.config.miron_id
    await query.answer("Drafts generated.", show_alert=False)
    await context.bot.send_message(chat_id=chat_id, text=f"Drafts for {label}:")
    for draft in drafts:
        await context.bot.send_message(
            chat_id=chat_id,
            text=draft.text,
            disable_web_page_preview=True,
        )


def _cleanup_picker_state(bot_data: dict) -> None:
    state = bot_data.get(PICKER_STATE_KEY, {})
    if not isinstance(state, dict):
        bot_data[PICKER_STATE_KEY] = {}
        return

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=PICKER_TTL_HOURS)
    for key, entry in list(state.items()):
        if not isinstance(entry, dict):
            state.pop(key, None)
            continue
        created_raw = entry.get("created_at")
        if not isinstance(created_raw, str):
            state.pop(key, None)
            continue
        created = parse_iso_datetime(created_raw, default_tz=dt.UTC)
        if created is None:
            state.pop(key, None)
            continue
        if created < cutoff:
            state.pop(key, None)


def _event_button_label(event: ParsedGameEvent) -> str:
    start = event.start.astimezone(BERLIN_TZ)
    kind = "Ref" if event.category == "referee" else "Coach"
    subject = event.league if event.category == "referee" else (event.team or "Team")
    return f"{start.strftime('%a %d.%m %H:%M')} {kind} {subject}"[:64]
