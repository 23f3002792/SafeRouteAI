from functools import wraps
from flask import request, g
from firebase_admin import auth as firebase_auth
from app.utils.errors import error_response


def require_auth(f):
    """
    Decorator that verifies the Firebase Bearer token on protected endpoints.
    Sets g.uid to the verified Firebase UID on success.
    Returns 401 UNAUTHORIZED on any auth failure.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response(401, "UNAUTHORIZED", "Missing or invalid Firebase token")

        token = auth_header[len("Bearer "):]
        try:
            decoded = firebase_auth.verify_id_token(token)
            g.uid = decoded["uid"]
        except Exception:
            return error_response(401, "UNAUTHORIZED", "Missing or invalid Firebase token")

        return f(*args, **kwargs)
    return decorated
