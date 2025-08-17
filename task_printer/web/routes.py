from __future__ import annotations

"""
Main UI routes and POST parsing/validation for Task Printer.

This blueprint provides:
- GET/POST /        : Main UI for entering grouped tasks with optional flair
- POST /test_print  : Queue a test print using saved config

Responsibilities extracted from the monolithic app:
- Enforce setup gating (redirect to /setup until config exists)
- Parse dynamic sections/tasks with input limits
- Validate against control characters and max sizes
- Handle flair (icon/image/qr) with upload storage
- Enqueue background jobs and surface job status via banner
"""

import os
import uuid
from typing import Any, Dict, List, Optional
import json

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from task_printer import csrf
from task_printer.core.assets import IMAGE_EXTS, get_available_icons, is_supported_image
from task_printer.core import db as dbh
from task_printer.core.config import MEDIA_PATH, load_config, get_config_path
from task_printer.printing.worker import enqueue_tasks, enqueue_test_print, ensure_worker

web_bp = Blueprint("web", __name__)


# Limits (env-driven, matching previous behavior)
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


MAX_SECTIONS = _env_int("TASKPRINTER_MAX_SECTIONS", 50)
MAX_TASKS_PER_SECTION = _env_int("TASKPRINTER_MAX_TASKS_PER_SECTION", 50)
MAX_TASK_LEN = _env_int("TASKPRINTER_MAX_TASK_LEN", 200)
MAX_SUBTITLE_LEN = _env_int("TASKPRINTER_MAX_SUBTITLE_LEN", 100)
MAX_TOTAL_CHARS = _env_int("TASKPRINTER_MAX_TOTAL_CHARS", 5000)
MAX_QR_LEN = _env_int("TASKPRINTER_MAX_QR_LEN", 512)
MAX_UPLOAD_SIZE = _env_int("TASKPRINTER_MAX_UPLOAD_SIZE", 5 * 1024 * 1024)


def _has_control_chars(s: str) -> bool:
    return any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in s)


@web_bp.before_app_request
def _setup_gating():
    """
    Redirect to /setup until config exists, mirroring previous app-wide behavior.
    Excludes /setup and /setup_test_print so the user can complete setup.
    """
    path = request.path or ""
    if path.startswith("/setup") or path.startswith("/setup_test_print"):
        return None
    cfg = load_config(get_config_path())
    if not cfg:
        return redirect(url_for("setup.setup"))
    g.config = cfg  # make config available to downstream handlers
    return None


@web_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        current_app.logger.info(
            "index POST received: form_keys=%s files=%s",
            list(request.form.keys()),
            list(request.files.keys()),
        )
        # Parse all subtitle/task groups from the form with limits
        subtitle_tasks: List[Dict[str, Any]] = []
        form = request.form
        section = 1

        while True:
            subtitle_key = f"subtitle_{section}"
            subtitle = (form.get(subtitle_key, "") or "").strip()

            if not subtitle and section == 1:
                # If the first section is empty, treat as no input
                break
            if not subtitle:
                # No more sections
                break

            if len(subtitle) > MAX_SUBTITLE_LEN:
                flash(f"Subtitle in section {section} is too long (max {MAX_SUBTITLE_LEN}).", "error")
                return redirect(url_for("web.index"))
            if _has_control_chars(subtitle):
                flash("Subtitles cannot contain control characters.", "error")
                return redirect(url_for("web.index"))

            # Find all tasks for this section
            task_num = 1
            while True:
                task_key = f"task_{section}_{task_num}"
                task = (form.get(task_key, "") or "").strip()
                if not task:
                    break

                if len(task) > MAX_TASK_LEN:
                    flash(f"Task {task_num} in section {section} is too long (max {MAX_TASK_LEN}).", "error")
                    return redirect(url_for("web.index"))
                if _has_control_chars(task):
                    flash("Tasks cannot contain control characters.", "error")
                    return redirect(url_for("web.index"))

                # Flair parsing
                flair: Optional[Dict[str, str]] = None
                ftype = form.get(f"flair_type_{section}_{task_num}", "none")

                if ftype == "icon":
                    icon_key = (form.get(f"flair_icon_{section}_{task_num}", "") or "").strip()
                    if icon_key:
                        flair = {"type": "icon", "value": icon_key}

                elif ftype == "qr":
                    qr_val = (form.get(f"flair_qr_{section}_{task_num}", "") or "").strip()
                    if qr_val:
                        if len(qr_val) > MAX_QR_LEN:
                            flash(
                                f"QR data too long in section {section} task {task_num} (max {MAX_QR_LEN}).",
                                "error",
                            )
                            return redirect(url_for("web.index"))
                        if _has_control_chars(qr_val):
                            flash("QR data cannot contain control characters.", "error")
                            return redirect(url_for("web.index"))
                        flair = {"type": "qr", "value": qr_val}

                elif ftype == "image":
                    file_key = f"flair_image_{section}_{task_num}"
                    if file_key in request.files:
                        file = request.files.get(file_key)
                        if file and file.filename:
                            fname = secure_filename(file.filename)
                            if not is_supported_image(fname):
                                exts = ", ".join(IMAGE_EXTS)
                                flash(f"Unsupported image type. Use one of: {exts}", "error")
                                return redirect(url_for("web.index"))

                            # size check
                            try:
                                file.stream.seek(0, os.SEEK_END)
                                size = file.stream.tell()
                                file.stream.seek(0)
                            except Exception:
                                size = 0
                            if size and size > MAX_UPLOAD_SIZE:
                                flash("Image too large.", "error")
                                return redirect(url_for("web.index"))

                            ext = os.path.splitext(fname)[1].lower()
                            unique = uuid.uuid4().hex + ext
                            dest = os.path.join(MEDIA_PATH, unique)
                            file.save(dest)
                            flair = {"type": "image", "value": dest}

                subtitle_tasks.append({"subtitle": subtitle, "task": task, "flair": flair})
                task_num += 1

                if task_num > MAX_TASKS_PER_SECTION:
                    flash(f"Too many tasks in section {section} (max {MAX_TASKS_PER_SECTION}).", "error")
                    return redirect(url_for("web.index"))

            section += 1
            if section > MAX_SECTIONS:
                flash(f"Too many sections (max {MAX_SECTIONS}).", "error")
                return redirect(url_for("web.index"))

        total_chars = sum(len(item.get("subtitle", "")) + len(item.get("task", "")) for item in subtitle_tasks)
        if total_chars > MAX_TOTAL_CHARS:
            flash(f"Input too large (max total characters {MAX_TOTAL_CHARS}).", "error")
            return redirect(url_for("web.index"))

        if not subtitle_tasks:
            flash("Please enter at least one task.", "error")
            return redirect(url_for("web.index"))

        # Parse optional tear-off delay
        raw = (form.get("tear_delay_seconds", "") or "").strip()
        delay: float = 0.0
        options: Optional[Dict[str, Any]] = None
        if raw:
            try:
                delay = float(raw)
            except Exception:
                flash("Invalid tear-off delay; please enter a number.", "error")
                return redirect(url_for("web.index"))
            # Clamp to [0, 60]
            if delay < 0:
                delay = 0.0
            if delay > 60:
                delay = 60.0
        if delay > 0:
            options = {"tear_delay_seconds": delay}

        try:
            ensure_worker()
            try:
                job_id = enqueue_tasks(subtitle_tasks, options=options)
            except TypeError:
                # Backward-compatible with patched tests that expect single-arg
                job_id = enqueue_tasks(subtitle_tasks)
            note = ""
            if options:
                note = f" Tear-off mode enabled: {delay}s (no cut)."
            flash(f"Queued {len(subtitle_tasks)} task(s) for printing. Job: {job_id}.{note}", "success")
            return redirect(url_for("web.index", job=job_id))
        except Exception as e:
            flash(f"Error queuing print job: {e!s}", "error")
            return redirect(url_for("web.index"))

    # GET
    job_id = request.args.get("job")
    prefill_id = request.args.get("prefill")
    prefill_template = None
    try:
        if prefill_id is not None:
            tid = int(prefill_id)
            t = dbh.get_template(tid)
            if t:
                prefill_template = t  # pass as object; template will tojson it
    except Exception:
        prefill_template = None

    # Default tear-off to preload in the form (modifiable per submission)
    default_tear_delay = 0.0
    try:
        cfg = getattr(g, "config", None) or {}
        raw = cfg.get("default_tear_delay_seconds", 0)
        d = float(raw or 0)
        if d < 0:
            d = 0.0
        if d > 60:
            d = 60.0
        default_tear_delay = d
    except Exception:
        default_tear_delay = 0.0

    return render_template(
        "index.html",
        job_id=job_id,
        icons=get_available_icons(),
        prefill_template=prefill_template,
        default_tear_delay=default_tear_delay,
    )


@csrf.exempt
@web_bp.route("/test_print", methods=["POST"])
def test_print():
    current_app.logger.info("POST /test_print received; cookies_has_csrf=%s", "csrf_token" in request.cookies)
    try:
        current_app.logger.info("test_print: ensuring worker...")
        ensure_worker()
        current_app.logger.info("test_print: worker ensured, enqueuing test job...")
        job_id = enqueue_test_print()
        current_app.logger.info("test_print: job enqueued id=%s", job_id)
        flash(f"Test print queued. Job: {job_id}", "success")
        location = url_for("web.index", job=job_id)
        current_app.logger.info("test_print: redirecting to %s", location)
        resp = redirect(location)
        return resp
    except Exception as e:
        current_app.logger.exception("test_print error: %s", e)
        flash(f"Error queuing test print: {e!s}", "error")
        return redirect(url_for("web.index"))


@web_bp.route("/help")
def help():
    """Display help page with usage instructions."""
    return render_template("help.html")
