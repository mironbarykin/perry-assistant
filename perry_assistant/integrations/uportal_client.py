from __future__ import annotations

import datetime as dt
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import UportalGame
from perry_assistant.storage.json_store import write_json

# Note: UportalClient uses synchronous requests library.
# Network calls have built-in timeout (30s) but no automatic exponential backoff retry.
# For production deployments with unreliable networks, consider adding the
# retry_with_backoff decorator from utils.py or migrating to async httpx client.

DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})")
DIST_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*km", re.IGNORECASE)
PAGINATION_KEYS = {"page", "p", "start", "offset", "seite"}


class UportalClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._debug_enabled = bool(config.debug_mode)
        self._last_debug_info: dict = {}
        self._debug_pages: list[dict[str, str]] = []

    def fetch_open_games(self) -> list[UportalGame]:
        self._last_debug_info = (
            {
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "login_url": self._config.uportal_login_url,
                "pages": [],
            }
            if self._debug_enabled
            else {}
        )
        self._debug_pages = []
        if not self._config.uportal_login_name or not self._config.uportal_login_password:
            raise ValueError("UPORTAL_LOGIN_NAME and UPORTAL_LOGIN_PASSWORD are required.")

        with requests.Session() as session:
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                }
            )
            login_response = self._login(session)
            self._remember_page("post_login", login_response.url, login_response.text)
            offene_umb_url = self._discover_offene_umb_url(session, login_response)
            if self._debug_enabled:
                self._last_debug_info["offene_umb_url"] = offene_umb_url
            return self._fetch_all_pages(session, offene_umb_url)

    def _login(self, session: requests.Session) -> requests.Response:
        response = session.get(self._config.uportal_login_url, timeout=30)
        response.raise_for_status()
        self._remember_page("login_page", response.url, response.text)
        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form", {"name": "form_login"}) or soup.find("form")
        if not form:
            raise ValueError("Login form not found on Uportal page.")

        action = form.get("action") or self._config.uportal_login_url
        submit_url = urljoin(self._config.uportal_login_url, action)
        payload: dict[str, str] = {}

        for input_tag in form.find_all("input"):
            name = input_tag.get("name")
            if not name:
                continue
            payload[name] = input_tag.get("value", "")

        payload["login_name"] = self._config.uportal_login_name
        payload["login_password"] = self._config.uportal_login_password

        login_response = session.post(submit_url, data=payload, timeout=30, allow_redirects=True)
        login_response.raise_for_status()

        if self._looks_like_login_page(login_response.text):
            raise ValueError("Uportal login failed; still on login form after submit.")
        if self._debug_enabled:
            self._last_debug_info["login_submit_url"] = submit_url
        return login_response

    def _discover_offene_umb_url(self, session: requests.Session, login_response: requests.Response) -> str:
        direct = self._extract_offene_umb_url(login_response.text, login_response.url)
        if direct:
            if self._debug_enabled:
                self._last_debug_info["offene_umb_source"] = "post_login"
            return direct

        dashboard_url = urljoin(self._config.uportal_login_url, "index.php")
        dashboard_response = session.get(dashboard_url, timeout=30)
        dashboard_response.raise_for_status()
        self._remember_page("dashboard", dashboard_response.url, dashboard_response.text)
        fallback = self._extract_offene_umb_url(dashboard_response.text, dashboard_response.url)
        if fallback:
            if self._debug_enabled:
                self._last_debug_info["offene_umb_source"] = "dashboard"
            return fallback

        raise ValueError("Could not find 'offene Umb.' link after login.")

    def _fetch_all_pages(self, session: requests.Session, start_url: str) -> list[UportalGame]:
        pending = [start_url]
        visited: set[str] = set()
        games: list[UportalGame] = []

        while pending:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)

            response = session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            page_games, meta = self._parse_games_with_meta(soup, base_url=response.url)
            if self._debug_enabled:
                self._last_debug_info["pages"].append(
                    {
                        "url": response.url,
                        "status_code": response.status_code,
                        "rows_found": len(page_games),
                        "table_found": meta["table_found"],
                        "table_headers": meta["table_headers"],
                        "table_count": meta["table_count"],
                    }
                )
            self._remember_page("list_page", response.url, response.text)
            games.extend(page_games)

            # If discovery chose a non-list page, try to recover by following the canonical offene Umb. list link.
            if not page_games:
                maybe_list_url = self._extract_offene_umb_url(response.text, response.url)
                if maybe_list_url and maybe_list_url not in visited and maybe_list_url not in pending:
                    pending.insert(0, maybe_list_url)

            for page_url in self._pagination_links(soup, base_url=url, root_url=start_url):
                if page_url not in visited and page_url not in pending:
                    pending.append(page_url)

        return games

    def _parse_games(self, soup: BeautifulSoup) -> list[UportalGame]:
        games, _ = self._parse_games_with_meta(soup, base_url="")
        return games

    def _parse_games_with_meta(self, soup: BeautifulSoup, base_url: str = "") -> tuple[list[UportalGame], dict]:
        table, meta = self._find_assignments_table(soup)
        if not table:
            return [], meta

        rows = table.find_all("tr")
        games: list[UportalGame] = []
        current_date: str | None = None
        row_index = 0

        while row_index < len(rows):
            row = rows[row_index]
            cells = row.find_all("td")
            if not cells:
                row_index += 1
                continue

            if len(cells) == 1 and int(cells[0].get("colspan", "1")) >= 4:
                current_date = self._extract_date(cells[0].get_text(" ", strip=True)) or current_date
                row_index += 1
                continue

            parsed_block = self._parse_three_row_block(rows, row_index, current_date, base_url)
            if parsed_block:
                game, consumed_rows = parsed_block
                games.append(game)
                row_index += consumed_rows
                continue

            parsed_legacy = self._parse_legacy_row(row, current_date, base_url)
            if parsed_legacy:
                games.append(parsed_legacy)
                row_index += 1
                continue

            row_index += 1

        return games, meta

    def _parse_three_row_block(
        self,
        rows,
        row_index: int,
        current_date: str | None,
        base_url: str,
    ) -> tuple[UportalGame, int] | None:
        row_a = rows[row_index]
        cells_a = row_a.find_all("td")
        if len(cells_a) != 4:
            return None

        liga = cells_a[0].get_text(" ", strip=True)
        number = cells_a[1].get_text(" ", strip=True)
        date_time_text = cells_a[2].get_text(" ", strip=True)
        hall = cells_a[3].get_text(" ", strip=True)
        date_text = self._extract_date(date_time_text) or current_date
        time_text = self._extract_time(date_time_text)
        if not liga or not number or not hall or not date_text or not time_text:
            return None

        if row_index + 2 >= len(rows):
            return None

        row_b = rows[row_index + 1]
        row_c = rows[row_index + 2]
        cells_b = row_b.find_all("td")
        cells_c = row_c.find_all("td")
        if not cells_b or len(cells_c) < 2:
            return None

        teams_text = " ".join(cell.get_text(" ", strip=True) for cell in cells_b)
        home_team, away_team = self._split_teams(teams_text)
        if not home_team or not away_team:
            return None

        ust = cells_c[0].get_text(" ", strip=True)
        referee_text = ""
        for cell in cells_c:
            candidate = cell.get_text(" ", strip=True)
            if "ursp" in candidate.lower():
                referee_text = candidate
                break
        if not referee_text:
            referee_text = cells_c[1].get_text(" ", strip=True)
        original_referee = re.sub(r"^\s*ursp\.\s*:\s*", "", referee_text, flags=re.IGNORECASE).strip()
        distance_km = 9999.0
        for cell in reversed(cells_c):
            distance_cell = cell.get_text(" ", strip=True)
            if DIST_RE.search(distance_cell):
                distance_km = self._extract_distance(distance_cell)
                break

        detail_id = self._extract_detail_id(row_a)
        if not detail_id:
            detail_id = self._extract_detail_id(row_b) or self._extract_detail_id(row_c)
        detail_url = self._extract_detail_url(row_a, base_url)
        if not detail_url:
            detail_url = self._extract_detail_url(row_b, base_url) or self._extract_detail_url(row_c, base_url)

        return (
            UportalGame(
                detail_id=detail_id,
                liga=liga,
                number=number,
                home_team=home_team,
                away_team=away_team,
                date=date_text,
                time=time_text,
                hall=hall,
                original_referee=original_referee,
                ust=ust,
                distance_km=distance_km,
                detail_url=detail_url,
                is_umb_offen=self._is_row_umb_offen(row_a),
            ),
            3,
        )

    def _parse_legacy_row(self, row, current_date: str | None, base_url: str) -> UportalGame | None:
        cells = row.find_all("td")
        if len(cells) < 11:
            return None

        date_text = self._extract_date(cells[5].get_text(" ", strip=True)) or current_date
        time_text = self._extract_time(cells[6].get_text(" ", strip=True))
        if not date_text or not time_text:
            return None

        detail_id = self._extract_detail_id(row)
        detail_url = self._extract_detail_url(row, base_url)
        return UportalGame(
            detail_id=detail_id,
            liga=cells[0].get_text(" ", strip=True),
            number=cells[1].get_text(" ", strip=True),
            home_team=cells[2].get_text(" ", strip=True),
            away_team=cells[4].get_text(" ", strip=True),
            date=date_text,
            time=time_text,
            hall=cells[7].get_text(" ", strip=True),
            original_referee=cells[8].get_text(" ", strip=True),
            ust=cells[9].get_text(" ", strip=True),
            distance_km=self._extract_distance(cells[10].get_text(" ", strip=True)),
            detail_url=detail_url,
            is_umb_offen=self._is_row_umb_offen(row),
        )

    @staticmethod
    def _split_teams(teams_text: str) -> tuple[str, str]:
        cleaned = re.sub(r"\s+", " ", teams_text or "").strip()
        if " - " in cleaned:
            left, right = cleaned.split(" - ", 1)
            return left.strip(), right.strip()
        if "-" in cleaned:
            left, right = cleaned.split("-", 1)
            return left.strip(), right.strip()
        return "", ""

    def _find_assignments_table(self, soup: BeautifulSoup):
        # Prefer the content column when present, but fall back to any table with the expected header set.
        search_roots = []
        content = soup.select_one("#col3_content")
        if content:
            search_roots.append(content)
        search_roots.append(soup)

        total_tables = 0
        for root in search_roots:
            for table in root.find_all("table"):
                total_tables += 1
                headers = [header.get_text(" ", strip=True).lower() for header in table.find_all("th")]
                has_liga = any("liga" in header for header in headers)
                has_number = any("nr" in header for header in headers)
                has_heim = any("heim" in header for header in headers)
                has_gast = any("gast" in header for header in headers)
                has_halle = any("halle" in header for header in headers)
                has_datum = any("datum" in header for header in headers)
                has_zeit = any("zeit" in header for header in headers)

                # Compact tables may expose one combined header "Datum/Zeit".
                is_legacy = has_liga and has_number and has_heim and has_gast and has_datum and has_zeit
                is_compact = has_liga and has_number and has_halle and has_datum
                if is_legacy or is_compact:
                    return table, {
                        "table_found": True,
                        "table_headers": sorted(set(headers)),
                        "table_count": total_tables,
                    }
        return None, {
            "table_found": False,
            "table_headers": [],
            "table_count": total_tables,
        }

    def _pagination_links(self, soup: BeautifulSoup, base_url: str, root_url: str) -> set[str]:
        root = urlparse(root_url)
        links: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            if "offene_umbesetzungen" not in href:
                continue
            candidate = urljoin(base_url, href)
            parsed = urlparse(candidate)
            if parsed.netloc != root.netloc:
                continue
            query_keys = set(parse_qs(parsed.query).keys())
            if "id" in query_keys and not (query_keys & PAGINATION_KEYS):
                continue
            if query_keys & PAGINATION_KEYS or "id" not in query_keys:
                links.add(candidate)
        return links

    @staticmethod
    def _extract_offene_umb_url(html: str, base_url: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[tuple[int, str]] = []

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            if not href:
                continue

            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            query = parse_qs(parsed.query)
            label = " ".join(anchor.stripped_strings).lower()

            sm_value = (query.get("sm") or [""])[0]
            has_id = "id" in query
            has_zugang = "zugang" in query

            if "offene umb" in label:
                score = 0
            elif sm_value == "offene_umbesetzungen":
                score = 1
            elif "offene_umbesetzungen" in href:
                score = 2
            else:
                continue

            # Prefer the list page over detail pages and links carrying explicit user access scope.
            if has_id:
                score += 10
            if has_zugang:
                score -= 1

            candidates.append((score, absolute))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = DATE_RE.search(text or "")
        return match.group(1) if match else None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        match = TIME_RE.search(text or "")
        if not match:
            return None
        value = match.group(1)
        hour, minute = value.split(":")
        return f"{int(hour):02d}:{minute}"

    @staticmethod
    def _extract_distance(text: str) -> float:
        match = DIST_RE.search(text or "")
        if not match:
            return 9999.0
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _extract_detail_id(row) -> str:
        for anchor in row.find_all("a", href=True):
            parsed = urlparse(anchor["href"])
            values = parse_qs(parsed.query).get("id")
            if values and values[0]:
                return values[0]
        return ""

    @staticmethod
    def _extract_detail_url(row, base_url: str) -> str:
        for anchor in row.find_all("a", href=True):
            href = anchor.get("href")
            if not href:
                continue
            parsed = urlparse(href)
            values = parse_qs(parsed.query).get("id")
            if values and values[0]:
                return urljoin(base_url, href) if base_url else href
        return ""

    @staticmethod
    def _is_row_umb_offen(row) -> bool:
        classes = row.get("class") or []
        return any(str(value).strip().lower() == "row_umb_offen" for value in classes)

    @staticmethod
    def _looks_like_login_page(body: str) -> bool:
        lowered = body.lower()
        return "name=\"form_login\"" in lowered and "login_password" in lowered

    def get_last_debug_info(self) -> dict:
        if not self._debug_enabled:
            return {}
        return dict(self._last_debug_info)

    def dump_last_debug_artifacts(self) -> dict:
        if not self._debug_enabled:
            return {}
        timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        directory = self._config.logs_dir / "uportal_debug"
        directory.mkdir(parents=True, exist_ok=True)

        debug_json_path = directory / f"{timestamp}_debug.json"
        write_json(debug_json_path, self._last_debug_info)

        html_paths: list[str] = []
        for index, page in enumerate(self._debug_pages[:5], start=1):
            safe_label = re.sub(r"[^a-z0-9_-]", "_", page["label"].lower())
            html_path = directory / f"{timestamp}_{index:02d}_{safe_label}.html"
            html_path.write_text(page["html"], encoding="utf-8", errors="ignore")
            html_paths.append(str(html_path))

        return {
            "debug_json": str(debug_json_path),
            "html_files": html_paths,
        }

    def _remember_page(self, label: str, url: str, html: str) -> None:
        if not self._debug_enabled:
            return
        if len(self._debug_pages) >= 8:
            return
        self._debug_pages.append(
            {
                "label": label,
                "url": url,
                "html": html,
            }
        )
