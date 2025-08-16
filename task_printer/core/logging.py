"""
Logging utilities for Task Printer.

Extracted from the monolithic app module to:
- Provide a RequestIdFilter that attaches request_id and path (when in a Flask request context)
- Provide a JsonFormatter for structured logs when TASKPRINTER_JSON_LOGS=true
- Provide configure_logging() to initialize root logging with journald or console, and integrate with Flask's logger
"""

from __future__ import annotations

import logging
import os


class RequestIdFilter(logging.Filter):
    """
    Attach request-scoped metadata (request_id, path) to log records.
    Safely degrades outside of a Flask request context.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            from flask import g, has_request_context, request  # lazy import

            record.request_id = g.request_id if has_request_context() and hasattr(g, "request_id") else "-"
            record.path = request.path if has_request_context() else "-"
        except Exception:
            record.request_id = "-"
            record.path = "-"
        return True


class JsonFormatter(logging.Formatter):
    """
    Minimal JSON formatter that includes timestamp, level, message, request_id, and path.
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        from json import dumps

        base = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        path = getattr(record, "path", None)
        if path is not None:
            base["path"] = path
        return dumps(base, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    """
    Configure root logging for the application.

    Behavior:
    - Sets root logger to INFO
    - Clears any existing handlers to avoid duplicates on reload
    - Chooses JSON or plain formatter based on TASKPRINTER_JSON_LOGS
    - Prefer systemd's JournalHandler, fallback to StreamHandler
    - Adds RequestIdFilter so formatters can reference %(request_id)s
    - Ensures Flask app logger propagates to root (no separate handlers)

    Returns the configured root logger.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate logs in dev reloads or repeated factory calls
    root.handlers = []

    json_logs = os.environ.get("TASKPRINTER_JSON_LOGS", "false").lower() in ("1", "true", "yes")
    formatter: logging.Formatter
    if json_logs:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(request_id)s %(message)s")

    # Prefer systemd journal when available
    try:
        from systemd.journal import JournalHandler  # type: ignore

        handler: logging.Handler = JournalHandler()
        handler.setFormatter(formatter)
    except Exception:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)

    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)

    # Make Flask's app logger propagate to root (avoid double formatting)
    try:
        flask_logger = logging.getLogger("flask.app")
        flask_logger.handlers = []
        flask_logger.propagate = True
    except Exception:
        # Non-fatal; continue without altering Flask logger
        pass

    return root


__all__ = ["JsonFormatter", "RequestIdFilter", "configure_logging"]
