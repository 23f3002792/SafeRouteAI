"""
Internal endpoint: POST /score

Integrates the AI engineer's FeatureOrchestrator + scorer directly.
Not versioned under /api/v1 – this is an internal service-to-service endpoint.

Request body:
    {
        "segment_id": "seg_123",
        "lat": 17.385,
        "lon": 78.4867
    }

Response:
    scorer.score(features).to_dict()
    → { "safety_score": float, "contributors": [...] }
"""
from flask import Blueprint, request, jsonify
from app.utils.errors import error_response
from app.services.scoring import score_segment

score_bp = Blueprint("score", __name__)


@score_bp.post("/score")
def score():
    data = request.get_json(silent=True) or {}

    # ── Validation ────────────────────────────────────────────────────────
    missing = [f for f in ("segment_id", "lat", "lon") if f not in data]
    if missing:
        return error_response(
            400, "VALIDATION_ERROR",
            f"Missing required fields: {', '.join(missing)}",
        )

    segment_id = data["segment_id"]
    lat        = data["lat"]
    lon        = data["lon"]

    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return error_response(400, "VALIDATION_ERROR", "lat and lon must be numeric")

    # ── Score ─────────────────────────────────────────────────────────────
    try:
        result = score_segment(segment_id=segment_id, lat=lat, lon=lon)
    except Exception as exc:
        return error_response(503, "SCORING_UNAVAILABLE", str(exc))

    return jsonify(result), 200
