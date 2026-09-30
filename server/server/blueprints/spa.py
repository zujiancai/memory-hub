"""SPA catch-all serving ``server/ui/dist``."""
from __future__ import annotations

import os

from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("spa", __name__)


def _ui_dir() -> str:
    return current_app.config["UI_DIST_DIR"]


@bp.get("/")
def index():
    return send_from_directory(_ui_dir(), "index.html")


@bp.get("/<path:path>")
def catch_all(path: str):
    if path.startswith("api/"):
        # Should not be reached (registered before api blueprints in app.py),
        # but this is a safety net.
        return {"error": "not found"}, 404
    file_path = os.path.join(_ui_dir(), path)
    if os.path.isfile(file_path):
        return send_from_directory(_ui_dir(), path)
    return send_from_directory(_ui_dir(), "index.html")
