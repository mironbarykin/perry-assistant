from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.bot.keyboards import build_main_keyboard
from perry_assistant.bot.handlers.common import get_services
from perry_assistant.storage.json_store import read_json


PUBLISH_STATE = 200

PUBLISH_TARGET_PARENTS = "parents"
PUBLISH_TARGET_UNTIS = "untis"

@require_admin
async def parents(update: Update, context: CallbackContext) -> None:
    services = get_services(context)

    parent_ids = read_json(services.config.parents_file, [])
    if not parent_ids:
        await update.message.reply_text("No parent subscribers yet.")
        return
    await update.message.reply_text("Parent subscribers:\n" + "\n".join(f"- {item}" for item in parent_ids))

@require_admin
async def published_start(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    args = context.args or []
    if not args or args[0] not in (PUBLISH_TARGET_PARENTS, PUBLISH_TARGET_UNTIS):
        await update.message.reply_text(
            "Usage: /published parents  or  /published untis"
        )
        return ConversationHandler.END

    target = args[0]
    context.user_data["publish_target"] = target
    await update.message.reply_text(
        f"Send your next message. It will be published to all {target}."
    )
    return PUBLISH_STATE

@require_admin
async def published_send(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    services = get_services(context)
    target = context.user_data.get("publish_target", PUBLISH_TARGET_PARENTS)

    if target == PUBLISH_TARGET_UNTIS:
        users = read_json(services.config.untis_users_file, {})
        recipient_ids = list(dict.fromkeys(int(uid) for uid in users.keys()))
    else:
        recipient_ids = read_json(services.config.parents_file, [])
        recipient_ids = list(dict.fromkeys(recipient_ids))

    recipient_ids = [rid for rid in recipient_ids if rid != services.config.miron_id]

    if not recipient_ids:
        await update.message.reply_text(f"No {target} subscribers found.")
        return ConversationHandler.END

    message_text = update.message.text
    sent_count = 0
    for recipient_id in recipient_ids:
        if target == PUBLISH_TARGET_UNTIS:
            reply_markup = build_main_keyboard(is_admin=False, is_parent=False)
        else:
            reply_markup = build_main_keyboard(is_admin=False, is_parent=True)
        try:
            await context.bot.send_message(
                chat_id=recipient_id,
                text=message_text,
                reply_markup=reply_markup,
            )
            sent_count += 1
        except Exception:
            continue

    await update.message.reply_text(f"Published to {sent_count} {target} subscriber(s).")
    return ConversationHandler.END

# TODO: ! Does not work apparently, check later...
def build_parent_game_notification(games_with_travel: list[dict]) -> str:
    """
    Build a parent-friendly game schedule notification with travel information.
    
    Each game dict should have:
    - date, time, home_team, away_team, hall (or gym alias)
    - Optional: travel_info (TravelResult object or dict) with car_leave_by, transit_departure, transit_arrival, transit_legs
    
    Returns formatted message for parent subscribers.
    """
    if not games_with_travel:
        return "No upcoming games scheduled."
    
    from perry_assistant.constants import GYM_ALIASES
    from datetime import datetime
    from perry_assistant.domain.models import TravelResult
    
    lines = ["📅 UPCOMING GAMES WITH TRANSPORT INFO\n"]
    
    for game in games_with_travel:
        try:
            date_str = game.get("date", "?")
            time_str = game.get("time", "?")
            home = game.get("home_team", "?")
            away = game.get("away_team", "?")
            hall = game.get("hall", "?")
            
            # Use alias if available
            gym_display = GYM_ALIASES.get(hall, hall)
            
            lines.append(f"🏀 {date_str} {time_str}")
            lines.append(f"   {home} vs {away}")
            lines.append(f"   📍 {gym_display}")
            
            # Add travel info if available
            travel = game.get("travel_info")
            if travel:
                # Handle both TravelResult objects and dicts
                if isinstance(travel, TravelResult):
                    # Convert TravelResult to dict for consistent access
                    if travel.car_leave_by:
                        leave_time = travel.car_leave_by.strftime("%H:%M") if hasattr(travel.car_leave_by, 'strftime') else str(travel.car_leave_by)
                        lines.append(f"   🚗 Los: {leave_time}")
                    
                    if travel.transit_departure:
                        depart_time = travel.transit_departure.strftime("%H:%M") if hasattr(travel.transit_departure, 'strftime') else str(travel.transit_departure)
                        if travel.transit_legs:
                            legs_preview = " → ".join(travel.transit_legs[:2])
                            lines.append(f"   🚆 {depart_time}: {legs_preview}")
                        else:
                            lines.append(f"   🚆 {depart_time}")
                    
                    if travel.transit_arrival:
                        arrival_time = travel.transit_arrival.strftime("%H:%M") if hasattr(travel.transit_arrival, 'strftime') else str(travel.transit_arrival)
                        lines.append(f"   ✅ Arrive: {arrival_time}")
                else:
                    # Handle dict format
                    if travel.get("car_leave_by"):
                        leave_val = travel.get("car_leave_by")
                        leave_time = leave_val.strftime("%H:%M") if hasattr(leave_val, 'strftime') else str(leave_val)
                        lines.append(f"   🚗 Los: {leave_time}")
                    
                    if travel.get("transit_departure"):
                        depart_val = travel.get("transit_departure")
                        depart_time = depart_val.strftime("%H:%M") if hasattr(depart_val, 'strftime') else str(depart_val)
                        transit_legs = travel.get("transit_legs", [])
                        if transit_legs:
                            legs_preview = " → ".join(transit_legs[:2])
                            lines.append(f"   🚆 {depart_time}: {legs_preview}")
                        else:
                            lines.append(f"   🚆 {depart_time}")
                    
                    if travel.get("transit_arrival"):
                        arrival_val = travel.get("transit_arrival")
                        arrival_time = arrival_val.strftime("%H:%M") if hasattr(arrival_val, 'strftime') else str(arrival_val)
                        lines.append(f"   ✅ Arrive: {arrival_time}")
            
            lines.append("")
        except (KeyError, AttributeError, TypeError):
            continue
    
    if len(lines) == 1:
        return "No games with complete information."
    
    return "\n".join(lines)

