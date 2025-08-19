from __future__ import annotations

"""
JSON API (v1) for Task Printer.

Endpoints:
- POST /api/v1/jobs          : Submit a print job (async). Returns 202 + Location
- GET  /api/v1/jobs/<job_id> : Fetch job status (mirrors /jobs/<id>)

Payload shape (POST /api/v1/jobs):
{
  "sections": [
    {"subtitle": str, "tasks": [
      {"text": str, "flair_type": "none|icon|image|qr|emoji", "flair_value": str, "metadata": {assigned,due,priority,assignee}}
    ]}
  ],
  "options": {"tear_delay_seconds": number}
}
"""

import os
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, jsonify, request, url_for

from task_printer import csrf
from task_printer.core.assets import IMAGE_EXTS, is_supported_image
from task_printer.core.config import MEDIA_PATH, load_config
from task_printer.printing.worker import ensure_worker, enqueue_tasks, get_job


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


# Limits (env-driven, consistent with web routes)
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


def _json_error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


@csrf.exempt
@api_bp.post("/jobs")
def submit_job():
    """
    Accept a JSON job submission, validate, flatten to worker payload, and enqueue.
    Returns 202 Accepted with a Location header to the job status resource.
    """
    if not request.is_json:
        return _json_error("Expected application/json body", 415)

    try:
        cfg = load_config()
    except Exception:
        cfg = None
    if not cfg:
        return _json_error("Service not configured. Complete setup at /setup.", 503)

    data = request.get_json(silent=True) or {}
    sections = data.get("sections") or []
    if not isinstance(sections, list) or not sections:
        return _json_error("sections must be a non-empty list", 400)

    options = data.get("options") or {}
    # Clamp options
    opts: Optional[Dict[str, Any]] = None
    try:
        delay = float(options.get("tear_delay_seconds", 0) or 0)
        if delay < 0:
            delay = 0.0
        if delay > 60:
            delay = 60.0
        if delay > 0:
            opts = {"tear_delay_seconds": delay}
    except Exception:
        # ignore invalid option and treat as absent
        opts = None

    # Validate/flatten
    subtitle_tasks: List[Dict[str, Any]] = []
    total_chars = 0

    for s_idx, sec in enumerate(sections, start=1):
        if not isinstance(sec, dict):
            return _json_error(f"sections[{s_idx}] must be an object", 400)
        subtitle = (sec.get("subtitle") or "").strip()
        if not subtitle:
            return _json_error(f"sections[{s_idx}].subtitle is required", 400)
        if len(subtitle) > MAX_SUBTITLE_LEN:
            return _json_error(
                f"Subtitle in section {s_idx} is too long (max {MAX_SUBTITLE_LEN}).",
                400,
            )
        if _has_control_chars(subtitle):
            return _json_error("Subtitles cannot contain control characters.", 400)
        total_chars += len(subtitle)

        tasks = sec.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return _json_error(f"sections[{s_idx}].tasks must be a non-empty list", 400)
        if len(tasks) > MAX_TASKS_PER_SECTION:
            return _json_error(
                f"Too many tasks in section {s_idx} (max {MAX_TASKS_PER_SECTION}).",
                400,
            )

        for t_idx, t in enumerate(tasks, start=1):
            if not isinstance(t, dict):
                return _json_error(f"sections[{s_idx}].tasks[{t_idx}] must be an object", 400)
            text = (t.get("text") or "").strip()
            if not text:
                # silently skip empties to mirror UI behavior
                continue
            if len(text) > MAX_TASK_LEN:
                return _json_error(
                    f"Task {t_idx} in section {s_idx} is too long (max {MAX_TASK_LEN}).",
                    400,
                )
            if _has_control_chars(text):
                return _json_error("Tasks cannot contain control characters.", 400)
            total_chars += len(text)

            flair = None
            ftype = str(t.get("flair_type") or "none").strip().lower()
            fval = t.get("flair_value")
            if ftype == "icon" and fval:
                flair = {"type": "icon", "value": fval}
            elif ftype == "emoji" and isinstance(fval, str) and fval.strip():
                ev = fval.strip()
                if len(ev) > 16 or _has_control_chars(ev):
                    return _json_error(
                        f"Emoji value invalid in section {s_idx} task {t_idx}.",
                        400,
                    )
                flair = {"type": "emoji", "value": ev}
            elif ftype == "qr" and fval:
                q = str(fval)
                if len(q) > MAX_QR_LEN or _has_control_chars(q):
                    return _json_error(
                        f"QR data invalid in section {s_idx} task {t_idx}.",
                        400,
                    )
                flair = {"type": "qr", "value": q}
            elif ftype == "image" and fval:
                # For API, only allow server-local path (already uploaded) to avoid multipart here
                path = str(fval)
                if not is_supported_image(path):
                    exts = ", ".join(IMAGE_EXTS)
                    return _json_error(f"Unsupported image type. Use one of: {exts}", 400)
                try:
                    # size check if file exists
                    import os as _os

                    if _os.path.isfile(path):
                        size = _os.path.getsize(path)
                        if size and size > MAX_UPLOAD_SIZE:
                            return _json_error("Image too large.", 400)
                except Exception:
                    pass
                flair = {"type": "image", "value": path}

            # Optional metadata
            meta = None
            m = t.get("metadata") or t.get("meta")
            if isinstance(m, dict):
                assigned = (m.get("assigned") or m.get("assigned_date") or "").strip()
                due = (m.get("due") or m.get("due_date") or "").strip()
                priority = (m.get("priority") or "").strip()
                assignee = (m.get("assignee") or "").strip()
                if assigned and not _valid_date_str(assigned):
                    return _json_error(f"Invalid assigned date in section {s_idx} task {t_idx}.", 400)
                if due and not _valid_date_str(due):
                    return _json_error(f"Invalid due date in section {s_idx} task {t_idx}.", 400)
                if any([assigned, due, priority, assignee]):
                    if len(assigned) > 30 or len(due) > 30 or len(priority) > 20 or len(assignee) > 60:
                        return _json_error("Metadata fields too long.", 400)
                    meta = {
                        "assigned": assigned,
                        "due": due,
                        "priority": priority,
                        "assignee": assignee,
                    }

            subtitle_tasks.append({"subtitle": subtitle, "task": text, "flair": flair, "meta": meta})

        if s_idx > MAX_SECTIONS:
            return _json_error(f"Too many sections (max {MAX_SECTIONS}).", 400)

    if total_chars > MAX_TOTAL_CHARS:
        return _json_error(f"Input too large (max total characters {MAX_TOTAL_CHARS}).", 400)
    if not subtitle_tasks:
        return _json_error("No tasks to print.", 400)

    # Enqueue
    try:
        ensure_worker()
        job_id = enqueue_tasks(subtitle_tasks, options=opts)
    except TypeError:
        job_id = enqueue_tasks(subtitle_tasks)  # backward-compat signature
    except Exception as e:
        current_app.logger.exception("Failed to enqueue job: %s", e)
        return _json_error(f"Failed to enqueue job: {e!s}", 500)

    # Construct response with useful links
    api_href = url_for("api.job_status", job_id=job_id)
    ui_href = url_for("jobs.job_status", job_id=job_id)
    resp = jsonify({"id": job_id, "status": "queued", "links": {"self": api_href, "job": ui_href}})
    resp.status_code = 202
    resp.headers["Location"] = api_href
    return resp


@api_bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    """
    Return job status JSON (live or persisted), 404 if not found.
    """
    # Reuse the existing job_status behavior from jobs blueprint via helpers
    job = get_job(job_id)
    if job:
        return job
    try:
        from task_printer.core import db as dbh

        db_job = dbh.get_job_db(job_id)
    except Exception:
        db_job = None
    if db_job:
        return {
            "id": db_job.get("id"),
            "type": db_job.get("type"),
            "status": db_job.get("status"),
            "created_at": db_job.get("created_at"),
            "updated_at": db_job.get("updated_at"),
            "total": db_job.get("total"),
            "origin": db_job.get("origin"),
        }
    return _json_error("not_found", 404)

