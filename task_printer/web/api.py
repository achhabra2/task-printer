from __future__ import annotations

"""
JSON API (v1) for Task Printer.

Endpoints:
- POST /api/v1/jobs          : Submit a print job (async). Returns 202 + Location
- GET  /api/v1/jobs/<job_id> : Fetch job status (mirrors /jobs/<id>)

Payload shape (POST /api/v1/jobs):
{
  "sections": [
    {"category": str, "tasks": [
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
from . import schemas


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
MAX_CATEGORY_LEN = _env_int("TASKPRINTER_MAX_CATEGORY_LEN", _env_int("TASKPRINTER_MAX_SUBTITLE_LEN", 100))
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
    # Validate with Pydantic models (limits via context)
    try:
        req = schemas.JobSubmitRequest.model_validate(
            data,
            context={
                "limits": {
                    "MAX_SECTIONS": MAX_SECTIONS,
                    "MAX_TASKS_PER_SECTION": MAX_TASKS_PER_SECTION,
                    "MAX_TASK_LEN": MAX_TASK_LEN,
                    "MAX_CATEGORY_LEN": MAX_CATEGORY_LEN,
                }
            },
        )
    except Exception as e:
        from pydantic import ValidationError

        if isinstance(e, ValidationError):
            # Return a concise error message
            try:
                first_err = e.errors()[0]
                msg = first_err.get("msg") or str(e)
            except Exception:
                msg = str(e)
            return _json_error(msg, 400)
        return _json_error("invalid JSON payload", 400)

    # Clamp/prepare options for the worker
    opts: Optional[Dict[str, Any]] = None
    if req.options and req.options.tear_delay_seconds:
        opts = {"tear_delay_seconds": req.options.tear_delay_seconds}

    # Flatten to worker payload
    subtitle_tasks: List[Dict[str, Any]] = []
    total_chars = 0

    for s_idx, sec in enumerate(req.sections, start=1):
        subtitle = sec.category
        total_chars += len(subtitle)
        for t_idx, t in enumerate(sec.tasks, start=1):
            text = (t.text or "").strip()
            if not text:
                continue  # mirror UI behavior
            total_chars += len(text)

            flair = None
            if t.flair_type == "icon" and t.flair_value:
                flair = {"type": "icon", "value": t.flair_value}
            elif t.flair_type == "emoji" and t.flair_value:
                ev = str(t.flair_value).strip()
                flair = {"type": "emoji", "value": ev}
            elif t.flair_type == "qr" and t.flair_value:
                q = str(t.flair_value)
                if len(q) > MAX_QR_LEN or _has_control_chars(q):
                    return _json_error(
                        f"QR data invalid in section {s_idx} task {t_idx}.",
                        400,
                    )
                flair = {"type": "qr", "value": q}
            elif t.flair_type == "image" and t.flair_value:
                path = str(t.flair_value)
                if not is_supported_image(path):
                    exts = ", ".join(IMAGE_EXTS)
                    return _json_error(f"Unsupported image type. Use one of: {exts}", 400)
                try:
                    import os as _os

                    if _os.path.isfile(path):
                        size = _os.path.getsize(path)
                        if size and size > MAX_UPLOAD_SIZE:
                            return _json_error("Image too large.", 400)
                except Exception:
                    pass
                flair = {"type": "image", "value": path}

            meta = None
            if t.metadata:
                assigned = (t.metadata.assigned or "").strip()
                due = (t.metadata.due or "").strip()
                priority = (t.metadata.priority or "").strip()
                assignee = (t.metadata.assignee or "").strip()
                if any([assigned, due, priority, assignee]):
                    meta = {
                        "assigned": assigned,
                        "due": due,
                        "priority": priority,
                        "assignee": assignee,
                    }

            subtitle_tasks.append({"category": subtitle, "task": text, "flair": flair, "meta": meta})

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
    resp_model = schemas.JobAcceptedResponse(id=job_id, status="queued", links=schemas.Links(self=api_href, job=ui_href))
    resp = jsonify(resp_model.model_dump())
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
