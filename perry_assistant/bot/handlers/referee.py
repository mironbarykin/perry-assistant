from __future__ import annotations


from telegram import Update
from telegram.ext import CallbackContext, ContextTypes

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin

@require_admin
async def emails(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("👀 Scanning referee emails...")
    services = get_services(context)
    await services.referee_service.process_new_emails(context)
    await update.message.reply_text("📧 Scan completed.")


async def process_basketball_emails_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    await services.referee_service.process_new_emails(context)


