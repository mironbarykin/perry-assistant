import logging
import os 
from logging.handlers import TimedRotatingFileHandler

LOGS_DIR = "/data/logs/"
LOGS_PATH = os.path.join(LOGS_DIR, "logs_")
LOGS_STATISTICS_LEVEL = 25

file_handler = TimedRotatingFileHandler(LOGS_PATH, when="midnight", encoding="utf-8")
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

logging.addLevelName(LOGS_STATISTICS_LEVEL, "STAT")

def stat(self, message, *args, **kwargs):
    if self.isEnabledFor(LOGS_STATISTICS_LEVEL):
        self._log(LOGS_STATISTICS_LEVEL, message, args, **kwargs)

logging.Logger.statistic = stat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        file_handler,
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
