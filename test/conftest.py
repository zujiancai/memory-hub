"""Pytest fixtures for the Memory Hub backend."""
from __future__ import annotations

import io
import os
import sys

import pytest
from PIL import Image

# Ensure ``server`` package importable regardless of cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.abspath(os.path.join(HERE, "..", "server"))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from server.app import create_app  # noqa: E402
from server.blob_storage import LocalBlobStore  # noqa: E402
from server.config import Config  # noqa: E402
from server.db import Base, SessionLocal, get_engine, init_engine  # noqa: E402
from server import models  # noqa: F401,E402


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        flask_secret="test-secret",
        jwt_signing_key="test-jwt-key",
        jwt_access_ttl_seconds=900,
        jwt_refresh_ttl_seconds=3600,
        trash_session_ttl_seconds=900,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        azure_storage_connection_string="",
        azure_storage_container="memoryhub-media",
        local_blob_dir=str(tmp_path / "blobs"),
        default_user_quota_bytes=50 * 1024 * 1024,
        max_avatar_bytes=2 * 1024 * 1024,
        trash_grace_days=30,
        google_client_id="test-google-client",
        google_client_secret="test-google-secret",
        google_redirect_uri="http://localhost:5173/oauth/google/callback",
        cors_allowed_origins=["http://localhost:5173"],
        trust_proxy=False,
        git_sha="test-sha",
    )


@pytest.fixture
def blob_store(config) -> LocalBlobStore:
    return LocalBlobStore(root_dir=config.local_blob_dir, container=config.azure_storage_container)


@pytest.fixture
def app(config, blob_store):
    app = create_app(config=config, blob_store=blob_store)
    Base.metadata.create_all(get_engine())
    app.config["TESTING"] = True
    yield app
    Base.metadata.drop_all(get_engine())


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------- helpers ----------
def _small_jpeg(width: int = 400, height: int = 300, color=(120, 45, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture
def sample_jpeg_factory():
    def _make(width: int = 400, height: int = 300, color=(120, 45, 200)) -> bytes:
        return _small_jpeg(width, height, color)

    return _make


@pytest.fixture
def signup_user(client):
    """Callable: signup(email, password) → (auth_headers, response_json)."""

    def _signup(email: str = "a@example.com", password: str = "hunter2", friendly_name: str = "A"):
        resp = client.post(
            "/api/user/signup",
            json={"email": email, "password": password, "friendly_name": friendly_name},
        )
        assert resp.status_code == 200, resp.get_json()
        payload = resp.get_json()
        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        return headers, payload

    return _signup


@pytest.fixture
def upload_asset(client, signup_user, sample_jpeg_factory, blob_store):
    """Helper: given auth headers, upload a small JPEG through the full flow."""

    import hashlib

    def _upload(headers, jpeg_bytes: bytes = None, filename: str = "photo.jpg"):
        if jpeg_bytes is None:
            jpeg_bytes = sample_jpeg_factory()
        sha = hashlib.sha256(jpeg_bytes).hexdigest()
        size = len(jpeg_bytes)

        pre = client.post(
            "/api/asset/precheck",
            json={"sha256": sha, "size": size},
            headers=headers,
        )
        assert pre.status_code == 200, pre.get_json()

        if not pre.get_json().get("exists", False):
            urlresp = client.post(
                "/api/asset/upload-url",
                json={"sha256": sha, "size": size, "mime_type": "image/jpeg"},
                headers=headers,
            )
            assert urlresp.status_code == 200
            # Simulate the SAS PUT by writing directly into the fake blob store.
            blob_store.put(sha, jpeg_bytes, content_type="image/jpeg")

        create = client.post(
            "/api/asset",
            json={
                "sha256": sha,
                "size": size,
                "original_filename": filename,
                "mime_type": "image/jpeg",
                "kind": "photo",
            },
            headers=headers,
        )
        assert create.status_code == 201, create.get_json()
        return create.get_json(), sha, jpeg_bytes

    return _upload
