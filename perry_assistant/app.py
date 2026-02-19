from __future__ import annotations

from perry_assistant.bot.router import build_application
from perry_assistant.config import load_config
from perry_assistant.domain.types import AppServices
from perry_assistant.integrations.calendar_client import CalendarClient
from perry_assistant.integrations.gmail_client import GmailClient
from perry_assistant.integrations.gym_client import GymClient
from perry_assistant.integrations.weather_client import WeatherClient
from perry_assistant.logging_setup import configure_logging
from perry_assistant.services.absence_service import AbsenceService
from perry_assistant.services.notification_service import NotificationService
from perry_assistant.services.referee_service import RefereeService
from perry_assistant.services.schedule_service import ScheduleService
from perry_assistant.storage.bootstrap import bootstrap_data


def build_services() -> AppServices:
    config = load_config()
    bootstrap_data(config)
    configure_logging(config.logs_dir)

    calendar_client = CalendarClient(config)
    gmail_client = GmailClient(config)
    gym_client = GymClient(config)
    weather_client = WeatherClient(config)

    schedule_service = ScheduleService(calendar_client, weather_client)
    notification_service = NotificationService(config)
    referee_service = RefereeService(config, gmail_client, calendar_client, gym_client)
    absence_service = AbsenceService(config)
    return AppServices(
        config=config,
        schedule_service=schedule_service,
        notification_service=notification_service,
        referee_service=referee_service,
        absence_service=absence_service,
    )


def run() -> None:
    services = build_services()
    app = build_application(services)
    app.run_polling()

