"""User blueprint — auth, profile, avatar, Google OAuth PKCE."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Optional

from flask import Blueprint, current_app, g, jsonify, make_response, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..auth import (
    current_user,
    find_and_validate_refresh_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    require_auth,
    verify_password,
)
from ..db import db
from ..logging_utils import log_event
from ..models import Blob, RefreshToken, User
from ..oauth_google import (
    build_authorization_url,
    exchange_code_for_userinfo,
    generate_pkce_pair,
)

bp = Blueprint("user", __name__)

REFRESH_COOKIE = "mh_refresh"
MAX_AVATAR_MIME = {"image/jpeg", "image/png", "image/webp"}


# ---------- helpers ----------
def _set_refresh_cookie(resp, raw: str) -> None:
    ttl = current_app.config["JWT_REFRESH_TTL_SECONDS"]
    resp.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=ttl,
        secure=False,  # In prod, put behind HTTPS/Ingress and flip to True via env.
        httponly=True,
        samesite="Lax",
        path="/api/user",
    )


def _clear_refresh_cookie(resp) -> None:
    resp.delete_cookie(REFRESH_COOKIE, path="/api/user")


def _issue_session_response(user: User, session, device_label: Optional[str] = None):
    access = issue_access_token(user.id)
    raw_refresh, _ = issue_refresh_token(session, user.id, device_label=device_label)
    session.commit()
    resp = make_response(
        jsonify(
            {
                "access_token": access,
                "refresh_token": raw_refresh,
                "token_type": "Bearer",
                "user": _user_public(user),
            }
        )
    )
    _set_refresh_cookie(resp, raw_refresh)
    return resp


def _user_public(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "friendly_name": user.friendly_name,
        "role": user.role,
        "avatar_blob_key": user.avatar_blob_key,
        "avatar_generator_json": user.avatar_generator_json,
        "storage_quota_bytes": user.storage_quota_bytes,
        "storage_used_bytes": user.storage_used_bytes,
        "has_deleted_pin": user.deleted_pin_hash is not None,
    }


# ---------- signup / login / refresh / logout ----------
@bp.post("/api/user/signup")
def signup():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    friendly_name = (body.get("friendly_name") or "").strip() or email
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    session = db()
    existing = session.query(User).filter(User.email == email).first()
    if existing:
        return jsonify({"error": "email already registered"}), 409
    user = User(
        email=email,
        password_hash=hash_password(password),
        friendly_name=friendly_name,
        storage_quota_bytes=current_app.config["DEFAULT_USER_QUOTA_BYTES"],
        role="user",
    )
    session.add(user)
    session.flush()
    log_event("user.signup", user_id=user.id, email=email)
    return _issue_session_response(user, session, device_label=body.get("device_label"))


@bp.post("/api/user/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    session = db()
    user = session.query(User).filter(User.email == email).first()
    if not user or not user.password_hash or not verify_password(user.password_hash, password):
        log_event("auth.login_failed", email=email)
        return jsonify({"error": "invalid credentials"}), 401
    log_event("user.login", user_id=user.id)
    return _issue_session_response(user, session, device_label=body.get("device_label"))


@bp.post("/api/user/refresh")
def refresh():
    """Rotate the refresh token and issue a new access token.

    Accepts the token either via the HttpOnly cookie (SPA) or as
    ``{refresh_token: ...}`` in the JSON body (mobile). The presented
    token is revoked and replaced.
    """
    body = request.get_json(silent=True) or {}
    # Body wins (mobile clients pass the token explicitly); the cookie is the
    # SPA fallback.
    raw = body.get("refresh_token") or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        return jsonify({"error": "no refresh token"}), 401
    session = db()
    row = find_and_validate_refresh_token(session, raw)
    if row is None:
        log_event("auth.refresh_denied", reason="not found or revoked")
        return jsonify({"error": "invalid refresh token"}), 401
    row.revoked_at = datetime.utcnow()
    session.flush()
    user = session.get(User, row.user_id)
    if user is None:
        return jsonify({"error": "user gone"}), 401
    log_event("user.refresh", user_id=user.id)
    return _issue_session_response(user, session, device_label=row.device_label)


@bp.post("/api/user/logout")
def logout():
    raw = request.cookies.get(REFRESH_COOKIE)
    body = request.get_json(silent=True) or {}
    raw = raw or body.get("refresh_token")
    session = db()
    if raw:
        row = find_and_validate_refresh_token(session, raw)
        if row:
            row.revoked_at = datetime.utcnow()
            session.commit()
    resp = make_response(jsonify({"ok": True}))
    _clear_refresh_cookie(resp)
    return resp


# ---------- profile ----------
@bp.get("/api/user/me")
@require_auth
def get_me():
    return jsonify(_user_public(current_user()))


@bp.patch("/api/user/me")
@require_auth
def patch_me():
    body = request.get_json(silent=True) or {}
    user = current_user()
    session = db()
    if "password" in body and body["password"]:
        user.password_hash = hash_password(body["password"])
    if "friendly_name" in body and body["friendly_name"]:
        user.friendly_name = str(body["friendly_name"]).strip()
    if "avatar_generator_json" in body:
        user.avatar_generator_json = body["avatar_generator_json"]
    session.commit()
    return jsonify(_user_public(user))


@bp.post("/api/user/me/avatar")
@require_auth
def upload_avatar():
    """Accept a small avatar image (multipart or raw) and store it as a blob."""
    file = request.files.get("avatar")
    data: bytes
    content_type: str
    if file is not None:
        data = file.read()
        content_type = file.mimetype or "application/octet-stream"
    else:
        data = request.get_data() or b""
        content_type = request.mimetype or "application/octet-stream"
    if content_type not in MAX_AVATAR_MIME:
        return jsonify({"error": "unsupported mime type"}), 415
    max_bytes = current_app.config["MAX_AVATAR_BYTES"]
    if len(data) > max_bytes:
        return jsonify({"error": "avatar too large"}), 413

    sha = hashlib.sha256(data).hexdigest()
    store = current_app.extensions["blob_store"]
    if not store.exists(sha):
        store.put(sha, data, content_type=content_type)

    session = db()
    blob = session.get(Blob, sha)
    if blob is None:
        blob = Blob(
            sha256=sha,
            size_bytes=len(data),
            mime_type=content_type,
            container=current_app.config["AZURE_STORAGE_CONTAINER"],
            blob_name=sha,
            ref_count=1,
        )
        session.add(blob)
    else:
        blob.ref_count += 1

    user = current_user()
    user.avatar_blob_key = sha
    session.commit()
    return jsonify({"avatar_blob_key": sha})


# ---------- deleted-pin ----------
@bp.post("/api/user/deleted-pin")
@require_auth
def set_deleted_pin():
    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin") or "").strip()
    if len(pin) < 4:
        return jsonify({"error": "pin must be at least 4 characters"}), 400
    user = current_user()
    user.deleted_pin_hash = hash_password(pin)
    db().commit()
    return jsonify({"ok": True})


def _trash_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["FLASK_SECRET"], salt="trash-session"
    )


@bp.post("/api/user/deleted-pin/verify")
@require_auth
def verify_deleted_pin():
    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin") or "").strip()
    user = current_user()
    if not user.deleted_pin_hash or not verify_password(user.deleted_pin_hash, pin):
        log_event(
            "trash.pin_denied", user_id=user.id, endpoint=request.path, reason="bad pin"
        )
        return jsonify({"error": "invalid pin"}), 401
    token = _trash_serializer().dumps({"uid": user.id})
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(
        "trash_session",
        token,
        max_age=current_app.config["TRASH_SESSION_TTL_SECONDS"],
        httponly=True,
        secure=False,
        samesite="Lax",
        path="/api/trash",
    )
    return resp


def verify_trash_cookie(user: User) -> bool:
    token = request.cookies.get("trash_session")
    if not token:
        return False
    try:
        payload = _trash_serializer().loads(
            token, max_age=current_app.config["TRASH_SESSION_TTL_SECONDS"]
        )
    except BadSignature:
        return False
    return payload.get("uid") == user.id


# ---------- Google OAuth (PKCE) ----------
@bp.get("/api/user/oauth/google/start")
def oauth_start():
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    if not client_id:
        return jsonify({"error": "google oauth not configured"}), 501
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(
        client_id=client_id,
        redirect_uri=current_app.config["GOOGLE_REDIRECT_URI"],
        code_challenge=challenge,
        state=state,
    )
    # The SPA is responsible for persisting the verifier + state locally until
    # the callback fires.
    return jsonify({"authorize_url": url, "code_verifier": verifier, "state": state})


@bp.post("/api/user/oauth/google/callback")
def oauth_callback():
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    verifier = body.get("code_verifier")
    if not code or not verifier:
        return jsonify({"error": "code and code_verifier required"}), 400
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    if not client_id:
        return jsonify({"error": "google oauth not configured"}), 501

    exchange = current_app.extensions.get("google_oauth_exchange", exchange_code_for_userinfo)
    try:
        google_sub, email, name = exchange(
            client_id,
            current_app.config["GOOGLE_CLIENT_SECRET"],
            current_app.config["GOOGLE_REDIRECT_URI"],
            code,
            verifier,
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_event("oauth.google_failed", reason=str(exc))
        return jsonify({"error": "google auth failed"}), 502

    session = db()
    user = session.query(User).filter(User.google_sub == google_sub).first()
    if user is None and email:
        user = session.query(User).filter(User.email == email.lower()).first()
        if user is not None:
            user.google_sub = google_sub
    if user is None:
        user = User(
            email=(email or f"{google_sub}@google.local").lower(),
            google_sub=google_sub,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            friendly_name=name or email or "New user",
            storage_quota_bytes=current_app.config["DEFAULT_USER_QUOTA_BYTES"],
            role="user",
        )
        session.add(user)
        session.flush()
        log_event("user.google_signup", user_id=user.id, email=user.email)
    log_event("user.google_login", user_id=user.id)
    return _issue_session_response(user, session)
