import os
import redis
import firebase_admin
from firebase_admin import credentials

# Module-level singletons – imported by service layer
redis_client: redis.Redis = None


def init_extensions(app):
    global redis_client

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = redis.from_url(redis_url, decode_responses=True)
    app.redis = redis_client

    # ── Firebase Admin SDK ─────────────────────────────────────────────────
    sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if sa_path and not firebase_admin._apps:
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred)
