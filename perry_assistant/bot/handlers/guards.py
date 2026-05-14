from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.storage.json_store import read_json

T = TypeVar("T")

ADMIN_DENIED_TEXT = "🫸You are not authorized to use this command. (Error: AL1)"
FAMILY_DENIED_TEXT = "🫸You are not authorized to use this command. (Error: AL2)"


def _response_message(update: Update):
    if getattr(update, "message", None):
        return update.message
    query = getattr(update, "callback_query", None)
    if query and getattr(query, "message", None):
        return query.message
    return None


async def _deny(update: Update, text: str, alert: bool = False) -> None:
    query = getattr(update, "callback_query", None)
    if query:
        try:
            await query.answer(text, show_alert=alert)
            return
        except Exception:
            pass

    message = _response_message(update)
    if message:
        await message.reply_text(text)


def _is_admin(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        return False
    services = get_services(context)
    return user.id == services.config.miron_id


def _is_family(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        return False

    services = get_services(context)
    if user.id == services.config.miron_id:
        return True

    parent_ids = read_json(services.config.parents_file, [])
    return user.id in parent_ids


def require_admin(handler):
    @wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        if not update.effective_user:
            return ConversationHandler.END
        if not _is_admin(update, context):
            await _deny(update, ADMIN_DENIED_TEXT, alert=True)
            return ConversationHandler.END
        return await handler(update, context, *args, **kwargs)
    return wrapper

def require_family(handler: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    @wraps(handler)
    async def wrapper(update: Update, context: CallbackContext, *args: Any, **kwargs: Any) -> T | None:
        if not update.effective_user:
            return None
        if not _is_family(update, context):
            await _deny(update, FAMILY_DENIED_TEXT, alert=True)
            return None
        return await handler(update, context, *args, **kwargs)

    return wrapper