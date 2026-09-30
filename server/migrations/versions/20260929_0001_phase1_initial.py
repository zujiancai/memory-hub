"""phase1 initial schema

Revision ID: 20260929_0001
Revises:
Create Date: 2026-09-29 00:00:00.000000

Ships all Phase 1 tables plus the three Phase 2/5 schema-forward NULL
columns (``asset.perceptual_hash``, ``asset.upload_quality``,
``asset.superseded_by``) so later phases don't have to ALTER populated
tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260929_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("friendly_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("avatar_blob_key", sa.String(length=64), nullable=True),
        sa.Column("avatar_generator_json", sa.JSON(), nullable=True),
        sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("deleted_pin_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_email"),
        sa.UniqueConstraint("google_sub", name="uq_user_google_sub"),
    )

    op.create_table(
        "refresh_token",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("device_label", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"])

    op.create_table(
        "blob",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False, server_default="application/octet-stream"),
        sa.Column("container", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("blob_name", sa.String(length=255), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("ref_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("sha256"),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("capture_ts", sa.DateTime(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("exif_json", sa.JSON(), nullable=True),
        # Phase-forward: populated in Phase 2.
        sa.Column("perceptual_hash", sa.String(length=16), nullable=True),
        # Phase-forward: populated in Phase 5.
        sa.Column("upload_quality", sa.String(length=16), nullable=True),
        # Phase-forward: populated in Phase 5.
        sa.Column("superseded_by", sa.String(length=36), nullable=True),
        sa.Column("poster_blob_sha256", sa.String(length=64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blob.sha256"]),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["poster_blob_sha256"], ["blob.sha256"]),
        sa.ForeignKeyConstraint(["superseded_by"], ["asset.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_owner_capture", "asset", ["owner_id", "capture_ts"])
    op.create_index("ix_asset_owner_deleted", "asset", ["owner_id", "deleted_at"])

    op.create_table(
        "ingestion_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("error", sa.String(length=2048), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_job_state", "ingestion_job", ["state"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_job_state", table_name="ingestion_job")
    op.drop_table("ingestion_job")
    op.drop_index("ix_asset_owner_deleted", table_name="asset")
    op.drop_index("ix_asset_owner_capture", table_name="asset")
    op.drop_table("asset")
    op.drop_table("blob")
    op.drop_index("ix_refresh_token_user_id", table_name="refresh_token")
    op.drop_table("refresh_token")
    op.drop_table("user")
