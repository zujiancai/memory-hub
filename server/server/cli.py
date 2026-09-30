"""Flask CLI commands (cleanup, dev seed, worker drain)."""
from __future__ import annotations

from datetime import datetime, timedelta

import click
from flask.cli import with_appcontext
from sqlalchemy import func

from .auth import hash_password
from .db import SessionLocal
from .models import Asset, Blob, User


@click.command("cleanup")
@with_appcontext
def cleanup_command():
    """Purge expired trash + recompute per-user storage_used_bytes."""
    from flask import current_app

    grace_days = current_app.config["TRASH_GRACE_DAYS"]
    cutoff = datetime.utcnow() - timedelta(days=grace_days)
    session = SessionLocal()
    store = current_app.extensions["blob_store"]
    try:
        # Purge assets whose deleted_at is beyond the grace period.
        expired = (
            session.query(Asset)
            .filter(Asset.deleted_at.is_not(None))
            .filter(Asset.deleted_at < cutoff)
            .all()
        )
        purged = 0
        for asset in expired:
            sha = asset.blob_sha256
            session.delete(asset)
            session.flush()
            blob = session.get(Blob, sha)
            if blob is not None:
                blob.ref_count -= 1
                if blob.ref_count <= 0:
                    try:
                        store.delete(sha)
                    except Exception:
                        pass
                    session.delete(blob)
            purged += 1

        # Delete blobs left with zero refs (safety net).
        orphans = session.query(Blob).filter(Blob.ref_count <= 0).all()
        for blob in orphans:
            try:
                store.delete(blob.sha256)
            except Exception:
                pass
            session.delete(blob)

        # Recompute storage_used_bytes for every user.
        totals = (
            session.query(Asset.owner_id, func.coalesce(func.sum(Blob.size_bytes), 0))
            .join(Blob, Blob.sha256 == Asset.blob_sha256)
            .filter(Asset.deleted_at.is_(None))
            .group_by(Asset.owner_id)
            .all()
        )
        totals_by_user = {uid: int(total) for uid, total in totals}
        for user in session.query(User).all():
            user.storage_used_bytes = totals_by_user.get(user.id, 0)

        session.commit()
        click.echo(f"cleanup: purged {purged} assets; recomputed quotas.")
    finally:
        session.close()


@click.command("seed-dev-user")
@click.option("--email", default="dev@memoryhub.local")
@click.option("--password", default="devpassword")
@click.option("--role", default="user")
@with_appcontext
def seed_dev_user_command(email: str, password: str, role: str):
    """Create a local dev user."""
    from flask import current_app

    session = SessionLocal()
    try:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            click.echo(f"user {email} already exists as {existing.id}")
            return
        user = User(
            email=email,
            password_hash=hash_password(password),
            friendly_name=email,
            storage_quota_bytes=current_app.config["DEFAULT_USER_QUOTA_BYTES"],
            role=role,
        )
        session.add(user)
        session.commit()
        click.echo(f"seeded {email} as {user.id}")
    finally:
        session.close()


@click.command("worker")
@with_appcontext
def worker_drain_command():
    """Drain queued ingestion jobs once."""
    from flask import current_app

    from .worker import drain_once

    n = drain_once(current_app)
    click.echo(f"drained {n} jobs")
