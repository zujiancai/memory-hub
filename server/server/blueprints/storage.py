"""Storage quota blueprint."""
from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import func

from ..auth import current_user, require_auth
from ..db import db
from ..models import Asset, Blob

bp = Blueprint("storage", __name__)


@bp.get("/api/storage/quota")
@require_auth
def get_quota():
    user = current_user()
    session = db()
    asset_count = (
        session.query(func.count(Asset.id))
        .filter(Asset.owner_id == user.id)
        .filter(Asset.deleted_at.is_(None))
        .scalar()
        or 0
    )
    deleted_pending = (
        session.query(func.coalesce(func.sum(Blob.size_bytes), 0))
        .join(Asset, Asset.blob_sha256 == Blob.sha256)
        .filter(Asset.owner_id == user.id)
        .filter(Asset.deleted_at.is_not(None))
        .scalar()
        or 0
    )
    return jsonify(
        {
            "used_bytes": int(user.storage_used_bytes),
            "quota_bytes": int(user.storage_quota_bytes),
            "asset_count": int(asset_count),
            "deleted_pending_purge_bytes": int(deleted_pending),
        }
    )
