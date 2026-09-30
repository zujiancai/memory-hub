"""SQLAlchemy ORM models — Phase 1 subset of buildout-design.md."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    google_sub: Mapped[Optional[str]] = mapped_column(String(255))
    friendly_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    avatar_blob_key: Mapped[Optional[str]] = mapped_column(String(64))
    avatar_generator_json: Mapped[Optional[dict]] = mapped_column(JSON)
    storage_quota_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    deleted_pin_hash: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
        UniqueConstraint("google_sub", name="uq_user_google_sub"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    device_label: Mapped[Optional[str]] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    __table_args__ = (
        Index("ix_refresh_token_user_id", "user_id"),
    )


class Blob(Base):
    __tablename__ = "blob"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    container: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    blob_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    ref_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    blob_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("blob.sha256"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # photo|video
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    capture_ts: Mapped[Optional[datetime]] = mapped_column(DateTime)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    exif_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # Phase-forward: populated in Phase 2 (perceptual_hash) and Phase 5 (upload_quality, superseded_by).
    perceptual_hash: Mapped[Optional[str]] = mapped_column(String(16))
    # Phase-forward: populated in Phase 5.
    upload_quality: Mapped[Optional[str]] = mapped_column(String(16))
    # Phase-forward: populated in Phase 5.
    superseded_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("asset.id")
    )

    poster_blob_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("blob.sha256")
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        Index("ix_asset_owner_capture", "owner_id", "capture_ts"),
        Index("ix_asset_owner_deleted", "owner_id", "deleted_at"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Phase 1 only stores 'asset'; column kept as free string for Phase 2 'entry'.
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error: Mapped[Optional[str]] = mapped_column(String(2048))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (
        Index("ix_ingestion_job_state", "state"),
    )
