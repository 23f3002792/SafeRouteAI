import os
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 1. FEATURE VECTOR
# ============================================================


@dataclass
class SegmentFeatures:
    segment_id: str

    accident_idx: float = 0.5
    lighting: float = 0.5
    crosswalk_present: float = 0.0
    road_quality: float = 0.5
    incident_score: float = 1.0
    weather_risk: float = 1.0

    computed_at: Optional[str] = None

    def as_vector(self) -> np.ndarray:
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

    def validate(self):
        for name, value in self.__dict__.items():
            if name in ["segment_id", "computed_at"]:
                continue
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in [0,1], got {value}")


# ============================================================
# 2. OUTPUT STRUCTURES
# ============================================================


@dataclass
class Contributor:
    factor: str
    weight: float
    value: float


@dataclass
class ScoredSegment:
    segment_id: str
    safety_score: float
    contributors: List[Contributor] = field(default_factory=list)
    scoring_backend: str = "heuristic"
    last_updated: Optional[str] = None

    def to_dict(self):
        return asdict(self)


# ============================================================
# 3. HEURISTIC WEIGHTS
# ============================================================

WEIGHTS = {
    "accident_idx": 0.30,
    "lighting": 0.25,
    "incident_score": 0.15,
    "crosswalk_present": 0.10,
    "road_quality": 0.10,
    "weather_risk": 0.10,
}

WEIGHT_KEYS = list(WEIGHTS.keys())
WEIGHT_VECTOR = np.array([WEIGHTS[k] for k in WEIGHT_KEYS], dtype=np.float32)

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6


# ============================================================
# 4. HEURISTIC SCORER
# ============================================================


class HeuristicScorer:
    def score(self, features: SegmentFeatures) -> ScoredSegment:
        features.validate()

        vec = features.as_vector()

        # Weighted score
        raw_score = float(np.dot(WEIGHT_VECTOR, vec))
        safety_score = float(np.clip(raw_score, 0.0, 1.0))

        # Explainability
        contributors = [
            Contributor(factor=key, weight=WEIGHTS[key], value=float(vec[i]))
            for i, key in enumerate(WEIGHT_KEYS)
        ]

        # Sort worst factors first
        contributors.sort(key=lambda c: c.weight * (1 - c.value), reverse=True)

        return ScoredSegment(
            segment_id=features.segment_id,
            safety_score=round(safety_score, 4),
            contributors=contributors,
            scoring_backend="heuristic",
            last_updated=features.computed_at,
        )


# ============================================================
# 5. OPTIONAL XGBOOST (FUTURE UPGRADE)
# ============================================================


class XGBoostScorer:
    def __init__(self, model_path: str):
        try:
            import xgboost as xgb

            self.model = xgb.Booster()
            self.model.load_model(model_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load XGBoost model: {e}")

    def score(self, features: SegmentFeatures) -> ScoredSegment:
        import xgboost as xgb

        features.validate()
        vec = features.as_vector().reshape(1, -1)

        dmatrix = xgb.DMatrix(vec, feature_names=WEIGHT_KEYS)
        accident_prob = float(self.model.predict(dmatrix)[0])

        safety_score = float(np.clip(1.0 - accident_prob, 0.0, 1.0))

        return ScoredSegment(
            segment_id=features.segment_id,
            safety_score=round(safety_score, 4),
            scoring_backend="xgboost",
            last_updated=features.computed_at,
        )


# ============================================================
# 6. SCORER FACTORY
# ============================================================


def get_scorer():
    backend = os.getenv("SCORER_BACKEND", "heuristic").lower()

    if backend == "xgboost":
        model_path = os.getenv("XGB_MODEL_PATH")
        if not model_path:
            raise ValueError("XGB_MODEL_PATH required for xgboost backend")
        return XGBoostScorer(model_path)

    return HeuristicScorer()


# ============================================================
# 7. UTILITIES (OPTIONAL BUT USEFUL)
# ============================================================


def normalise_accident_idx(accidents_per_km: float, clip_max: float = 20.0) -> float:
    accidents_per_km = min(accidents_per_km, clip_max)
    return float(1.0 - (accidents_per_km / clip_max))
