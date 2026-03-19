from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ConversationHandler

from perry_assistant.bot.keyboards import build_main_keyboard
from perry_assistant.bot.handlers.common import get_services
from perry_assistant.storage.json_store import read_json


PUBLISH_STATE = 200

PUBLISH_TARGET_PARENTS = "parents"
PUBLISH_TARGET_UNTIS = "untis"


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


async def published_send(update: Update, context: CallbackContext) -> int:
    if not update.message:
        return ConversationHandler.END

    services = get_services(context)
    if update.effective_user.id != services.config.miron_id:
        return ConversationHandler.END

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
        try:
            await context.bot.send_message(
                chat_id=recipient_id,
                text=message_text,
                reply_markup=build_main_keyboard(is_admin=False),
            )
            sent_count += 1
        except Exception:
            continue

    await update.message.reply_text(f"Published to {sent_count} {target} subscriber(s).")
    return ConversationHandler.END
