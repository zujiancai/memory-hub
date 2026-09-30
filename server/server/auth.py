"""Auth helpers: JWT access tokens + argon2-hashed refresh tokens + decorators."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import current_app, g, jsonify, request
from jose import JWTError, jwt

from .db import db
from .logging_utils import log_auth_denied
from .models import RefreshToken, User

_ph = PasswordHasher()


# ---- password hashing ----
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---- refresh tokens ----
def new_refresh_token_raw() -> str:
    return secrets.token_urlsafe(48)


def issue_refresh_token(
    session, user_id: str, device_label: Optional[str] = None
) -> Tuple[str, RefreshToken]:
    raw = new_refresh_token_raw()
    ttl = current_app.config["JWT_REFRESH_TTL_SECONDS"]
    row = RefreshToken(
        user_id=user_id,
        token_hash=_ph.hash(raw),
        device_label=device_label,
        expires_at=datetime.utcnow() + timedelta(seconds=ttl),
    )
    session.add(row)
    session.flush()
    return raw, row


def find_and_validate_refresh_token(session, raw: str) -> Optional[RefreshToken]:
    """Locate the refresh-token row matching ``raw`` (linear scan is fine for
    a small user base; Phase 6 can add a token_prefix index if this ever
    becomes hot)."""
    now = datetime.utcnow()
    rows = (
        session.query(RefreshToken)
        .filter(RefreshToken.revoked_at.is_(None))
        .filter(RefreshToken.expires_at > now)
        .all()
    )
    for row in rows:
        try:
            if _ph.verify(row.token_hash, raw):
                return row
        except VerifyMismatchError:
            continue
        except Exception:
            continue
    return None


# ---- JWT access tokens ----
def _jwt_secret() -> str:
    return current_app.config["JWT_SIGNING_KEY"]


def issue_access_token(user_id: str) -> str:
    ttl = current_app.config["JWT_ACCESS_TTL_SECONDS"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except JWTError:
        return None


# ---- Flask decorators ----
def _extract_bearer() -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_bearer()
        if not token:
            log_auth_denied(
                "auth.missing_token", request.path, None, "no bearer token"
            )
            return jsonify({"error": "unauthenticated"}), 401
        payload = decode_access_token(token)
        if not payload:
            log_auth_denied(
                "auth.invalid_token", request.path, None, "jwt decode failed"
            )
            return jsonify({"error": "unauthenticated"}), 401
        user_id = payload.get("sub")
        session = db()
        user = session.get(User, user_id) if user_id else None
        if not user:
            log_auth_denied(
                "auth.unknown_user", request.path, user_id, "user not found"
            )
            return jsonify({"error": "unauthenticated"}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user: User = g.user
        if user.role != "admin":
            log_auth_denied(
                "auth.forbidden", request.path, user.id, "not admin"
            )
            return jsonify({"error": "forbidden"}), 403
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> User:
    return g.user
