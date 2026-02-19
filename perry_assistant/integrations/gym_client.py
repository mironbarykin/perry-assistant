from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup

from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import read_json, write_json


logger = logging.getLogger(__name__)


class GymClient:
    def __init__(self, config: AppConfig) -> None:
        self._cache_file = config.gyms_cache_file

    def get_gym_address(self, gym_id: str | None) -> str | None:
        if not gym_id:
            return None

        cache: dict[str, str] = read_json(self._cache_file, {})
        if gym_id in cache:
            return cache[gym_id]

        found = self._scrape_address(gym_id)
        if found:
            cache[gym_id] = found
            write_json(self._cache_file, cache)
        return found

    def _scrape_address(self, gym_id: str) -> str | None:
        url = "https://www.basketball-bund.net/halleSearch.do?reqCode=list"
        data = (
            "defaultview=1"
            "&verbandBezirkKreisVereinSelection.verband_id=0"
            "&verbandBezirkKreisVereinSelection.verein="
            "&spielfeldklassifikation_id=-1"
            "&bezeichnung="
            f"&kurzbezeichnung={gym_id}"
            "&postleitzahl="
            "&ort="
        )

        try:
            response = requests.post(url, data=data, timeout=20)
        except requests.RequestException as exc:
            logger.warning("Gym lookup failed for %s: %s", gym_id, exc)
            return None

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table", {"class": "sportView"})
        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:
                cols = row.find_all("td")
                if len(cols) < 5:
                    continue
                code = cols[1].get_text(strip=True).replace(" ", "")
                if code != gym_id:
                    continue
                street = cols[2].get_text(strip=True)
                postal = cols[3].get_text(strip=True)
                city = cols[4].get_text(strip=True)
                return f"{street}, {postal} {city}"
        return None

