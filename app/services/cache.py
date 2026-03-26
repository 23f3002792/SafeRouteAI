"""
Cache helpers built on top of the shared Redis client.

Score cache key  : score:<segment_id>
Rate-limit key   : ratelimit:reports:<uid>
TTL              : 30 minutes for scores, 1 hour window for rate limits
"""
import json
from app.extensions import redis_client

SCORE_TTL_SECONDS      = 30 * 60   # 30 minutes
REPORT_RATE_LIMIT      = 10        # max reports per hour per user
RATE_LIMIT_WINDOW_SECS = 60 * 60   # 1 hour


def get_cached_score(segment_id: str) -> dict | None:
    raw = redis_client.get(f"score:{segment_id}")
    if raw:
        return json.loads(raw)
    return None


def set_cached_score(segment_id: str, score_dict: dict):
    redis_client.setex(
        f"score:{segment_id}",
        SCORE_TTL_SECONDS,
        json.dumps(score_dict),
    )


def check_and_increment_report_rate(uid: str) -> bool:
    """
    Returns True if the user is UNDER the rate limit (request is allowed).
    Increments their counter; sets TTL on first request in a window.
    """
    key = f"ratelimit:reports:{uid}"
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, RATE_LIMIT_WINDOW_SECS)
    return count <= REPORT_RATE_LIMIT
