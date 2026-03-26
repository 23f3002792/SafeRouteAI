"""
SafeRouteAI — Routing Engine
==============================
Strategy  : OpenRouteService API for real Hyderabad road geometry
             + modified Dijkstra weighted by safety scores from scorer.py
Demo-safe : No Docker, no local OSRM, single API key in .env
Post-MVP  : Swap ORS for self-hosted OSRM by changing get_road_graph()

Author: Tech Lead
"""

from __future__ import annotations

import os
import math
import heapq
import logging
import requests
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────
ORS_BASE = "https://api.openrouteservice.org"
ORS_DIRECTIONS = f"{ORS_BASE}/v2/directions/foot-walking/geojson"
ORS_MATRIX = f"{ORS_BASE}/v2/matrix/foot-walking"
ORS_API_KEY = os.getenv("ORS_API_KEY", "")

# Alpha values per mode (matches API contract)
MODE_ALPHA = {
    "safest": 0.0,  # pure safety — ignore time
    "balanced": 0.5,
    "fastest": 1.0,  # pure time — ignore safety
}

# Hyderabad bounding box — validate all requests stay within city
HYD_BBOX = {
    "lat_min": 17.20,
    "lat_max": 17.60,
    "lon_min": 78.20,
    "lon_max": 78.70,
}


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────


@dataclass
class Coordinate:
    lon: float
    lat: float

    def in_hyderabad(self) -> bool:
        return (
            HYD_BBOX["lat_min"] <= self.lat <= HYD_BBOX["lat_max"]
            and HYD_BBOX["lon_min"] <= self.lon <= HYD_BBOX["lon_max"]
        )

    def as_ors(self) -> list[float]:
        return [self.lon, self.lat]  # ORS uses [lon, lat]


@dataclass
class RouteSegment:
    """One edge in the route — a stretch of road between two waypoints."""

    start: Coordinate
    end: Coordinate
    distance_m: float
    duration_s: float
    safety_score: float  # 0.0 (unsafe) → 1.0 (safest)
    contributors: list[dict] = field(default_factory=list)


@dataclass
class RouteResult:
    """Final response — matches POST /route API contract exactly."""

    route_id: str
    mode: str
    profile: str
    eta_seconds: int
    distance_m: float
    safety_score: float  # mean across all segments
    geometry: dict  # GeoJSON LineString
    segments: list[dict]
    alerts: list[dict]
    computed_at: str

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "mode": self.mode,
            "profile": self.profile,
            "eta_seconds": self.eta_seconds,
            "distance_m": round(self.distance_m, 1),
            "safety_score": round(self.safety_score, 4),
            "geometry": self.geometry,
            "segments": self.segments,
            "alerts": self.alerts,
            "computed_at": self.computed_at,
        }


# ─────────────────────────────────────────────────────────────────
# ORS client — real road geometry
# ─────────────────────────────────────────────────────────────────


class ORSClient:
    """
    Thin wrapper around OpenRouteService Directions API.
    Returns GeoJSON with distance + duration per step.

    Free tier: 6000 requests/day, 40 requests/minute.
    Get key at: https://openrouteservice.org/dev/#/signup
    Set ORS_API_KEY in .env
    """

    def __init__(self, api_key: str = ORS_API_KEY):
        if not api_key:
            raise ValueError(
                "ORS_API_KEY not set. Get a free key at "
                "https://openrouteservice.org/dev/#/signup and add to .env"
            )
        self._key = api_key
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": api_key,
                "Content-Type": "application/json",
            }
        )

    def get_directions(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot-walking",  # or "cycling-regular"
    ) -> dict:
        """
        Returns ORS GeoJSON FeatureCollection with route geometry + steps.
        Raises requests.HTTPError on API failure.
        """
        profile_url = f"{ORS_BASE}/v2/directions/{profile}/geojson"
        payload = {
            "coordinates": [start.as_ors(), end.as_ors()],
            "instructions": True,
            "instructions_format": "html",
            "units": "m",
        }
        resp = self._session.post(profile_url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def parse_waypoints(self, ors_geojson: dict) -> list[dict]:
        """
        Extract per-step waypoints from ORS response.
        Returns list of {start: [lon,lat], end: [lon,lat], distance_m, duration_s}
        """
        steps = []
        feature = ors_geojson["features"][0]
        coords = feature["geometry"]["coordinates"]
        segments_data = feature["properties"]["segments"]

        for seg in segments_data:
            for step in seg["steps"]:
                way_pts = step["way_points"]  # [from_idx, to_idx] into coords
                start_c = coords[way_pts[0]]
                end_c = coords[way_pts[1]]
                steps.append(
                    {
                        "start": start_c,  # [lon, lat]
                        "end": end_c,
                        "distance_m": step["distance"],
                        "duration_s": step["duration"],
                    }
                )
        return steps


# ─────────────────────────────────────────────────────────────────
# Safety scorer bridge
# ─────────────────────────────────────────────────────────────────


class RoutingScorer:
    """
    Adapts the existing scorer.py for routing use.
    Scores a (lat, lon) waypoint by looking up the nearest
    accident_idx from the KDTree CSV, then filling other
    features with defaults until real pipelines are live.

    Import path assumes this file sits alongside scorer.py and
    feature_extractor.py in ai/scoring/
    """

    def __init__(self):
        self._weather_cache: Optional[tuple[float, float]] = None  # (score, timestamp)
        self._weather_ttl = 1800  # 30 min

        # Lazy-load to avoid import errors if deps missing
        self._scorer = None
        self._orchestrator = None
        self._init_scorer()

    def _init_scorer(self):
        try:
            from scorer import get_scorer
            from feature_extractor import FeatureOrchestrator

            self._scorer = get_scorer()
            logger.info(f"Routing scorer ready: {type(self._scorer).__name__}")
        except Exception as e:
            logger.warning(f"Scorer not loaded ({e}) — using neutral scores")

    def score_waypoint(self, lon: float, lat: float) -> tuple[float, list[dict]]:
        """
        Returns (safety_score, contributors) for a lat/lon point.
        Falls back to 0.5 neutral if scorer unavailable.
        """
        if self._scorer is None:
            return 0.5, []

        try:
            from feature_extractor import (
                AccidentFeatureExtractor,
                WeatherFeatureExtractor,
                FeatureOrchestrator,
                HYDERABAD_COORDS,
            )
            from scorer import SegmentFeatures

            # Use a synthetic segment_id from coordinates
            seg_id = f"route_{lat:.4f}_{lon:.4f}"

            # Weather is cached city-wide — don't call API per waypoint
            weather = self._get_cached_weather()

            # Accident lookup via KDTree (already implemented in extractor)
            # Other features use stub defaults until pipelines are live
            features = SegmentFeatures(
                segment_id=seg_id,
                accident_idx=self._lookup_accident(lat, lon),
                lighting=0.5,  # stub — vision pipeline pending
                crosswalk_present=0.0,  # stub
                road_quality=0.6,  # stub — assume reasonable roads
                incident_score=0.8,  # stub — assume low incident base
                weather_risk=weather,
                computed_at=datetime.utcnow().isoformat() + "Z",
            )

            result = self._scorer.score(features)
            contributors = [
                {"factor": c.factor, "weight": c.weight, "value": c.value}
                for c in result.contributors
            ]
            return result.safety_score, contributors

        except Exception as e:
            logger.warning(f"Scoring failed for ({lat},{lon}): {e}")
            return 0.5, []

    def _lookup_accident(self, lat: float, lon: float) -> float:
        """KDTree lookup on synthetic CSV. Returns accident_idx in [0,1]."""
        try:
            import pandas as pd
            from scipy.spatial import KDTree
            import numpy as np

            if not hasattr(self, "_kdtree"):
                df = pd.read_csv("hyderabad_accident_idx_synthetic.csv")
                self._kd_coords = df[["lat", "lon"]].values
                self._kd_scores = df["accident_idx"].values
                self._kdtree = KDTree(self._kd_coords)
                logger.info(f"KDTree loaded: {len(df)} synthetic points")

            _, idxs = self._kdtree.query([lat, lon], k=3)
            return float(np.mean(self._kd_scores[idxs]))
        except Exception as e:
            logger.warning(f"KDTree lookup failed: {e}")
            return 0.5

    def _get_cached_weather(self) -> float:
        """City-wide weather score cached for 30 min."""
        import time

        now = time.time()
        if self._weather_cache and (now - self._weather_cache[1]) < self._weather_ttl:
            return self._weather_cache[0]

        try:
            from feature_extractor import WeatherFeatureExtractor

            score = WeatherFeatureExtractor().extract()
            self._weather_cache = (score, now)
            return score
        except Exception:
            return 1.0  # assume clear if API fails


# ─────────────────────────────────────────────────────────────────
# Modified Dijkstra
# ─────────────────────────────────────────────────────────────────


def edge_cost(duration_s: float, safety_score: float, alpha: float) -> float:
    """
    Combined edge cost for Dijkstra.

    alpha = 0.0 → pure safety optimisation (minimise risk = 1 - safety_score)
    alpha = 1.0 → pure time optimisation   (minimise duration)
    alpha = 0.5 → balanced

    Both terms are normalised to comparable scales:
    - time term   : duration in seconds (raw)
    - safety term : (1 - safety_score) × 600  (scales risk to ~seconds equivalent)
                    600 = typical Hyderabad segment crossing time in seconds
                    This makes a maximally unsafe segment cost ~10 min equivalent

    The multiplier keeps both terms in the same order of magnitude so alpha
    actually produces meaningful tradeoffs rather than one term dominating.
    """
    RISK_SCALE = 600.0
    time_cost = duration_s
    safety_cost = (1.0 - safety_score) * RISK_SCALE
    return alpha * time_cost + (1.0 - alpha) * safety_cost


def dijkstra_route(
    steps: list[dict],
    scorer: RoutingScorer,
    alpha: float,
) -> list[dict]:
    """
    Modified Dijkstra over the ORS waypoint graph.

    Each ORS step is a directed edge: start_node → end_node.
    We build a graph from waypoints and find the minimum-cost path.

    For the demo, ORS already returns A→B along real roads, so the
    graph is essentially linear (no branching). The Dijkstra adds the
    safety scoring layer and demonstrates the algorithmic story to judges.

    Post-MVP: replace with full Hyderabad OSM graph where Dijkstra
    actually explores alternative paths rather than just scoring one.
    """
    if not steps:
        return []

    # Build adjacency list from steps
    # Node key = rounded (lon, lat) string for hashability
    def node_key(coord):
        return f"{coord[0]:.5f},{coord[1]:.5f}"

    graph: dict[str, list[tuple[str, dict]]] = {}
    for step in steps:
        src = node_key(step["start"])
        dst = node_key(step["end"])
        if src not in graph:
            graph[src] = []
        graph[src].append((dst, step))

    start_key = node_key(steps[0]["start"])
    end_key = node_key(steps[-1]["end"])

    # Priority queue: (cost, node_key, path_so_far)
    pq = [(0.0, start_key, [])]
    seen = set()
    scored_steps = []

    while pq:
        cost, node, path = heapq.heappop(pq)
        if node in seen:
            continue
        seen.add(node)

        if node == end_key:
            scored_steps = path
            break

        for neighbour, step in graph.get(node, []):
            if neighbour in seen:
                continue
            lon, lat = step["end"]
            safety, contrib = scorer.score_waypoint(lon, lat)
            step_cost = edge_cost(step["duration_s"], safety, alpha)
            enriched = {**step, "safety_score": safety, "contributors": contrib}
            heapq.heappush(pq, (cost + step_cost, neighbour, path + [enriched]))

    return scored_steps


# ─────────────────────────────────────────────────────────────────
# Main router — called by Flask /route endpoint
# ─────────────────────────────────────────────────────────────────


class SafetyRouter:
    """
    Singleton — instantiate once at Flask app startup.

    Usage (backend dev wires this into the Flask route handler):

        from router import SafetyRouter
        router = SafetyRouter()   # app startup

        @app.route("/api/v1/route", methods=["POST"])
        def route():
            data   = request.get_json()
            result = router.compute(
                start   = data["start"],    # [lon, lat]
                end     = data["end"],
                mode    = data.get("mode", "balanced"),
                profile = data.get("profile", "pedestrian"),
            )
            return jsonify(result.to_dict())
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ors = ORSClient()
            cls._instance._scorer = RoutingScorer()
            logger.info("SafetyRouter initialised")
        return cls._instance

    def compute(
        self,
        start: list[float],  # [lon, lat]
        end: list[float],
        mode: str = "balanced",
        profile: str = "pedestrian",
    ) -> RouteResult:
        """
        Full pipeline: validate → ORS geometry → score → Dijkstra → response.
        Raises ValueError for invalid inputs, requests.HTTPError for ORS failures.
        """
        # 1. Validate inputs
        start_c = Coordinate(lon=start[0], lat=start[1])
        end_c = Coordinate(lon=end[0], lat=end[1])
        self._validate(start_c, end_c, mode)

        alpha = MODE_ALPHA[mode]
        ors_prof = "foot-walking" if profile == "pedestrian" else "cycling-regular"

        # 2. Get real road geometry from ORS
        logger.info(f"ORS request: {start} → {end}, mode={mode}")
        ors_resp = self._ors.get_directions(start_c, end_c, profile=ors_prof)
        steps = self._ors.parse_waypoints(ors_resp)
        if not steps:
            raise ValueError("ORS returned no route steps")

        # 3. Score + Dijkstra
        scored_steps = dijkstra_route(steps, self._scorer, alpha)

        # 4. Aggregate metrics
        total_distance = sum(s["distance_m"] for s in scored_steps)
        total_duration = sum(s["duration_s"] for s in scored_steps)
        scores = [s["safety_score"] for s in scored_steps]
        mean_safety = sum(scores) / len(scores) if scores else 0.5

        # 5. Build GeoJSON geometry from ORS response
        ors_feature = ors_resp["features"][0]
        geometry = ors_feature["geometry"]  # already a GeoJSON LineString

        # 6. Build segment list for API response
        segments = [
            {
                "segment_id": f"seg_{i:04d}",
                "distance_m": round(s["distance_m"], 1),
                "duration_s": round(s["duration_s"], 1),
                "safety_score": round(s["safety_score"], 4),
                "contributors": s.get("contributors", []),
            }
            for i, s in enumerate(scored_steps)
        ]

        # 7. Generate alerts for low-scoring segments
        alerts = [
            {
                "segment_id": seg["segment_id"],
                "type": "low_safety",
                "summary": f"Safety score {seg['safety_score']:.2f} — exercise caution",
                "severity": "high" if seg["safety_score"] < 0.3 else "medium",
            }
            for seg in segments
            if seg["safety_score"] < 0.5
        ]

        import uuid

        return RouteResult(
            route_id=f"rt_{uuid.uuid4().hex[:8]}",
            mode=mode,
            profile=profile,
            eta_seconds=int(total_duration),
            distance_m=round(total_distance, 1),
            safety_score=round(mean_safety, 4),
            geometry=geometry,
            segments=segments,
            alerts=alerts,
            computed_at=datetime.utcnow().isoformat() + "Z",
        )

    def compute_comparison(
        self,
        start: list[float],
        end: list[float],
        profile: str = "pedestrian",
    ) -> dict:
        """
        Returns BOTH safest and fastest routes in one call.
        This is the demo money shot — judges see the side-by-side comparison.

        Response shape:
        {
            "safest":  { ...RouteResult... },
            "fastest": { ...RouteResult... },
            "delta": {
                "time_penalty_s":    120,   # safest takes this much longer
                "safety_improvement": 0.23  # safest is this much safer
            }
        }
        """
        safest = self.compute(start, end, mode="safest", profile=profile)
        fastest = self.compute(start, end, mode="fastest", profile=profile)

        delta = {
            "time_penalty_s": safest.eta_seconds - fastest.eta_seconds,
            "safety_improvement": round(safest.safety_score - fastest.safety_score, 4),
        }

        return {
            "safest": safest.to_dict(),
            "fastest": fastest.to_dict(),
            "delta": delta,
        }

    @staticmethod
    def _validate(start: Coordinate, end: Coordinate, mode: str):
        if not start.in_hyderabad():
            raise ValueError(f"Start {start} is outside Hyderabad bbox")
        if not end.in_hyderabad():
            raise ValueError(f"End {end} is outside Hyderabad bbox")
        if mode not in MODE_ALPHA:
            raise ValueError(f"mode must be one of {list(MODE_ALPHA.keys())}")


# ─────────────────────────────────────────────────────────────────
# Flask integration snippet — give this to the backend dev
# ─────────────────────────────────────────────────────────────────

FLASK_INTEGRATION = '''
# ── Add to app/__init__.py or wherever Flask app is created ──────
from router import SafetyRouter
router = SafetyRouter()   # singleton, initialised once at startup

# ── Add to app/routes/route.py ───────────────────────────────────
from flask import Blueprint, request, jsonify
from router import SafetyRouter

route_bp = Blueprint("route", __name__)

@route_bp.route("/api/v1/route", methods=["POST"])
def post_route():
    data = request.get_json(force=True)
    try:
        result = SafetyRouter().compute(
            start   = data["start"],
            end     = data["end"],
            mode    = data.get("mode", "balanced"),
            profile = data.get("profile", "pedestrian"),
        )
        return jsonify(result.to_dict()), 200
    except ValueError as e:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    except Exception as e:
        return jsonify({"error": {"code": "ROUTING_ERROR", "message": str(e)}}), 503

@route_bp.route("/api/v1/route/compare", methods=["POST"])
def compare_routes():
    """Demo endpoint — returns safest + fastest side by side."""
    data = request.get_json(force=True)
    try:
        result = SafetyRouter().compute_comparison(
            start   = data["start"],
            end     = data["end"],
            profile = data.get("profile", "pedestrian"),
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    except Exception as e:
        return jsonify({"error": {"code": "ROUTING_ERROR", "message": str(e)}}), 503
'''


# ─────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with Hyderabad Charminar → Jubilee Hills (known landmarks)
    CHARMINAR = [78.4742, 17.3616]  # [lon, lat]
    JUBILEE_HILLS = [78.4098, 17.4325]

    print("SafetyRouter smoke test")
    print(f"Route: Charminar → Jubilee Hills, mode=balanced")
    print()

    # Test edge cost calculation
    print("Edge cost sanity check:")
    for alpha, label in [(0.0, "safest"), (0.5, "balanced"), (1.0, "fastest")]:
        cost = edge_cost(duration_s=300, safety_score=0.3, alpha=alpha)
        print(
            f"  alpha={alpha} ({label:8s})  duration=300s  safety=0.30  → cost={cost:.1f}"
        )

    print()
    print("Coordinate validation:")
    c = Coordinate(lon=78.4742, lat=17.3616)
    print(f"  Charminar in Hyderabad bbox: {c.in_hyderabad()}")
    c2 = Coordinate(lon=77.5946, lat=12.9716)
    print(f"  Bengaluru in Hyderabad bbox: {c2.in_hyderabad()}")

    print()
    print("ORS_API_KEY set:", bool(ORS_API_KEY))
    if not ORS_API_KEY:
        print("  → Set ORS_API_KEY in .env to run full route test")
        print("  → Get free key: https://openrouteservice.org/dev/#/signup")
    else:
        try:
            router = SafetyRouter()
            result = router.compute(CHARMINAR, JUBILEE_HILLS, mode="balanced")
            print(f"Route computed successfully:")
            print(f"  route_id    : {result.route_id}")
            print(
                f"  eta         : {result.eta_seconds}s ({result.eta_seconds // 60} min)"
            )
            print(f"  distance    : {result.distance_m:.0f} m")
            print(f"  safety_score: {result.safety_score:.4f}")
            print(f"  segments    : {len(result.segments)}")
            print(f"  alerts      : {len(result.alerts)}")
        except Exception as e:
            print(f"Error: {e}")

    print()
    print("Flask integration snippet:")
    print(FLASK_INTEGRATION)
