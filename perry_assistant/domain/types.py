from __future__ import annotations

from dataclasses import dataclass

from perry_assistant.config import AppConfig
from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.services.notification_service import NotificationService
from perry_assistant.services.referee_service import RefereeService
from perry_assistant.services.schedule_service import ScheduleService
from perry_assistant.services.stats_service import StatsService
from perry_assistant.services.game_message_service import GameMessageService
from perry_assistant.services.untis_service import UntisService
from perry_assistant.services.uportal_service import UportalService
from perry_assistant.services.weather_archive_service import WeatherArchiveService
from perry_assistant.services.weather_location_service import WeatherLocationService


@dataclass(slots=True)
class AppServices:
    config: AppConfig
    schedule_service: ScheduleService
    notification_service: NotificationService
    referee_service: RefereeService
    absence_service: AbsenceService
    game_message_service: GameMessageService
    uportal_service: UportalService
    untis_service: UntisService
    stats_service: StatsService
    weather_location_service: WeatherLocationService
    weather_archive_service: WeatherArchiveService
