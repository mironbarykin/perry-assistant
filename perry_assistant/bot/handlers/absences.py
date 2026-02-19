from __future__ import annotations

import datetime as dt
from collections import defaultdict

from telegram import Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.keyboards import build_absences_menu_keyboard


def _is_admin(update: Update, context: CallbackContext) -> bool:
    services = get_services(context)
    user = update.effective_user
    return bool(user and user.id == services.config.miron_id)


async def _require_admin(update: Update, context: CallbackContext) -> bool:
    if not update.message:
        return False
    if _is_admin(update, context):
        return True
    await update.message.reply_text("Admin only.")
    return False


def _group_unexcused_lines(items) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        grouped[item.date].append(item.subject)

    output: list[str] = []
    for date in sorted(grouped):
        output.append(f"{date}: {', '.join(sorted(grouped[date]))}")
    return output


async def absence(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
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


async def absences_today(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
        return

    services = get_services(context)
    now = dt.datetime.now()
    excusable = services.absence_service.get_excusable_absences_today(now)
    if not excusable:
        await update.message.reply_text("No excusable absences for today.")
        return

    lines = _group_unexcused_lines(excusable)
    await update.message.reply_text("Excusable today:\n" + "\n".join(lines))


async def absences_all(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
        return

    services = get_services(context)
    unexcused = services.absence_service.get_unexcused_absences()
    if not unexcused:
        await update.message.reply_text("No unexcused absences.")
        return

    lines = _group_unexcused_lines(unexcused)
    await update.message.reply_text("Unexcused absences:\n" + "\n".join(lines))


async def absences_absent(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
        return

    services = get_services(context)
    now = dt.datetime.now()
    timetable = services.absence_service.get_school_timetable()
    today_subjects = timetable.get(now.weekday(), [])
    if not today_subjects:
        await update.message.reply_text("No subjects found for today in timetable.")
        return

    date_str = now.strftime("%Y-%m-%d")
    created = services.absence_service.add_absence(date_str, today_subjects)
    if not created:
        await update.message.reply_text("No subjects were added.")
        return

    lines = [f"- {item.subject}" for item in created]
    await update.message.reply_text(f"Absences added for today ({date_str}):\n" + "\n".join(lines))


async def excuse(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
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


async def absences_menu(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return
    if not await _require_admin(update, context):
        return
    await update.message.reply_text("OK", reply_markup=build_absences_menu_keyboard())
