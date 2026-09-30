"""Structured logging helpers."""
from __future__ import annotations

import json
import logging
from typing import Any

_logger = logging.getLogger("memoryhub")


def get_logger() -> logging.Logger:
    return _logger


def configure_logging(level: int = logging.INFO) -> None:
    if _logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(level)


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured log line."""
    payload = {"event": event, **fields}
    _logger.info(json.dumps(payload, default=str))


def log_auth_denied(event: str, endpoint: str, user_id: str | None, reason: str) -> None:
    log_event(event, endpoint=endpoint, user_id=user_id, reason=reason)
