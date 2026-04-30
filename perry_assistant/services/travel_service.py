from __future__ import annotations

import logging
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from perry_assistant.domain.models import TravelResult, UportalGame
from perry_assistant.integrations.travel_client import (
    geocode_address,
    get_car_duration_minutes,
    get_transit_journey,
)
from perry_assistant.storage.address_cache import AddressCache

logger = logging.getLogger(__name__)


def apply_traffic_buffer(minutes: int) -> int:
    """Apply traffic buffer: 1.2x + 5 minutes."""
    return int(minutes * 1.2) + 5


class TravelService:
    """
    Service for computing travel routes with optimizations for Google Maps API Tier 2 (5K/month).
    
    Optimizations:
    - Address caching (Nominatim results)
    - Travel result caching (prevents redundant Google API calls)
    - Skip transit for same-gym same-day games
    - API usage monitoring
    """
    
    def __init__(self, cache_file: Path, ors_api_key: str, google_api_key: str | None = None):
        self.cache = AddressCache(cache_file)
        self.ors_api_key = ors_api_key
        self.google_api_key = google_api_key
        self._travel_result_cache: dict[str, TravelResult] = {}
        self._api_call_count = 0

    def _get_coords(self, address: str) -> tuple[float, float] | None:
        """Get coordinates for an address, with caching."""
        cached = self.cache.get_cached_coords(address)
        if cached:
            return cached
        
        coords = geocode_address(address)
        if coords:
            self.cache.cache_coords(address, coords[0], coords[1])
        return coords
    
    def _get_travel_cache_key(self, origin: str, dest: str, goal_arrival: datetime, role: str) -> str:
        """Generate cache key for travel result."""
        # Use date + hour (not exact minute) to allow 1-hour reuse window
        arrival_window = goal_arrival.replace(minute=0, second=0, microsecond=0).isoformat()
        key_str = f"{origin}|{dest}|{arrival_window}|{role}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached_travel(self, key: str) -> TravelResult | None:
        """Get cached travel result."""
        return self._travel_result_cache.get(key)
    
    def _cache_travel(self, key: str, result: TravelResult) -> None:
        """Cache a travel result."""
        self._travel_result_cache[key] = result

    def compute_travel(
        self,
        origin_addr: str,
        dest_addr: str,
        goal_arrival: datetime,
        role: str,  # "referee" or "coach"
        skip_transit: bool = False,  # NEW: Skip Google API for availability checks
        game_start: datetime | None = None,  # NEW: Actual game start time (for early arrival)
        is_second_game_in_double: bool = False,  # NEW: Skip calendar event for 2nd game
    ) -> TravelResult:
        """
        Compute travel options (car and transit) for a given route and arrival deadline.
        
        Optimized for Google Maps API Tier 2 (5K/month):
        - Caches travel results to avoid redundant API calls
        - Skips transit routing during availability checks
        - Uses address caching for geocoding
        - Ensures arrival 30-40 minutes BEFORE game start (not at goal_arrival)
        
        Args:
            origin_addr: Origin address (e.g., home or gym)
            dest_addr: Destination address (e.g., gym)
            goal_arrival: Target arrival time (for API queries, legacy)
            role: "referee" (30 min buffer) or "coach" (50 min buffer)
            skip_transit: If True, only compute car (for availability checks)
            game_start: Actual game start time (use this to compute early arrival)
            is_second_game_in_double: If True, set skip_calendar_event=True
            
        Returns:
            TravelResult with car/transit options
        """
        # Check travel result cache first
        cache_key = self._get_travel_cache_key(origin_addr, dest_addr, goal_arrival, role)
        cached_result = self._get_cached_travel(cache_key)
        if cached_result:
            logger.debug(f"Travel cache hit: {origin_addr} → {dest_addr}")
            return cached_result
        
        # Early arrival: 30-40 minutes BEFORE game start
        # Use game_start if provided, otherwise use goal_arrival
        target_arrival = game_start - timedelta(minutes=35) if game_start else goal_arrival
        
        # Buffer for API queries (30 min for referee, 50 min for coach)
        buffer_minutes = 30 if role == "referee" else 50
        must_arrive_by = target_arrival - timedelta(minutes=buffer_minutes)
        
        # Geocode both addresses
        origin_coords = self._get_coords(origin_addr)
        dest_coords = self._get_coords(dest_addr)
        
        car_duration = None
        car_leave_by = None
        if origin_coords and dest_coords:
            car_duration = get_car_duration_minutes(origin_coords, dest_coords, self.ors_api_key)
            if car_duration:
                buffered_duration = apply_traffic_buffer(car_duration)
                # Leave in time to arrive 35 minutes before game (30-40 min early arrival)
                car_leave_by = target_arrival - timedelta(minutes=buffered_duration)
        
        transit_departure = None
        transit_arrival = None
        transit_legs = []
        transit_impossible = True
        
        # Skip transit if requested (e.g., during availability checks) or if no Google key
        if not skip_transit and self.google_api_key and origin_coords and dest_coords:
            journey = get_transit_journey(
                origin_coords,
                origin_addr,
                dest_coords,
                dest_addr,
                must_arrive_by.isoformat(),
                self.google_api_key
            )
            if journey:
                self._api_call_count += 1
                transit_impossible = False
                transit_departure = datetime.fromisoformat(journey["departure_iso"]) if journey["departure_iso"] else None
                transit_arrival = datetime.fromisoformat(journey["arrival_iso"]) if journey["arrival_iso"] else None
                transit_legs = journey["legs_summary"]
        
        result = TravelResult(
            origin_address=origin_addr,
            dest_address=dest_addr,
            car_duration_minutes=car_duration,
            car_leave_by=car_leave_by,
            transit_departure=transit_departure,
            transit_arrival=transit_arrival,
            transit_legs=transit_legs,
            transit_impossible=transit_impossible,
            strategy=None,
            skip_calendar_event=is_second_game_in_double,  # Skip calendar for 2nd game
        )
        
        # Cache the result
        self._cache_travel(cache_key, result)
        
        return result

    def compute_double_game_strategy(
        self,
        game_a: UportalGame,
        game_b: UportalGame,
        home_coords: dict[str, float],
    ) -> TravelResult:
        """
        Compute travel strategy for back-to-back games on the same day.
        
        Applies Home Stay Rule: if rest time >= 45 min AND rest time > (commute_a→home + commute_home→b),
        then stay home between games. Otherwise, commute directly.
        
        Args:
            game_a: First game (earlier)
            game_b: Second game (later)
            home_coords: {"lat": float, "lon": float}
            
        Returns:
            TravelResult with strategy ("home_visit" or "direct")
        """
        home_lat = home_coords["lat"]
        home_lon = home_coords["lon"]
        home_tuple = (home_lat, home_lon)
        
        # Parse game times
        try:
            # Assuming game_a.date is "YYYY-MM-DD" and game_a.time is "HH:MM"
            game_a_start = datetime.fromisoformat(f"{game_a.date}T{game_a.time}:00")
            game_b_start = datetime.fromisoformat(f"{game_b.date}T{game_b.time}:00")
        except (ValueError, AttributeError) as e:
            logger.error(f"Failed to parse game times: {e}")
            return TravelResult(
                origin_address=game_a.address or game_a.hall,
                dest_address=game_b.address or game_b.hall,
                car_duration_minutes=None,
                car_leave_by=None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy=None,
            )
        
        end_game_a = game_a_start + timedelta(minutes=120)
        
        # Get geocodes for gyms
        gym_a_addr = game_a.address or game_a.hall
        gym_b_addr = game_b.address or game_b.hall
        
        gym_a_coords = self._get_coords(gym_a_addr)
        gym_b_coords = self._get_coords(gym_b_addr)
        
        if not gym_a_coords or not gym_b_coords:
            logger.warning("Could not geocode game addresses for double-game strategy")
            return TravelResult(
                origin_address=gym_a_addr,
                dest_address=gym_b_addr,
                car_duration_minutes=None,
                car_leave_by=None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy=None,
            )
        
        # Calculate commute times
        commute_a_to_home = get_car_duration_minutes(gym_a_coords, home_tuple, self.ors_api_key)
        commute_home_to_b = get_car_duration_minutes(home_tuple, gym_b_coords, self.ors_api_key)
        commute_direct = get_car_duration_minutes(gym_a_coords, gym_b_coords, self.ors_api_key)
        
        if not all([commute_a_to_home, commute_home_to_b, commute_direct]):
            logger.warning("Could not compute all commute durations for double-game strategy")
            return TravelResult(
                origin_address=gym_a_addr,
                dest_address=gym_b_addr,
                car_duration_minutes=commute_direct,
                car_leave_by=end_game_a + timedelta(minutes=apply_traffic_buffer(commute_direct)) if commute_direct else None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy="direct",
            )
        
        buffered_a_to_home = apply_traffic_buffer(commute_a_to_home)
        buffered_home_to_b = apply_traffic_buffer(commute_home_to_b)
        buffered_direct = apply_traffic_buffer(commute_direct)
        
        rest_time = (game_b_start - end_game_a).total_seconds() / 60 - (buffered_a_to_home + buffered_home_to_b)
        
        # Home Stay Rule
        if rest_time >= 45 and rest_time > (buffered_a_to_home + buffered_home_to_b):
            strategy = "home_visit"
            origin = "Home"
            origin_coords = home_tuple
        else:
            strategy = "direct"
            origin = gym_a_addr
            origin_coords = gym_a_coords
        
        # Compute travel from origin to game_b
        journey = None
        if self.google_api_key:  # Only call Google API if key is available
            journey = get_transit_journey(
                origin_coords,
                origin,
                gym_b_coords,
                gym_b_addr,
                (game_b_start - timedelta(minutes=50)).isoformat(),  # coach buffer
                self.google_api_key  # FIXED: Pass API key
            )
            if journey:
                self._api_call_count += 1
        
        transit_legs = journey["legs_summary"] if journey else []
        
        # Determine if we should skip calendar event
        # Skip ONLY if both games are at the same gym (no commute needed)
        same_gym = (gym_a_addr.lower().strip() == gym_b_addr.lower().strip())
        skip_event = same_gym  # Skip event only if same gym
        
        return TravelResult(
            origin_address=origin,
            dest_address=gym_b_addr,
            car_duration_minutes=buffered_direct if strategy == "direct" else buffered_home_to_b,
            car_leave_by=(end_game_a + timedelta(minutes=buffered_direct)) if strategy == "direct" else (game_b_start - timedelta(minutes=buffered_home_to_b + 50)),
            transit_departure=datetime.fromisoformat(journey["departure_iso"]) if journey and journey["departure_iso"] else None,
            transit_arrival=datetime.fromisoformat(journey["arrival_iso"]) if journey and journey["arrival_iso"] else None,
            transit_legs=transit_legs,
            transit_impossible=journey is None,
            strategy=strategy,
            skip_calendar_event=skip_event,  # NEW: Skip only if same gym (no commute)
        )
    
    def get_api_stats(self) -> dict:
        """Get API usage statistics."""
        return {
            "google_api_calls": self._api_call_count,
            "cached_travel_results": len(self._travel_result_cache),
            "estimated_monthly_calls": max(self._api_call_count, 100),  # Conservative estimate
        }

    @staticmethod
    def format_travel_message(result: TravelResult) -> str:
        """Format a TravelResult into a Telegram-friendly message."""
        lines = []
        
        if result.car_duration_minutes:
            if result.car_leave_by:
                leave_time = result.car_leave_by.strftime("%H:%M")
                lines.append(f"🚗 Leave by {leave_time} ({result.car_duration_minutes} min)")
            else:
                lines.append(f"🚗 Car: {result.car_duration_minutes} min")
        else:
            lines.append("🚗 No car route found")
        
        if not result.transit_impossible:
            if result.transit_departure and result.transit_arrival:
                dep_time = result.transit_departure.strftime("%H:%M")
                arr_time = result.transit_arrival.strftime("%H:%M")
                legs_str = " → ".join(result.transit_legs) if result.transit_legs else "Transit"
                lines.append(f"🚆 {dep_time} → {arr_time} via {legs_str}")
            else:
                lines.append(f"🚆 Transit available")
        else:
            lines.append("🚨 Transit impossible")
        
        return "\n".join(lines)

    def compute_double_game_strategy(
        self,
        game_a: UportalGame,
        game_b: UportalGame,
        home_coords: dict[str, float],
    ) -> TravelResult:
        """
        Compute travel strategy for back-to-back games on the same day.
        
        Applies Home Stay Rule: if rest time >= 45 min AND rest time > (commute_a→home + commute_home→b),
        then stay home between games. Otherwise, commute directly.
        
        Args:
            game_a: First game (earlier)
            game_b: Second game (later)
            home_coords: {"lat": float, "lon": float}
            
        Returns:
            TravelResult with strategy ("home_visit" or "direct")
        """
        home_lat = home_coords["lat"]
        home_lon = home_coords["lon"]
        home_tuple = (home_lat, home_lon)
        
        # Parse game times
        try:
            # Assuming game_a.date is "YYYY-MM-DD" and game_a.time is "HH:MM"
            game_a_start = datetime.fromisoformat(f"{game_a.date}T{game_a.time}:00")
            game_b_start = datetime.fromisoformat(f"{game_b.date}T{game_b.time}:00")
        except (ValueError, AttributeError) as e:
            logger.error(f"Failed to parse game times: {e}")
            return TravelResult(
                origin_address=game_a.address or game_a.hall,
                dest_address=game_b.address or game_b.hall,
                car_duration_minutes=None,
                car_leave_by=None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy=None,
            )
        
        end_game_a = game_a_start + timedelta(minutes=120)
        
        # Get geocodes for gyms
        gym_a_addr = game_a.address or game_a.hall
        gym_b_addr = game_b.address or game_b.hall
        
        gym_a_coords = self._get_coords(gym_a_addr)
        gym_b_coords = self._get_coords(gym_b_addr)
        
        if not gym_a_coords or not gym_b_coords:
            logger.warning("Could not geocode game addresses for double-game strategy")
            return TravelResult(
                origin_address=gym_a_addr,
                dest_address=gym_b_addr,
                car_duration_minutes=None,
                car_leave_by=None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy=None,
            )
        
        # Calculate commute times
        commute_a_to_home = get_car_duration_minutes(gym_a_coords, home_tuple, self.ors_api_key)
        commute_home_to_b = get_car_duration_minutes(home_tuple, gym_b_coords, self.ors_api_key)
        commute_direct = get_car_duration_minutes(gym_a_coords, gym_b_coords, self.ors_api_key)
        
        if not all([commute_a_to_home, commute_home_to_b, commute_direct]):
            logger.warning("Could not compute all commute durations for double-game strategy")
            return TravelResult(
                origin_address=gym_a_addr,
                dest_address=gym_b_addr,
                car_duration_minutes=commute_direct,
                car_leave_by=end_game_a + timedelta(minutes=apply_traffic_buffer(commute_direct)) if commute_direct else None,
                transit_departure=None,
                transit_arrival=None,
                transit_legs=[],
                transit_impossible=True,
                strategy="direct",
            )
        
        buffered_a_to_home = apply_traffic_buffer(commute_a_to_home)
        buffered_home_to_b = apply_traffic_buffer(commute_home_to_b)
        buffered_direct = apply_traffic_buffer(commute_direct)
        
        rest_time = (game_b_start - end_game_a).total_seconds() / 60 - (buffered_a_to_home + buffered_home_to_b)
        
        # Home Stay Rule
        if rest_time >= 45 and rest_time > (buffered_a_to_home + buffered_home_to_b):
            strategy = "home_visit"
            origin = "Home"
            origin_coords = home_tuple
        else:
            strategy = "direct"
            origin = gym_a_addr
            origin_coords = gym_a_coords
        
        # Compute travel from origin to game_b
        journey = get_transit_journey(
            origin_coords,
            origin,
            gym_b_coords,
            gym_b_addr,
            (game_b_start - timedelta(minutes=50)).isoformat(),  # coach buffer
        )
        
        transit_legs = journey["legs_summary"] if journey else []
        
        return TravelResult(
            origin_address=origin,
            dest_address=gym_b_addr,
            car_duration_minutes=buffered_direct if strategy == "direct" else buffered_home_to_b,
            car_leave_by=(end_game_a + timedelta(minutes=buffered_direct)) if strategy == "direct" else (game_b_start - timedelta(minutes=buffered_home_to_b + 50)),
            transit_departure=datetime.fromisoformat(journey["departure_iso"]) if journey and journey["departure_iso"] else None,
            transit_arrival=datetime.fromisoformat(journey["arrival_iso"]) if journey and journey["arrival_iso"] else None,
            transit_legs=transit_legs,
            transit_impossible=journey is None,
            strategy=strategy,
        )

    @staticmethod
    def format_travel_message(result: TravelResult) -> str:
        """Format a TravelResult into a Telegram-friendly message."""
        lines = []
        
        if result.car_duration_minutes:
            if result.car_leave_by:
                leave_time = result.car_leave_by.strftime("%H:%M")
                lines.append(f"🚗 Leave by {leave_time} ({result.car_duration_minutes} min)")
            else:
                lines.append(f"🚗 Car: {result.car_duration_minutes} min")
        else:
            lines.append("🚗 No car route found")
        
        if not result.transit_impossible:
            if result.transit_departure and result.transit_arrival:
                dep_time = result.transit_departure.strftime("%H:%M")
                arr_time = result.transit_arrival.strftime("%H:%M")
                legs_str = " → ".join(result.transit_legs) if result.transit_legs else "Transit"
                lines.append(f"🚆 {dep_time} → {arr_time} via {legs_str}")
            else:
                lines.append(f"🚆 Transit available")
        else:
            lines.append("🚨 Transit impossible")
        
        return "\n".join(lines)
