"""Structured logging + error-tracking hook (Phase 6 — observability).

* **JSON lines** — :class:`JsonFormatter` emits one JSON object per log
  record (``ts``, ``level``, ``logger``, ``msg``, ``request_id`` and, when
  present, ``method``/``path``/``status``/``duration_ms`` extras).
* **Request ids** — a :class:`contextvars.ContextVar` carries the current
  request's id; the backend middleware assigns or propagates the
  ``X-Request-ID`` header and stamps it on every line logged while
  handling that request.
* **Privacy rule** — log lines carry method, path, status and duration
  only: never request/response bodies, e-mails, tokens or profile text.
  :func:`redact_path` additionally scrubs token-like path segments
  (magic-link / consent-confirm tokens travel in URLs) before logging.
* **Error hook** — :func:`notify_error_webhook` posts a minimal JSON
  payload (error type, truncated message, request id — no bodies, no
  user data) to ``ERROR_WEBHOOK_URL`` when set. It is a no-op by default
  and every failure inside it is swallowed: tracking must never break
  the request it is reporting on.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import urllib.request
import uuid
from datetime import datetime, timezone

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "career_guidance_request_id", default=""
)

_TOKEN_SEGMENT = re.compile(r"^[A-Za-z0-9_\-.]{24,}$")


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str:
    return request_id_ctx.get()


def set_request_id(value: str):
    return request_id_ctx.set(value)


def redact_path(path: str) -> str:
    """Replace token-like path segments with ``[redacted]``."""
    parts = []
    for segment in path.split("/"):
        parts.append("[redacted]" if _TOKEN_SEGMENT.match(segment) else segment)
    return "/".join(parts)


class JsonFormatter(logging.Formatter):
    """One JSON object per record; extras pass through when present."""

    _EXTRA_KEYS = ("method", "path", "status", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="seconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "") or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key in self._EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def install_json_logging(level: str = "INFO") -> logging.Logger:
    """Route the root logger through the JSON formatter (idempotent)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for handler in root.handlers:
        if getattr(handler, "_cg_json", False):
            return logging.getLogger("career_guidance")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler._cg_json = True  # type: ignore[attr-defined]
    root.handlers = [handler]
    return logging.getLogger("career_guidance")


def notify_error_webhook(error_type: str, message: str, request_id: str = "") -> bool:
    """POST a minimal error payload to ``ERROR_WEBHOOK_URL`` (no-op unset).

    Returns True when a webhook was configured and accepted the POST.
    All failures are swallowed — this hook must never raise.
    """
    url = os.getenv("ERROR_WEBHOOK_URL", "").strip()
    if not url:
        return False
    payload = json.dumps(
        {
            "event": "unhandled_error",
            "error_type": error_type,
            "message": str(message)[:500],
            "request_id": request_id or get_request_id(),
        }
    ).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=2):  # noqa: S310 - operator-set URL
            return True
    except Exception:  # noqa: BLE001 - tracking failures are swallowed by design
        return False
