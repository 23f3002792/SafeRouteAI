"""
GET /api/v1/segment/<segment_id>/score

Returns the pre-computed safety score for a single road segment.
Checks Redis cache first (30-min TTL); on a miss, calls the AI scorer
and backfills the cache.

Response shape (from API contract §3):
    {
        "segment_id":   "seg_001",
        "osm_way_id":   123456789,
        "safety_score": 0.91,
        "contributors": [
            { "factor": "lighting",     "weight": 0.35, "value": "good" },
            { "factor": "crime_index",  "weight": 0.30, "value": 0.12   },
            { "factor": "accident",     "weight": 0.25, "value": 0.08   },
            { "factor": "weather",      "weight": 0.10, "value": "clear"}
        ],
        "last_updated": "2025-06-01T12:00:00Z"
    }

Error codes:
    404  SEGMENT_NOT_FOUND   segment_id does not exist
    503  DB_UNAVAILABLE      PostGIS or Redis is unreachable
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from app.utils.errors import error_response
from app.services.cache import get_cached_score, set_cached_score
from app.services.scoring import score_segment

segment_bp = Blueprint("segment", __name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@segment_bp.get("/segment/<segment_id>/score")
def get_segment_score(segment_id: str):
    # ── Cache hit ─────────────────────────────────────────────────────────
    try:
        cached = get_cached_score(segment_id)
    except Exception:
        return error_response(503, "DB_UNAVAILABLE", "Redis is unreachable")

    if cached:
        return jsonify(cached), 200

    # ── Cache miss → call AI scorer ───────────────────────────────────────
    # NOTE: For MVP the scorer derives lat/lon from the KDTree via segment_id.
    # We pass placeholder coords (0.0, 0.0); the orchestrator resolves the real
    # position from the dataset using the segment_id key.
    try:
        score_data = score_segment(
            segment_id=segment_id,
            lat=0.0,
            lon=0.0,
        )
    except LookupError:
        # scorer raises LookupError when segment_id is not in the dataset
        return error_response(404, "SEGMENT_NOT_FOUND",
                              f"segment_id '{segment_id}' does not exist")
    except Exception as exc:
        return error_response(503, "DB_UNAVAILABLE", str(exc))

    # ── Build response shape ──────────────────────────────────────────────
    response = {
        "segment_id":   segment_id,
        "osm_way_id":   score_data.get("osm_way_id"),   # may be None for MVP
        "safety_score": score_data["safety_score"],
        "contributors": score_data.get("contributors", []),
        "last_updated": _now_iso(),
    }

    # ── Backfill cache ────────────────────────────────────────────────────
    try:
        set_cached_score(segment_id, response)
    except Exception:
        pass  # cache write failure is non-fatal

    return jsonify(response), 200
