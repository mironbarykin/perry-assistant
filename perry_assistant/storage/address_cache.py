from __future__ import annotations

from pathlib import Path

from perry_assistant.storage.json_store import read_json, write_json


class AddressCache:
    """Caches geocoded gym addresses (address string → {lat, lon}) to avoid repeat geocoding calls."""

    def __init__(self, cache_file: Path):
        self.cache_file = cache_file

    def get_cached_coords(self, address: str) -> tuple[float, float] | None:
        """Returns (lat, lon) or None if not cached."""
        cached = read_json(self.cache_file, {})
        if address in cached:
            coords = cached[address]
            return (coords["lat"], coords["lon"])
        return None

    def cache_coords(self, address: str, lat: float, lon: float) -> None:
        """Cache coordinates for an address."""
        cached = read_json(self.cache_file, {})
        cached[address] = {"lat": lat, "lon": lon}
        write_json(self.cache_file, cached)
