from __future__ import annotations

import logging
import shutil
from pathlib import Path

from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import read_json, write_json


logger = logging.getLogger(__name__)


def _ensure_json_file(path: Path, default_data) -> None:
    if not path.exists():
        write_json(path, default_data)


def bootstrap_data(config: AppConfig) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    _migrate_legacy_absence_file(config.data_dir, config.school_absence_file)

    _ensure_json_file(config.notification_file, {})
    _ensure_json_file(config.parents_file, [])
    _ensure_json_file(config.processed_emails_file, [])
    _ensure_json_file(config.referee_events_file, {})
    _ensure_json_file(config.gyms_cache_file, {})
    _ensure_json_file(config.school_absence_file, [])
    _ensure_json_file(config.school_timetable_file, {})

    _copy_if_missing(Path("google_calendar_benny_access.json"), config.credentials_file)
    _copy_if_missing(Path("token.pickle"), config.token_pickle_file)


def _copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    logger.info("Copied %s -> %s", src, dst)


def _migrate_legacy_absence_file(data_dir: Path, new_file: Path) -> None:
    legacy_file = data_dir / "school_absence.json"
    legacy_alt = data_dir / "school_absences.json"

    if legacy_file.exists() and not new_file.exists():
        legacy_file.rename(new_file)
        logger.info("Migrated %s -> %s", legacy_file, new_file)

    if legacy_alt.exists() and legacy_alt != new_file and not new_file.exists():
        legacy_alt.rename(new_file)
        logger.info("Migrated %s -> %s", legacy_alt, new_file)

    if legacy_file.exists() and new_file.exists():
        merged = read_json(new_file, [])
        legacy_data = read_json(legacy_file, [])
        if isinstance(merged, list) and isinstance(legacy_data, list):
            merged.extend(legacy_data)
            deduped = []
            seen = set()
            for item in merged:
                key = (
                    str(item.get("date")),
                    str(item.get("subject")),
                    bool(item.get("excused", False)),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            write_json(new_file, deduped)
        legacy_file.unlink(missing_ok=True)

