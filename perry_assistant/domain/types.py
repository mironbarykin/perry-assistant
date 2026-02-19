from __future__ import annotations

from dataclasses import dataclass

from perry_assistant.config import AppConfig
from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.services.notification_service import NotificationService
from perry_assistant.services.referee_service import RefereeService
from perry_assistant.services.schedule_service import ScheduleService


@dataclass(slots=True)
class AppServices:
    config: AppConfig
    schedule_service: ScheduleService
    notification_service: NotificationService
    referee_service: RefereeService
    absence_service: AbsenceService

