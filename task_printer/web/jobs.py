from __future__ import annotations

"""
Jobs endpoints for Task Printer.

This blueprint exposes:
- GET /jobs: Render the jobs list page
- GET /jobs/<job_id>: Return JSON status for a specific job (404 if not found)
"""

from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, render_template

from task_printer.printing.worker import get_job, list_jobs
from task_printer.core import db as dbh

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    """
    Return the JSON representation of a job by id, or 404 if not found.
    """
    # Prefer in-memory live status; fall back to DB if not present
    job: Optional[Dict[str, Any]] = get_job(job_id)
    if job:
        current_app.logger.info("GET /jobs/%s ok status=%s (live)", job_id, job.get("status"))
        return job
    db_job = dbh.get_job_db(job_id)
    if db_job:
        current_app.logger.info("GET /jobs/%s ok (db)", job_id)
        # return a minimal compatible payload
        return {
            "id": db_job.get("id"),
            "type": db_job.get("type"),
            "status": db_job.get("status"),
            "created_at": db_job.get("created_at"),
            "updated_at": db_job.get("updated_at"),
            "total": db_job.get("total"),
            "origin": db_job.get("origin"),
        }
    current_app.logger.info("GET /jobs/%s not found", job_id)
    return {"error": "not_found"}, 404


@jobs_bp.get("/jobs")
def jobs_list():
    """
    Render the jobs list page, ordered by created_at descending.
    """
    # Prefer persisted jobs; overlay in-memory status where available
    jobs: List[Dict[str, Any]] = dbh.list_jobs_db(limit=200)
    live = {j.get("id"): j for j in list_jobs()}
    for j in jobs:
        lid = j.get("id")
        if lid in live:
            j["status"] = live[lid].get("status", j.get("status"))
            j["updated_at"] = live[lid].get("updated_at", j.get("updated_at"))
    current_app.logger.info("GET /jobs list count=%d (db)", len(jobs))
    return render_template("jobs.html", jobs=jobs)


@jobs_bp.get("/jobs/<job_id>/view")
def job_view(job_id: str):
    """
    Render a detail view for a persisted job with its items.
    """
    job = dbh.get_job_db(job_id)
    if not job:
        # Try live as a minimal fallback
        live = get_job(job_id)
        if not live:
            return render_template("jobs_view.html", job=None, error="Job not found"), 404
        # Live job won't have items; present minimal info
        return render_template("jobs_view.html", job={
            "id": live.get("id"),
            "type": live.get("type"),
            "status": live.get("status"),
            "created_at": live.get("created_at"),
            "updated_at": live.get("updated_at"),
            "total": live.get("total"),
            "origin": live.get("origin"),
            "items": [],
        })
    # Normalize options
    try:
        import json as _json

        opts = job.get("options_json")
        job["options"] = _json.loads(opts) if isinstance(opts, str) and opts else {}
    except Exception:
        job["options"] = {}
    return render_template("jobs_view.html", job=job)
