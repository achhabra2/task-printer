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

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    """
    Return the JSON representation of a job by id, or 404 if not found.
    """
    job: Optional[Dict[str, Any]] = get_job(job_id)
    if not job:
        current_app.logger.info("GET /jobs/%s not found", job_id)
        return {"error": "not_found"}, 404
    current_app.logger.info("GET /jobs/%s ok status=%s", job_id, job.get("status"))
    return job


@jobs_bp.get("/jobs")
def jobs_list():
    """
    Render the jobs list page, ordered by created_at descending.
    """
    jobs: List[Dict[str, Any]] = list_jobs()
    current_app.logger.info("GET /jobs list count=%d", len(jobs))
    return render_template("jobs.html", jobs=jobs)
