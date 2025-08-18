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

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from task_printer import csrf
from task_printer.core import db as dbh
from task_printer.core.assets import IMAGE_EXTS, get_available_icons, is_supported_image
from task_printer.core.config import MEDIA_PATH, get_config_path, load_config
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


def _valid_date_str(s: str) -> bool:
    """Allow empty, YYYY-MM-DD, MM-DD, or MM/DD; check basic ranges."""
    if not s:
        return True
    try:
        s = str(s).strip()
        if not s:
            return True
        import re

        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            y, m, d = s.split("-")
            mi, di = int(m), int(d)
            return 1 <= mi <= 12 and 1 <= di <= 31
        if re.match(r"^\d{2}-\d{2}$", s) or re.match(r"^\d{2}/\d{2}$", s):
            parts = s.replace("/", "-").split("-")
            mi, di = int(parts[0]), int(parts[1])
            return 1 <= mi <= 12 and 1 <= di <= 31
        return False
    except Exception:
        return False


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
        # Build tasks either from JSON payload (preferred) or legacy dynamic form
        subtitle_tasks: List[Dict[str, Any]] = []
        form = request.form

        payload_raw = form.get("payload_json")
        used_payload = False
        if payload_raw:
            try:
                data = json.loads(payload_raw)
                sections = data.get("sections") or []
                if not isinstance(sections, list):
                    raise ValueError("sections must be a list")
                if len(sections) > MAX_SECTIONS:
                    raise ValueError(f"Too many sections (max {MAX_SECTIONS}).")

                # Prepare a set of known icon names (best-effort)
                icons: set[str] = set()
                try:
                    for ic in get_available_icons():
                        name = None
                        try:
                            name = ic.get("name")  # type: ignore[attr-defined]
                        except Exception:
                            name = getattr(ic, "name", None)
                        if name:
                            icons.add(str(name))
                except Exception:
                    icons = set()

                total_chars = 0
                for s_idx, sec in enumerate(sections, start=1):
                    if not isinstance(sec, dict):
                        continue
                    subtitle = (sec.get("subtitle") or "").strip()
                    if subtitle:
                        if len(subtitle) > MAX_SUBTITLE_LEN:
                            raise ValueError(f"Subtitle in section {s_idx} is too long (max {MAX_SUBTITLE_LEN}).")
                        if _has_control_chars(subtitle):
                            raise ValueError("Subtitles cannot contain control characters.")
                        total_chars += len(subtitle)

                    tasks = list(sec.get("tasks") or [])
                    if not isinstance(tasks, list):
                        tasks = []
                    if len(tasks) > MAX_TASKS_PER_SECTION:
                        raise ValueError(f"Too many tasks in section {s_idx} (max {MAX_TASKS_PER_SECTION}).")

                    # For each task, validate and optionally attach flair
                    for t_idx, t in enumerate(tasks, start=1):
                        if not isinstance(t, dict):
                            continue
                        text = (t.get("text") or "").strip()
                        if not text:
                            continue
                        if len(text) > MAX_TASK_LEN:
                            raise ValueError(f"Task {t_idx} in section {s_idx} is too long (max {MAX_TASK_LEN}).")
                        if _has_control_chars(text):
                            raise ValueError("Tasks cannot contain control characters.")
                        total_chars += len(text)

                        flair = None
                        meta: Optional[Dict[str, Any]] = None
                        ftype = str(t.get("flair_type") or "none").strip().lower()
                        fval = t.get("flair_value")

                        if ftype == "icon":
                            if fval:
                                # Tolerate unknown icon name; do not hard fail
                                flair = {"type": "icon", "value": fval}
                        elif ftype == "emoji":
                            if isinstance(fval, str) and fval.strip():
                                ev = fval.strip()
                                # Basic validation: limit length and control chars
                                if len(ev) > 16:
                                    raise ValueError(
                                        f"Emoji value too long in section {s_idx} task {t_idx} (max 16).",
                                    )
                                if _has_control_chars(ev):
                                    raise ValueError("Emoji cannot contain control characters.")
                                flair = {"type": "emoji", "value": ev}
                        elif ftype == "qr":
                            if fval:
                                q = str(fval)
                                if len(q) > MAX_QR_LEN:
                                    raise ValueError(
                                        f"QR data too long in section {s_idx} task {t_idx} (max {MAX_QR_LEN}).",
                                    )
                                if _has_control_chars(q):
                                    raise ValueError("QR data cannot contain control characters.")
                                flair = {"type": "qr", "value": q}
                        elif ftype == "image":
                            # Determine upload field from payload (flair_value) or fallback to DOM-aligned default
                            file_key = str(fval) if (isinstance(fval, str) and fval) else f"flair_image_{s_idx}_{t_idx}"
                            if file_key in request.files:
                                file = request.files.get(file_key)
                                if file and file.filename:
                                    fname = secure_filename(file.filename)
                                    if not is_supported_image(fname):
                                        exts = ", ".join(IMAGE_EXTS)
                                        raise ValueError(f"Unsupported image type. Use one of: {exts}")
                                    # size check
                                    try:
                                        file.stream.seek(0, os.SEEK_END)
                                        size = file.stream.tell()
                                        file.stream.seek(0)
                                    except Exception:
                                        size = 0
                                    if size and size > MAX_UPLOAD_SIZE:
                                        raise ValueError("Image too large.")
                                    ext = os.path.splitext(fname)[1].lower()
                                    unique = uuid.uuid4().hex + ext
                                    dest = os.path.join(MEDIA_PATH, unique)
                                    file.save(dest)
                                    flair = {"type": "image", "value": dest}

                        # Optional metadata
                        m = t.get("metadata") or t.get("meta")
                        if isinstance(m, dict):
                            # Shallow validation/limits
                            assigned = (m.get("assigned") or m.get("assigned_date") or "").strip()
                            due = (m.get("due") or m.get("due_date") or "").strip()
                            priority = (m.get("priority") or "").strip()
                            assignee = (m.get("assignee") or "").strip()
                            if assigned and not _valid_date_str(assigned):
                                raise ValueError(f"Invalid assigned date in section {s_idx} task {t_idx}.")
                            if due and not _valid_date_str(due):
                                raise ValueError(f"Invalid due date in section {s_idx} task {t_idx}.")
                            if any([assigned, due, priority, assignee]):
                                # Length clamps
                                if len(assigned) > 30 or len(due) > 30 or len(priority) > 20 or len(assignee) > 60:
                                    raise ValueError("Metadata fields too long.")
                                meta = {
                                    "assigned": assigned,
                                    "due": due,
                                    "priority": priority,
                                    "assignee": assignee,
                                }

                        subtitle_tasks.append({"subtitle": subtitle, "task": text, "flair": flair, "meta": meta})

                if total_chars > MAX_TOTAL_CHARS:
                    raise ValueError(f"Input too large (max total characters {MAX_TOTAL_CHARS}).")

                # If we reached here, the payload_json path succeeded; suppress legacy parsing
                used_payload = True
                # Ensure the legacy parser below sees an empty form
                form = {}
            except Exception as e:
                current_app.logger.warning(
                    "payload_json parse/validate failed: %s; falling back to legacy form parser",
                    e,
                )

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

                elif ftype == "emoji":
                    emoji_val = (form.get(f"flair_emoji_{section}_{task_num}", "") or "").strip()
                    if emoji_val:
                        if len(emoji_val) > 16:
                            flash(
                                f"Emoji too long in section {section} task {task_num} (max 16).",
                                "error",
                            )
                            return redirect(url_for("web.index"))
                        if _has_control_chars(emoji_val):
                            flash("Emoji cannot contain control characters.", "error")
                            return redirect(url_for("web.index"))
                        flair = {"type": "emoji", "value": emoji_val}

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

                # Optional metadata via legacy fields
                assigned = (form.get(f"detail_assigned_{section}_{task_num}", "") or "").strip()
                due = (form.get(f"detail_due_{section}_{task_num}", "") or "").strip()
                priority = (form.get(f"detail_priority_{section}_{task_num}", "") or "").strip()
                assignee = (form.get(f"detail_assignee_{section}_{task_num}", "") or "").strip()
                meta = None
                if any([assigned, due, priority, assignee]):
                    if assigned and not _valid_date_str(assigned):
                        flash("Invalid assigned date.", "error")
                        return redirect(url_for("web.index"))
                    if due and not _valid_date_str(due):
                        flash("Invalid due date.", "error")
                        return redirect(url_for("web.index"))
                    if len(assigned) > 30 or len(due) > 30 or len(priority) > 20 or len(assignee) > 60:
                        flash("Metadata fields too long.", "error")
                        return redirect(url_for("web.index"))
                    meta = {
                        "assigned": assigned,
                        "due": due,
                        "priority": priority,
                        "assignee": assignee,
                    }

                subtitle_tasks.append({"subtitle": subtitle, "task": task, "flair": flair, "meta": meta})
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
