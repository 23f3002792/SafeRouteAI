import os
import logging
import pandas as pd
import numpy as np
import requests
from scipy.spatial import KDTree
from typing import Optional, List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================
# 1. ACCIDENT FEATURE EXTRACTOR (KDTree - WORKING VERSION)
# ============================================================


FEATURE_COLS = [
    "accident_idx",
    "lighting",
    "road_quality",
    "incident_score",
    "crosswalk_present",
]


@dataclass
class SpatialFeatures:
    """All 5 spatially-varying features from KDTree lookup."""

    accident_idx: float
    lighting: float
    road_quality: float
    incident_score: float
    crosswalk_present: float


class AccidentFeatureExtractor:
    """
    KDTree lookup returning ALL 5 spatial features at once.
    Replaces the old single-value extractor.
    """

    def __init__(self, data_path: str = "hyderabad_accident_idx_synthetic.csv"):
        df = pd.read_csv(data_path)
        # Validate all required columns exist
        missing = [c for c in FEATURE_COLS if c not in df.columns]
        if missing:
            raise ValueError(
                f"CSV missing columns: {missing}. Regenerate using generate_zones_6d.py"
            )
        self._df = df
        self._tree = KDTree(df[["lat", "lon"]].values)
        logger.info(f"KDTree loaded: {len(df)} points, {len(FEATURE_COLS)} features")

    def extract(self, lat: float, lon: float, k: int = 3) -> SpatialFeatures:
        """
        k-nearest neighbour lookup, averaged across k neighbours.
        Returns SpatialFeatures with all values in [0, 1].
        """
        try:
            _, idxs = self._tree.query([lat, lon], k=k)
            neighbours = self._df.iloc[idxs]
            return SpatialFeatures(
                accident_idx=float(neighbours["accident_idx"].mean()),
                lighting=float(neighbours["lighting"].mean()),
                road_quality=float(neighbours["road_quality"].mean()),
                incident_score=float(neighbours["incident_score"].mean()),
                crosswalk_present=float(neighbours["crosswalk_present"].mean()),
            )
        except Exception as e:
            logger.error(f"KDTree lookup failed for ({lat},{lon}): {e}")
            return SpatialFeatures(0.5, 0.5, 0.5, 0.8, 0.0)


# ============================================================
# 2. VISION FEATURE EXTRACTOR (STUB - SAFE DEFAULT)
# ============================================================


@dataclass
class VisionFeatures:
    lighting: float
    crosswalk_present: float
    road_quality: float


class VisionFeatureExtractor:
    def extract(self, image_urls: List[str]) -> VisionFeatures:
        # Safe defaults (won’t break system)
        return VisionFeatures(lighting=0.5, crosswalk_present=0.0, road_quality=0.5)


# ============================================================
# 3. NLP FEATURE EXTRACTOR (STUB - SAFE DEFAULT)
# ============================================================


class NLPFeatureExtractor:
    def extract(self, raw_texts: List[Dict]) -> float:
        # No incidents → safest
        return 1.0


# ============================================================
# 4. WEATHER FEATURE EXTRACTOR (FULLY IMPLEMENTED)
# ============================================================


class WeatherNormaliser:
    def normalise(
        self,
        rain_mm_per_hr: float,
        visibility_m: float,
        wind_km_per_hr: float,
        owm_weather_id: int,
    ) -> float:

        penalty = 0.0

        # Rain
        if rain_mm_per_hr > 10:
            penalty += 0.5
        elif rain_mm_per_hr > 2:
            penalty += 0.25
        elif rain_mm_per_hr > 0:
            penalty += 0.1

        # Visibility
        if visibility_m < 200:
            penalty += 0.4
        elif visibility_m < 1000:
            penalty += 0.15

        # Wind
        if wind_km_per_hr > 60:
            penalty += 0.3
        elif wind_km_per_hr > 40:
            penalty += 0.15

        # Weather type
        group = owm_weather_id // 100
        if group == 2:
            penalty += 0.4  # thunderstorm
        elif group == 7:
            penalty += 0.2  # fog

        return float(np.clip(1.0 - penalty, 0.0, 1.0))


class WeatherFeatureExtractor:
    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("OWM_API_KEY")

    def extract(self, lat: float, lon: float) -> float:
        if not self._api_key:
            logger.warning("No API key for weather. Returning default.")
            return 1.0

        try:
            resp = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": self._api_key,
                    "units": "metric",
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()

            rain = data.get("rain", {}).get("1h", 0.0)
            visibility = data.get("visibility", 10000)
            wind = data.get("wind", {}).get("speed", 0.0) * 3.6
            weather_id = data.get("weather", [{}])[0].get("id", 800)

            return WeatherNormaliser().normalise(
                rain_mm_per_hr=rain,
                visibility_m=visibility,
                wind_km_per_hr=wind,
                owm_weather_id=weather_id,
            )

        except Exception as e:
            logger.error(f"Weather API failed: {e}")
            return 1.0


# ============================================================
# 5. FEATURE ORCHESTRATOR (FINAL INTEGRATION)
# ============================================================


class FeatureOrchestrator:
    def __init__(self):
        self._accident = AccidentFeatureExtractor()
        self._vision = VisionFeatureExtractor()
        self._nlp = NLPFeatureExtractor()
        self._weather = WeatherFeatureExtractor()

    def build(
        orchestrator_self,
        segment_id: str,
        lat: float,
        lon: float,
        image_urls: Optional[list] = None,
        raw_texts: Optional[list] = None,
        computed_at: Optional[str] = None,
    ):
        """
        Drop-in replacement for FeatureOrchestrator.build().
        Now reads all 5 spatial features from KDTree instead of just accident_idx.
        """
        from core.scorer import SegmentFeatures

        spatial = orchestrator_self._accident.extract(lat, lon)
        weather = orchestrator_self._weather.extract(lat, lon)

        return SegmentFeatures(
            segment_id=segment_id,
            accident_idx=spatial.accident_idx,
            lighting=spatial.lighting,
            road_quality=spatial.road_quality,
            incident_score=spatial.incident_score,
            crosswalk_present=spatial.crosswalk_present,
            weather_risk=weather,
            computed_at=computed_at,
        )
