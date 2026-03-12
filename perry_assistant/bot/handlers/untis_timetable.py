from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, ConversationHandler, ContextTypes

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.domain.models import UntisCredentials
from perry_assistant.services.untis_service import format_change_notification


logger = logging.getLogger(__name__)

# ConversationHandler states
UNTIS_ASK_USERNAME = 10
UNTIS_ASK_PASSWORD = 11
_MAX_MESSAGE_LEN = 3500
_MAX_CHANGE_LINES = 40


async def untis_setup(update: Update, context: CallbackContext) -> int:
    """Entry point: ask for Untis username."""
    if not update.message:
        return ConversationHandler.END
    await update.message.reply_text(
        "🏫 *Untis Setup*\n\nBitte gib deinen Untis-Benutzernamen ein:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return UNTIS_ASK_USERNAME


async def untis_setup_username(update: Update, context: CallbackContext) -> int:
    """Store username and ask for password."""
    if not update.message:
        return ConversationHandler.END
    if context.user_data is not None:
        context.user_data["untis_username"] = update.message.text.strip()
    await update.message.reply_text("🔑 Bitte gib dein Untis-Passwort ein:")
    return UNTIS_ASK_PASSWORD


async def untis_setup_password(update: Update, context: CallbackContext) -> int:
    """Store password, validate credentials, persist."""
    if not update.message or not update.effective_user:
        return ConversationHandler.END

    services = get_services(context)
    user_id = update.effective_user.id
    username = (context.user_data or {}).get("untis_username", "")
    password = update.message.text.strip()

    # Delete the password message for privacy
    try:
        await update.message.delete()
    except Exception:
        pass

    creds = UntisCredentials(
        server=services.config.untis_server,
        school=services.config.untis_school,
        username=username,
        password=password,
    )

    await update.effective_chat.send_message("⏳ Verbindung wird geprüft…")

    from perry_assistant.integrations.untis_client import UntisClient

    client = UntisClient(
        server=creds.server,
        school=creds.school,
        username=creds.username,
        password=creds.password,
    )
    valid = client.test_connection()

    if not valid:
        await update.effective_chat.send_message(
            "❌ Verbindung fehlgeschlagen. Bitte überprüfe Benutzernamen und Passwort und versuche "
            "/untis_setup erneut."
        )
        return ConversationHandler.END

    services.untis_service.save_credentials(user_id, creds)
    await update.effective_chat.send_message(
        "✅ Untis erfolgreich verbunden! Du erhältst ab jetzt Benachrichtigungen bei Änderungen."
    )
    logger.info("Untis credentials saved for user %s", user_id)
    return ConversationHandler.END


async def untis_status(update: Update, context: CallbackContext) -> None:
    """Show current Untis connection status and today's digest."""
    if not update.message or not update.effective_user:
        return
    services = get_services(context)
    user_id = update.effective_user.id

    if not services.untis_service.has_credentials(user_id):
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏫 Untis einrichten", callback_data="untis_setup")]]
        )
        await update.message.reply_text(
            "Du hast noch keinen Untis-Account verbunden.\nTippe /untis_setup um zu starten.",
            reply_markup=keyboard,
        )
        return

    try:
        changes = services.untis_service.refresh_user_timetable(user_id)
    except Exception:
        await update.message.reply_text(
            "⚠️ Konnte den Untis-Stundenplan gerade nicht abrufen. Bitte versuche es später erneut."
        )
        return

    digest = services.untis_service.daily_digest_for_user(user_id)
    if changes:
        change_lines = [format_change_notification(ch) for ch in changes]
        if len(change_lines) > _MAX_CHANGE_LINES:
            summary = _summarize_changes(changes)
            omitted = len(change_lines) - _MAX_CHANGE_LINES
            change_lines = (
                [summary]
                + change_lines[:_MAX_CHANGE_LINES]
                + [f"... {omitted} weitere Ã„nderungen ausgeblendet."]
            )
        text = "\n".join(change_lines + ["", digest])
    else:
        text = digest
    await _reply_with_chunks(update.message, text, parse_mode=ParseMode.MARKDOWN)


async def untis_disconnect(update: Update, context: CallbackContext) -> None:
    """Remove stored Untis credentials for user."""
    if not update.message or not update.effective_user:
        return
    services = get_services(context)
    user_id = update.effective_user.id
    removed = services.untis_service.delete_credentials(user_id)
    if removed:
        await update.message.reply_text("✅ Deine Untis-Verbindung wurde getrennt.")
    else:
        await update.message.reply_text("Du hattest keine Untis-Verbindung.")


async def untis_setup_callback(update: Update, context: CallbackContext) -> int:
    """Handle inline button 'untis_setup' – enters the ConversationHandler."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    await query.message.reply_text(
        "🏫 *Untis Setup*\n\nBitte gib deinen Untis-Benutzernamen ein:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return UNTIS_ASK_USERNAME


# ---------------------------------------------------------------------------
# Background job: check all users for timetable changes
# ---------------------------------------------------------------------------

async def check_timetable_changes_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic job that checks all registered users for timetable changes and
    sends Telegram notifications.
    """
    services = context.application.bot_data["services"]
    logger.debug("Untis timetable check triggered")

    try:
        changes_by_user = services.untis_service.check_all_users_for_changes()
    except Exception as exc:
        logger.error("Untis global check failed: %s", exc)
        return

    for user_id, changes in changes_by_user.items():
        msgs = [format_change_notification(ch) for ch in changes]
        if not msgs:
            continue
        if len(msgs) > _MAX_CHANGE_LINES:
            summary = _summarize_changes(changes)
            omitted = len(msgs) - _MAX_CHANGE_LINES
            msgs = [summary] + msgs[:_MAX_CHANGE_LINES] + [f"... {omitted} weitere Ã„nderungen ausgeblendet."]
        text = "\n".join(msgs)
        try:
            await _send_with_chunks(context.bot, user_id, text, parse_mode=ParseMode.MARKDOWN)
        except Exception as exc:
            logger.warning("Failed to send Untis notification to %s: %s", user_id, exc)


def _split_message(text: str, max_len: int = _MAX_MESSAGE_LEN) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current = ""
    for line in lines:
        if not current:
            candidate = line
        else:
            candidate = current + "\n" + line
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > max_len:
            chunks.append(line[:max_len])
            line = line[max_len:]
        current = line
    if current:
        chunks.append(current)
    return chunks


async def _reply_with_chunks(message, text: str, parse_mode: str) -> None:
    for chunk in _split_message(text):
        await message.reply_text(chunk, parse_mode=parse_mode)


async def _send_with_chunks(bot, chat_id: int, text: str, parse_mode: str) -> None:
    for chunk in _split_message(text):
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)


def _summarize_changes(changes) -> str:
    counts: dict[str, int] = {}
    for ch in changes:
        counts[ch.change_type] = counts.get(ch.change_type, 0) + 1
    parts: list[str] = []
    if counts.get("cancelled"):
        parts.append(f"âŒ {counts['cancelled']} entfallen")
    if counts.get("restored"):
        parts.append(f"âœ… {counts['restored']} wieder da")
    if counts.get("irregular"):
        parts.append(f"âš ï¸ {counts['irregular']} Vertretung")
    if counts.get("new_exam"):
        parts.append(f"ðŸ“ {counts['new_exam']} PrÃ¼fung")
    if counts.get("modified"):
        parts.append(f"ðŸ”„ {counts['modified']} geÃ¤ndert")
    if not parts:
        return "â„¹ï¸ Ã„nderungen vorhanden."
    return "â„¹ï¸ Ã„nderungen: " + ", ".join(parts)
