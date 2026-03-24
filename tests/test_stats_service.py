from __future__ import annotations

import datetime as dt

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.services.stats_service import StatsService
from perry_assistant.storage.json_store import write_json


def test_yesterday_usage_counts_from_stats_logs(app_config):
    app_config.logs_dir.mkdir(parents=True, exist_ok=True)
    write_json(app_config.parents_file, [222])
    app_config.untis_users_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(app_config.untis_users_file, {"999": {"username": "u", "password": "p"}})

    yesterday = (dt.datetime.now(BERLIN_TZ) - dt.timedelta(days=1)).date().isoformat()
    today = dt.datetime.now(BERLIN_TZ).date().isoformat()
    log_file = app_config.logs_dir / "perry.log"
    log_file.write_text(
        "\n".join(
            [
                f'{yesterday} 08:00:00,001 STATS perry.stats incoming={{"user_id":222}}',
                f'{yesterday} 08:05:00,001 STATS perry.stats incoming={{"user_id":999}}',
                f'{today} 08:05:00,001 STATS perry.stats incoming={{"user_id":222}}',
                f"{yesterday} 08:07:00,001 INFO perry.stats incoming={{\"user_id\":222}}",
            ]
        ),
        encoding="utf-8",
    )

    service = StatsService(app_config)
    total, parent_total, untis_total = service.yesterday_usage_counts()
    assert total == 2
    assert parent_total == 1
    assert untis_total == 1


def test_yesterday_usage_line_format(app_config):
    app_config.logs_dir.mkdir(parents=True, exist_ok=True)
    (app_config.logs_dir / "perry.log").write_text("", encoding="utf-8")
    service = StatsService(app_config)
    line = service.yesterday_usage_line()
    assert "Perry was used 0 times" in line
    assert "0 by parents" in line
    assert "0 for untis" in line
    assert "inform about 0 school timetable edits" in line

