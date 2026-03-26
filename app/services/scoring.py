"""
Scoring service layer.

Imports the AI engineer's modules once at startup and exposes a single
`score_segment` function used by both the internal POST /score endpoint
and the route generation service.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../ai/scoring"))

from core.feature_extractor import FeatureOrchestrator
from core.scorer import get_scorer

# Initialised once at import time (app startup)
_orchestrator = FeatureOrchestrator()
_scorer = get_scorer()


def score_segment(segment_id: str, lat: float, lon: float) -> dict:
    """
    Build features for one segment and return scorer output as a plain dict.

    Returns a dict with at least:
        {
            "safety_score": float,      # 0.0 – 1.0
            "contributors": [...]       # list of SafetyContributor dicts
        }
    """
    features = _orchestrator.build(
        segment_id=segment_id,
        lat=lat,
        lon=lon,
        image_urls=[],  # Vision stub – ignored for MVP
        raw_texts=[],  # NLP stub  – ignored for MVP
    )
    result = _scorer.score(features)
    return result.to_dict()
