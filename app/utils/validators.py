import os
from datetime import datetime, timezone
from typing import Tuple, Optional


VALID_MODES    = {"safest", "balanced", "fastest"}
VALID_PROFILES = {"pedestrian", "cyclist"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_INCIDENT_TYPES = {
    "poor_lighting", "pothole", "unsafe_crossing",
    "theft", "assault", "harassment", "other",
}


def _city_bbox() -> Tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) from env, defaulting to Bengaluru."""
    raw = os.getenv("CITY_BBOX", "77.4601,12.8340,77.7782,13.1439")
    parts = [float(x) for x in raw.split(",")]
    return tuple(parts)  # (min_lon, min_lat, max_lon, max_lat)


def validate_coordinate(coord, name: str) -> Optional[str]:
    """Return error message string or None if valid."""
    if not isinstance(coord, list) or len(coord) != 2:
        return f"{name} must be a [lon, lat] array"
    lon, lat = coord
    if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))):
        return f"{name} must contain numeric values"
    return None


def within_bbox(coord) -> bool:
    lon, lat = coord
    min_lon, min_lat, max_lon, max_lat = _city_bbox()
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def validate_iso8601(value: str) -> Optional[str]:
    """Return error string or None. Value must not be in the future."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "occurred_at must be a valid ISO 8601 string"
    now = datetime.now(timezone.utc)
    if dt > now:
        return "occurred_at must not be in the future"
    return None
