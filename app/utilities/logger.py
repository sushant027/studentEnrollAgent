"""Structured JSON logging.

Every line is one JSON object carrying `request_id`, `session_id` and `event`, so a whole
conversation can be reconstructed with `grep request_id` or piped through `jq`.

Correlation IDs travel in context variables rather than being threaded through every call
signature, which means tools and graph nodes deep in the stack log the same IDs as the HTTP
layer without knowing about it.

Redaction: passwords, hashes, tokens, API keys, names and email addresses are never logged.
`student_id` and `applicant_id` ARE logged — access decisions have to be auditable.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")
_student_id: ContextVar[str] = ContextVar("student_id", default="-")

#: Keys that must never appear in a log line, whatever the caller passes.
_FORBIDDEN_KEYS = {
    "password",
    "password_hash",
    "hash",
    "token",
    "access_token",
    "jwt",
    "authorization",
    "api_key",
    "openai_api_key",
    "jwt_secret",
    "secret",
    "email",
    "name",
    "applicant_name",
}

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_context(
    request_id: str | None = None,
    session_id: str | None = None,
    student_id: str | None = None,
) -> None:
    """Bind correlation IDs for everything logged on this task from here on."""
    if request_id is not None:
        _request_id.set(request_id)
    if session_id is not None:
        _session_id.set(session_id)
    if student_id is not None:
        _student_id.set(student_id)


def get_context() -> dict[str, str]:
    return {
        "request_id": _request_id.get(),
        "session_id": _session_id.get(),
        "student_id": _student_id.get(),
    }


def clear_context() -> None:
    _request_id.set("-")
    _session_id.set("-")
    _student_id.set("-")


def mask_email(email: str) -> str:
    """`john@example.com` -> `j***@example.com`. For debugging logins without logging PII."""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _scrub(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop forbidden keys and rename collisions with LogRecord attributes."""
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key.lower() in _FORBIDDEN_KEYS:
            out[f"{key}_redacted"] = True
            continue
        out[f"{key}_" if key in _RESERVED else key] = value
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": getattr(record, "event", "LOG"),
            "request_id": getattr(record, "request_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "student_id": getattr(record, "student_id", "-"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return json.dumps({"level": "ERROR", "message": "unserializable log record"})


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. Safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    # uvicorn's own handlers would double-print; route them through ours instead.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(noisy)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("openai").setLevel("WARNING")


class EventLogger:
    """Thin wrapper that stamps every line with the current correlation IDs."""

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, message: str, fields: dict[str, Any]) -> None:
        extra = {"event": event, **get_context(), **_scrub(fields)}
        self._log.log(level, message, extra=extra, stacklevel=3)

    def event(self, event: str, message: str = "", **fields: Any) -> None:
        self._emit(logging.INFO, event, message or event, fields)

    def debug(self, event: str, message: str = "", **fields: Any) -> None:
        self._emit(logging.DEBUG, event, message or event, fields)

    def warn(self, event: str, message: str = "", **fields: Any) -> None:
        self._emit(logging.WARNING, event, message or event, fields)

    def error(self, event: str, message: str = "", exc_info: bool = False, **fields: Any) -> None:
        extra = {"event": event, **get_context(), **_scrub(fields)}
        self._log.error(message or event, extra=extra, exc_info=exc_info, stacklevel=2)

    @contextmanager
    def timed(self, event: str, message: str = "", **fields: Any):
        """Log an event with `duration_ms` attached, and log failures automatically.

        Used around every tool call and LLM call so a slow or failing step is obvious
        in the log without extra instrumentation.
        """
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self.error(
                event,
                message or event,
                exc_info=True,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                outcome="exception",
                error_type=type(exc).__name__,
                **fields,
            )
            raise
        else:
            self._emit(
                logging.INFO,
                event,
                message or event,
                {
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "outcome": "ok",
                    **fields,
                },
            )


def get_logger(name: str) -> EventLogger:
    return EventLogger(name)
