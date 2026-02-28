from __future__ import annotations

from perry_assistant.bot.router import build_application
from perry_assistant.config import load_config
from perry_assistant.domain.types import AppServices
from perry_assistant.integrations.calendar_client import CalendarClient
from perry_assistant.integrations.gmail_client import GmailClient
from perry_assistant.integrations.gym_client import GymClient
from perry_assistant.integrations.uportal_client import UportalClient
from perry_assistant.integrations.weather_client import WeatherClient
from perry_assistant.logging_setup import configure_logging
from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.services.game_message_service import GameMessageService
from perry_assistant.services.notification_service import NotificationService
from perry_assistant.services.referee_service import RefereeService
from perry_assistant.services.schedule_service import ScheduleService
from perry_assistant.services.stats_service import StatsService
from perry_assistant.services.uportal_service import UportalService
from perry_assistant.services.weather_archive_service import WeatherArchiveService
from perry_assistant.services.weather_location_service import WeatherLocationService
from perry_assistant.storage.bootstrap import bootstrap_data


def build_services() -> AppServices:
    config = load_config()
    bootstrap_data(config)
    configure_logging(config.logs_dir, debug_mode=config.debug_mode)

    calendar_client = CalendarClient(config)
    gmail_client = GmailClient(config)
    gym_client = GymClient(config)
    weather_client = WeatherClient(config)
    uportal_client = UportalClient(config)

    schedule_service = ScheduleService(calendar_client, weather_client)
    notification_service = NotificationService(config)
    referee_service = RefereeService(config, gmail_client, calendar_client, gym_client)
    absence_service = AbsenceService(config)
    game_message_service = GameMessageService(config, calendar_client)
    uportal_service = UportalService(config, uportal_client, calendar_client)
    weather_location_service = WeatherLocationService(config)
    weather_archive_service = WeatherArchiveService(config, weather_client, weather_location_service)
    stats_service = StatsService(config)
    return AppServices(
        config=config,
        schedule_service=schedule_service,
        notification_service=notification_service,
        referee_service=referee_service,
        absence_service=absence_service,
        game_message_service=game_message_service,
        uportal_service=uportal_service,
        stats_service=stats_service,
        weather_location_service=weather_location_service,
        weather_archive_service=weather_archive_service,
    )


def run() -> None:
    services = build_services()
    app = build_application(services)
    app.run_polling()
