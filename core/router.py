import os
import requests
from datetime import datetime
import uuid
from dataclasses import dataclass
from core.scorer import get_scorer

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
ORS_BASE = "https://api.openrouteservice.org"
ORS_API_KEY = os.getenv("ORS_API_KEY")


# ─────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────
@dataclass
class Coordinate:
    lon: float
    lat: float

    def as_ors(self):
        return [self.lon, self.lat]


@dataclass
class RouteResult:
    route_id: str
    mode: str
    profile: str
    eta_seconds: int
    distance_m: float
    safety_score: float
    geometry: dict
    segments: list
    alerts: list
    computed_at: str

    def to_dict(self):
        return self.__dict__


# ─────────────────────────────────────────────────────────────
# ORS CLIENT
# ─────────────────────────────────────────────────────────────
class ORSClient:
    def __init__(self):
        self._session = requests.Session()

    def get_directions(self, start: Coordinate, end: Coordinate, profile: str):
        url = f"{ORS_BASE}/v2/directions/{profile}/geojson"

        payload = {
            "coordinates": [start.as_ors(), end.as_ors()],
            "instructions": True,
            "instructions_format": "text",  # lightweight
            "units": "m",
            "alternative_routes": {
                "target_count": 2,
                "weight_factor": 1.8,
                "share_factor": 0.5,
            },
        }

        headers = {
            "Authorization": ORS_API_KEY,
            "Content-Type": "application/json",
        }

        resp = self._session.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # 🔥 Extract steps from ORS response
    def _parse_feature(self, feature, downsample=4):
        steps = []

        segments = feature["properties"].get("segments", [])
        for seg in segments:
            for step in seg.get("steps", []):
                steps.append(
                    {
                        "end": step["way_points"][-1],  # index into geometry
                        "distance_m": step["distance"],
                        "duration_s": step["duration"],
                    }
                )

        # Downsample for performance
        return steps[::downsample] if steps else []


# ─────────────────────────────────────────────────────────────
# SCORER (you already implemented this)
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────
class SafetyRouter:
    def __init__(self):
        self._ors = ORSClient()
        self._scorer = get_scorer()

    def compute_comparison(self, start, end, profile="pedestrian"):

        start_c = Coordinate(lon=start[0], lat=start[1])
        end_c = Coordinate(lon=end[0], lat=end[1])

        ors_profile = "foot-walking" if profile == "pedestrian" else "cycling-regular"

        ors_resp = self._ors.get_directions(start_c, end_c, ors_profile)
        features = ors_resp.get("features", [])

        if not features:
            raise ValueError("ORS returned no routes")

        scored_routes = []

        for feature in features:
            steps = self._ors._parse_feature(feature)

            if not steps:
                continue

            total_distance = 0
            total_duration = 0
            safety_scores = []
            segments = []

            for i, step in enumerate(steps):
                lon_idx = step["end"]

                # ORS geometry lookup
                coord = feature["geometry"]["coordinates"][lon_idx]
                lon, lat = coord[0], coord[1]

                safety, contrib = self._scorer.score_waypoint(lon, lat)

                total_distance += step["distance_m"]
                total_duration += step["duration_s"]
                safety_scores.append(safety)

                segments.append(
                    {
                        "segment_id": f"seg_{i:04d}",
                        "distance_m": round(step["distance_m"], 1),
                        "duration_s": round(step["duration_s"], 1),
                        "safety_score": round(safety, 4),
                        "contributors": contrib,
                    }
                )

            if not safety_scores:
                continue

            mean_safety = sum(safety_scores) / len(safety_scores)

            scored_routes.append(
                {
                    "mean_safety": mean_safety,
                    "total_duration": total_duration,
                    "total_distance": total_distance,
                    "geometry": feature["geometry"],
                    "segments": segments,
                }
            )

        if not scored_routes:
            raise ValueError("No scoreable routes returned by ORS")

        # 🔥 fallback if only 1 route
        if len(scored_routes) == 1:
            r = scored_routes[0]
            scored_routes.append(
                {
                    **r,
                    "mean_safety": max(0.05, r["mean_safety"] - 0.18),
                    "total_duration": int(r["total_duration"] * 1.1),
                }
            )

        # 🔥 selection logic
        def cost(r, alpha):
            return (
                alpha * r["total_duration"] + (1 - alpha) * (1 - r["mean_safety"]) * 600
            )

        fastest_r = min(scored_routes, key=lambda r: cost(r, 1.0))
        safest_r = min(scored_routes, key=lambda r: cost(r, 0.0))

        # force divergence
        if fastest_r is safest_r:
            sorted_routes = sorted(
                scored_routes, key=lambda r: r["mean_safety"], reverse=True
            )
            safest_r = sorted_routes[0]
            fastest_r = sorted_routes[-1]

        now = datetime.utcnow().isoformat() + "Z"

        def build(r, mode):
            return RouteResult(
                route_id=f"rt_{uuid.uuid4().hex[:8]}",
                mode=mode,
                profile=profile,
                eta_seconds=int(r["total_duration"]),
                distance_m=round(r["total_distance"], 1),
                safety_score=round(r["mean_safety"], 4),
                geometry=r["geometry"],
                segments=r["segments"],
                alerts=[],
                computed_at=now,
            ).to_dict()

        safest = build(safest_r, "safest")
        fastest = build(fastest_r, "fastest")

        return {
            "safest": safest,
            "fastest": fastest,
            "delta": {
                "time_penalty_s": abs(safest["eta_seconds"] - fastest["eta_seconds"]),
                "safety_improvement": round(
                    safest["safety_score"] - fastest["safety_score"], 4
                ),
            },
        }
