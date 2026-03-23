"""
DESIGN VERSION (NOT USED IN PRODUCTION)

This file defines the planned architecture for:
- PostGIS integration
- Vision (CLIP + BLIP2)
- NLP (RoBERTa)

Current implementation uses simplified pipelines.



SafeRouteAI — Risk Scoring Engine
==================================
Phase 1: Weighted heuristic scorer (no training data required).
Phase 2: Drop-in XGBoost replacement via SCORER_BACKEND env var.

Both phases accept the same SegmentFeatures input and return the same
ScoredSegment output — the routing engine and Flask API never change.

Author : Tech Lead
City   : Hyderabad, Telangana
"""

from __future__ import annotations

import os
import logging
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional
from enum import Enum

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Feature vector  (AI/Data engineer fills this in from pipelines)
# ─────────────────────────────────────────────────────────────────


@dataclass
class SegmentFeatures:
    """
    Normalised feature vector for one road segment.
    ALL values must be in [0.0, 1.0] where 1.0 = safest / best.

    The AI/Data engineer populates this by calling:
        - AccidentFeatureExtractor.extract(segment_id)
        - VisionFeatureExtractor.extract(image_urls)
        - NLPFeatureExtractor.extract(segment_id)
        - WeatherFeatureExtractor.extract(lat, lon)

    See feature_extractor.py for those contracts.
    """

    segment_id: str

    # ── Accident / crime  (PostGIS spatial join on GHMC/TSPC data) ──
    # Raw: accident count per km over past 3 years
    # Normalised: 1 - min_max(count, clip_max=20)
    accident_idx: float = 0.5  # 1.0 = zero accidents, 0.0 = ≥20/km

    # ── Vision features  (BLIP2 caption + CLIP similarity) ──────────
    # lighting: cosine_sim(segment_embed, "well-lit road at night")
    lighting: float = 0.5  # 1.0 = very well lit, 0.0 = pitch dark

    # crosswalk: binary from BLIP2 caption keyword detection
    crosswalk_present: float = 0.0  # 1.0 = crosswalk detected, 0.0 = absent

    # road_quality: 1 - cosine_sim(segment_embed, "pothole damaged road")
    road_quality: float = 0.5  # 1.0 = smooth, 0.0 = heavily damaged

    # ── NLP features  (RoBERTa zero-shot on geo-tagged incidents) ────
    # Raw: severity-weighted mean of incidents in last 30 days near segment
    # severity weights: low=0.2, medium=0.5, high=1.0
    # Normalised: 1 - clipped_mean
    incident_score: float = 1.0  # 1.0 = no incidents, 0.0 = severe recent incidents

    # ── Weather  (OpenWeatherMap — rule-based normalisation) ─────────
    # See WeatherNormaliser below
    weather_risk: float = 1.0  # 1.0 = clear, 0.0 = storm/flood

    # ── Metadata (not used in scoring) ───────────────────────────────
    osm_way_id: Optional[int] = None
    computed_at: Optional[str] = None  # ISO 8601

    def as_vector(self) -> np.ndarray:
        """Return the feature values in canonical weight order."""
        return np.array(
            [
                self.accident_idx,
                self.lighting,
                self.crosswalk_present,
                self.road_quality,
                self.incident_score,
                self.weather_risk,
            ],
            dtype=np.float32,
        )

    def validate(self) -> None:
        """Raise ValueError if any feature is out of [0, 1]."""
        for name, val in [
            ("accident_idx", self.accident_idx),
            ("lighting", self.lighting),
            ("crosswalk_present", self.crosswalk_present),
            ("road_quality", self.road_quality),
            ("incident_score", self.incident_score),
            ("weather_risk", self.weather_risk),
        ]:
            if not (0.0 <= val <= 1.0):
                raise ValueError(
                    f"Feature '{name}' = {val} is out of range [0, 1] "
                    f"for segment {self.segment_id}"
                )


# ─────────────────────────────────────────────────────────────────
# Scored output
# ─────────────────────────────────────────────────────────────────


@dataclass
class Contributor:
    factor: str
    weight: float
    value: float  # the normalised [0,1] feature value (not the raw input)


@dataclass
class ScoredSegment:
    """
    Output shape — matches the API contract exactly.
    This is what gets cached in Redis and returned by POST /route.
    """

    segment_id: str
    safety_score: float  # 0.0 (unsafe) – 1.0 (safest)
    contributors: list[Contributor] = field(default_factory=list)
    scoring_backend: str = "heuristic"  # "heuristic" | "xgboost"
    last_updated: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ─────────────────────────────────────────────────────────────────
# Phase 1 — Heuristic scorer
# ─────────────────────────────────────────────────────────────────

# Weights must sum to 1.0.
# Rationale:
#   accident_idx  0.30 — strongest ground-truth signal even without ML
#   lighting      0.25 — #1 perceived safety factor for pedestrians at night
#   incident_score 0.15 — user reports + NLP; lower weight until data volume grows
#   crosswalk     0.10 — infrastructure binary; meaningful but not dominant
#   road_quality  0.10 — cyclist-relevant; less critical for pedestrians
#   weather_risk  0.10 — transient; refreshed every 30 min, lower long-term weight
HEURISTIC_WEIGHTS = {
    "accident_idx": 0.30,
    "lighting": 0.25,
    "incident_score": 0.15,
    "crosswalk_present": 0.10,
    "road_quality": 0.10,
    "weather_risk": 0.10,
}
assert abs(sum(HEURISTIC_WEIGHTS.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"

WEIGHT_ORDER = list(HEURISTIC_WEIGHTS.keys())
WEIGHT_VECTOR = np.array([HEURISTIC_WEIGHTS[k] for k in WEIGHT_ORDER], dtype=np.float32)


class HeuristicScorer:
    """
    Weighted linear combination of normalised features.
    S = sum(w_i * f_i)  where all f_i in [0,1] and sum(w_i) = 1.
    """

    def score(self, features: SegmentFeatures) -> ScoredSegment:
        features.validate()
        vec = features.as_vector()
        raw_score = float(np.dot(WEIGHT_VECTOR, vec))
        # Clip for floating-point safety
        safety_score = float(np.clip(raw_score, 0.0, 1.0))

        contributors = [
            Contributor(
                factor=name, weight=HEURISTIC_WEIGHTS[name], value=float(vec[i])
            )
            for i, name in enumerate(WEIGHT_ORDER)
        ]
        # Sort descending by (weight × negative deviation from 1.0) — worst factors first
        contributors.sort(key=lambda c: c.weight * (1.0 - c.value), reverse=True)

        return ScoredSegment(
            segment_id=features.segment_id,
            safety_score=round(safety_score, 4),
            contributors=contributors,
            scoring_backend="heuristic",
            last_updated=features.computed_at,
        )


# ─────────────────────────────────────────────────────────────────
# Phase 2 — XGBoost scorer (plug-in replacement)
# ─────────────────────────────────────────────────────────────────


class XGBoostScorer:
    """
    Trained XGBoost regressor.
    Target variable: binary accident occurred on segment in next 90 days.
    Output is 1 - predicted_accident_probability → safety_score.

    Training pipeline (AI/Data engineer):
        1. Build segment feature matrix from PostGIS (same SegmentFeatures fields).
        2. Join with GHMC accident records (positive labels).
        3. Train XGBRegressor with objective='binary:logistic'.
        4. Save model with model.save_model('models/xgb_scorer_v1.ubj').
        5. Set SCORER_BACKEND=xgboost + XGB_MODEL_PATH in env.

    This class loads the saved model at startup and runs inference.
    The scoring interface is identical to HeuristicScorer.
    """

    def __init__(self, model_path: str):
        try:
            import xgboost as xgb

            self._model = xgb.Booster()
            self._model.load_model(model_path)
            logger.info(f"XGBoost scorer loaded from {model_path}")
        except ImportError:
            raise RuntimeError(
                "xgboost package not installed. Run: pip install xgboost"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load XGBoost model from {model_path}: {e}")

    def score(self, features: SegmentFeatures) -> ScoredSegment:
        import xgboost as xgb

        features.validate()
        vec = features.as_vector().reshape(1, -1)
        dmatrix = xgb.DMatrix(vec, feature_names=WEIGHT_ORDER)
        accident_prob = float(self._model.predict(dmatrix)[0])
        safety_score = float(np.clip(1.0 - accident_prob, 0.0, 1.0))

        # Feature importance from model for explainability
        importance = self._model.get_score(importance_type="gain")
        total = sum(importance.values()) or 1.0
        contributors = [
            Contributor(
                factor=name,
                weight=round(importance.get(name, 0.0) / total, 4),
                value=float(features.as_vector()[i]),
            )
            for i, name in enumerate(WEIGHT_ORDER)
        ]
        contributors.sort(key=lambda c: c.weight * (1.0 - c.value), reverse=True)

        return ScoredSegment(
            segment_id=features.segment_id,
            safety_score=round(safety_score, 4),
            contributors=contributors,
            scoring_backend="xgboost",
            last_updated=features.computed_at,
        )


# ─────────────────────────────────────────────────────────────────
# Scorer factory — selected by env var
# ─────────────────────────────────────────────────────────────────


def get_scorer() -> HeuristicScorer | XGBoostScorer:
    """
    Call once at app startup. Returns the configured scorer.

    Env vars:
        SCORER_BACKEND   : "heuristic" (default) | "xgboost"
        XGB_MODEL_PATH   : path to .ubj model file (required if backend=xgboost)
    """
    backend = os.getenv("SCORER_BACKEND", "heuristic").lower()
    if backend == "xgboost":
        model_path = os.getenv("XGB_MODEL_PATH")
        if not model_path:
            raise ValueError("XGB_MODEL_PATH must be set when SCORER_BACKEND=xgboost")
        return XGBoostScorer(model_path)
    return HeuristicScorer()


# ─────────────────────────────────────────────────────────────────
# Weather normaliser  (standalone utility, no ML needed)
# ─────────────────────────────────────────────────────────────────


class WeatherNormaliser:
    """
    Converts OpenWeatherMap current conditions to a [0,1] weather_risk score.
    1.0 = perfectly clear, 0.0 = extreme storm / flood.

    Rule table (additive penalty — final = 1.0 - total_penalty, clipped to 0):
        Rain  > 10 mm/hr   : -0.50
        Rain  2–10 mm/hr   : -0.25
        Rain  0–2 mm/hr    : -0.10
        Visibility < 200 m : -0.40
        Visibility < 1 km  : -0.15
        Wind  > 60 km/hr   : -0.30
        Wind  40–60 km/hr  : -0.15
        Thunderstorm (OWM) : -0.40 (applied if weather group = 2xx)
        Fog / mist (OWM)   : -0.20 (applied if weather group = 7xx)
    """

    RAIN_PENALTIES = [
        (10.0, 0.50),
        (2.0, 0.25),
        (0.0, 0.10),
    ]
    VISIBILITY_PENALTIES = [
        (200, 0.40),
        (1000, 0.15),
    ]
    WIND_PENALTIES = [
        (60.0, 0.30),
        (40.0, 0.15),
    ]
    OWM_GROUP_PENALTIES = {
        2: 0.40,  # Thunderstorm
        7: 0.20,  # Atmosphere (fog, mist, haze)
    }

    def normalise(
        self,
        rain_mm_per_hr: float = 0.0,
        visibility_m: float = 10000.0,
        wind_km_per_hr: float = 0.0,
        owm_weather_id: int = 800,  # 800 = clear sky
    ) -> float:
        penalty = 0.0

        for threshold, p in self.RAIN_PENALTIES:
            if rain_mm_per_hr > threshold:
                penalty += p
                break

        for threshold, p in self.VISIBILITY_PENALTIES:
            if visibility_m < threshold:
                penalty += p
                break

        for threshold, p in self.WIND_PENALTIES:
            if wind_km_per_hr > threshold:
                penalty += p
                break

        owm_group = owm_weather_id // 100
        penalty += self.OWM_GROUP_PENALTIES.get(owm_group, 0.0)

        return float(np.clip(1.0 - penalty, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────────
# Accident index normaliser  (PostGIS result → feature value)
# ─────────────────────────────────────────────────────────────────


def normalise_accident_idx(accidents_per_km: float, clip_max: float = 20.0) -> float:
    """
    accidents_per_km : raw count from PostGIS spatial join (last 3 years / segment length).
    clip_max         : value at which score bottoms out to 0.0.
    Returns          : 1.0 (zero accidents) → 0.0 (≥clip_max accidents/km).
    """
    clipped = min(accidents_per_km, clip_max)
    return float(1.0 - (clipped / clip_max))


# ─────────────────────────────────────────────────────────────────
# Incident score normaliser  (NLP pipeline result → feature value)
# ─────────────────────────────────────────────────────────────────

SEVERITY_WEIGHTS = {"low": 0.2, "medium": 0.5, "high": 1.0}


def normalise_incident_score(
    incidents: list[dict],  # [{"severity": "medium", "days_ago": 5}, ...]
    window_days: int = 30,
    decay_half_life_days: float = 7.0,
) -> float:
    """
    Compute a recency-decayed severity mean, then invert to a safety score.

    Each incident is weighted by:
        severity_weight × exp(-lambda × days_ago)
    where lambda = ln(2) / half_life.

    Returns 1.0 (no incidents) → 0.0 (severe very recent incidents).
    """
    if not incidents:
        return 1.0

    import math

    lam = math.log(2) / decay_half_life_days
    total_weight = 0.0
    weighted_severity = 0.0

    for inc in incidents:
        days_ago = float(inc.get("days_ago", window_days))
        if days_ago > window_days:
            continue
        sev = SEVERITY_WEIGHTS.get(inc.get("severity", "low"), 0.2)
        decay = math.exp(-lam * days_ago)
        w = sev * decay
        weighted_severity += w
        total_weight += decay  # normalise against total possible decay mass

    if total_weight == 0:
        return 1.0

    normalised = weighted_severity / total_weight
    return float(np.clip(1.0 - normalised, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────────
# Quick smoke test
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Simulate a moderately unsafe segment in Hyderabad old city
    weather = WeatherNormaliser()
    features = SegmentFeatures(
        segment_id="seg_hyd_001",
        osm_way_id=123456789,
        accident_idx=normalise_accident_idx(accidents_per_km=8.0),
        lighting=0.35,  # dim street lighting
        crosswalk_present=0.0,  # no crosswalk
        road_quality=0.55,  # some potholes
        incident_score=normalise_incident_score(
            [
                {"severity": "high", "days_ago": 3},
                {"severity": "medium", "days_ago": 12},
            ]
        ),
        weather_risk=weather.normalise(
            rain_mm_per_hr=3.0,
            visibility_m=800,
            wind_km_per_hr=15.0,
            owm_weather_id=501,  # moderate rain
        ),
        computed_at="2026-03-13T10:00:00Z",
    )

    scorer = get_scorer()  # HeuristicScorer (default)
    result = scorer.score(features)

    print(f"\nSegment  : {result.segment_id}")
    print(f"Backend  : {result.scoring_backend}")
    print(f"Score    : {result.safety_score:.4f}  (0=unsafe, 1=safest)")
    print("\nContributors (worst first):")
    for c in result.contributors:
        bar = "#" * int(c.value * 20)
        print(f"  {c.factor:<22} w={c.weight:.2f}  val={c.value:.3f}  [{bar:<20}]")

    print("\nRaw dict (for Redis / API response):")
    import json

    print(json.dumps(result.to_dict(), indent=2))
