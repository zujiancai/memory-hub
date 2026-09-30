"""Ingestion worker — Phase 1 EXIF + poster/thumbnail path (no CLIP)."""
from __future__ import annotations

import hashlib
import io
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .app import create_app
from .blob_storage import BlobStore
from .db import SessionLocal
from .logging_utils import get_logger
from .models import Asset, Blob, IngestionJob

log = get_logger()

MAX_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Media processing
# ---------------------------------------------------------------------------


def _process_photo(data: bytes) -> tuple[dict, bytes, tuple[int, int]]:
    """Return (metadata_dict, poster_bytes, (w, h))."""
    from PIL import ExifTags, Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        width, height = img.size
        exif_data: dict = {}
        try:
            exif = img.getexif()
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="ignore")
                    except Exception:
                        value = None
                exif_data[str(tag)] = str(value) if value is not None else None
        except Exception:
            pass

        # Build a 512-px long-edge JPEG poster.
        poster_img = img.copy()
        poster_img.thumbnail((512, 512))
        buf = io.BytesIO()
        if poster_img.mode not in ("RGB", "L"):
            poster_img = poster_img.convert("RGB")
        poster_img.save(buf, format="JPEG", quality=85)
        poster_bytes = buf.getvalue()

    metadata = {"exif": exif_data}
    dt_raw = exif_data.get("DateTimeOriginal")
    if dt_raw:
        try:
            metadata["capture_ts"] = datetime.strptime(dt_raw, "%Y:%m:%d %H:%M:%S").isoformat()
        except Exception:
            pass
    return metadata, poster_bytes, (width, height)


def _process_video(data: bytes) -> tuple[dict, bytes, tuple[int, int, int]]:
    """Return (metadata_dict, poster_bytes, (w, h, duration_ms))."""
    import av  # type: ignore
    from PIL import Image

    container = av.open(io.BytesIO(data))
    duration_ms = 0
    if container.duration:
        duration_ms = int(container.duration / av.time_base * 1000)
    stream = next((s for s in container.streams if s.type == "video"), None)
    if stream is None:
        raise RuntimeError("no video stream")
    width, height = stream.codec_context.width or 0, stream.codec_context.height or 0

    mid_ts = duration_ms / 2 / 1000 if duration_ms > 0 else 0
    try:
        container.seek(int(mid_ts * av.time_base), any_frame=False, backward=True, stream=stream)
    except Exception:
        pass

    frame = None
    for f in container.decode(stream):
        frame = f
        break

    if frame is None:
        raise RuntimeError("failed to decode video frame")

    img = frame.to_image()
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    poster_bytes = buf.getvalue()

    metadata = {"duration_ms": duration_ms, "video_stream": {"codec": stream.codec_context.name}}
    container.close()
    return metadata, poster_bytes, (width, height, duration_ms)


# ---------------------------------------------------------------------------
# Job handling
# ---------------------------------------------------------------------------


def _upload_poster(store: BlobStore, container: str, poster_bytes: bytes) -> str:
    sha = hashlib.sha256(poster_bytes).hexdigest()
    if not store.exists(sha):
        store.put(sha, poster_bytes, content_type="image/jpeg")
    return sha


def process_asset_job(session: Session, store: BlobStore, container: str, job: IngestionJob) -> None:
    asset: Optional[Asset] = session.get(Asset, job.subject_id)
    if asset is None:
        job.state = "failed"
        job.error = "asset missing"
        return

    data = store.get(asset.blob_sha256)

    if asset.kind == "video":
        metadata, poster_bytes, dims = _process_video(data)
        width, height, duration_ms = dims
        asset.width = width or asset.width
        asset.height = height or asset.height
        asset.duration_ms = duration_ms or asset.duration_ms
    else:
        metadata, poster_bytes, dims = _process_photo(data)
        width, height = dims
        asset.width = width
        asset.height = height

    # Save poster blob (registered as its own row) — reuse Blob table for storage accounting.
    poster_sha = _upload_poster(store, container, poster_bytes)
    poster_blob = session.get(Blob, poster_sha)
    if poster_blob is None:
        poster_blob = Blob(
            sha256=poster_sha,
            size_bytes=len(poster_bytes),
            mime_type="image/jpeg",
            container=container,
            blob_name=poster_sha,
            ref_count=1,
        )
        session.add(poster_blob)
    else:
        poster_blob.ref_count += 1
    asset.poster_blob_sha256 = poster_sha

    exif_json = asset.exif_json or {}
    exif_json.update(metadata)
    asset.exif_json = exif_json

    if asset.capture_ts is None:
        ts_iso = metadata.get("capture_ts")
        if ts_iso:
            try:
                asset.capture_ts = datetime.fromisoformat(ts_iso)
            except Exception:
                pass

    job.state = "done"
    job.error = None


def _backoff_seconds(attempts: int) -> int:
    return min(60 * (2 ** attempts), 3600)


def _next_job(session: Session) -> Optional[IngestionJob]:
    now = datetime.utcnow()
    return (
        session.query(IngestionJob)
        .filter(IngestionJob.state.in_(["queued"]))
        .filter((IngestionJob.next_attempt_at.is_(None)) | (IngestionJob.next_attempt_at <= now))
        .order_by(IngestionJob.created_at)
        .first()
    )


def drain_once(app) -> int:
    """Run one drain pass. Returns the number of jobs handled."""
    session = SessionLocal()
    handled = 0
    try:
        while True:
            job = _next_job(session)
            if job is None:
                break
            job.state = "hashing"
            job.attempts += 1
            session.flush()
            try:
                with app.app_context():
                    store = app.extensions["blob_store"]
                    container = app.config["AZURE_STORAGE_CONTAINER"]
                    process_asset_job(session, store, container, job)
                session.commit()
                handled += 1
            except Exception as exc:  # pragma: no cover - defensive
                session.rollback()
                job_row = session.get(IngestionJob, job.id)
                if job_row is not None:
                    job_row.error = str(exc)[:2000]
                    if job_row.attempts >= MAX_ATTEMPTS:
                        job_row.state = "failed"
                    else:
                        job_row.state = "queued"
                        job_row.next_attempt_at = datetime.utcnow() + timedelta(
                            seconds=_backoff_seconds(job_row.attempts)
                        )
                    session.commit()
                log.exception("ingestion job failed", extra={"job_id": job.id})
    finally:
        session.close()
    return handled


def run_forever(poll_seconds: int = 5) -> None:  # pragma: no cover - long-running
    app = create_app()
    while True:
        n = drain_once(app)
        if n == 0:
            time.sleep(poll_seconds)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    if "--drain" in sys.argv:
        app = create_app()
        n = drain_once(app)
        print(f"drained {n} jobs")
    else:
        run_forever()
