# SafeRouteAI – AI-Powered Smart Navigation for Pedestrian & Cyclist Safety

SafeRouteAI is an **AI-powered navigation system** that recommends the safest routes for pedestrians and cyclists.  
Unlike traditional navigation apps that only optimize for speed, SafeRouteAI incorporates **real-world safety factors** such as:
- Accident & crime data
- Weather conditions
- Lighting and road quality from street-level images
- Real-time incident reports from news and social media

---

## What It Does ?

Cities are getting crowded, and navigation apps like Google Maps only optimize for speed, not safety. Pedestrians and cyclists often face unsafe routes (poor lighting, lack of sidewalks, high accident zones).

**SafeRouteAI solves this by**:

1. **Collecting real-world data**: Accident reports, crime statistics, weather APIs, traffic feeds, and OpenStreetMap data.

2. **Analyzing risk factors** with Hugging Face models:

    - Detect poorly lit or unsafe areas from **Image-to-Text** street view images.

    - Use **Text Classification** + **Zero-Shot Classification** on local news/Twitter feeds to detect safety incidents (accidents, thefts, harassment).

    - Use **Reinforcement Learning** to dynamically recommend routes balancing speed vs safety.

**Output**: A **safety-optimized navigation app** for cyclists/pedestrians, with an interactive map showing “safest” and “riskiest” paths in real-time.

---

## System Architecture & Implementation Plan

### 1. High-level Architecture:

 ![Flow diagram](Flowchart.png)

## Tech Stack
 
| Layer | Technology |
|---|---|
| **Backend** | Python 3.11, Flask, SQLAlchemy, Firebase Admin SDK |
| **Database** | PostgreSQL + PostGIS (road segments, safety scores) |
| **Auth & Reports** | Firebase Auth + Firestore |
| **Cache** | Redis (safety score TTL: 30 min) |
| **Routing engine** | OSRM / GraphHopper |
| **Frontend** | Vite, Vue.js, JavaScript |
| **Map rendering** | Mapbox GL JS / Leaflet |
| **Vision AI** | BLIP2, CLIP (Hugging Face) |
| **NLP AI** | RoBERTa, T5 (Hugging Face) |
| **Risk scoring** | XGBoost + PostGIS feature extraction |
| **RL routing** | Stable-Baselines3 (post-MVP) |
| **Data pipeline** | Python scripts + Cron (MVP) / Airflow (future) |
| **Containerisation** | Docker + Docker Compose |
 
---
 
## API — Key Endpoints (v1)
 
All endpoints are prefixed `/api/v1/`. Full contract in [`API_Contract_v1.docx`](./API_Contract_v1.docx).
 
### `POST /api/v1/route`
Generate a safety-optimised route between two coordinates.
 
```json
// Request
{
  "start":   [77.5946, 12.9716],
  "end":     [77.6101, 12.9352],
  "mode":    "safest",
  "profile": "pedestrian"
}
 
// Response (abbreviated)
{
  "route_id":     "rt_a1b2c3d4",
  "eta_seconds":  840,
  "safety_score": 0.82,
  "geometry":     { "type": "LineString", "coordinates": [...] },
  "segments":     [ { "segment_id": "seg_001", "safety_score": 0.91, "contributors": [...] } ]
}
```
 
**Mode values**: `"safest"` · `"balanced"` · `"fastest"`
 
### `GET /api/v1/segment/:segment_id/score`
Fetch the safety score and contributing factors for a single road segment. Used by the frontend heatmap.
 
### `POST /api/v1/report` *(auth required)*
Submit a user-reported safety incident (poor lighting, pothole, theft, etc.). Reports feed the NLP retraining pipeline.
 
---
 
## Safety Scoring Model
 
Each road segment receives a score from **0.0** (unsafe) to **1.0** (safest), computed from four weighted factors:
 
| Factor | Weight | Source |
|---|---|---|
| Lighting quality | 35% | BLIP2 / CLIP vision inference on street images |
| Crime index | 30% | City open data crime statistics |
| Accident history | 25% | Government accident report databases |
| Weather conditions | 10% | OpenWeatherMap real-time API |
 
Weights are configurable and will be tuned against historical accident ground truth.
 
---
 
## Data Sources
 
- **Road geometry** — OpenStreetMap via Overpass API
- **Street images** — Mapillary (open) / Google Street View (where permitted)
- **Accident & crime data** — City open data portals (CSV / JSON)
- **Social / news** — Twitter API (geotagged) + news RSS feeds
- **Weather** — OpenWeatherMap API
 
---
 
## Repository Structure
 
```
SafeRouteAI/
├── backend/
│   ├── app/
│   │   ├── routes/          # Flask route handlers
│   │   ├── models/          # SQLAlchemy models
│   │   ├── services/        # Routing, scoring, cache logic
│   │   └── utils/
│   ├── migrations/          # Alembic DB migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # Vue components
│   │   ├── views/           # Page views
│   │   ├── composables/     # API + map logic
│   │   └── mock/            # Mock API responses (dev)
│   └── vite.config.js
├── ai/
│   ├── vision/              # BLIP2 / CLIP pipeline
│   ├── nlp/                 # RoBERTa / T5 pipeline
│   ├── scoring/             # XGBoost risk model
│   └── rl/                  # Stable-Baselines3 router (post-MVP)
├── data/
│   ├── ingest/              # Data ingestion scripts
│   └── schemas/             # PostGIS schema definitions
├── docker-compose.yml
├── API_Contract_v1.docx
└── README.md
```
 
---
 
## Getting Started
 
### Prerequisites
- Docker & Docker Compose
- Node.js 18+
- Python 3.11+
- A Firebase project with Auth and Firestore enabled
 
### Environment setup
 
Copy `.env.example` to `.env` in the `backend/` directory and fill in:
 
```env
FLASK_ENV=development
DATABASE_URL=postgresql://user:pass@localhost:5432/saferoute
REDIS_URL=redis://localhost:6379/0
FIREBASE_SERVICE_ACCOUNT_JSON=/path/to/serviceAccountKey.json
OSRM_BASE_URL=http://localhost:5000
CITY_BBOX=77.4601,12.8340,77.7782,13.1439
```
 
### Run with Docker Compose
 
```bash
docker-compose up --build
```
 
This starts: Flask API · PostgreSQL + PostGIS · Redis · OSRM
 
### Frontend dev server
 
```bash
cd frontend
npm install
npm run dev
```
 
Set `VITE_USE_MOCK=true` in `frontend/.env.development` to develop against mock API responses without a running backend.
 
---
 
## Team & Roles
 
| Role | Responsibilities |
|---|---|
| **Technical Lead / System Architect** | Architecture, AI/algorithm logic, OSRM integration, code review, repo ownership |
| **Backend Developer** | Flask API, SQLAlchemy models, Firebase integration, Redis caching |
| **Frontend Developer** | Vite + Vue.js UI, Mapbox/Leaflet map, route display, incident reporter |
| **Data / AI Engineer** | Vision pipeline (BLIP2/CLIP), NLP pipeline (RoBERTa/T5), XGBoost scoring model, data ingestion |
 
---
 
## Roadmap
 
**MVP (current)**
- Single-city routing (Hyderabad)
- Three route modes: safest / balanced / fastest
- Safety heatmap overlay
- User incident reporting
 
**Post-MVP**
- RL-based dynamic routing (Stable-Baselines3)
- Multi-city support with scalable ingestion
- Bulk segment score endpoint for heatmap performance
- Image attachment on incident reports
- Mobile app with push safety alerts
- IoT / smart city data integration
 
---
 
## Privacy & Ethics
 
- No personal identifiers are stored from social media or street images — PII is stripped at ingest.
- User location history is not persisted beyond the active session.
- Incident reports are used solely for safety analysis, not surveillance.
- Users can opt out of location history storage in account settings.
 
---
 
## License
 
Apache License 2.0 — see [LICENSE](./LICENSE).
