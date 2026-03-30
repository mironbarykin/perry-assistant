from __future__ import annotations

import datetime as dt
import hashlib
import html
import random
from dataclasses import asdict, dataclass
from urllib.parse import quote_plus

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from perry_assistant.config import AppConfig
from perry_assistant.constants import (
    BERLIN_TZ,
    DEFAULT_GAME_DURATION_HOURS,
    ICON_GREEN,
    ICON_ORANGE,
    ICON_RED,
    ICON_STAR,
    ICON_PLANE,
)
from perry_assistant.domain.models import UportalGame
from perry_assistant.integrations.calendar_client import CalendarClient, parse_google_datetime
from perry_assistant.integrations.gym_client import GymClient
from perry_assistant.integrations.uportal_client import UportalClient
from perry_assistant.storage.json_store import read_json, write_json



WINDOWS = {
    "night": {"hour": 0},
    "morning": {"hour": 10},
    "evening": {"hour": 20},
}

IGNORE_CALLBACK_PREFIX = "uio:"
IGNORE_GAME_CALLBACK_PREFIX = "uio:g:"
IGNORE_ALL_CALLBACK_PREFIX = "uio:a:"
MAX_BUTTONS_PER_CHUNK = 20
SEEN_RETENTION_DAYS = 90
IGNORED_RETENTION_DAYS = 90
CATALOG_PAST_RETENTION_DAYS = 30
GENERATED_JOB_MORNING = "uportal_generated_morning"
GENERATED_JOB_EVENING = "uportal_generated_evening"
GENERATED_JOB_MIDNIGHT = "uportal_generated_midnight"


@dataclass(slots=True)
class EvaluatedGame:
    game: UportalGame
    status: str
    icon: str
    kind: str


@dataclass(slots=True)
class RenderedChunk:
    text: str
    buttons: list[tuple[str, str]]


class UportalService:
    def __init__(
        self,
        config: AppConfig,
        uportal_client: UportalClient,
        calendar_client: CalendarClient,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config
        self._uportal_client = uportal_client
        self._calendar = calendar_client
        self._gym = GymClient(config)
        self._rng = rng or random.Random()
        self._daily_event_intervals_cache: dict[str, list[tuple[dt.datetime, dt.datetime]]] | None = None
        self._referee_event_intervals_cache: list[tuple[dt.datetime, dt.datetime]] | None = None
        self._last_raw_rows_debug_file: str = ""
        self._hall_address_cache: dict[str, str] = {}
        self._ignore_groups: dict[str, list[str]] = {}

    async def run_manual_scan(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._scan_and_notify(context, reason="manual")

    async def run_show_ignored(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        chunks = self._render_ignored_chunks()
        for chunk in chunks:
            await context.bot.send_message(
                chat_id=self._config.miron_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    async def process_scheduled_tick(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = dt.datetime.now(BERLIN_TZ)
        state = self._load_or_create_window_state(now)
        due_window = self._due_window(state, now)
        if not due_window:
            return

        await self._scan_and_notify(context, reason=f"scheduled:{due_window}")
        state["executed"][due_window] = True
        self._save_window_state(state)

    async def run_generated_scan(self, context: ContextTypes.DEFAULT_TYPE, reason: str) -> None:
        await self._scan_and_notify(context, reason=reason)

    def generate_daily_scan_jobs(self, app: Application, callback) -> dict[str, str]:
        now = dt.datetime.now(BERLIN_TZ)
        state = read_json(self._config.uportal_window_state_file, {})
        targets = self._load_or_create_generated_targets(state, now)
        self._save_window_state(state)

        for name in (GENERATED_JOB_MORNING, GENERATED_JOB_EVENING, GENERATED_JOB_MIDNIGHT):
            for job in app.job_queue.get_jobs_by_name(name):
                job.schedule_removal()

        app.job_queue.run_once(
            callback,
            when=targets["morning_dt"],
            name=GENERATED_JOB_MORNING,
            data={"reason": "generated:morning"},
        )
        app.job_queue.run_once(
            callback,
            when=targets["evening_dt"],
            name=GENERATED_JOB_EVENING,
            data={"reason": "generated:evening"},
        )
        app.job_queue.run_once(
            callback,
            when=targets["midnight_dt"],
            name=GENERATED_JOB_MIDNIGHT,
            data={"reason": "generated:midnight"},
        )
        return {
            "morning": targets["morning_dt"].isoformat(),
            "evening": targets["evening_dt"].isoformat(),
            "midnight": targets["midnight_dt"].isoformat(),
        }

    def _load_or_create_window_state(self, now: dt.datetime) -> dict:
        state = read_json(self._config.uportal_window_state_file, {})
        today = now.date().isoformat()
        if state.get("date") == today:
            return state
        fresh = self._new_daily_window_state(now.date())
        self._save_window_state(fresh)
        return fresh

    def _new_daily_window_state(self, day: dt.date) -> dict:
        targets: dict[str, str] = {}
        for name, spec in WINDOWS.items():
            minute = self._rng.randint(0, 10)
            targets[name] = f"{spec['hour']:02d}:{minute:02d}"
        return {
            "date": day.isoformat(),
            "targets": targets,
            "executed": {name: False for name in WINDOWS},
        }

    @staticmethod
    def _window_bounds(name: str, day: dt.date) -> tuple[dt.datetime, dt.datetime]:
        hour = WINDOWS[name]["hour"]
        start = dt.datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=BERLIN_TZ)
        end = dt.datetime(day.year, day.month, day.day, hour, 10, 59, tzinfo=BERLIN_TZ)
        return start, end

    def _due_window(self, state: dict, now: dt.datetime) -> str | None:
        if state.get("date") != now.date().isoformat():
            return None
        targets = state.get("targets", {})
        executed = state.get("executed", {})

        for name in ("night", "morning", "evening"):
            if executed.get(name):
                continue
            target_text = targets.get(name)
            if not target_text:
                continue
            start, end = self._window_bounds(name, now.date())
            if now < start or now > end:
                continue
            target_hour, target_minute = map(int, target_text.split(":"))
            target = dt.datetime(
                now.year,
                now.month,
                now.day,
                target_hour,
                target_minute,
                0,
                tzinfo=BERLIN_TZ,
            )
            if now >= target:
                return name
        return None

    def _save_window_state(self, state: dict) -> None:
        write_json(self._config.uportal_window_state_file, state)

    def _load_or_create_generated_targets(self, state: dict, now: dt.datetime) -> dict[str, dt.datetime]:
        today_iso = now.date().isoformat()
        existing_for = state.get("generated_for")
        generated = state.get("generated_targets", {})
        if existing_for == today_iso and isinstance(generated, dict):
            parsed = self._parse_generated_targets(generated)
            if parsed:
                return parsed

        morning_dt = dt.datetime(now.year, now.month, now.day, 10, self._rng.randint(0, 10), 0, tzinfo=BERLIN_TZ)
        evening_dt = dt.datetime(now.year, now.month, now.day, 20, self._rng.randint(0, 10), 0, tzinfo=BERLIN_TZ)
        tomorrow = now.date() + dt.timedelta(days=1)
        midnight_dt = dt.datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            0,
            self._rng.randint(0, 10),
            0,
            tzinfo=BERLIN_TZ,
        )

        if morning_dt <= now:
            morning_dt = now + dt.timedelta(minutes=1)
        if evening_dt <= now:
            evening_dt = now + dt.timedelta(minutes=1)
        if midnight_dt <= now:
            midnight_dt = now + dt.timedelta(minutes=1)

        state["generated_for"] = today_iso
        state["generated_targets"] = {
            "morning": morning_dt.isoformat(),
            "evening": evening_dt.isoformat(),
            "midnight": midnight_dt.isoformat(),
        }
        return {
            "morning_dt": morning_dt,
            "evening_dt": evening_dt,
            "midnight_dt": midnight_dt,
        }

    @staticmethod
    def _parse_generated_targets(payload: dict) -> dict[str, dt.datetime] | None:
        morning = UportalService._parse_iso_dt(payload.get("morning"))
        evening = UportalService._parse_iso_dt(payload.get("evening"))
        midnight = UportalService._parse_iso_dt(payload.get("midnight"))
        if not morning or not evening or not midnight:
            return None
        return {
            "morning_dt": morning,
            "evening_dt": evening,
            "midnight_dt": midnight,
        }

    @staticmethod
    def _parse_iso_dt(raw: object) -> dt.datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            parsed = dt.datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=BERLIN_TZ)
        return parsed.astimezone(BERLIN_TZ)

    def ignore_game_by_id(self, ignore_id: str) -> tuple[bool, str]:
        catalog = read_json(self._config.uportal_game_catalog_file, {})
        ignored = self._prune_ignored_entries(read_json(self._config.uportal_ignored_rows_file, {}))
        if ignore_id in ignored:
            return False, "Uportal: already ignored."
        game_data = catalog.get(ignore_id)
        if not isinstance(game_data, dict):
            return False, "Uportal: game not found in catalog. Run /uportal first."

        payload = dict(game_data)
        payload["ignored_at"] = dt.datetime.now(dt.UTC).isoformat()
        ignored[ignore_id] = payload
        write_json(self._config.uportal_ignored_rows_file, ignored)
        line = self._ignored_line(game_data)
        return True, f"Ignored: {line}"

    def ignore_all_in_group(self, group_id: str) -> tuple[bool, str]:
        ignore_ids = self._ignore_groups.get(group_id, [])
        if not ignore_ids:
            return False, "Uportal: ignore group expired. Run /uportal again."

        catalog = read_json(self._config.uportal_game_catalog_file, {})
        ignored = self._prune_ignored_entries(read_json(self._config.uportal_ignored_rows_file, {}))
        added = 0
        for ignore_id in ignore_ids:
            if ignore_id in ignored:
                continue
            game_data = catalog.get(ignore_id)
            if not isinstance(game_data, dict):
                continue
            payload = dict(game_data)
            payload["ignored_at"] = dt.datetime.now(dt.UTC).isoformat()
            ignored[ignore_id] = payload
            added += 1

        write_json(self._config.uportal_ignored_rows_file, ignored)
        return True, f"Ignored {added} game(s) from this message."

    async def _scan_and_notify(self, context: ContextTypes.DEFAULT_TYPE, reason: str) -> None:
        try:
            rows_raw = self._uportal_client.fetch_open_games()
            rows = self._dedupe_rows(rows_raw)
            self._last_raw_rows_debug_file = self._dump_raw_rows_debug(rows, reason=reason)
            self._update_game_catalog(rows)
            evaluated, counts = self._evaluate_rows(rows)
            if not evaluated:
                if reason == "manual":
                    debug_summary = self._manual_debug_summary()
                    await context.bot.send_message(
                        chat_id=self._config.miron_id,
                        text=(
                            "Uportal: no reportable rows. "
                            f"fetched={counts['fetched']}, "
                            f"new={counts['new']}, "
                            f"updated={counts['updated']}, "
                            f"old_green={counts['old_green']}, "
                            f"hidden={counts['hidden']}, "
                            f"ignored={counts['ignored']}"
                        ),
                    )
                    if debug_summary:
                        await context.bot.send_message(chat_id=self._config.miron_id, text=debug_summary)
                return

            for chunk in self._render_chunks(evaluated, reason=reason):
                await context.bot.send_message(
                    chat_id=self._config.miron_id,
                    text=chunk.text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=self._build_ignore_keyboard(chunk.buttons),
                )
        except Exception as exc:  # noqa: BLE001
            await context.bot.send_message(
                chat_id=self._config.miron_id,
                text=f"Uportal scan failed: {exc}",
            )
            debug_summary = self._manual_debug_summary()
            if debug_summary and reason == "manual":
                await context.bot.send_message(chat_id=self._config.miron_id, text=debug_summary)

    def _dedupe_rows(self, rows: list[UportalGame]) -> list[UportalGame]:
        by_key: dict[tuple[str, str, str], UportalGame] = {}
        for row in rows:
            key = (row.date.strip(), row.hall.strip(), row.number.strip())
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = row
                continue
            by_key[key] = self._merge_duplicate_game(existing, row)
        return list(by_key.values())

    @staticmethod
    def _merge_duplicate_game(primary: UportalGame, candidate: UportalGame) -> UportalGame:
        best = primary
        other = candidate
        if candidate.is_umb_offen and not primary.is_umb_offen:
            best = candidate
            other = primary
        if not best.detail_url and other.detail_url:
            best.detail_url = other.detail_url
        if other.is_umb_offen:
            best.is_umb_offen = True
        if best.distance_km > other.distance_km:
            best.distance_km = other.distance_km
        return best

    def _dump_raw_rows_debug(self, rows: list[UportalGame], reason: str) -> str:
        if not self._config.debug_mode:
            return ""
        timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe_reason = reason.replace(":", "_")
        directory = self._config.logs_dir / "uportal_debug"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{timestamp}_{safe_reason}_rows.json"
        payload = {
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "reason": reason,
            "total_rows": len(rows),
            "rows": [asdict(row) for row in rows],
        }
        write_json(path, payload)
        return str(path)

    def _update_game_catalog(self, rows: list[UportalGame]) -> None:
        catalog = read_json(self._config.uportal_game_catalog_file, {})
        for game in rows:
            ignore_id = self._ignore_id(game)
            payload = asdict(game)
            payload["ignore_id"] = ignore_id
            payload["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
            catalog[ignore_id] = payload
        catalog = self._prune_catalog_entries(catalog)
        write_json(self._config.uportal_game_catalog_file, catalog)

    def _evaluate_rows(self, rows: list[UportalGame]) -> tuple[list[EvaluatedGame], dict[str, int]]:
        seen: dict[str, dict] = self._prune_seen_entries(read_json(self._config.uportal_seen_rows_file, {}))
        ignored: dict[str, dict] = self._prune_ignored_entries(read_json(self._config.uportal_ignored_rows_file, {}))
        now_iso = dt.datetime.now(dt.UTC).isoformat()
        evaluated: list[EvaluatedGame] = []
        counts = {"fetched": len(rows), "new": 0, "updated": 0, "old_green": 0, "hidden": 0, "ignored": 0}
        self._daily_event_intervals_cache = self._build_daily_event_intervals_cache(rows)
        self._referee_event_intervals_cache = self._build_referee_event_intervals_cache(rows)

        try:
            for row in rows:
                identity = self._identity_key(row)
                ignore_id = self._ignore_id(row)
                fingerprint = self._fingerprint(row)
                status, icon = self._availability(row)

                if ignore_id in ignored:
                    kind = "ignored"
                else:
                    previous = seen.get(identity)
                    if previous is None:
                        kind = "new"
                    elif previous.get("fingerprint") != fingerprint:
                        kind = "updated"
                    elif status == "green":
                        kind = "old_green"
                    else:
                        kind = "hidden"

                if kind != "hidden":
                    if kind != "ignored":
                        evaluated.append(EvaluatedGame(game=row, status=status, icon=icon, kind=kind))
                counts[kind] += 1

                previous = seen.get(identity)
                if previous is None:
                    seen[identity] = {
                        "fingerprint": fingerprint,
                        "first_seen_at": now_iso,
                        "last_seen_at": now_iso,
                    }
                else:
                    previous["fingerprint"] = fingerprint
                    previous["last_seen_at"] = now_iso
        finally:
            self._daily_event_intervals_cache = None
            self._referee_event_intervals_cache = None

        write_json(self._config.uportal_seen_rows_file, seen)
        write_json(self._config.uportal_ignored_rows_file, ignored)
        return sorted(evaluated, key=self._sort_key), counts

    @staticmethod
    def _identity_key(game: UportalGame) -> str:
        base = "|".join(
            [
                game.detail_id.strip(),
                game.liga.strip(),
                game.number.strip(),
                game.home_team.strip(),
                game.away_team.strip(),
                game.original_referee.strip(),
            ]
        )
        return base.lower()

    @staticmethod
    def _ignore_key(game: UportalGame) -> str:
        base = "|".join(
            [
                game.detail_id.strip(),
                game.liga.strip(),
                game.number.strip(),
                game.home_team.strip(),
                game.away_team.strip(),
                game.date.strip(),
                game.time.strip(),
                game.hall.strip(),
            ]
        )
        return base.lower()

    def _ignore_id(self, game: UportalGame) -> str:
        digest = hashlib.sha1(self._ignore_key(game).encode("utf-8")).hexdigest()  # noqa: S324
        return digest[:16]

    @staticmethod
    def _fingerprint(game: UportalGame) -> str:
        payload = "|".join(
            [
                game.detail_id,
                game.liga,
                game.number,
                game.home_team,
                game.away_team,
                game.date,
                game.time,
                game.hall,
                game.original_referee,
                game.ust,
                f"{game.distance_km:.3f}",
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _sort_key(item: EvaluatedGame) -> tuple[dt.datetime, float]:
        parsed = dt.datetime.strptime(
            f"{item.game.date} {item.game.time}",
            "%d.%m.%Y %H:%M",
        ).replace(tzinfo=BERLIN_TZ)
        return parsed, item.game.distance_km

    def _availability(self, game: UportalGame) -> tuple[str, str]:
        start = dt.datetime.strptime(f"{game.date} {game.time}", "%d.%m.%Y %H:%M").replace(tzinfo=BERLIN_TZ)
        end = start + dt.timedelta(hours=DEFAULT_GAME_DURATION_HOURS)
        min_gap_hours: float | None = None

        for event_start, event_end in self._availability_event_intervals(start):
            gap = self._interval_gap_hours(start, end, event_start, event_end)
            if min_gap_hours is None or gap < min_gap_hours:
                min_gap_hours = gap

        if min_gap_hours is None or min_gap_hours >= 2:
            return "green", ICON_GREEN
        if min_gap_hours >= 1:
            return "orange", ICON_ORANGE
        return "red", ICON_RED

    def _availability_event_intervals(
        self,
        target_start: dt.datetime,
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        intervals: list[tuple[dt.datetime, dt.datetime]] = []

        if self._referee_event_intervals_cache is not None:
            intervals.extend(self._referee_event_intervals_cache)
        else:
            intervals.extend(self._fetch_referee_event_intervals(target_start - dt.timedelta(hours=6)))

        if self._daily_event_intervals_cache is not None:
            for day_offset in (-1, 0, 1):
                key = (target_start.date() + dt.timedelta(days=day_offset)).isoformat()
                intervals.extend(self._daily_event_intervals_cache.get(key, []))
            return intervals

        for day_offset in (-1, 0, 1):
            day = target_start + dt.timedelta(days=day_offset)
            intervals.extend(self._intervals_for_day(day))
        return intervals

    def _build_daily_event_intervals_cache(
        self,
        rows: list[UportalGame],
    ) -> dict[str, list[tuple[dt.datetime, dt.datetime]]]:
        cache: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {}
        unique_days: set[dt.date] = set()

        for row in rows:
            try:
                day = dt.datetime.strptime(row.date, "%d.%m.%Y").date()
            except ValueError:
                continue
            unique_days.add(day - dt.timedelta(days=1))
            unique_days.add(day)
            unique_days.add(day + dt.timedelta(days=1))

        for day in sorted(unique_days):
            day_dt = dt.datetime(day.year, day.month, day.day, tzinfo=BERLIN_TZ)
            cache[day.isoformat()] = self._intervals_for_day(day_dt)

        return cache

    def _build_referee_event_intervals_cache(
        self,
        rows: list[UportalGame],
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        starts: list[dt.datetime] = []
        for row in rows:
            try:
                starts.append(
                    dt.datetime.strptime(f"{row.date} {row.time}", "%d.%m.%Y %H:%M").replace(tzinfo=BERLIN_TZ)
                )
            except ValueError:
                continue
        if not starts:
            return []
        earliest = min(starts) - dt.timedelta(hours=6)
        return self._fetch_referee_event_intervals(earliest)

    def _fetch_referee_event_intervals(self, start_time: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
        intervals: list[tuple[dt.datetime, dt.datetime]] = []
        referee_events = self._calendar.get_future_referee_game_events(start_time)
        for event in referee_events:
            start_raw = event.get("start", {}).get("dateTime")
            end_raw = event.get("end", {}).get("dateTime")
            event_start = parse_google_datetime(start_raw)
            if not event_start:
                continue
            event_end = parse_google_datetime(end_raw) or (event_start + dt.timedelta(hours=DEFAULT_GAME_DURATION_HOURS))
            intervals.append((event_start, event_end))
        return intervals

    def _intervals_for_day(self, day: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
        intervals: list[tuple[dt.datetime, dt.datetime]] = []
        for event in self._calendar.get_events_for_date(day):
            if event.is_all_day or not event.start:
                continue
            event_end = event.end or (event.start + dt.timedelta(hours=DEFAULT_GAME_DURATION_HOURS))
            intervals.append((event.start, event_end))
        return intervals

    @staticmethod
    def _interval_gap_hours(
        start_a: dt.datetime,
        end_a: dt.datetime,
        start_b: dt.datetime,
        end_b: dt.datetime,
    ) -> float:
        if end_a <= start_b:
            return (start_b - end_a).total_seconds() / 3600
        if end_b <= start_a:
            return (start_a - end_b).total_seconds() / 3600
        return 0.0

    def _render_chunks(self, rows: list[EvaluatedGame], reason: str) -> list[RenderedChunk]:
        grouped: dict[str, list[EvaluatedGame]] = {}
        for row in rows:
            grouped.setdefault(row.game.date, []).append(row)

        chunks: list[RenderedChunk] = []
        dates = sorted(grouped.keys(), key=lambda value: dt.datetime.strptime(value, "%d.%m.%Y"))
        for date in dates:
            day_items = sorted(grouped[date], key=self._sort_key)
            header_lines = [f"Uportal report ({html.escape(reason)})", self._weekday_date_label(date)]
            header_len = sum(len(line) + 1 for line in header_lines)

            current_lines = header_lines.copy()
            current_len = header_len
            current_buttons: list[tuple[str, str]] = []
            current_chunk_ignore_ids: list[str] = []

            for item in day_items:
                line = self._row_line(item)
                add_len = len(line) + 1
                if (
                    current_lines
                    and (current_len + add_len > 3500 or len(current_buttons) >= MAX_BUTTONS_PER_CHUNK)
                    and len(current_lines) > len(header_lines)
                ):
                    group_id = self._remember_ignore_group(current_chunk_ignore_ids)
                    buttons_with_all = [("👎 Ignore all", f"{IGNORE_ALL_CALLBACK_PREFIX}{group_id}"), *current_buttons]
                    chunks.append(RenderedChunk(text="\n".join(current_lines).strip(), buttons=buttons_with_all))
                    current_lines = header_lines.copy()
                    current_len = header_len
                    current_buttons = []
                    current_chunk_ignore_ids = []

                current_lines.append(line)
                current_len += add_len
                ignore_id = self._ignore_id(item.game)
                current_chunk_ignore_ids.append(ignore_id)
                current_buttons.append((self._ignore_button_label(item), f"{IGNORE_GAME_CALLBACK_PREFIX}{ignore_id}"))

            group_id = self._remember_ignore_group(current_chunk_ignore_ids)
            buttons_with_all = [("👎 Ignore all", f"{IGNORE_ALL_CALLBACK_PREFIX}{group_id}"), *current_buttons]
            chunks.append(RenderedChunk(text="\n".join(current_lines).strip(), buttons=buttons_with_all))

        return chunks

    def _row_line(self, item: EvaluatedGame) -> str:
        kind_badge = {"new": "🆕", "updated": "♻️", "old_green": ""}.get(item.kind, "")
        game = item.game
        distance_badge = self._distance_badge(game.distance_km)
        marker = f"{item.icon}{distance_badge}"
        distance = int(game.distance_km) if game.distance_km.is_integer() else round(game.distance_km, 1)
        priority_badge = " 🫡" if game.is_umb_offen else ""
        address = self._address_for_hall(game.hall)
        maps_url = f"https://maps.google.com/?q={quote_plus(address)}" if address else ""
        location_part = (
            f'<a href="{html.escape(maps_url, quote=True)}">{html.escape(address)}</a>'
            if maps_url
            else html.escape(address)
        )
        league_part = f"{html.escape(game.liga)} #{html.escape(game.number)}"
        if game.detail_url:
            league_part = f'<a href="{html.escape(game.detail_url, quote=True)}">{league_part}</a>'
        trailing = f"{priority_badge} {kind_badge}".rstrip() if kind_badge else priority_badge
        return (
            f"{marker} @ {html.escape(game.time)} {location_part} ({distance} km) / "
            f"{league_part} {html.escape(game.home_team)} - {html.escape(game.away_team)}{trailing}"
        )

    @staticmethod
    def _distance_badge(distance_km: float) -> str:
        """Return ⭐ for gyms within 20 km, ✈️ for gyms more than 40 km away, else empty."""
        if distance_km < 20:
            return ICON_STAR
        if distance_km > 40:
            return ICON_PLANE
        return ""

    def _ignore_button_label(self, item: EvaluatedGame) -> str:
        game = item.game
        distance_badge = self._distance_badge(game.distance_km)
        priority_badge = "🫡" if game.is_umb_offen else ""
        emoji_part = f"{item.icon}{distance_badge}{priority_badge}".rstrip()
        return f"👎 {emoji_part} {game.time} {game.liga} #{game.number}".rstrip()

    def _remember_ignore_group(self, ignore_ids: list[str]) -> str:
        cleaned = sorted({item for item in ignore_ids if item})
        seed = "|".join(cleaned) + "|" + dt.datetime.now(dt.UTC).isoformat()
        group_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]  # noqa: S324
        self._ignore_groups[group_id] = cleaned
        if len(self._ignore_groups) > 200:
            oldest = list(self._ignore_groups.keys())[:-200]
            for key in oldest:
                self._ignore_groups.pop(key, None)
        return group_id

    def _address_for_hall(self, hall_code: str) -> str:
        code = (hall_code or "").strip()
        if not code:
            return "-"
        cached = self._hall_address_cache.get(code)
        if cached:
            return cached
        address = self._gym.get_gym_address(code) or code
        self._hall_address_cache[code] = address
        return address

    @staticmethod
    def _weekday_date_label(date_text: str) -> str:
        parsed = dt.datetime.strptime(date_text, "%d.%m.%Y")
        return parsed.strftime("%a %d.%m.%Y")

    def _build_ignore_keyboard(self, buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None
        rows = [
            [InlineKeyboardButton(text=label, callback_data=callback_data)]
            for label, callback_data in buttons
        ]
        return InlineKeyboardMarkup(rows)

    def _render_ignored_chunks(self) -> list[str]:
        ignored = self._prune_ignored_entries(read_json(self._config.uportal_ignored_rows_file, {}))
        write_json(self._config.uportal_ignored_rows_file, ignored)
        if not ignored:
            return ["No ignored Uportal games."]

        grouped: dict[str, list[dict]] = {}
        for entry in ignored.values():
            if not isinstance(entry, dict):
                continue
            date_text = str(entry.get("date", ""))
            if not date_text:
                continue
            grouped.setdefault(date_text, []).append(entry)

        if not grouped:
            return ["No ignored Uportal games."]

        lines = ["Ignored Uportal games"]
        for date in sorted(grouped.keys(), key=lambda value: dt.datetime.strptime(value, "%d.%m.%Y")):
            lines.append("")
            lines.append(self._weekday_date_label(date))
            for game in sorted(grouped[date], key=lambda item: (item.get("time", ""), float(item.get("distance_km", 9999.0)))):
                lines.append(self._ignored_line(game))

        return self._split_plain_message("\n".join(lines).strip())

    def _ignored_line(self, game: dict) -> str:
        distance = float(game.get("distance_km", 9999.0))
        shown_distance = int(distance) if distance.is_integer() else round(distance, 1)
        hall_code = str(game.get("hall", "-"))
        address = self._address_for_hall(hall_code)
        maps_url = f"https://maps.google.com/?q={quote_plus(address)}" if address else ""
        location_part = (
            f'<a href="{html.escape(maps_url, quote=True)}">{html.escape(address)}</a>'
            if maps_url
            else html.escape(address)
        )
        league_part = f"{html.escape(str(game.get('liga', '-')))} #{html.escape(str(game.get('number', '-')))}"
        detail_url = str(game.get("detail_url", ""))
        if detail_url:
            league_part = f'<a href="{html.escape(detail_url, quote=True)}">{league_part}</a>'
        priority_badge = " 🫡" if bool(game.get("is_umb_offen")) else ""
        return (
            f"👎 @ {html.escape(str(game.get('time', '-')))} {location_part} ({shown_distance} km) / "
            f"{league_part} {html.escape(str(game.get('home_team', '-')))} - {html.escape(str(game.get('away_team', '-')))}{priority_badge}"
        )

    @staticmethod
    def _split_plain_message(text: str, limit: int = 3500) -> list[str]:
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in text.splitlines():
            line_len = len(line) + 1
            if current and current_len + line_len > limit:
                chunks.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len
        if current:
            chunks.append("\n".join(current))
        return chunks
    def _manual_debug_summary(self) -> str:
        if not self._config.debug_mode:
            return ""
        get_info = getattr(self._uportal_client, "get_last_debug_info", None)
        dump_info = getattr(self._uportal_client, "dump_last_debug_artifacts", None)
        base_summary = ""
        if callable(get_info) and callable(dump_info):
            debug = get_info()
            artifacts = dump_info()
            pages = debug.get("pages", [])
            first_page = pages[0] if pages else {}

            base_summary = (
                "Uportal debug: "
                f"offene_umb_url={debug.get('offene_umb_url', '-')}, "
                f"source={debug.get('offene_umb_source', '-')}, "
                f"pages_visited={len(pages)}, "
                f"first_rows={first_page.get('rows_found', '-')}, "
                f"first_table_found={first_page.get('table_found', '-')}, "
                f"debug_json={artifacts.get('debug_json', '-')}"
            )

        if self._last_raw_rows_debug_file:
            if base_summary:
                return f"{base_summary}, rows_json={self._last_raw_rows_debug_file}"
            return f"Uportal debug: rows_json={self._last_raw_rows_debug_file}"
        return base_summary

    def _prune_seen_entries(self, seen: dict[str, dict]) -> dict[str, dict]:
        if not isinstance(seen, dict):
            return {}
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=SEEN_RETENTION_DAYS)
        kept: dict[str, dict] = {}
        for key, payload in seen.items():
            if not isinstance(payload, dict):
                continue
            timestamp = self._parse_iso_timestamp(payload.get("last_seen_at")) or self._parse_iso_timestamp(
                payload.get("first_seen_at")
            )
            if timestamp and timestamp < cutoff:
                continue
            kept[key] = payload
        return kept

    def _prune_catalog_entries(self, catalog: dict[str, dict]) -> dict[str, dict]:
        if not isinstance(catalog, dict):
            return {}
        cutoff = dt.datetime.now(BERLIN_TZ).date() - dt.timedelta(days=CATALOG_PAST_RETENTION_DAYS)
        kept: dict[str, dict] = {}
        for key, payload in catalog.items():
            if not isinstance(payload, dict):
                continue
            game_date = self._parse_game_date(payload.get("date"))
            if game_date and game_date < cutoff:
                continue
            kept[key] = payload
        return kept

    def _prune_ignored_entries(self, ignored: dict[str, dict]) -> dict[str, dict]:
        if not isinstance(ignored, dict):
            return {}
        cutoff = dt.datetime.now(BERLIN_TZ).date() - dt.timedelta(days=IGNORED_RETENTION_DAYS)
        kept: dict[str, dict] = {}
        for key, payload in ignored.items():
            if not isinstance(payload, dict):
                continue
            game_date = self._parse_game_date(payload.get("date"))
            ignored_at = self._parse_iso_timestamp(payload.get("ignored_at"))
            if game_date and game_date < cutoff:
                continue
            if ignored_at and ignored_at.date() < cutoff:
                continue
            kept[key] = payload
        return kept

    @staticmethod
    def _parse_iso_timestamp(raw: object) -> dt.datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            parsed = dt.datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)

    @staticmethod
    def _parse_game_date(raw: object) -> dt.date | None:
        if not isinstance(raw, str):
            return None
        try:
            return dt.datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError:
            return None
