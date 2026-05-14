from __future__ import annotations

import datetime as dt
import html
import logging
import traceback

import telegram
from google.auth.exceptions import RefreshError
from telegram import Update
from telegram.ext import ContextTypes

from perry_assistant.bot.handlers.auth import send_auth_link_to_admin
from perry_assistant.constants import BERLIN_TZ


logger = logging.getLogger(__name__)


async def global_error_notify(
    update: object | Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    error: Exception,
) -> None:
    services = context.application.bot_data["services"]

    if isinstance(error, RefreshError):
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Google authentication expired. Admin has been notified.",
            )
        await send_auth_link_to_admin(context, "Google token expired.")
        return

    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    logger.error(tb)
    timestamp = dt.datetime.now(BERLIN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    user_name = "JobQueue"
    chat_id = None
    if isinstance(update, Update):
        user_name = getattr(update.effective_user, "username", "Unknown")
        chat_id = getattr(update.effective_chat, "id", None)

    safe_tb = html.escape(tb)
    admin_message = (
        f"Error during {user_name}\n"
        f"Timestamp: {timestamp}\n"
        f"<pre>{safe_tb}</pre>"
    )
    await context.bot.send_message(
        chat_id=services.config.miron_id,
        text=admin_message,
        parse_mode=telegram.constants.ParseMode.HTML,
    )
    if chat_id and chat_id != services.config.miron_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Your request failed and the admin was notified.",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = getattr(context, "error", None) or Exception("Unknown error")
    await global_error_notify(update, context, error)

