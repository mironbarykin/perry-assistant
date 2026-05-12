from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.keyboards import (
    build_main_keyboard,
    build_parent_keyboard,
    build_referee_menu_keyboard,
    build_schedule_keyboard,
    build_tracker_menu_keyboard,
)
from perry_assistant.domain.types import AppServices
from perry_assistant.storage.json_store import read_json


SET_TIME_STATE = 1


def get_services(context: CallbackContext) -> AppServices:
    return context.application.bot_data["services"]


def _is_admin(user_id: int, services: AppServices) -> bool:
    return user_id == services.config.miron_id


def _is_parent(user_id: int, services: AppServices) -> bool:
    parents = read_json(services.config.parents_file, [])
    return user_id in parents


def _is_admin_or_parent(user_id: int, services: AppServices) -> bool:
    return _is_admin(user_id, services) or _is_parent(user_id, services)


async def _require_admin_or_parent(update: Update, context: CallbackContext) -> bool:
    """Return True if user is admin or parent; reply with error and return False otherwise."""
    if not update.message or not update.effective_user:
        return False
    services = get_services(context)
    if _is_admin_or_parent(update.effective_user.id, services):
        return True
    await update.message.reply_text("Access denied.")
    return False


async def _require_not_parent(update: Update, context: CallbackContext) -> bool:
    """Return True for admin and non-parent users; block parents."""
    if not update.message or not update.effective_user:
        return False
    services = get_services(context)
    if not _is_parent(update.effective_user.id, services):
        return True
    await update.message.reply_text("This feature is not available.")
    return False


async def start(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    user = update.effective_user
    if not user or not update.message:
        return

    admin = _is_admin(user.id, services)
    parent = _is_parent(user.id, services)

    # Admins and pre-registered parents get the full command menu
    if admin or parent:
        command_text = "Commands: /today /tomorrow /weekend"
        if admin:
            command_text += " /absence /absences /excused /excuse /published /setweatherloc /weatherloc /games"
        keyboard = build_main_keyboard(is_admin=admin, is_parent=parent)
        await update.message.reply_text(
            (
                "Welcome to Perry.\n"
                "Use /settime to configure daily notifications.\n"
                f"{command_text}"
            ),
            reply_markup=keyboard,
        )
        return

    # New / unknown users: welcoming onboarding message with Untis setup button
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    has_untis = services.untis_service.has_credentials(user.id)
    if has_untis:
        await update.message.reply_text(
            "👋 Hi! Ich bin Perry.\n\n"
            "Dein Untis-Account ist bereits verbunden.\n"
            "Nutze /untis_status für den aktuellen Stundenplan oder "
            "/untis_setup um deine Zugangsdaten zu aktualisieren.",
        )
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏫 Untis einrichten", callback_data="untis_setup")]]
        )
        await update.message.reply_text(
            "👋 Hi! Ich bin Perry.\n\n"
            "Ich kann deinen Untis-Stundenplan im Auge behalten und dich "
            "benachrichtigen, wenn sich etwas ändert – damit du weißt, ob du "
            "wirklich in die Schule musst 😉\n\n"
            "Tippe unten auf den Button oder /untis_setup, um loszulegen!",
            reply_markup=keyboard,
        )


async def settime(update: Update, context: CallbackContext) -> int:
    if not await _require_admin_or_parent(update, context):
        return ConversationHandler.END
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
    is_admin = bool(user and _is_admin(user.id, services))
    is_parent = bool(user and _is_parent(user.id, services))

    # Admin-only buttons
    if text in {
        "ABSENCES",
        "EXCUSABLE TODAY",
        "ALL ABSENCES",
        "EXCUSED ABSENCES",
        "I AM ABSENT",
        "REFEREE",
        "EMAILS",
        "UPORTAL",
        "GAMES",
        "TRACKER",
        "SHOWER",
        "FAP"
    } and not is_admin:
        await update.message.reply_text("Access denied. Admin only.")
        return

    # Non-untis buttons require admin or parent
    if text in {
        "TODAY",
        "SCHEDULE",
        "THIS WEEKEND",
        "NEXT WEEKEND",
        "OTHER DATE",
        "BACK",
    } and not is_admin and not is_parent:
        await update.message.reply_text("Access denied.")
        return

    # Untis buttons are not available for parents
    if text == "UNTIS" and is_parent:
        await update.message.reply_text("This feature is not available.")
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

    if text == "EXCUSED ABSENCES":
        from perry_assistant.bot.handlers.absences import absences_excused

        await absences_excused(update, context)
        return

    if text == "I AM ABSENT":
        from perry_assistant.bot.handlers.absences import absences_absent

        await absences_absent(update, context)
        return

    if text == "SCHEDULE":
        await update.message.reply_text("OK", reply_markup=build_schedule_keyboard())
        return

    if text == "REFEREE":
        await update.message.reply_text("OK", reply_markup=build_referee_menu_keyboard())
        return

    if text == "TODAY":
        from perry_assistant.bot.handlers.schedule import today

        await today(update, context)
        return

    if text == "TOMORROW":
        from perry_assistant.bot.handlers.schedule import tomorrow

        await tomorrow(update, context)
        return

    if text == "THIS WEEKEND":
        from perry_assistant.bot.handlers.schedule import this_weekend

        await this_weekend(update, context)
        return

    if text == "NEXT WEEKEND":
        from perry_assistant.bot.handlers.schedule import next_weekend

        await next_weekend(update, context)
        return

    if text == "OTHER DATE":
        from perry_assistant.bot.handlers.schedule import other_date_start

        await other_date_start(update, context)
        return

    if text == "EMAILS":
        from perry_assistant.bot.handlers.referee import emails

        await emails(update, context)
        return

    if text == "UPORTAL":
        from perry_assistant.bot.handlers.uportal import uportal

        await uportal(update, context)
        return

    if text == "GAMES":
        from perry_assistant.bot.handlers.game_messages import games

        await games(update, context)
        return

    if text == "BACK":
        await update.message.reply_text("OK", reply_markup=build_main_keyboard(is_admin=is_admin, is_parent=is_parent))
        return

    if text == "UNTIS":
        from perry_assistant.bot.handlers.untis_timetable import untis_status

        await untis_status(update, context)
        return

    if text == "TRACKER":
        await update.message.reply_text("OK", reply_markup=build_tracker_menu_keyboard())
        return
    
    if text == "SHOWER":
        from perry_assistant.bot.handlers.trackers import shower

        await shower(update, context)
        return
    
    if text == "FAP":
        from perry_assistant.bot.handlers.trackers import fap

        await fap(update, context)
        return
