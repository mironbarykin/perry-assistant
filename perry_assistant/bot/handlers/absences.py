from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services


async def absence(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /absence YYYY-MM-DD subject1,subject2")
        return

    date = context.args[0]
    subjects = " ".join(context.args[1:]).split(",")
    try:
        created = services.absence_service.add_absence(date, subjects)
    except ValueError:
        await update.message.reply_text("Invalid date. Use YYYY-MM-DD.")
        return

    if not created:
        await update.message.reply_text("No subjects were added.")
        return

    lines = [f"- {item.date} | {item.subject}" for item in created]
    await update.message.reply_text("Absences added:\n" + "\n".join(lines))


async def absences(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    unexcused = services.absence_service.get_unexcused_absences()
    if not unexcused:
        await update.message.reply_text("No unexcused absences.")
        return

    lines = [f"- {item.date} | {item.subject}" for item in unexcused]
    excusable = services.absence_service.get_excusable_absences_today()
    if excusable:
        lines.append("")
        lines.append("Excusable today:")
        lines.extend(f"- {item.date} | {item.subject}" for item in excusable)

    await update.message.reply_text("\n".join(lines))


async def excuse(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    services = get_services(context)
    if not context.args:
        await update.message.reply_text("Usage: /excuse YYYY-MM-DD [subject]")
        return

    date = context.args[0]
    subject = " ".join(context.args[1:]) if len(context.args) > 1 else None
    try:
        updated = services.absence_service.mark_absence_excused(date, subject)
    except ValueError:
        await update.message.reply_text("Invalid date. Use YYYY-MM-DD.")
        return

    if updated:
        await update.message.reply_text("Absence status updated.")
    else:
        await update.message.reply_text("No matching unexcused absence found.")

