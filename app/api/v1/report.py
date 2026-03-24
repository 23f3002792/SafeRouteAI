"""
POST /api/v1/report

Accepts a user-submitted safety incident, validates it, enforces a rate
limit (10 reports/user/hour via Redis), then writes to Firebase Firestore.

Auth: Required – Firebase ID token in Authorization: Bearer <token>

Request body (from API contract §3):
    {
        "location":    [77.5978, 12.9654],   // [lon, lat]
        "type":        "poor_lighting",
        "description": "No street lights from the junction onward.",
        "severity":    "medium",
        "occurred_at": "2025-06-01T20:00:00Z"   // optional
    }

Response:
    {
        "report_id":  "rep_x9y8z7",
        "status":     "received",
        "message":    "Thank you. Your report has been queued for review.",
        "created_at": "2025-06-01T14:35:00Z"
    }

Error codes:
    400  VALIDATION_ERROR   Missing location / type / severity
    400  INVALID_ENUM       type or severity not in allowed set
    401  UNAUTHORIZED       Missing or invalid Firebase token
    429  RATE_LIMITED       > 10 reports/hour
"""
import re
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from firebase_admin import firestore

from app.utils.auth import require_auth
from app.utils.errors import error_response
from app.utils.validators import (
    validate_coordinate,
    validate_iso8601,
    VALID_SEVERITIES,
    VALID_INCIDENT_TYPES,
)
from app.services.cache import check_and_increment_report_rate

report_bp = Blueprint("report", __name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@report_bp.post("/report")
@require_auth
def submit_report():
    data = request.get_json(silent=True) or {}

    # ── Required field presence ───────────────────────────────────────────
    for field in ("location", "type", "severity"):
        if field not in data:
            return error_response(
                400, "VALIDATION_ERROR", f"'{field}' is required"
            )

    # ── Coordinate validation ─────────────────────────────────────────────
    coord_err = validate_coordinate(data["location"], "location")
    if coord_err:
        return error_response(400, "VALIDATION_ERROR", coord_err)

    # ── Enum validation ───────────────────────────────────────────────────
    if data["type"] not in VALID_INCIDENT_TYPES:
        return error_response(
            400, "INVALID_ENUM",
            f"type must be one of: {', '.join(sorted(VALID_INCIDENT_TYPES))}",
        )
    if data["severity"] not in VALID_SEVERITIES:
        return error_response(
            400, "INVALID_ENUM",
            f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}",
        )

    # ── Optional field: occurred_at ───────────────────────────────────────
    occurred_at = data.get("occurred_at", _now_iso())
    ts_err = validate_iso8601(occurred_at)
    if ts_err:
        return error_response(400, "VALIDATION_ERROR", ts_err)

    # ── Description: strip HTML, enforce 500-char limit ───────────────────
    description = _strip_html(data.get("description", ""))[:500]

    # ── Rate limiting (10 reports/user/hour) ──────────────────────────────
    uid = g.uid
    try:
        allowed = check_and_increment_report_rate(uid)
    except Exception:
        allowed = True  # Redis failure is non-fatal for rate-limiting
    if not allowed:
        return error_response(
            429, "RATE_LIMITED", "You have exceeded 10 reports per hour"
        )

    # ── Write to Firestore ─────────────────────────────────────────────────
    report_id  = f"rep_{uuid.uuid4().hex[:6]}"
    created_at = _now_iso()
    lon, lat   = data["location"]

    doc = {
        "report_id":   report_id,
        "uid":         uid,
        "location":    firestore.GeoPoint(lat, lon),   # Firestore: lat first
        "type":        data["type"],
        "description": description,
        "severity":    data["severity"],
        "occurred_at": occurred_at,
        "created_at":  created_at,
        "status":      "received",
        "nlp_label":   None,
    }

    try:
        db = firestore.client()
        db.collection("incident_reports").document(report_id).set(doc)
    except Exception as exc:
        return error_response(503, "DB_UNAVAILABLE", f"Firestore write failed: {exc}")

    return jsonify({
        "report_id":  report_id,
        "status":     "received",
        "message":    "Thank you. Your report has been queued for review.",
        "created_at": created_at,
    }), 201
