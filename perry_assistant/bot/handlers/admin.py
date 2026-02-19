from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.storage.json_store import read_json


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

