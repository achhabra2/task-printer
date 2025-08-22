"""
Task Printer package

This module provides an application factory with minimal wiring:
- Configures logging (uses task_printer.core.logging if present; falls back otherwise)
- Creates a Flask app with template/static folders pointing at the repository-level dirs
- Initializes CSRF protection and sets a CSRF cookie after each request
- Registers available blueprints if they exist (non-failing optional imports)
- Optionally ensures the background worker is started if available
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from flask import Flask, g, request
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from jinja2 import StrictUndefined

csrf = CSRFProtect()


def _default_secret_key() -> str:
    return os.environ.get("TASKPRINTER_SECRET_KEY", "taskprinter_dev_secret_key")


def _configure_logging() -> None:
    """
    Configure logging using the project's logging module if available,
    otherwise fall back to a reasonable default.
    """
    try:
        # Prefer a dedicated logging module if/when it exists after refactor.
        mod = importlib.import_module("task_printer.core.logging")
        if hasattr(mod, "configure_logging"):
            mod.configure_logging()  # type: ignore[attr-defined]
            return
    except Exception:
        pass

    # Fallback: basic console logging with a minimal formatter
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
        root.addHandler(handler)


def _maybe_register_blueprint(app: Flask, import_path: str, attr: str) -> None:
    """
    Try to import a blueprint from import_path and register it if found.
    Silently ignores missing modules/attributes to keep scaffolding non-breaking.
    """
    try:
        mod = importlib.import_module(import_path)
        bp = getattr(mod, attr, None)
        if bp is not None:
            app.register_blueprint(bp)
            app.logger.info(f"Registered blueprint: {import_path}.{attr}")
    except Exception as e:
        # Intentionally quiet in early scaffolding; log at debug level.
        app.logger.debug(f"Blueprint not registered ({import_path}.{attr}): {e}")


def _set_request_id() -> None:
    """
    Assign a request ID for logging if not set by a filter elsewhere.
    """
    try:
        import uuid

        g.request_id = getattr(g, "request_id", uuid.uuid4().hex)
    except Exception:
        # Non-fatal; just skip if something goes wrong
        pass


def _set_csrf_cookie(response):
    """
    Ensure a CSRF cookie is present for client-side requests that use AJAX.
    """
    try:
        token = generate_csrf()
        response.set_cookie("csrf_token", token, secure=False, httponly=False, samesite="Lax")
    except Exception:
        # Don't block responses if CSRF cookie can't be set
        pass
    return response


def create_app(
    config_overrides: Optional[dict] = None,
    blueprints: Optional[Sequence[tuple[str, str]]] = None,
    register_worker: bool = True,
    enable_mcp: bool = False,
) -> Flask:
    """
    Application factory.

    Parameters:
    - config_overrides: values to inject into app.config after defaults
    - blueprints: optional list of (import_path, attribute) tuples to register
      If None, a sensible default set is attempted.
    - register_worker: if True, attempts to start the background worker if available
    - enable_mcp: if True, creates and attaches an MCP server instance to the app

    Returns:
    - Flask app instance
    """
    # Point templates/static at repo-level folders to preserve current filesystem layout
    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent  # task-printer/
    templates_dir = repo_root / "templates"
    static_dir = repo_root / "static"

    app = Flask(
        "task_printer",
        template_folder=str(templates_dir) if templates_dir.exists() else None,
        static_folder=str(static_dir) if static_dir.exists() else None,
    )
    # Fail fast on missing variables in templates
    app.jinja_env.undefined = StrictUndefined

    # Basic config and limits (mirrors current env-driven approach)
    app.secret_key = _default_secret_key()
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("TASKPRINTER_MAX_CONTENT_LENGTH", 1024 * 1024))  # 1 MiB

    # Initialize extensions
    csrf.init_app(app)
    # Initialize DB teardown hooks if available
    try:
        from task_printer.core import db as _db

        _db.init_app(app)  # type: ignore[attr-defined]
    except Exception:
        pass

    # Logging
    _configure_logging()
    app.logger.info("Task Printer app created")

    # Strict slashes off for more forgiving routing
    app.url_map.strict_slashes = False

    # Generic request hooks
    @app.before_request
    def _before_request():
        _set_request_id()

    @app.after_request
    def _after_request(response):
        # Always set CSRF cookie on safe methods and redirects so forms keep working after POST→redirect.
        if request.method in ("GET", "HEAD", "OPTIONS") or (300 <= response.status_code < 400):
            return _set_csrf_cookie(response)
        return response

    # Register blueprints
    default_blueprints = [
        # These are optional and will be skipped if files don't exist yet.
        ("task_printer.web.routes", "web_bp"),  # main UI
        ("task_printer.web.jobs", "jobs_bp"),  # jobs list/status
        ("task_printer.web.health", "health_bp"),  # health endpoint
        ("task_printer.web.setup", "setup_bp"),  # setup flow
        ("task_printer.web.templates", "templates_bp"),  # templates CRUD/print
        ("task_printer.web.api", "api_bp"),  # versioned JSON API
        ("task_printer.web.api_templates", "api_templates_bp"),  # templates CRUD API (v1)
    ]
    for import_path, attr in blueprints or default_blueprints:
        _maybe_register_blueprint(app, import_path, attr)

    # Optionally ensure background worker is running
    if register_worker:
        try:
            worker_mod = importlib.import_module("task_printer.printing.worker")
            if hasattr(worker_mod, "ensure_worker"):
                worker_mod.ensure_worker()  # type: ignore[attr-defined]
                app.logger.info("Background worker ensured")
        except Exception as e:
            app.logger.debug(f"Worker not started (optional): {e}")

    # Optionally create MCP server
    if enable_mcp:
        try:
            from .mcp import create_mcp_server_if_available
            mcp_server = create_mcp_server_if_available(app)
            if mcp_server:
                app.mcp_server = mcp_server
                app.logger.info("MCP server created and attached to app")
            else:
                app.logger.warning("MCP server creation failed or unavailable")
        except Exception as e:
            app.logger.debug(f"MCP server not available: {e}")

    # Allow runtime overrides
    if config_overrides:
        app.config.update(config_overrides)

    return app


# Re-export common blueprints when available for convenience
try:
    from .web import health_bp, jobs_bp, setup_bp, templates_bp, web_bp  # type: ignore
except Exception:
    # Keep names defined for type checkers; actual availability is optional
    web_bp = jobs_bp = setup_bp = health_bp = templates_bp = None  # type: ignore

__all__ = ["create_app", "csrf", "health_bp", "jobs_bp", "setup_bp", "templates_bp", "web_bp"]

# Eagerly import subpackages to avoid implicit namespace package diagnostics in some tooling
try:
    import task_printer.core
    import task_printer.printing
    import task_printer.web  # noqa: F401
except Exception:
    pass
