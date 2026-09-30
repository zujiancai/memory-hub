"""SQLAlchemy engine + session helpers."""
from __future__ import annotations

from typing import Optional

from flask import Flask, g
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Shared declarative base."""


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def init_engine(database_url: str) -> Engine:
    global _engine, _SessionLocal
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
    )
    if database_url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _enable_fk(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialised. Call init_engine first.")
    return _engine


def SessionLocal() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Sessionmaker not initialised.")
    return _SessionLocal()


def register_session_teardown(app: Flask) -> None:
    """Attach a request-scoped session to Flask ``g``."""

    @app.before_request
    def _open_session() -> None:  # noqa: ANN202
        g.db = SessionLocal()

    @app.teardown_request
    def _close_session(exc):  # noqa: ANN001, ANN202
        db = g.pop("db", None)
        if db is None:
            return
        try:
            if exc is not None:
                db.rollback()
        finally:
            db.close()


def db() -> Session:
    return g.db
