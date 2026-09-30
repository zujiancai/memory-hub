"""Minimal admin blueprint — Phase 1 only exposes bootstrap user creation."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..auth import hash_password, require_admin, require_auth
from ..db import db
from ..logging_utils import log_event
from ..models import User

bp = Blueprint("admin", __name__)


@bp.post("/api/admin/user")
@require_auth
@require_admin
def create_user():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email") or "").strip().lower()
    password = body.get("password") or "changeme"
    friendly_name = body.get("friendly_name") or email
    role = body.get("role") or "user"
    if not email:
        return jsonify({"error": "email required"}), 400
    session = db()
    if session.query(User).filter(User.email == email).first():
        return jsonify({"error": "email already registered"}), 409
    user = User(
        email=email,
        password_hash=hash_password(password),
        friendly_name=friendly_name,
        storage_quota_bytes=current_app.config["DEFAULT_USER_QUOTA_BYTES"],
        role=role,
    )
    session.add(user)
    session.commit()
    log_event("admin.user_created", user_id=user.id, email=email, role=role)
    return jsonify({"id": user.id, "email": user.email, "role": user.role}), 201
