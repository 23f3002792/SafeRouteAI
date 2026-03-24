# SafeRouteAI — Flask Backend

Flask API server for the SafeRouteAI MVP. Handles route generation,
per-segment safety scoring, and user incident reporting.

---

## Project structure

```
backend/
├── run.py                        # Entry point  →  flask run / gunicorn
├── requirements.txt
├── .env.example                  # Copy to .env and fill in values
├── .gitignore
└── app/
    ├── __init__.py               # create_app() factory (CORS, blueprints, extensions)
    ├── extensions.py             # Redis client + Firebase Admin SDK init
    │
    ├── api/v1/
    │   ├── route.py              # POST  /api/v1/route
    │   ├── segment.py            # GET   /api/v1/segment/<id>/score
    │   ├── report.py             # POST  /api/v1/report  (auth required)
    │   └── score.py              # POST  /score  (internal — AI engineer integration)
    │
    ├── services/
    │   ├── scoring.py            # Thin wrapper around FeatureOrchestrator + scorer
    │   └── cache.py              # Redis helpers: score cache, rate-limit counters
    │
    └── utils/
        ├── errors.py             # Standard error envelope helper
        ├── validators.py         # Coordinate, enum, ISO 8601, bbox validation
        └── auth.py               # @require_auth decorator (Firebase JWT)
```

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env — fill in OWM_API_KEY, FIREBASE_SERVICE_ACCOUNT_JSON, etc.

# 4. Start the dev server
flask --app run run --debug
# or
python run.py
```

For production use gunicorn:

```bash
gunicorn "run:app" --workers 4 --bind 0.0.0.0:8000
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `FLASK_ENV` | yes | `development` or `production` |
| `DATABASE_URL` | yes | PostgreSQL + PostGIS connection string |
| `REDIS_URL` | yes | Redis connection string |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | yes | Path to Firebase service account key JSON |
| `OSRM_BASE_URL` | yes | Base URL of the OSRM routing engine |
| `CITY_BBOX` | yes | `min_lon,min_lat,max_lon,max_lat` — request boundary |
| `OWM_API_KEY` | yes | OpenWeatherMap API key (used by AI feature extractor) |
| `FRONTEND_ORIGIN` | prod only | Allowed CORS origin in production |

---

## API endpoints

### `POST /api/v1/route` — Generate a safety-optimised route
**Auth:** None (public)

```json
// Request
{ "start": [77.5946, 12.9716], "end": [77.6101, 12.9352],
  "mode": "safest", "profile": "pedestrian" }

// Response 200
{ "route_id": "rt_a1b2c3d4", "mode": "safest", "profile": "pedestrian",
  "eta_seconds": 840, "distance_m": 1240, "safety_score": 0.82,
  "geometry": { "type": "LineString", "coordinates": [...] },
  "segments": [ { "segment_id": "seg_001", "safety_score": 0.91,
                  "contributors": [...] } ],
  "alerts": [], "computed_at": "2025-06-01T14:30:00Z" }
```

| Error code | Key | Meaning |
|---|---|---|
| 400 | VALIDATION_ERROR | Missing / invalid fields |
| 400 | OUT_OF_BOUNDS | Coordinates outside city boundary |
| 404 | NO_ROUTE_FOUND | OSRM found no path |
| 503 | ROUTING_UNAVAILABLE | OSRM engine unreachable |

---

### `GET /api/v1/segment/<segment_id>/score` — Single segment safety score
**Auth:** None (public)

```json
// Response 200
{ "segment_id": "seg_001", "osm_way_id": 123456789,
  "safety_score": 0.91,
  "contributors": [
    { "factor": "lighting",    "weight": 0.35, "value": "good"  },
    { "factor": "crime_index", "weight": 0.30, "value": 0.12    },
    { "factor": "accident",    "weight": 0.25, "value": 0.08    },
    { "factor": "weather",     "weight": 0.10, "value": "clear" }
  ],
  "last_updated": "2025-06-01T12:00:00Z" }
```

| Error code | Key | Meaning |
|---|---|---|
| 404 | SEGMENT_NOT_FOUND | segment_id not in dataset |
| 503 | DB_UNAVAILABLE | Redis / PostGIS unreachable |

---

### `POST /api/v1/report` — Submit a safety incident
**Auth:** Required — `Authorization: Bearer <firebase_id_token>`

```json
// Request
{ "location": [77.5978, 12.9654], "type": "poor_lighting",
  "description": "No street lights from the junction onward.",
  "severity": "medium", "occurred_at": "2025-06-01T20:00:00Z" }

// Response 201
{ "report_id": "rep_x9y8z7", "status": "received",
  "message": "Thank you. Your report has been queued for review.",
  "created_at": "2025-06-01T14:35:00Z" }
```

| Error code | Key | Meaning |
|---|---|---|
| 400 | VALIDATION_ERROR | Missing location / type / severity |
| 400 | INVALID_ENUM | type or severity not an allowed value |
| 401 | UNAUTHORIZED | Missing or invalid Firebase token |
| 429 | RATE_LIMITED | > 10 reports/hour for this user |

Incident type enum: `poor_lighting` · `pothole` · `unsafe_crossing` · `theft` · `assault` · `harassment` · `other`

---

### `POST /score` — Internal AI scoring endpoint
**Auth:** None (internal service call only)

```json
// Request  (matches the AI engineer's integration spec)
{ "segment_id": "seg_123", "lat": 17.385, "lon": 78.4867 }

// Response 200  (scorer.score(features).to_dict())
{ "safety_score": 0.74, "contributors": [...] }
```

---

## AI integration

`app/services/scoring.py` imports the AI engineer's modules at startup:

```python
from ai_model.core.feature_extractor import FeatureOrchestrator
from ai_model.core.scorer import get_scorer
```

Both `FeatureOrchestrator` and the scorer are singletons — they are
instantiated once when the app boots, not on every request.

The `score_segment(segment_id, lat, lon)` function is the single
call-site used by all three endpoints that need a score.

---

## Caching strategy

Redis key format and TTLs:

| Key | TTL | Used for |
|---|---|---|
| `score:<segment_id>` | 30 min | Cached safety score payload |
| `ratelimit:reports:<uid>` | 1 hour window | Report rate-limit counter |

A cache miss on `GET /segment/:id/score` or during route scoring
triggers a live scorer call and backfills the cache.

---

## Error envelope

Every error response — regardless of endpoint — uses this shape
(defined in `app/utils/errors.py`):

```json
{
  "error": {
    "code":    "VALIDATION_ERROR",
    "message": "human-readable description",
    "details": {}
  }
}
```

---

## Validation rules (from API contract)

- `start` / `end` / `location` must be `[lon, lat]` arrays within `CITY_BBOX`.
- `mode` ∈ `{safest, balanced, fastest}`.
- `profile` ∈ `{pedestrian, cyclist}` (default: `pedestrian`).
- `description` is stripped of HTML tags server-side; truncated to 500 chars.
- `occurred_at` must be a valid ISO 8601 string and must not be in the future.
- Rate limit: 10 reports per Firebase UID per hour, enforced via Redis.
