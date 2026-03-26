import os
from flask import Flask
from flask_cors import CORS

from app.api.v1.route import route_bp
from app.api.v1.segment import segment_bp
from app.api.v1.report import report_bp
from app.api.v1.score import score_bp
from app.extensions import init_extensions


def create_app():
    app = Flask(__name__)

    # ── CORS ──────────────────────────────────────────────────────────────────
    env = os.getenv("FLASK_ENV", "development")
    if env == "development":
        CORS(app)
    else:
        CORS(app, origins=[os.getenv("FRONTEND_ORIGIN", "")])

    # ── Extensions (Redis, Firebase) ──────────────────────────────────────────
    init_extensions(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(route_bp, url_prefix="/api/v1")
    app.register_blueprint(segment_bp, url_prefix="/api/v1")
    app.register_blueprint(report_bp, url_prefix="/api/v1")
    app.register_blueprint(score_bp, url_prefix="")  # internal: POST /score

    return app
