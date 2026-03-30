from __future__ import annotations

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# Nominatim endpoint (OpenStreetMap geocoding, rate-limited)
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"

# Google Maps API endpoint
GOOGLE_MAPS_BASE_URL = "https://maps.googleapis.com/maps/api"


def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Geocode an address to (lat, lon) using Nominatim (OpenStreetMap).
    
    Args:
        address: Street address to geocode
        
    Returns:
        (lat, lon) tuple or None if geocoding fails
    """
    try:
        response = requests.get(
            f"{NOMINATIM_BASE_URL}/search",
            params={"q": address, "format": "json"},
            timeout=10,
            headers={"User-Agent": "Perry-Assistant/1.0"}
        )
        response.raise_for_status()
        
        data = response.json()
        if not data:
            logger.warning(f"Nominatim: No results for address '{address}'")
            return None
        
        result = data[0]
        lat = float(result["lat"])
        lon = float(result["lon"])
        return (lat, lon)
    except Exception as e:
        logger.error(f"Geocoding error for '{address}': {e}")
        return None


def get_car_duration_minutes(
    origin_coords: tuple[float, float],
    dest_coords: tuple[float, float],
    ors_api_key: str
) -> int | None:
    """
    Get car routing duration using OpenRouteService.
    
    Args:
        origin_coords: (lat, lon) origin
        dest_coords: (lat, lon) destination
        ors_api_key: OpenRouteService API key
        
    Returns:
        Duration in minutes or None if route not found
    """
    try:
        # ORS uses lon/lat order, not lat/lon
        origin_lon, origin_lat = origin_coords[1], origin_coords[0]
        dest_lon, dest_lat = dest_coords[1], dest_coords[0]
        
        response = requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-car",
            json={"coordinates": [[origin_lon, origin_lat], [dest_lon, dest_lat]]},
            headers={"Authorization": ors_api_key},
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        if not data.get("routes"):
            logger.warning(f"ORS: No route found from {origin_coords} to {dest_coords}")
            return None
        
        duration_seconds = data["routes"][0]["summary"]["duration"]
        return int(duration_seconds / 60)
    except Exception as e:
        logger.error(f"ORS error: {e}")
        return None


def get_transit_journey(
    origin_coords: tuple[float, float],
    origin_address: str,
    dest_coords: tuple[float, float],
    dest_address: str,
    arrival_iso: str,
    google_api_key: str | None = None
) -> dict | None:
    """
    Get transit journey using Google Directions API with transit mode.
    
    Uses the Google Maps Directions API to find public transport routes.
    
    Args:
        origin_coords: (lat, lon) origin
        origin_address: Origin address string for display
        dest_coords: (lat, lon) destination
        dest_address: Destination address string for display
        arrival_iso: ISO8601 arrival time (e.g., "2026-03-30T18:30:00+02:00")
        google_api_key: Google Maps API key
        
    Returns:
        Dict with 'departure_iso', 'arrival_iso', 'legs_summary' or None if journey not found
    """
    if not google_api_key:
        logger.error("Google API key not provided - transit routing unavailable")
        return None
    
    try:
        from datetime import datetime as dt
        
        origin_lat, origin_lon = origin_coords
        dest_lat, dest_lon = dest_coords
        
        logger.info(f"Google Directions: Querying transit route from {origin_address} to {dest_address}")
        
        # Parse arrival time to Unix timestamp
        try:
            arrival_dt = dt.fromisoformat(arrival_iso.replace('Z', '+00:00'))
            arrival_timestamp = int(arrival_dt.timestamp())
        except Exception as e:
            logger.error(f"Failed to parse arrival time {arrival_iso}: {e}")
            return None
        
        # Query directions with transit mode
        response = requests.get(
            f"{GOOGLE_MAPS_BASE_URL}/directions/json",
            params={
                "origin": f"{origin_lat},{origin_lon}",
                "destination": f"{dest_lat},{dest_lon}",
                "mode": "transit",  # Use public transit
                "arrival_time": arrival_timestamp,  # Arrive by this time
                "key": google_api_key,
            },
            timeout=15
        )
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") != "OK":
            logger.warning(f"Google Directions: Status {data.get('status')} - {data.get('error_message', 'No message')}")
            return None
        
        if not data.get("routes") or len(data["routes"]) == 0:
            logger.warning(f"Google Directions: No route found from {origin_address} to {dest_address}")
            return None
        
        route = data["routes"][0]
        
        # Extract legs information
        legs_summary = []
        departure_time = None
        arrival_time = None
        
        for leg in route.get("legs", []):
            # Get departure time from first leg
            if departure_time is None and leg.get("departure_time"):
                dep_data = leg["departure_time"]
                # Google provides either iso8601 or unix timestamp + timezone
                if "iso8601" in dep_data:
                    departure_time = dep_data["iso8601"]
                elif "value" in dep_data:
                    # Convert Unix timestamp to ISO8601
                    # Note: We lose timezone precision but it's close enough for scheduling
                    ts = dep_data["value"]
                    tz_name = dep_data.get("time_zone", "UTC")
                    dt_obj = datetime.fromtimestamp(ts)
                    # Format as ISO8601 with Z suffix (UTC representation)
                    departure_time = dt_obj.isoformat() + "Z"
            
            # Get arrival time from last leg
            if leg.get("arrival_time"):
                arr_data = leg["arrival_time"]
                # Google provides either iso8601 or unix timestamp + timezone
                if "iso8601" in arr_data:
                    arrival_time = arr_data["iso8601"]
                elif "value" in arr_data:
                    # Convert Unix timestamp to ISO8601
                    ts = arr_data["value"]
                    tz_name = arr_data.get("time_zone", "UTC")
                    dt_obj = datetime.fromtimestamp(ts)
                    # Format as ISO8601 with Z suffix (UTC representation)
                    arrival_time = dt_obj.isoformat() + "Z"
            
            # Extract transit steps (non-walking)
            for step in leg.get("steps", []):
                if step.get("travel_mode") == "TRANSIT":
                    transit_details = step.get("transit_details", {})
                    line = transit_details.get("line", {})
                    
                    # Get transport type and route
                    vehicle_type = transit_details.get("line", {}).get("vehicle", {}).get("type", "")
                    route_short_name = line.get("short_name", line.get("name", ""))
                    
                    # Get destination stop name
                    dest_stop = transit_details.get("arrival_stop", {}).get("name", "Unknown")
                    
                    if route_short_name or vehicle_type:
                        leg_desc = ""
                        if vehicle_type:
                            # Map Google vehicle types to short codes
                            type_map = {
                                "BUS": "🚌",
                                "SUBWAY": "🚇",
                                "TRAIN": "🚆",
                                "TRAM": "🚊",
                                "RAIL": "🚂",
                            }
                            leg_desc += type_map.get(vehicle_type, "")
                        
                        if route_short_name:
                            leg_desc += f" {route_short_name}"
                        
                        if dest_stop:
                            leg_desc += f" → {dest_stop}"
                        
                        legs_summary.append(leg_desc.strip())
        
        if not departure_time or not arrival_time:
            logger.warning("Could not extract departure/arrival times from Google Directions response")
            return None
        
        return {
            "departure_iso": departure_time,
            "arrival_iso": arrival_time,
            "legs_summary": legs_summary,
        }
        
    except Exception as e:
        logger.error(f"Google Directions transit routing error: {e}")
        return None


# Old HAFAS and db-vendo-client code removed (using Google Directions API instead)
