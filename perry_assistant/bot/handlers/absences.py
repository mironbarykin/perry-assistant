from __future__ import annotations

import datetime as dt
from collections import defaultdict
import re

from telegram import Update
from telegram.ext import CallbackContext

from perry_assistant.bot.handlers.common import get_services
from perry_assistant.bot.handlers.guards import require_admin
from perry_assistant.bot.keyboards import build_absences_menu_keyboard


DATE_MM_DD_RE = re.compile(r"^\d{2}-\d{2}$")

def _group_absence_lines(items) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        grouped[item.date].append(item.subject)

    output: list[str] = []
    for date in sorted(grouped):
        output.append(f"{date}: {', '.join(sorted(grouped[date]))}")
    return output


def _parse_excuse_groups(args: list[str]) -> list[tuple[str, list[str]]] | None:
    if len(args) < 2 or len(args) % 2 != 0:
        return None

    groups: list[tuple[str, list[str]]] = []
    for index in range(0, len(args), 2):
        date_text = args[index].strip()
        subjects_csv = args[index + 1].strip()
        if not DATE_MM_DD_RE.fullmatch(date_text):
            return None
        subjects = [subject.strip() for subject in subjects_csv.split(",") if subject.strip()]
        if not subjects:
            return None
        groups.append((date_text, subjects))
    return groups

@require_admin
async def absence(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /absence MM-DD subject1,subject2")
        return

    date = context.args[0]
    subjects = " ".join(context.args[1:]).split(",")
    try:
        created = services.absence_service.add_absence(date, subjects)
    except ValueError:
        await update.message.reply_text("Invalid date. Use MM-DD.")
        return

    if not created:
        await update.message.reply_text("No subjects were added.")
        return

    lines = [f"- {item.date} | {item.subject}" for item in created]
    await update.message.reply_text("Absences added:\n" + "\n".join(lines))


@require_admin
async def absences_today(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    now = dt.datetime.now()
    excusable = services.absence_service.get_excusable_absences_today(now)
    if not excusable:
        await update.message.reply_text("No excusable absences for today.")
        return

    lines = _group_absence_lines(excusable)
    await update.message.reply_text("Excusable today:\n" + "\n".join(lines))

@require_admin
async def absences_all(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    unexcused = services.absence_service.get_unexcused_absences()
    if not unexcused:
        await update.message.reply_text("No unexcused absences.")
        return

    lines = _group_absence_lines(unexcused)
    await update.message.reply_text("Unexcused absences:\n" + "\n".join(lines))

@require_admin
async def absences_excused(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    excused = services.absence_service.get_excused_absences()
    if not excused:
        await update.message.reply_text("No excused absences.")
        return

    lines = _group_absence_lines(excused)
    await update.message.reply_text("Excused absences:\n" + "\n".join(lines))

@require_admin
async def absences_absent(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    now = dt.datetime.now()
    timetable = services.absence_service.get_school_timetable()
    today_subjects = timetable.get(now.weekday(), [])
    if not today_subjects:
        await update.message.reply_text("No subjects found for today in timetable.")
        return

    date_str = now.strftime("%m-%d")
    created = services.absence_service.add_absence(date_str, today_subjects)
    if not created:
        await update.message.reply_text("No subjects were added.")
        return

    lines = [f"- {item.subject}" for item in created]
    await update.message.reply_text(f"Absences added for today ({date_str}):\n" + "\n".join(lines))

@require_admin
async def excuse(update: Update, context: CallbackContext) -> None:
    services = get_services(context)
    groups = _parse_excuse_groups(context.args)
    if groups is None:
        await update.message.reply_text("Usage: /excuse MM-DD subject1,subject2 [MM-DD subject3,subject4 ...]")
        return

    try:
        updated = services.absence_service.mark_absences_excused(groups)
    except ValueError:
        await update.message.reply_text("Invalid date. Use MM-DD.")
        return

    if updated > 0:
        await update.message.reply_text(f"Absence status updated ({updated} marked excused).")
    else:
        await update.message.reply_text("No matching unexcused absence found.")


@require_admin
async def absences_menu(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("OK", reply_markup=build_absences_menu_keyboard())
