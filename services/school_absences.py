import os
import json
from datetime import datetime

from .consts import DATA_DIR, SCHOOL_ABSENCE_FILE, SCHOOL_TIMETABLE_FILE

def add_absence(date: str, subjects: list):
    """
    Adds an absence record to school_absence.json.
    Each record: {"date": "YYYY-MM-DD", "subjects": [...], "excused": False}
    """
    with open(SCHOOL_ABSENCE_FILE, "r") as f:
        absences = json.load(f)
    for subject in subjects:
        absences.append({
            "date": date,
            "subject": subject,
            "excused": False
        })
    with open(SCHOOL_ABSENCE_FILE, "w") as f:
        json.dump(absences, f, indent=2)

def get_unexcused_absences():
    """
    Returns all absences marked as not excused.
    """
    with open(SCHOOL_ABSENCE_FILE, "r") as f:
        absences = json.load(f)
    return [a for a in absences if not a.get("excused", False)]

def get_school_timetable():
    """
    Returns the school timetable as a dict mapping weekdays (0=Monday) to list of subjects.
    Example: {0: ["Math", "English"], 1: ["Physics"], ...}
    """
    if not os.path.exists(SCHOOL_TIMETABLE_FILE):
        return {}
    with open(SCHOOL_TIMETABLE_FILE, "r") as f:
        timetable = json.load(f)

    return {int(day): subjects for day, subjects in timetable.items()}

def get_excusable_absences_today():
    """
    Returns unexcused absences that can be excused today:
    - The absence is on the same weekday as today
    - The subject is in today's timetable
    """
    today = datetime.now()
    weekday = today.weekday()
    timetable = get_school_timetable()
    today_subjects = set(timetable.get(weekday, []))
    unexcused = get_unexcused_absences()
    excusable = []
    for a in unexcused:
        absence_date = datetime.strptime(a["date"], "%Y-%m-%d")
        if absence_date.weekday() == weekday and a["subject"] in today_subjects:
            excusable.append(a)
    return excusable

def mark_absence_excused(date: str, subject: str = None):
    """
    Marks an absence as excused by date and subject (or all subjects on that day).
    """
    with open(SCHOOL_ABSENCE_FILE, "r") as f:
        absences = json.load(f)
    updated = False
    for a in absences:
        if subject:
            if a["date"] == date and a["subject"] == subject and not a.get("excused", False):
                a["excused"] = True
                updated = True
        else:
            if a["date"] == date and not a.get("excused", False):
                a["excused"] = True
                updated = True
    with open(SCHOOL_ABSENCE_FILE, "w") as f:
        json.dump(absences, f, indent=2)
    return updated
