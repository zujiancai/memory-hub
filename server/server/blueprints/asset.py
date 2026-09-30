"""Asset blueprint — upload precheck / URL / register, list, thumbnail, delete."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Optional, Tuple

from flask import Blueprint, current_app, jsonify, redirect, request
from sqlalchemy import and_, desc, func, or_

from ..auth import current_user, require_auth
from ..db import db
from ..logging_utils import log_event
from ..models import Asset, Blob, IngestionJob, User

bp = Blueprint("asset", __name__)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


def _validate_sha(sha: str) -> bool:
    return bool(sha and SHA256_RE.match(sha.lower()))


def _encode_cursor(capture_ts: Optional[datetime], asset_id: str) -> str:
    payload = {
        "ts": capture_ts.isoformat() if capture_ts else None,
        "id": asset_id,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(raw: str) -> Optional[Tuple[Optional[datetime], str]]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except Exception:
        return None
    ts_raw = payload.get("ts")
    ts = datetime.fromisoformat(ts_raw) if ts_raw else None
    return ts, payload.get("id", "")


def _asset_dict(asset: Asset, thumbnail_url: Optional[str] = None) -> dict:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "original_filename": asset.original_filename,
        "capture_ts": asset.capture_ts.isoformat() if asset.capture_ts else None,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "blob_sha256": asset.blob_sha256,
        "poster_blob_sha256": asset.poster_blob_sha256,
        "thumbnail_url": thumbnail_url,
        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
        "created_at": asset.created_at.isoformat(),
    }


# ---------- upload flow ----------
@bp.post("/api/asset/precheck")
@require_auth
def precheck():
    body = request.get_json(silent=True) or {}
    sha = str(body.get("sha256") or "").lower()
    size = int(body.get("size") or 0)
    if not _validate_sha(sha) or size <= 0:
        return jsonify({"error": "sha256 and size required"}), 400
    # Phase-forward: body may include `phash` or `upload_quality`. Ignore in Phase 1.
    session = db()
    blob = session.get(Blob, sha)
    store = current_app.extensions["blob_store"]
    exists_in_store = store.exists(sha)
    exists = blob is not None and exists_in_store
    resp: dict = {"exists": exists}
    if not exists:
        resp["upload_url"] = store.upload_sas_url(sha)
    return jsonify(resp)


@bp.post("/api/asset/upload-url")
@require_auth
def upload_url():
    body = request.get_json(silent=True) or {}
    sha = str(body.get("sha256") or "").lower()
    size = int(body.get("size") or 0)
    if not _validate_sha(sha) or size <= 0:
        return jsonify({"error": "sha256 and size required"}), 400
    mime_type = body.get("mime_type") or "application/octet-stream"
    store = current_app.extensions["blob_store"]
    url = store.upload_sas_url(sha)
    return jsonify({"upload_url": url, "sha256": sha, "mime_type": mime_type})


def _detect_kind(mime_type: str, filename: str) -> str:
    mime = (mime_type or "").lower()
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "photo"
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext in {"mp4", "mov", "webm", "mkv", "avi", "m4v"}:
        return "video"
    return "photo"


@bp.post("/api/asset")
@require_auth
def create_asset():
    body = request.get_json(silent=True) or {}
    sha = str(body.get("sha256") or "").lower()
    size = int(body.get("size") or 0)
    original_filename = str(body.get("original_filename") or "")
    capture_ts_raw = body.get("capture_ts")
    kind_hint = body.get("kind")
    mime_type = body.get("mime_type") or ""

    if not _validate_sha(sha) or size <= 0:
        return jsonify({"error": "sha256 and size required"}), 400

    session = db()
    store = current_app.extensions["blob_store"]
    if not store.exists(sha):
        return jsonify({"error": "blob missing in storage"}), 400
    actual_size = store.size_of(sha)
    if actual_size is not None and actual_size != size:
        return jsonify({"error": "size mismatch"}), 400

    user = current_user()
    blob = session.get(Blob, sha)
    new_blob = blob is None
    delta = size if new_blob else 0
    if user.storage_used_bytes + delta > user.storage_quota_bytes:
        log_event(
            "quota.exceeded",
            user_id=user.id,
            requested=size,
            used=user.storage_used_bytes,
            quota=user.storage_quota_bytes,
        )
        return jsonify({"error": "quota exceeded"}), 413

    if new_blob:
        blob = Blob(
            sha256=sha,
            size_bytes=size,
            mime_type=mime_type or "application/octet-stream",
            container=current_app.config["AZURE_STORAGE_CONTAINER"],
            blob_name=sha,
            ref_count=1,
        )
        session.add(blob)
        session.flush()  # Ensure Blob is committed before Asset FK reference.
    else:
        blob.ref_count += 1
        session.flush()

    kind = kind_hint or _detect_kind(mime_type, original_filename)
    capture_ts: Optional[datetime] = None
    if capture_ts_raw:
        try:
            capture_ts = datetime.fromisoformat(capture_ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            capture_ts = None

    asset = Asset(
        blob_sha256=sha,
        owner_id=user.id,
        kind=kind,
        original_filename=original_filename,
        capture_ts=capture_ts,
    )
    session.add(asset)
    session.flush()

    user.storage_used_bytes += delta

    job = IngestionJob(
        subject_type="asset",
        subject_id=asset.id,
        state="queued",
    )
    session.add(job)
    session.commit()
    log_event("asset.created", asset_id=asset.id, user_id=user.id, size=size, dedup=(not new_blob))
    return jsonify(_asset_dict(asset)), 201


# ---------- listing ----------
@bp.get("/api/asset")
@require_auth
def list_assets():
    user = current_user()
    session = db()
    limit_raw = request.args.get("limit", str(DEFAULT_PAGE_SIZE))
    try:
        limit = min(int(limit_raw), MAX_PAGE_SIZE)
    except ValueError:
        limit = DEFAULT_PAGE_SIZE
    cursor = request.args.get("cursor")

    q = (
        session.query(Asset)
        .filter(Asset.owner_id == user.id)
        .filter(Asset.deleted_at.is_(None))
    )
    sort_key = func.coalesce(Asset.capture_ts, Asset.created_at)
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is not None:
            ts, aid = decoded
            if ts is not None:
                q = q.filter(
                    or_(
                        sort_key < ts,
                        and_(sort_key == ts, Asset.id > aid),
                    )
                )
    q = q.order_by(desc(sort_key), Asset.id)
    rows = q.limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    store = current_app.extensions["blob_store"]
    items = []
    for asset in rows:
        thumb_sha = asset.poster_blob_sha256 or asset.blob_sha256
        thumb_url = store.read_sas_url(thumb_sha)
        items.append(_asset_dict(asset, thumbnail_url=thumb_url))

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        last_ts = last.capture_ts or last.created_at
        next_cursor = _encode_cursor(last_ts, last.id)

    return jsonify({"items": items, "next_cursor": next_cursor})


@bp.get("/api/asset/<asset_id>")
@require_auth
def get_asset(asset_id: str):
    user = current_user()
    session = db()
    asset = session.get(Asset, asset_id)
    if not asset or asset.owner_id != user.id or asset.deleted_at is not None:
        log_event(
            "asset.forbidden",
            user_id=user.id,
            endpoint=request.path,
            reason="not visible",
        )
        return jsonify({"error": "not found"}), 404
    store = current_app.extensions["blob_store"]
    read_url = store.read_sas_url(asset.blob_sha256)
    poster_url = (
        store.read_sas_url(asset.poster_blob_sha256)
        if asset.poster_blob_sha256
        else read_url
    )
    payload = _asset_dict(asset, thumbnail_url=poster_url)
    payload["read_url"] = read_url
    payload["poster_url"] = poster_url
    return jsonify(payload)


@bp.get("/api/asset/<asset_id>/thumbnail")
@require_auth
def get_thumbnail(asset_id: str):
    user = current_user()
    session = db()
    asset = session.get(Asset, asset_id)
    if not asset or asset.owner_id != user.id or asset.deleted_at is not None:
        return jsonify({"error": "not found"}), 404
    store = current_app.extensions["blob_store"]
    thumb_sha = asset.poster_blob_sha256 or asset.blob_sha256
    return redirect(store.read_sas_url(thumb_sha), code=302)


@bp.delete("/api/asset/<asset_id>")
@require_auth
def soft_delete_asset(asset_id: str):
    user = current_user()
    session = db()
    asset = session.get(Asset, asset_id)
    if not asset or asset.owner_id != user.id or asset.deleted_at is not None:
        return jsonify({"error": "not found"}), 404
    asset.deleted_at = datetime.utcnow()
    session.commit()
    log_event("asset.soft_deleted", asset_id=asset.id, user_id=user.id)
    return jsonify({"ok": True})
