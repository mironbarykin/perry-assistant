from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from telegram.ext import ContextTypes

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.integrations.calendar_client import CalendarClient, parse_google_datetime
from perry_assistant.storage.json_store import read_json, write_json
from perry_assistant.utils import clean_text


WEDNESDAY_INDEX = 2
SELF_NAMES = {"miron"}
GERMAN_WEEKDAYS = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}


@dataclass(slots=True)
class ParsedGameEvent:
    event_id: str
    summary: str
    description: str
    location: str
    start: dt.datetime
    end: dt.datetime
    category: str  # referee|coach
    league: str
    team: str
    team_bucket: str
    home_or_guest: str
    referees: list[str]

    @property
    def game_date(self) -> dt.date:
        return self.start.astimezone(BERLIN_TZ).date()


@dataclass(slots=True)
class DraftMessage:
    key: str
    text: str
    game_date: dt.date


class GameMessageService:
    def __init__(self, config: AppConfig, calendar_client: CalendarClient) -> None:
        self._config = config
        self._calendar = calendar_client
        self._rules_file = config.game_message_rules_file
        self._state_file = config.game_message_state_file

    async def run_daily_scan(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        now = dt.datetime.now(BERLIN_TZ)
        state = self._load_state()
        rules = self._load_rules()

        await self._send_due_weekday_drafts(context, state, now.date())

        try:
            events = self._fetch_events(now)
            parsed = self._parse_events(events)
        except Exception as exc:  # noqa: BLE001
            await self._safe_notify_admin(context, f"Game message scan failed while fetching events: {exc}")
            self._save_state(state)
            return

        if now.weekday() == WEDNESDAY_INDEX:
            weekend_drafts = self._build_weekend_drafts(parsed, rules, now.date())
            await self._send_immediate_drafts(context, state, weekend_drafts)
            self._schedule_weekday_drafts(state, parsed, rules, now.date())
            await self._send_due_weekday_drafts(context, state, now.date())

        self._save_state(state)

    def list_upcoming_games(self, days: int = 7, now: dt.datetime | None = None) -> list[ParsedGameEvent]:
        days = max(1, days)
        start = (now or dt.datetime.now(BERLIN_TZ)).astimezone(BERLIN_TZ)
        end = start + dt.timedelta(days=days)
        events = self._calendar.get_basketball_events_between(start, end)
        parsed = self._parse_events(events)
        return sorted(
            [item for item in parsed if start <= item.start <= end],
            key=lambda item: item.start,
        )

    def build_drafts_for_selected_game(
        self,
        event_id: str,
        start_iso: str | None = None,
        now: dt.datetime | None = None,
    ) -> list[DraftMessage]:
        if not event_id.strip():
            return []

        start_filter: dt.datetime | None = None
        if isinstance(start_iso, str) and start_iso.strip():
            try:
                parsed_start = dt.datetime.fromisoformat(start_iso)
                if parsed_start.tzinfo is None:
                    parsed_start = parsed_start.replace(tzinfo=BERLIN_TZ)
                start_filter = parsed_start.astimezone(BERLIN_TZ)
            except ValueError:
                start_filter = None

        candidates = self.list_upcoming_games(days=21, now=now)
        selected = [item for item in candidates if item.event_id == event_id]
        if start_filter is not None:
            selected = [item for item in selected if item.start == start_filter]
        if not selected:
            return []

        rules = self._load_rules()
        return self._build_drafts_for_events([selected[0]], rules)

    def _fetch_events(self, now: dt.datetime) -> list[dict]:
        start = (now - dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + dt.timedelta(days=21)).replace(hour=23, minute=59, second=59, microsecond=0)
        return self._calendar.get_basketball_events_between(start, end)

    def _parse_events(self, events: list[dict]) -> list[ParsedGameEvent]:
        parsed: list[ParsedGameEvent] = []
        for event in events:
            summary = str(event.get("summary", "")).strip()
            lowered = summary.lower()
            if "referee game" not in lowered and "coach game" not in lowered:
                continue

            start_raw = event.get("start", {}).get("dateTime") if isinstance(event.get("start"), dict) else None
            end_raw = event.get("end", {}).get("dateTime") if isinstance(event.get("end"), dict) else None
            start = parse_google_datetime(start_raw)
            end = parse_google_datetime(end_raw)
            if not start:
                continue
            if not end:
                end = start + dt.timedelta(hours=2)

            category = "referee" if "referee game" in lowered else "coach"
            team = self._extract_team(summary)
            team_bucket = self._team_bucket(team)
            home_or_guest = self._extract_home_or_guest(summary)
            league = self._extract_league(summary)
            description = str(event.get("description", "") or "")
            referees = self._extract_referees(description)
            location = str(event.get("location", "") or "").strip()
            event_id = str(event.get("id") or f"{summary}|{start.isoformat()}|{location}")

            parsed.append(
                ParsedGameEvent(
                    event_id=event_id,
                    summary=summary,
                    description=description,
                    location=location,
                    start=start.astimezone(BERLIN_TZ),
                    end=end.astimezone(BERLIN_TZ),
                    category=category,
                    league=league,
                    team=team,
                    team_bucket=team_bucket,
                    home_or_guest=home_or_guest,
                    referees=referees,
                )
            )
        return parsed

    def _load_rules(self) -> dict:
        payload = read_json(self._rules_file, {})
        return payload if isinstance(payload, dict) else {}

    def _load_state(self) -> dict:
        payload = read_json(self._state_file, {})
        if not isinstance(payload, dict):
            payload = {}
        scheduled = payload.get("scheduled_weekday")
        sent = payload.get("sent_keys")
        payload["scheduled_weekday"] = scheduled if isinstance(scheduled, dict) else {}
        payload["sent_keys"] = sent if isinstance(sent, list) else []
        return payload

    def _save_state(self, state: dict) -> None:
        write_json(self._state_file, state)

    async def _send_due_weekday_drafts(self, context: ContextTypes.DEFAULT_TYPE, state: dict, today: dt.date) -> None:
        scheduled: dict = state.get("scheduled_weekday", {})
        for key, entry in list(scheduled.items()):
            if not isinstance(entry, dict):
                continue
            if entry.get("sent"):
                continue
            remind_on = self._parse_iso_date(entry.get("remind_on"))
            if not remind_on or remind_on > today:
                continue
            texts = entry.get("texts", [])
            if not isinstance(texts, list) or not texts:
                entry["sent"] = True
                continue
            sent_ok = True
            for text in texts:
                if not isinstance(text, str) or not text.strip():
                    continue
                sent = await self._safe_send_text(context, text.strip())
                sent_ok = sent_ok and sent
            if sent_ok:
                entry["sent"] = True
                self._remember_sent_key(state, key)

    async def _send_immediate_drafts(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        state: dict,
        drafts: list[DraftMessage],
    ) -> None:
        for draft in drafts:
            if self._is_sent(state, draft.key):
                continue
            sent = await self._safe_send_text(context, draft.text)
            if sent:
                self._remember_sent_key(state, draft.key)

    def _schedule_weekday_drafts(self, state: dict, events: list[ParsedGameEvent], rules: dict, today: dt.date) -> None:
        weekday_events = [event for event in events if event.game_date.weekday() <= 4]
        drafts = self._build_drafts_for_events(weekday_events, rules)
        scheduled: dict = state.get("scheduled_weekday", {})

        for draft in drafts:
            reminder_date = draft.game_date - dt.timedelta(days=3)
            if reminder_date < today:
                reminder_date = today
            schedule_key = f"weekday:{draft.key}"
            if schedule_key in scheduled:
                continue
            if self._is_sent(state, schedule_key):
                continue
            scheduled[schedule_key] = {
                "remind_on": reminder_date.isoformat(),
                "texts": [draft.text],
                "sent": False,
                "created_at": dt.datetime.now(dt.UTC).isoformat(),
            }

    def _build_weekend_drafts(self, events: list[ParsedGameEvent], rules: dict, today: dt.date) -> list[DraftMessage]:
        saturday = today + dt.timedelta((5 - today.weekday()) % 7)
        sunday = saturday + dt.timedelta(days=1)
        weekend_events = [event for event in events if event.game_date in {saturday, sunday}]
        return self._build_drafts_for_events(weekend_events, rules)

    def _build_drafts_for_events(self, events: list[ParsedGameEvent], rules: dict) -> list[DraftMessage]:
        referee = [event for event in events if event.category == "referee"]
        coach = [event for event in events if event.category == "coach"]
        drafts: list[DraftMessage] = []
        drafts.extend(self._build_referee_drafts(referee, rules))
        drafts.extend(self._build_coach_drafts(coach, rules))
        return drafts

    def _build_referee_drafts(self, events: list[ParsedGameEvent], rules: dict) -> list[DraftMessage]:
        if not events:
            return []

        by_day_loc: dict[tuple[dt.date, str], list[ParsedGameEvent]] = {}
        for event in events:
            key = (event.game_date, clean_text(event.location or "-"))
            by_day_loc.setdefault(key, []).append(event)

        drafts: list[DraftMessage] = []
        for (_, _), bucket in by_day_loc.items():
            for group in self._split_referee_merge_groups(bucket):
                games = sorted(group, key=lambda item: item.start)
                partner_names = self._partner_names_for_group(games)
                if not partner_names:
                    partner_names = [""]

                arrival_min, arrival_max = self._arrival_range(games, rules)
                for partner in partner_names:
                    text = self._render_referee_text(partner, games, arrival_min, arrival_max, rules)
                    partner_key = clean_text(partner or "generic")
                    key = f"ref:{games[0].event_id}:{games[0].game_date.isoformat()}:{partner_key}:{len(games)}"
                    drafts.append(DraftMessage(key=key, text=text, game_date=games[0].game_date))
        return drafts

    def _split_referee_merge_groups(self, bucket: list[ParsedGameEvent]) -> list[list[ParsedGameEvent]]:
        if any(not event.referees for event in bucket):
            return [bucket]
        groups: dict[tuple[str, ...], list[ParsedGameEvent]] = {}
        for event in bucket:
            signature = tuple(sorted(clean_text(name) for name in event.referees))
            groups.setdefault(signature, []).append(event)
        return list(groups.values())

    def _partner_names_for_group(self, games: list[ParsedGameEvent]) -> list[str]:
        names: list[str] = []
        for game in games:
            for name in game.referees:
                cleaned = clean_text(name)
                if cleaned in SELF_NAMES:
                    continue
                if name not in names:
                    names.append(name)
        return names

    def _arrival_range(self, games: list[ParsedGameEvent], rules: dict) -> tuple[int, int]:
        ranges: list[tuple[int, int]] = []
        entries = (
            rules.get("referee", {})
            .get("arrival_minutes_by_league_regex", [])
            if isinstance(rules, dict)
            else []
        )
        if not isinstance(entries, list):
            entries = []

        for game in games:
            league = game.league or game.summary
            selected = None
            for item in entries:
                if not isinstance(item, dict):
                    continue
                pattern = str(item.get("pattern", ""))
                try:
                    if re.search(pattern, league, flags=re.IGNORECASE):
                        selected = item
                        break
                except re.error:
                    continue
            if selected:
                minimum = int(selected.get("min", 30))
                maximum = int(selected.get("max", 40))
            else:
                minimum, maximum = 30, 40
            ranges.append((minimum, maximum))

        if not ranges:
            return 30, 40
        mins = [item[0] for item in ranges]
        maxs = [item[1] for item in ranges]
        return min(mins), max(maxs)

    def _render_referee_text(
        self,
        partner: str,
        games: list[ParsedGameEvent],
        arrival_min: int,
        arrival_max: int,
        rules: dict,
    ) -> str:
        phrases = rules.get("referee", {}).get("phrases", {}) if isinstance(rules, dict) else {}
        greetings = phrases.get("greetings", []) if isinstance(phrases, dict) else []
        arrival_phrases = phrases.get("arrival", []) if isinstance(phrases, dict) else []
        closings = phrases.get("closings", []) if isinstance(phrases, dict) else []

        greeting_tmpl = self._pick(greetings, games[0].event_id + (partner or ""), "Hi {name},")
        arrival_tmpl = self._pick(
            arrival_phrases,
            games[0].event_id + "arr",
            "Ich werde ca. {min}-{max} Minuten vor dem Tipoff da sein.",
        )
        closing_tmpl = self._pick(closings, games[0].event_id + "cls", "Bis dann! VG Miron ;)")

        partner_label = partner or "KOLLEGE"
        greeting = greeting_tmpl.format(name=partner_label)
        arrival_line = arrival_tmpl.format(min=arrival_min, max=arrival_max)
        closing = closing_tmpl
        day_label = GERMAN_WEEKDAYS[games[0].start.weekday()]
        location = self._referee_city_label(games[0].location)

        if len(games) == 1:
            game = games[0]
            time_text = game.start.strftime("%H:%M")
            body = (
                f"wir pfeifen zusammen am {day_label}, {game.league} in {location} um {time_text} Uhr."
            )
        else:
            game_parts = [f"{game.start.strftime('%H:%M')} {game.league}" for game in games]
            body = (
                f"wir pfeifen am {day_label} in {location} mehrere Spiele zusammen: "
                + ", ".join(game_parts)
                + "."
            )
        return "\n".join([greeting, body, arrival_line, closing]).strip()

    def _build_coach_drafts(self, events: list[ParsedGameEvent], rules: dict) -> list[DraftMessage]:
        drafts: list[DraftMessage] = []
        for event in sorted(events, key=lambda item: item.start):
            rule, missing_rule = self._coach_team_rule(event.team_bucket, rules)
            home_10am_override = int(rules.get("coach", {}).get("home_10am_override_minutes", 60))
            meeting_minutes = int(rule.get("meeting_minutes", 50))
            if event.home_or_guest == "home" and event.start.hour == 10:
                meeting_minutes = home_10am_override

            location_url = (
                f"https://maps.app.goo.gl/?q={quote_plus(event.location)}"
                if event.location
                else "LOCATION_PLACEHOLDER"
            )
            opponent = self._extract_opponent(event.description)
            day = GERMAN_WEEKDAYS[event.start.weekday()]
            date_text = event.start.strftime("%d.%m")
            time_text = event.start.strftime("%H:%M")
            home_guest_text = "heim" if event.home_or_guest == "home" else "ausw\u00e4rts"
            meet_text = self._meeting_phrase(meeting_minutes)
            jersey = self._jersey_placeholders(event.team_bucket, rules)
            warn = (
                f"\n[WARN: missing team rule for {event.team_bucket or 'UNKNOWN'}; fallback defaults used]"
                if missing_rule
                else ""
            )

            if bool(rule.get("send_parents", True)):
                greeting = self._pick(
                    rules.get("coach", {}).get("greetings_parents", []),
                    event.event_id + "p",
                    "Hallo zusammen!",
                )
                text = (
                    f"{greeting} Am {day} ({date_text}) um {time_text} spielen wir {home_guest_text} "
                    f"gegen {opponent}. Wir treffen uns: {meet_text} vor dem Spiel, hier: {location_url}. "
                    f"Trikots bringt {jersey['bring']} und nimmt {jersey['wash']} mit, zum Waschen! VG Miron ;){warn}"
                )
                key = f"coach:parents:{event.event_id}:{event.game_date.isoformat()}"
                drafts.append(DraftMessage(key=key, text=text, game_date=event.game_date))

            if bool(rule.get("send_players", False)):
                greeting = self._pick(
                    rules.get("coach", {}).get("greetings_players", []),
                    event.event_id + "k",
                    "Hi Team!",
                )
                text = (
                    f"{greeting} Am {day} ({date_text}) um {time_text} spielen wir {home_guest_text} "
                    f"gegen {opponent}. Treffpunkt: {meet_text} vor Tipoff, hier: {location_url}. "
                    f"Trikots bringt {jersey['bring']} und nimmt {jersey['wash']} mit, zum Waschen! VG Miron ;){warn}"
                )
                key = f"coach:players:{event.event_id}:{event.game_date.isoformat()}"
                drafts.append(DraftMessage(key=key, text=text, game_date=event.game_date))
        return drafts

    async def _safe_send_text(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
        try:
            await context.bot.send_message(
                chat_id=self._config.miron_id,
                text=text,
                disable_web_page_preview=True,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _safe_notify_admin(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        try:
            await context.bot.send_message(chat_id=self._config.miron_id, text=text)
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    def _extract_league(summary: str) -> str:
        match = re.split(r"referee game", summary, flags=re.IGNORECASE)
        value = match[0].strip(" \t👍🎖️")
        return value or "LEAGUE"

    @staticmethod
    def _extract_team(summary: str) -> str:
        match = re.search(r"\(([^)]+)\)", summary)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _team_bucket(team: str) -> str:
        if not team:
            return ""
        token = team.split("-", 1)[0].strip().upper()
        return token

    @staticmethod
    def _extract_home_or_guest(summary: str) -> str:
        lowered = summary.lower()
        if " home " in f" {lowered} ":
            return "home"
        if " guest " in f" {lowered} ":
            return "guest"
        return "guest"

    @staticmethod
    def _extract_referees(description: str) -> list[str]:
        if not description:
            return []
        match = re.search(r"Referees:\s*([^\n]+)", description, flags=re.IGNORECASE)
        if not match:
            return []
        text = match.group(1)
        names = re.findall(r"([A-Za-zÄÖÜäöüß\-]+),\s*([A-Za-zÄÖÜäöüß\-]+)", text)
        if names:
            return [first for _, first in names]
        raw_tokens = [token.strip() for token in re.split(r",|;", text)]
        filtered = []
        for token in raw_tokens:
            if not token or "mailto" in token.lower():
                continue
            if token.strip("() ").isdigit():
                continue
            filtered.append(token)
        return filtered

    @staticmethod
    def _extract_opponent(description: str) -> str:
        if not description:
            return "den Gegner"
        line = description.splitlines()[0].strip()
        if not line:
            return "den Gegner"
        segment = line.split(",", 1)[0].strip()
        if " - " in segment:
            return segment.split(" - ", 1)[1].strip() or "den Gegner"
        return segment

    @staticmethod
    def _pick(options: object, seed: str, default: str) -> str:
        if not isinstance(options, list) or not options:
            return default
        index = abs(hash(seed)) % len(options)
        value = options[index]
        return str(value)

    @staticmethod
    def _meeting_phrase(minutes: int) -> str:
        if minutes >= 60:
            return "1 Stunde"
        return f"{minutes} Minuten"

    @staticmethod
    def _parse_iso_date(raw: object) -> dt.date | None:
        if not isinstance(raw, str):
            return None
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            return None

    def _coach_team_rule(self, team_bucket: str, rules: dict) -> tuple[dict, bool]:
        team_rules = rules.get("coach", {}).get("team_rules", {}) if isinstance(rules, dict) else {}
        if isinstance(team_rules, dict) and team_bucket in team_rules and isinstance(team_rules[team_bucket], dict):
            return team_rules[team_bucket], False
        return {"meeting_minutes": 50, "send_parents": True, "send_players": False}, True

    def _jersey_placeholders(self, team_bucket: str, rules: dict) -> dict[str, str]:
        placeholders = rules.get("coach", {}).get("jersey_placeholders", {}) if isinstance(rules, dict) else {}
        if isinstance(placeholders, dict):
            item = placeholders.get(team_bucket)
            if isinstance(item, dict):
                bring = str(item.get("bring", "NAME")).strip() or "NAME"
                wash = str(item.get("wash", "NAME")).strip() or "NAME"
                return {"bring": bring, "wash": wash}
        return {"bring": "NAME", "wash": "NAME"}

    @staticmethod
    def _referee_city_label(location: str) -> str:
        raw = str(location or "").replace("\n", " ").strip(" ,")
        if not raw:
            return "CITY"

        parts = [item.strip() for item in raw.split(",") if item.strip()]
        candidate = parts[-1] if parts else raw
        candidate = re.sub(r"^\d{4,5}\s+", "", candidate).strip()

        if candidate and not re.search(r"\d", candidate):
            if len(parts) > 1 or len(candidate.split()) <= 2:
                return candidate

        postal_match = re.search(r"\b\d{4,5}\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-\s]+)$", raw)
        if postal_match:
            city = postal_match.group(1).strip()
            if city:
                return city
        return "CITY"

    @staticmethod
    def _is_sent(state: dict, key: str) -> bool:
        sent_keys = state.get("sent_keys", [])
        return isinstance(sent_keys, list) and key in sent_keys

    @staticmethod
    def _remember_sent_key(state: dict, key: str) -> None:
        sent_keys = state.setdefault("sent_keys", [])
        if not isinstance(sent_keys, list):
            sent_keys = []
            state["sent_keys"] = sent_keys
        if key not in sent_keys:
            sent_keys.append(key)
        if len(sent_keys) > 5000:
            state["sent_keys"] = sent_keys[-5000:]
