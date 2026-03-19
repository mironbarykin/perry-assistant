from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.keyboards import build_main_keyboard
from perry_assistant.bot.handlers.common import get_services
from perry_assistant.storage.json_store import read_json


PUBLISH_STATE = 200


async def parents(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    if update.effective_user.id != services.config.miron_id:
        await update.message.reply_text("Admin only.")
        return

    parent_ids = read_json(services.config.parents_file, [])
    if not parent_ids:
        await update.message.reply_text("No parent subscribers yet.")
        return
    await update.message.reply_text("Parent subscribers:\n" + "\n".join(f"- {item}" for item in parent_ids))


async def published_start(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    services = get_services(context)
    if update.effective_user.id != services.config.miron_id:
        await update.message.reply_text("Admin only.")
        return ConversationHandler.END

    await update.message.reply_text("Send your next message. It will be published to all parents.")
    return PUBLISH_STATE


async def published_send(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    services = get_services(context)
    if update.effective_user.id != services.config.miron_id:
        return ConversationHandler.END

    parent_ids = read_json(services.config.parents_file, [])
    parent_ids = list(dict.fromkeys(parent_ids))
    parent_ids = [pid for pid in parent_ids if pid != services.config.miron_id]

    if not parent_ids:
        await update.message.reply_text("No parent subscribers found.")
        return ConversationHandler.END

    message_text = update.message.text
    sent_count = 0
    for parent_id in parent_ids:
        try:
            await context.bot.send_message(
                chat_id=parent_id,
                text=message_text,
                reply_markup=build_main_keyboard(is_admin=False, is_parent=True),
            )
            sent_count += 1
        except Exception:
            continue

    await update.message.reply_text(f"Published to {sent_count} parent(s).")
    return ConversationHandler.END
