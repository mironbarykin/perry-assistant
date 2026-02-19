from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_STATS_LEVEL = 25
logging.addLevelName(LOG_STATS_LEVEL, "STAT")


def statistic(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(LOG_STATS_LEVEL):
        self._log(LOG_STATS_LEVEL, message, args, **kwargs)


logging.Logger.statistic = statistic  # type: ignore[attr-defined]


def configure_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "perry.log"

    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
        force=True,
    )

