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


class AccidentFeatureExtractor:
    def __init__(self, data_path: str = "data/hyderabad_accident_idx_synthetic.csv"):
        self._df = pd.read_csv(data_path)
        self._tree = KDTree(self._df[["lat", "lon"]].values)

    def extract(self, lat: float, lon: float) -> float:
        try:
            _, idx = self._tree.query([lat, lon], k=3)
            return float(self._df.iloc[idx]["accident_idx"].mean())
        except Exception as e:
            logger.error(f"Accident lookup failed: {e}")
            return 0.5


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
        self,
        segment_id: str,
        lat: float,
        lon: float,
        image_urls: Optional[List[str]] = None,
        raw_texts: Optional[List[Dict]] = None,
        computed_at: Optional[str] = None,
    ):
        from scorer import SegmentFeatures  # avoid circular import

        image_urls = image_urls or []
        raw_texts = raw_texts or []

        vision = self._vision.extract(image_urls)

        return SegmentFeatures(
            segment_id=segment_id,
            accident_idx=self._accident.extract(lat, lon),
            lighting=vision.lighting,
            crosswalk_present=vision.crosswalk_present,
            road_quality=vision.road_quality,
            incident_score=self._nlp.extract(raw_texts),
            weather_risk=self._weather.extract(lat, lon),
            computed_at=computed_at,
        )
