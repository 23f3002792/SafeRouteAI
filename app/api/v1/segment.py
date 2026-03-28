"""
GET /api/v1/segment/<segment_id>/score?lat=<lat>&lon=<lon>

Returns the safety score for a single road segment.  Used by the
frontend heatmap to colour segments without a full route request.

MVP behaviour (KDTree / coordinate-based):
  The AI pipeline does NOT use segment_id for lookup — it scores purely
  from (lat, lon) using a KDTree of accident data.  Any valid coordinate
  pair always produces a score; there is no "segment not found" case at
  this stage.  lat and lon are therefore REQUIRED query parameters.

  Coordinates are validated against the Hyderabad dataset bbox
  (17.2–17.6 N, 78.2–78.7 E).  Points outside this range would silently
  hit an unrelated KDTree neighbour, so they are rejected with 400
  OUT_OF_BOUNDS.

  When we migrate to PostGIS, segment_id will map to a DB row and lat/lon
  will become optional (derived from the geometry).  The 404
  SEGMENT_NOT_FOUND error code is reserved for that future path.

Flow:
  1. Validate lat and lon query parameters → 400 on missing/invalid.
  2. Bbox check against Hyderabad dataset region → 400 OUT_OF_BOUNDS.
  3. Check Redis cache (30-min TTL) keyed by segment_id → return on hit.
  4. Cache miss → call AI scorer with (segment_id, lat, lon).
  5. Write result back to Redis and return.

Response (API contract §3):
    {
        "segment_id":   "seg_001",
        "osm_way_id":   123456789,
        "safety_score": 0.91,
        "contributors": [
            { "factor": "lighting",    "weight": 0.35, "value": "good"  },
            { "factor": "crime_index", "weight": 0.30, "value": 0.12    },
            { "factor": "accident",    "weight": 0.25, "value": 0.08    },
            { "factor": "weather",     "weight": 0.10, "value": "clear" }
        ],
        "last_updated": "2025-06-01T12:00:00Z"
    }

Error codes:
    400  VALIDATION_ERROR  lat or lon missing / non-numeric
    400  OUT_OF_BOUNDS     coordinates outside Hyderabad dataset region
    503  DB_UNAVAILABLE    Redis unreachable

Future (PostGIS):
    404  SEGMENT_NOT_FOUND  segment_id not found in database
"""

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from app.utils.errors import error_response
from app.utils.validators import validate_segment_coords
from app.services.cache import get_cached_score, set_cached_score
from app.services.scoring import score_segment

segment_bp = Blueprint("segment", __name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@segment_bp.get("/segment/<segment_id>/score")
def get_segment_score(segment_id: str):

    # ── 1. Validate lat/lon query params ──────────────────────────────────
    # KDTree scoring is coordinate-based, so lat and lon are required.
    # Example: GET /api/v1/segment/seg_001/score?lat=17.385&lon=78.4867
    raw_lat = request.args.get("lat")
    raw_lon = request.args.get("lon")

    if raw_lat is None or raw_lon is None:
        return error_response(
            400,
            "VALIDATION_ERROR",
            "Query parameters 'lat' and 'lon' are required",
        )
    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except ValueError:
        return error_response(
            400,
            "VALIDATION_ERROR",
            "'lat' and 'lon' must be numeric",
        )

    # ── 2. Bbox check — Hyderabad dataset region ──────────────────────────
    # Rejects coords outside the area the KDTree was trained on, preventing
    # silent nearest-neighbour scores for completely unrelated locations.
    bbox_err = validate_segment_coords(lat, lon)
    if bbox_err:
        return error_response(400, "OUT_OF_BOUNDS", bbox_err)

    # ── 3. Cache hit ──────────────────────────────────────────────────────
    try:
        cached = get_cached_score(segment_id)
    except Exception:
        return error_response(503, "DB_UNAVAILABLE", "Redis is unreachable")

    if cached:
        return jsonify(cached), 200

    # ── 4. Cache miss → score via AI layer ────────────────────────────────
    # The scorer uses (lat, lon) as the KDTree query point and always
    # returns the nearest-neighbour score — no LookupError is possible.
    try:
        scored = score_segment(segment_id=segment_id, lat=lat, lon=lon)
    except Exception as exc:
        return error_response(503, "DB_UNAVAILABLE", str(exc))

    # ── 5. Build response payload ─────────────────────────────────────────
    response = {
        "segment_id": segment_id,
        "osm_way_id": scored.get("osm_way_id"),  # None until PostGIS is wired
        "safety_score": scored["safety_score"],
        "contributors": scored.get("contributors", []),
        "last_updated": _utcnow_iso(),
    }

    # ── 6. Backfill cache (non-fatal) ─────────────────────────────────────
    try:
        set_cached_score(segment_id, response)
    except Exception:
        pass

    return jsonify(response), 200
