"""
Reusable validation helpers.

All functions return either None (valid) or a plain string error message
that callers can pass straight to error_response().
"""

import os
from datetime import datetime, timezone
from typing import Any

# ── Allowed enum values ────────────────────────────────────────────────────────

VALID_MODES = {"safest", "balanced", "fastest"}
VALID_PROFILES = {"pedestrian", "cyclist"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_INCIDENT_TYPES = {
    "poor_lighting",
    "pothole",
    "unsafe_crossing",
    "theft",
    "assault",
    "harassment",
    "other",
}

# ── Bounding boxes ─────────────────────────────────────────────────────────────


# Route endpoint bbox: read from CITY_BBOX env var (min_lon,min_lat,max_lon,max_lat).
# Defaults to Bengaluru — used by POST /api/v1/route.
def _route_bbox() -> tuple[float, float, float, float]:
    raw = os.getenv("CITY_BBOX", "77.4601,12.8340,77.7782,13.1439")
    min_lon, min_lat, max_lon, max_lat = (float(x) for x in raw.split(","))
    return min_lon, min_lat, max_lon, max_lat


# Segment / scorer bbox: hardcoded to the Hyderabad region that the
# AI accident dataset was generated for.  Any (lat, lon) outside this box
# would produce a meaningless nearest-neighbour score from the KDTree.
# Remove once we migrate to PostGIS segment-based lookup.
_HYDERABAD_BBOX = {
    "min_lat": 17.2,
    "max_lat": 17.6,
    "min_lon": 78.2,
    "max_lon": 78.7,
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def validate_coordinate(value: Any, field_name: str) -> str | None:
    """
    Validate that *value* is a two-element [lon, lat] array of numbers.
    Returns an error string or None.
    """
    if not isinstance(value, list) or len(value) != 2:
        return f"'{field_name}' must be a [lon, lat] array"
    lon, lat = value
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return f"'{field_name}' must contain numeric longitude and latitude"
    return None


def within_city_bbox(coord: list) -> bool:
    """Return True if [lon, lat] falls inside the route CITY_BBOX env var."""
    lon, lat = coord
    min_lon, min_lat, max_lon, max_lat = _route_bbox()
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def validate_segment_coords(lat: float, lon: float) -> str | None:
    """
    Validate that (lat, lon) falls inside the Hyderabad dataset bbox.

    The AI KDTree is trained on accident data within this region — coordinates
    outside it would silently score an unrelated nearest neighbour.  Returns
    an error string on failure, None when the coord is in-bounds.

    TODO (PostGIS): remove this check once segment_id maps to a DB row
    and out-of-area requests return 404 SEGMENT_NOT_FOUND instead.
    """
    bb = _HYDERABAD_BBOX
    if not (bb["min_lat"] <= lat <= bb["max_lat"]):
        return (
            f"'lat' {lat} is outside the supported region "
            f"({bb['min_lat']}–{bb['max_lat']})"
        )
    if not (bb["min_lon"] <= lon <= bb["max_lon"]):
        return (
            f"'lon' {lon} is outside the supported region "
            f"({bb['min_lon']}–{bb['max_lon']})"
        )
    return None


def validate_iso8601(value: str) -> str | None:
    """
    Return an error string if *value* is not a valid ISO 8601 UTC string,
    or if it represents a time in the future.
    Returns None when valid.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "'occurred_at' must be a valid ISO 8601 datetime string"

    if dt > datetime.now(timezone.utc):
        return "'occurred_at' must not be in the future"

    return None
