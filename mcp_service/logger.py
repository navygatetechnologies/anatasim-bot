"""Structured JSON logger for mcp_service.

Every log line is a single JSON object written to stdout, suitable for
ingestion by any log aggregator (Datadog, CloudWatch, Grafana Loki, etc.).

Usage:
    from logger import get_logger, new_request_id

    # At the start of each request (main.py):
    new_request_id()

    # Anywhere in the call stack:
    log = get_logger(__name__)
    log.info("tool_call_started", tool="get_velocity_context", user_id="u_123")
    log.warning("agent_max_turns_reached", turns=10, user_id="u_123")
    log.error("agent_loop_error", error=str(exc), traceback=tb)

Every call automatically stamps:
    ts          ISO-8601 UTC timestamp
    level       debug / info / warning / error
    logger      the __name__ of the caller
    request_id  the current request's correlation ID (set by new_request_id())
"""
import json
import logging
import traceback as tb_module
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Request correlation ID — stored in a ContextVar so concurrent async
# requests each carry their own ID without interfering with each other.
# ---------------------------------------------------------------------------
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Generate a fresh short ID and bind it to the current async context.
    Call this once at the top of every request handler."""
    rid = uuid.uuid4().hex[:8]
    _request_id_var.set(rid)
    return rid


def current_request_id() -> str:
    return _request_id_var.get()


# ---------------------------------------------------------------------------
# JSON formatter — turns a LogRecord into one JSON line on stdout.
# ---------------------------------------------------------------------------
class _JsonFormatter(logging.Formatter):

    _LEVEL_MAP = {
        logging.DEBUG:    "debug",
        logging.INFO:     "info",
        logging.WARNING:  "warning",
        logging.ERROR:    "error",
        logging.CRITICAL: "critical",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Base fields always present
        payload: dict[str, Any] = {
            "ts":         datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level":      self._LEVEL_MAP.get(record.levelno, "unknown"),
            "logger":     record.name,
            "request_id": current_request_id(),
            "event":      record.getMessage(),
        }

        # Extra keyword fields attached via log.info("event", **kwargs)
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _STDLIB_ATTRS:
                continue
            payload[key] = value

        # Exception info — include traceback text when present
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


# Standard LogRecord attributes we don't want to re-emit as extra fields
_STDLIB_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_configured = False


def _configure(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())

    # Remove any existing handlers (e.g. uvicorn's default ones) so we don't
    # get duplicate lines
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers that aren't useful in prod
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


class _StructuredLogger:
    """Thin wrapper around a standard Logger that accepts keyword arguments
    as extra structured fields on each log call.

    log.info("tool_call_started", tool="get_velocity_context", duration_ms=42)
    """

    def __init__(self, name: str):
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, **kwargs: Any) -> None:
        if self._log.isEnabledFor(level):
            self._log.log(level, event, extra=kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.WARNING, event, **kwargs)

    def error(self, event: str, exc_info: bool = False, **kwargs: Any) -> None:
        if exc_info:
            kwargs["traceback"] = tb_module.format_exc()
        self._emit(logging.ERROR, event, **kwargs)


def get_logger(name: str) -> _StructuredLogger:
    """Return a structured logger for the given module name.
    Call _configure() first (done automatically by main.py at startup)."""
    return _StructuredLogger(name)


def configure(level: str = "INFO") -> None:
    """Configure the root logger. Called once from main.py lifespan."""
    _configure(level)
