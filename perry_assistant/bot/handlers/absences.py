from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import CallbackContext

async def review_absences(logs: str, context: CallbackContext) -> None:
    logs_str = logs.replace('ABSENCES: ', '').strip()

    absence_service = context.bot_data.get('absence_service')
    untis_service = context.bot_data.get('untis_service')
    schedule = untis_service.load_user_timetable(context.config.miron_id) # ! might not work as expected, cause it's loading it from the jsons
    logs = absence_service.parse_school_logs(logs_str)

    absences = absence_service.find_absences(dt.date.today(), schedule, logs)

    # todo: create todos for absences, return it's amount and display
    # todo: save absences to a file for later review and processing

    absence_service.create_absence_todos(dt.date.today(), absences, schedule)
    pass # TODO: implement absences service and handlers