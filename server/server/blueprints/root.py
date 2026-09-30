"""Root/health blueprint."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..__version__ import __version__

bp = Blueprint("root", __name__)


@bp.get("/api/ping")
def ping():
    return jsonify(
        {
            "ok": True,
            "version": __version__,
            "commit": current_app.config.get("GIT_SHA", "dev"),
        }
    )
