from __future__ import annotations

import datetime as dt

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import UntisPeriod
from perry_assistant.storage.json_store import read_json, write_json

class AbsenceService:
    def __init__(self, config: AppConfig) -> None:
        self._cache_file = config.absences_file
    
    def parse_school_logs(self, logs_str: str) -> list[dict[str, str]]|None:
        """Function to parse entrances and exits from the school logs message."""
        if logs_str == '':
            return None
        logs = []
        for line in logs_str.split("\n")[1:]:
            if not line.strip():
                continue
            try:
                action, timestamp_str = line.split(',')
                timestamp = dt.datetime.strptime(timestamp_str.strip(), "%d.%m.%Y %H:%M:%S")
                logs.append({'log': action.strip(), 'timestamp': timestamp})
            except ValueError:
                continue
        return logs if logs else None
    

    def find_absences(self, day: dt.date, schedule: list[UntisPeriod], logs: list[(dt.datetime, dt.datetime)]) -> list[UntisPeriod]:
        """Function to determine if the student is currently absent based on the logs."""
        absences = []
        for period in schedule:
            period_start = dt.datetime.combine(day, period.start_time)
            period_end = dt.datetime.combine(day, period.end_time)
            # Check if the student was absent during this period
            if not any(log_start <= period_start <= log_end or log_start <= period_end <= log_end for log_start, log_end in logs):
                absences.append(period)
            else:
                # if the user was not absent during this period, remove it from the absences list if it was previously added
                if period in absences:
                    absences.remove(period)
        write_json(self._cache_file, [period.__dict__ for period in absences])
        return absences
    
    def create_absence_todo(self, day: dt.date, absences: list[UntisPeriod], following_schedule: list[UntisPeriod]) -> str:
        """Function to create a todo task in google for me if I was absent."""
        # TODO: create a main task for the day, then go through each and every subject, add additional todo for taking the Entschuldigung list from Hausmeister
        # TODO: as a deadline set 14 days from the day of absence
        # TODO: set the reminder to the next slot of this subject accordin to the untis schedule, at the time of 2 mins before the lesson starts
        pass
    