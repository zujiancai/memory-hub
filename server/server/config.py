"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _list_env(name: str, default: List[str]) -> List[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    # Flask / secrets
    flask_secret: str = ""
    jwt_signing_key: str = ""
    jwt_access_ttl_seconds: int = 15 * 60
    jwt_refresh_ttl_seconds: int = 30 * 24 * 60 * 60
    trash_session_ttl_seconds: int = 15 * 60

    # DB
    database_url: str = "sqlite:///app.db"

    # Blob storage
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "memoryhub-media"
    local_blob_dir: str = "./blobstore"

    # Quotas
    default_user_quota_bytes: int = 5 * 1024 * 1024 * 1024
    max_avatar_bytes: int = 2 * 1024 * 1024
    trash_grace_days: int = 30

    # OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:5173/oauth/google/callback"

    # CORS
    cors_allowed_origins: List[str] = field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # Misc
    trust_proxy: bool = False
    git_sha: str = "dev"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            flask_secret=os.environ.get("FLASK_SECRET", "dev-flask-secret"),
            jwt_signing_key=os.environ.get("JWT_SIGNING_KEY", "dev-jwt-key"),
            jwt_access_ttl_seconds=_int_env("JWT_ACCESS_TTL_SECONDS", 15 * 60),
            jwt_refresh_ttl_seconds=_int_env("JWT_REFRESH_TTL_SECONDS", 30 * 24 * 60 * 60),
            trash_session_ttl_seconds=_int_env("TRASH_SESSION_TTL_SECONDS", 15 * 60),
            database_url=os.environ.get("DATABASE_URL", "sqlite:///app.db"),
            azure_storage_connection_string=os.environ.get(
                "AZURE_STORAGE_CONNECTION_STRING", ""
            ),
            azure_storage_container=os.environ.get(
                "AZURE_STORAGE_CONTAINER", "memoryhub-media"
            ),
            local_blob_dir=os.environ.get("LOCAL_BLOB_DIR", "./blobstore"),
            default_user_quota_bytes=_int_env(
                "DEFAULT_USER_QUOTA_BYTES", 5 * 1024 * 1024 * 1024
            ),
            max_avatar_bytes=_int_env("MAX_AVATAR_BYTES", 2 * 1024 * 1024),
            trash_grace_days=_int_env("TRASH_GRACE_DAYS", 30),
            google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            google_redirect_uri=os.environ.get(
                "GOOGLE_OAUTH_REDIRECT_URI",
                "http://localhost:5173/oauth/google/callback",
            ),
            cors_allowed_origins=_list_env(
                "CORS_ALLOWED_ORIGINS", ["http://localhost:5173"]
            ),
            trust_proxy=_bool_env("TRUST_PROXY", False),
            git_sha=os.environ.get("GIT_SHA", "dev"),
        )
