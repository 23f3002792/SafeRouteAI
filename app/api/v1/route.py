# app/api/v1/route.py
"""
POST /api/v1/route

Generate a safety-optimised route between two coordinates.
LEGACY ROUTING IMPLEMENTATION (OSRM)

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

from core.router import SafetyRouter
from app.utils.errors import error_response
from flask import Blueprint, request, jsonify

route_bp = Blueprint("route", __name__)

_router = SafetyRouter()  # singleton


@route_bp.post("/route")
def post_route():
    data = request.get_json(force=True) or {}

    try:
        result = _router.compute(
            start=data["start"],
            end=data["end"],
            mode=data.get("mode", "balanced"),
            profile=data.get("profile", "pedestrian"),
        )
        return jsonify(result.to_dict()), 200

    except KeyError as e:
        return error_response(400, "VALIDATION_ERROR", f"Missing field: {e}")

    except ValueError as e:
        code = "OUT_OF_BOUNDS" if "outside" in str(e).lower() else "VALIDATION_ERROR"
        return error_response(400, code, str(e))

    except Exception as e:
        return error_response(503, "ROUTING_UNAVAILABLE", str(e))


@route_bp.post("/route/compare")
def compare_routes():
    data = request.get_json(force=True) or {}

    try:
        result = _router.compute_comparison(
            start=data["start"],
            end=data["end"],
            profile=data.get("profile", "pedestrian"),
        )
        return jsonify(result), 200

    except KeyError as e:
        return error_response(400, "VALIDATION_ERROR", f"Missing field: {e}")

    except ValueError as e:
        return error_response(400, "VALIDATION_ERROR", str(e))

    except Exception as e:
        return error_response(503, "ROUTING_UNAVAILABLE", str(e))
