"""
POST /api/v1/route

Generate a safety-optimised route between two coordinates.
LEGACY ROUTING IMPLEMENTATION (OSRM)

This file contains the previous OSRM-based routing pipeline.
Replaced by ORS + SafetyRouter for demo stability.

Do NOT use in production/demo.

Auth: None (public for MVP)

Request body (API contract §3):
    {
        "start":   [78.2000,17.2000],   // [lon, lat]
        "end":     [77.6101, 12.9352],
        "mode":    "safest",             // "safest" | "balanced" | "fastest"
        "profile": "pedestrian"          // optional, default: pedestrian
    }

Flow (MVP):
    1. Validate inputs.
    2. Fetch route geometry from OSRM.
    3. Split geometry into segments and score each one (cache-first).
    4. Compute overall weighted safety score.
    5. Return route payload.

Error codes:
    400  VALIDATION_ERROR    Missing / invalid fields
    400  OUT_OF_BOUNDS       Coordinates outside CITY_BBOX
    404  NO_ROUTE_FOUND      OSRM returned no path
    503  ROUTING_UNAVAILABLE OSRM engine unreachable
"""

import os
import uuid
import statistics
from datetime import datetime, timezone

import requests
from flask import Blueprint, request, jsonify

from app.utils.errors import error_response
from app.utils.validators import (
    validate_coordinate,
    within_city_bbox,
    VALID_MODES,
    VALID_PROFILES,
)
from app.services.cache import get_cached_score, set_cached_score
from app.services.scoring import score_segment

route_bp = Blueprint("route", __name__)

SCORE_CACHE_TTL = 30 * 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── OSRM helper ───────────────────────────────────────────────────────────────


def _fetch_osrm_route(lon1, lat1, lon2, lat2, profile: str) -> dict:
    """
    Call the OSRM HTTP API and return the raw JSON response.
    Raises requests.RequestException on connection failure.
    """
    osrm_base = os.getenv("OSRM_BASE_URL", "http://localhost:5000")
    # OSRM expects lon,lat order in the URL
    url = (
        f"{osrm_base}/route/v1/{profile}/"
        f"{lon1},{lat1};{lon2},{lat2}"
        "?overview=full&geometries=geojson&steps=true"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Segment scoring ───────────────────────────────────────────────────────────


def _score_for_segment(seg_id: str, lat: float, lon: float) -> dict:
    """Return scored dict from cache or scorer."""
    cached = get_cached_score(seg_id)
    if cached:
        return cached

    scored = score_segment(segment_id=seg_id, lat=lat, lon=lon)
    payload = {
        "segment_id": seg_id,
        "safety_score": scored["safety_score"],
        "contributors": scored.get("contributors", []),
        "last_updated": _now_iso(),
    }
    try:
        set_cached_score(seg_id, payload)
    except Exception:
        pass
    return payload


# ── Route handler ─────────────────────────────────────────────────────────────


@route_bp.post("/route")
def generate_route():
    data = request.get_json(silent=True) or {}

    # ── Field presence ────────────────────────────────────────────────────
    for field in ("start", "end", "mode"):
        if field not in data:
            return error_response(400, "VALIDATION_ERROR", f"'{field}' is required")

    # ── Coordinate validation ─────────────────────────────────────────────
    for name in ("start", "end"):
        err = validate_coordinate(data[name], name)
        if err:
            return error_response(400, "VALIDATION_ERROR", err)

    # ── Mode & profile ────────────────────────────────────────────────────
    mode = data["mode"]
    profile = data.get("profile", "pedestrian")

    if mode not in VALID_MODES:
        return error_response(
            400,
            "VALIDATION_ERROR",
            f"mode must be one of: {', '.join(sorted(VALID_MODES))}",
        )
    if profile not in VALID_PROFILES:
        return error_response(
            400,
            "VALIDATION_ERROR",
            f"profile must be one of: {', '.join(sorted(VALID_PROFILES))}",
        )

    # ── Bounding-box check ────────────────────────────────────────────────
    for name in ("start", "end"):
        if not within_city_bbox(data[name]):
            return error_response(
                400,
                "OUT_OF_BOUNDS",
                f"{name} coordinates are outside the supported city boundary",
            )

    start_lon, start_lat = data["start"]
    end_lon, end_lat = data["end"]

    # ── Fetch OSRM route ──────────────────────────────────────────────────
    try:
        osrm = _fetch_osrm_route(start_lon, start_lat, end_lon, end_lat, profile)
    except requests.ConnectionError:
        return error_response(
            503, "ROUTING_UNAVAILABLE", "Routing engine is unreachable"
        )
    except requests.RequestException as exc:
        return error_response(503, "ROUTING_UNAVAILABLE", str(exc))

    if osrm.get("code") != "Ok" or not osrm.get("routes"):
        return error_response(
            404, "NO_ROUTE_FOUND", "No navigable path exists between the two points"
        )

    osrm_route = osrm["routes"][0]
    geometry = osrm_route["geometry"]  # GeoJSON LineString
    eta = int(osrm_route.get("duration", 0))
    distance = int(osrm_route.get("distance", 0))

    # ── Build per-segment scores ──────────────────────────────────────────
    # OSRM legs → steps give individual road segments.
    # We derive a segment_id and midpoint for each step.
    segments_out = []
    coords = geometry["coordinates"]  # [[lon,lat], ...]

    legs = osrm_route.get("legs", [])
    step_index = 0
    for leg in legs:
        for step in leg.get("steps", []):
            step_coords = step.get("geometry", {}).get("coordinates", [])
            if not step_coords:
                continue
            mid = step_coords[len(step_coords) // 2]
            mid_lon, mid_lat = mid[0], mid[1]

            # Deterministic segment id from OSM way reference when available,
            # otherwise index-based for MVP
            osm_ref = (step.get("name") or "").replace(" ", "_")
            seg_id = f"seg_{osm_ref}_{step_index}" if osm_ref else f"seg_{step_index}"
            step_index += 1

            scored = _score_for_segment(seg_id, mid_lat, mid_lon)
            segments_out.append(
                {
                    "segment_id": seg_id,
                    "safety_score": scored["safety_score"],
                    "contributors": scored["contributors"],
                }
            )

    # ── Overall safety score (simple mean for MVP) ────────────────────────
    if segments_out:
        overall_safety = round(
            statistics.mean(s["safety_score"] for s in segments_out), 4
        )
    else:
        overall_safety = 0.0

    # ── Alerts (MVP: none – placeholder) ─────────────────────────────────
    alerts = []

    # ── Response ──────────────────────────────────────────────────────────
    route_id = f"rt_{uuid.uuid4().hex[:8]}"
    return jsonify(
        {
            "route_id": route_id,
            "mode": mode,
            "profile": profile,
            "eta_seconds": eta,
            "distance_m": distance,
            "safety_score": overall_safety,
            "geometry": geometry,
            "segments": segments_out,
            "alerts": alerts,
            "computed_at": _now_iso(),
        }
    ), 200
