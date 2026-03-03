from pathlib import Path


def test_router_removed_per_minute_uportal_polling():
    router = Path("perry_assistant/bot/router.py").read_text(encoding="utf-8")
    assert "run_repeating(uportal.process_uportal_schedule_tick_job" not in router


def test_morning_job_triggers_operational_scans():
    schedule_handler = Path("perry_assistant/bot/handlers/schedule.py").read_text(encoding="utf-8")
    assert "game_message_service.run_daily_scan" in schedule_handler
    assert "generate_daily_scan_jobs" in schedule_handler


def test_router_registers_games_command_and_picker_callback():
    router = Path("perry_assistant/bot/router.py").read_text(encoding="utf-8")
    assert 'CommandHandler("games", game_messages.games)' in router
    assert 'CallbackQueryHandler(game_messages.select_game, pattern=r"^gmsg:")' in router
