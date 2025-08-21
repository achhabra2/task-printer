from __future__ import annotations

"""
Templates JSON API (v1) with Pydantic validation.

Endpoints:
- GET    /api/v1/templates              : List templates
- POST   /api/v1/templates              : Create template
- GET    /api/v1/templates/<id>         : Fetch template
- PUT    /api/v1/templates/<id>         : Update template
- DELETE /api/v1/templates/<id>         : Delete template
"""

import os
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from task_printer import csrf
from task_printer.core import db as dbh
from . import schemas
from task_printer.printing import worker
from task_printer.core.config import load_config, get_config_path


api_templates_bp = Blueprint("api_templates", __name__, url_prefix="/api/v1")


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


def _json_error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


@api_templates_bp.get("/templates")
def list_templates_api():
    items = dbh.list_templates()
    out = [schemas.TemplateListItem.model_validate(i).model_dump() for i in items]
    return jsonify(out)


@csrf.exempt
@api_templates_bp.post("/templates")
def create_template_api():
    if not request.is_json:
        return _json_error("Expected application/json body", 415)
    data = request.get_json(silent=True) or {}
    try:
        req = schemas.TemplateCreateRequest.model_validate(
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
            try:
                msg = (e.errors() or [{}])[0].get("msg") or str(e)
            except Exception:
                msg = str(e)
            return _json_error(msg, 400)
        return _json_error("invalid JSON payload", 400)

    # Cross-field total characters and QR length checks
    total_chars = 0
    for sec in req.sections:
        total_chars += len(sec.category)
        for t in sec.tasks:
            total_chars += len(t.text)
            if t.flair_type == "qr" and t.flair_value:
                q = str(t.flair_value)
                if len(q) > MAX_QR_LEN:
                    return _json_error(f"QR data too long (max {MAX_QR_LEN}).", 400)
    if total_chars > MAX_TOTAL_CHARS:
        return _json_error(f"Input too large (max total characters {MAX_TOTAL_CHARS}).", 400)

    # Convert to DB-friendly shape
    sections: List[Dict[str, Any]] = []
    for sec in req.sections:
        s = {"category": sec.category, "tasks": []}  # type: ignore[var-annotated]
        for t in sec.tasks:
            item: Dict[str, Any] = {
                "text": t.text,
                "flair_type": t.flair_type,
                "flair_value": t.flair_value,
            }
            if t.flair_size is not None:
                item["flair_size"] = t.flair_size
            if t.metadata and (t.metadata.priority or t.metadata.assignee):
                item["metadata"] = {
                    **({"priority": t.metadata.priority} if t.metadata.priority else {}),
                    **({"assignee": t.metadata.assignee} if t.metadata.assignee else {}),
                }
            s["tasks"].append(item)
        sections.append(s)

    try:
        tid = dbh.create_template(req.name, req.notes, sections)
        return jsonify({"id": tid, "name": req.name}), 201
    except Exception as e:
        return _json_error(str(e), 400)


@api_templates_bp.get("/templates/<int:template_id>")
def get_template_api(template_id: int):
    t = dbh.get_template(template_id)
    if not t:
        return _json_error("not_found", 404)
    model = schemas.TemplateResponse.model_validate(t)
    return jsonify(model.model_dump())


@csrf.exempt
@api_templates_bp.put("/templates/<int:template_id>")
def update_template_api(template_id: int):
    if not request.is_json:
        return _json_error("Expected application/json body", 415)
    data = request.get_json(silent=True) or {}
    try:
        req = schemas.TemplateUpdateRequest.model_validate(
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
            try:
                msg = (e.errors() or [{}])[0].get("msg") or str(e)
            except Exception:
                msg = str(e)
            return _json_error(msg, 400)
        return _json_error("invalid JSON payload", 400)

    # Cross-field checks
    total_chars = 0
    for sec in req.sections:
        total_chars += len(sec.category)
        for t in sec.tasks:
            total_chars += len(t.text)
            if t.flair_type == "qr" and t.flair_value:
                q = str(t.flair_value)
                if len(q) > MAX_QR_LEN:
                    return _json_error(f"QR data too long (max {MAX_QR_LEN}).", 400)
    if total_chars > MAX_TOTAL_CHARS:
        return _json_error(f"Input too large (max total characters {MAX_TOTAL_CHARS}).", 400)

    # Convert and call DB update
    sections: List[Dict[str, Any]] = []
    for sec in req.sections:
        s = {"category": sec.category, "tasks": []}  # type: ignore[var-annotated]
        for t in sec.tasks:
            item: Dict[str, Any] = {
                "text": t.text,
                "flair_type": t.flair_type,
                "flair_value": t.flair_value,
            }
            if t.flair_size is not None:
                item["flair_size"] = t.flair_size
            if t.metadata and (t.metadata.priority or t.metadata.assignee):
                item["metadata"] = {
                    **({"priority": t.metadata.priority} if t.metadata.priority else {}),
                    **({"assignee": t.metadata.assignee} if t.metadata.assignee else {}),
                }
            s["tasks"].append(item)
        sections.append(s)

    ok = dbh.update_template(template_id, req.name, req.notes, sections)
    if not ok:
        return _json_error("not_found", 404)
    return jsonify({"ok": True})


@csrf.exempt
@api_templates_bp.delete("/templates/<int:template_id>")
def delete_template_api(template_id: int):
    ok = dbh.delete_template(template_id)
    if not ok:
        return _json_error("not_found", 404)
    return jsonify({"ok": True})


def _template_to_print_payload(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for sec in t.get("sections", []):
        subtitle = (sec.get("category") or sec.get("subtitle") or "") if isinstance(sec, dict) else ""
        for task in sec.get("tasks", []):
            text = (task.get("text") or "") if isinstance(task, dict) else ""
            if not text.strip():
                continue
            flair = None
            ftype = (task.get("flair_type") or "none").strip().lower()
            fval = task.get("flair_value")
            fsize = task.get("flair_size")
            if ftype and ftype != "none":
                flair = {"type": ftype, "value": fval}
                if fsize is not None:
                    flair["size"] = fsize
            item = {"category": subtitle, "task": text, "flair": flair}
            if isinstance(task, dict):
                md = task.get("metadata")
                if isinstance(md, dict):
                    priority = (md.get("priority") or "").strip()
                    assignee = (md.get("assignee") or "").strip()
                    if priority or assignee:
                        item["meta"] = {k: v for k, v in {"priority": priority, "assignee": assignee}.items() if v}
            payload.append(item)
    return payload


@csrf.exempt
@api_templates_bp.post("/templates/<int:template_id>/print")
def print_template_api(template_id: int):
    t = dbh.get_template(template_id)
    if not t:
        return _json_error("not_found", 404)

    payload = _template_to_print_payload(t)
    if not payload:
        return _json_error("empty_template", 400)

    # Optional options override
    options = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        try:
            pr = schemas.TemplatePrintRequest.model_validate(data)
            if pr.options and pr.options.tear_delay_seconds:
                options = {"tear_delay_seconds": pr.options.tear_delay_seconds}
        except Exception:
            # ignore invalid body and fall back to defaults
            options = None

    # Fallback to global default if no override provided
    if not options:
        try:
            cfg = load_config(get_config_path())
            raw = (cfg or {}).get("default_tear_delay_seconds", 0)
            delay = float(raw or 0)
            if delay < 0:
                delay = 0.0
            if delay > 60:
                delay = 60.0
            if delay > 0:
                options = {"tear_delay_seconds": delay}
        except Exception:
            options = None

    try:
        worker.ensure_worker()
        try:
            job_id = worker.enqueue_tasks(payload, options=options)
        except TypeError:
            job_id = worker.enqueue_tasks(payload)
        dbh.touch_template_last_used(template_id)
        resp = schemas.TemplatePrintResponse(job_id=str(job_id))
        return jsonify(resp.model_dump())
    except Exception as e:
        return _json_error(str(e), 500)
