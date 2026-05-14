from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext, ContextTypes

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.services.uportal_service import (
    IGNORE_CALLBACK_PREFIX,
    IGNORE_ALL_CALLBACK_PREFIX,
    IGNORE_GAME_CALLBACK_PREFIX,
)

@require_admin
async def uportal(update: Update, context: CallbackContext) -> None:
    services = get_services(context)

    await update.message.reply_text("Running Uportal scan...")
    await services.uportal_service.run_manual_scan(context)
    await update.message.reply_text("Uportal scan finished.")


async def process_uportal_schedule_tick_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    await services.uportal_service.process_scheduled_tick(context)


async def process_uportal_generated_scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    reason = "generated"
    if context.job and isinstance(context.job.data, dict):
        reason = str(context.job.data.get("reason", reason))
    await services.uportal_service.run_generated_scan(context, reason=reason)

@require_admin
async def uportal_ignored(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    await services.uportal_service.run_show_ignored(context)


@require_admin
async def ignore_uportal_game(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not query:
        return

    services = get_services(context)

    data = query.data or ""
    if not data.startswith(IGNORE_CALLBACK_PREFIX):
        await query.answer()
        return

    if data.startswith(IGNORE_GAME_CALLBACK_PREFIX):
        ignore_id = data.removeprefix(IGNORE_GAME_CALLBACK_PREFIX).strip()
        ok, message = services.uportal_service.ignore_game_by_id(ignore_id)
    elif data.startswith(IGNORE_ALL_CALLBACK_PREFIX):
        group_id = data.removeprefix(IGNORE_ALL_CALLBACK_PREFIX).strip()
        ok, message = services.uportal_service.ignore_all_in_group(group_id)
    else:
        await query.answer("Unknown action.", show_alert=False)
        return

    await query.answer("Ignored." if ok else "Not ignored.", show_alert=False)
    if query.message:
        await query.message.reply_text(message, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await context.bot.send_message(
            chat_id=services.config.miron_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
