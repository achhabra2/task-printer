from __future__ import annotations

"""
Templates blueprint — persistence CRUD and print endpoints.

Routes:
- GET    /templates                      → List templates (JSON)
- POST   /templates                      → Create template (JSON or form)
- GET    /templates/<int:template_id>    → Fetch template structure (JSON)
- POST   /templates/<int:template_id>/update   → Replace structure (JSON or form)
- POST   /templates/<int:template_id>/delete   → Delete
- POST   /templates/<int:template_id>/duplicate→ Duplicate (optional new_name)
- POST   /templates/<int:template_id>/print    → Queue print job from stored data

Notes:
- CSRF is enabled globally via flask-wtf. Include csrf_token in forms or X-CSRFToken header for JSON.
- Accepts JSON payloads for API clients; form parsing mirrors the dynamic fields used by index UI.
"""

import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from task_printer.core import db as dbh
from task_printer.core.assets import IMAGE_EXTS, is_supported_image
from task_printer.core.config import MEDIA_PATH, load_config
from task_printer.printing import worker

templates_bp = Blueprint("templates", __name__)


# Wire DB teardown when this blueprint is registered
@templates_bp.record_once
def _on_register(state):
    try:
        dbh.init_app(state.app)
    except Exception:
        # Non-fatal; the DB helper will still function, but connections won't be auto-closed
        pass


# Limits aligned with the rest of the app (env-driven)
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


def _wants_json() -> bool:
    # Prefer HTML by default; only return JSON on explicit request
    fmt = (request.args.get("format") or "").lower()
    if fmt == "json":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    # Only choose JSON if the client explicitly prefers it and not HTML
    return ("application/json" in accept) and ("text/html" not in accept)


def _parse_sections_from_form() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Parse dynamic form fields into a nested sections structure suitable for DB storage.

    Returns:
        (sections, error)
        sections: list of {subtitle, tasks:[{text, flair_type, flair_value, flair_size?}]}
        error: error string if a validation error is encountered; None otherwise
    """
    form = request.form
    sections: List[Dict[str, Any]] = []

    # Accumulate total chars for soft limit check (final authoritative check occurs in DB layer)
    total_chars = 0

    section_idx = 1
    while True:
        subtitle_key = f"subtitle_{section_idx}"
        subtitle = (form.get(subtitle_key, "") or "").strip()
        if not subtitle:
            # Stop when a missing subtitle is encountered (after first)
            if section_idx == 1:
                break
            break

        if len(subtitle) > MAX_SUBTITLE_LEN:
            return [], f"Subtitle in section {section_idx} is too long (max {MAX_SUBTITLE_LEN})."
        if _has_control_chars(subtitle):
            return [], "Subtitles cannot contain control characters."

        sec_dict: Dict[str, Any] = {"subtitle": subtitle, "tasks": []}
        total_chars += len(subtitle)

        task_num = 1
        while True:
            task_key = f"task_{section_idx}_{task_num}"
            task = (form.get(task_key, "") or "").strip()
            if not task:
                break

            if len(task) > MAX_TASK_LEN:
                return [], f"Task {task_num} in section {section_idx} is too long (max {MAX_TASK_LEN})."
            if _has_control_chars(task):
                return [], "Tasks cannot contain control characters."
            total_chars += len(task)

            # Flair parsing
            flair_type = (form.get(f"flair_type_{section_idx}_{task_num}", "none") or "none").strip().lower()
            flair_value: Optional[str] = None
            flair_size: Optional[int] = None

            if flair_type == "icon":
                icon_key = (form.get(f"flair_icon_{section_idx}_{task_num}", "") or "").strip()
                flair_value = icon_key or None
            elif flair_type == "qr":
                qr_val = (form.get(f"flair_qr_{section_idx}_{task_num}", "") or "").strip()
                if qr_val:
                    if len(qr_val) > MAX_QR_LEN:
                        return [], f"QR data too long in section {section_idx} task {task_num} (max {MAX_QR_LEN})."
                    if _has_control_chars(qr_val):
                        return [], "QR data cannot contain control characters."
                    flair_value = qr_val
            elif flair_type == "image":
                file_key = f"flair_image_{section_idx}_{task_num}"
                existing_key = f"flair_image_existing_{section_idx}_{task_num}"
                # Prefer a newly uploaded file if present
                if file_key in request.files:
                    file = request.files.get(file_key)
                    if file and file.filename:
                        fname = secure_filename(file.filename)
                        if not is_supported_image(fname):
                            exts = ", ".join(IMAGE_EXTS)
                            return [], f"Unsupported image type. Use one of: {exts}"

                        # size check
                        try:
                            file.stream.seek(0, os.SEEK_END)
                            size = file.stream.tell()
                            file.stream.seek(0)
                        except Exception:
                            size = 0
                        if size and size > MAX_UPLOAD_SIZE:
                            return [], "Image too large."

                        ext = os.path.splitext(fname)[1].lower()
                        unique = uuid.uuid4().hex + ext
                        dest = os.path.join(MEDIA_PATH, unique)
                        file.save(dest)
                        flair_value = dest
                # Otherwise, preserve any existing stored path when provided by the form
                if flair_value is None:
                    ex_val = (form.get(existing_key, "") or "").strip()
                    if ex_val:
                        flair_value = ex_val

            # Optional metadata (details)
            assigned = (form.get(f"detail_assigned_{section_idx}_{task_num}", "") or "").strip()
            due = (form.get(f"detail_due_{section_idx}_{task_num}", "") or "").strip()
            priority = (form.get(f"detail_priority_{section_idx}_{task_num}", "") or "").strip()
            assignee = (form.get(f"detail_assignee_{section_idx}_{task_num}", "") or "").strip()
            metadata = None
            if any([assigned, due, priority, assignee]):
                metadata = {
                    "assigned": assigned,
                    "due": due,
                    "priority": priority,
                    "assignee": assignee,
                }

            sec_dict["tasks"].append(
                {
                    "text": task,
                    "flair_type": flair_type,
                    "flair_value": flair_value,
                    "flair_size": flair_size,
                    **({"metadata": metadata} if metadata else {}),
                },
            )

            task_num += 1
            if task_num > MAX_TASKS_PER_SECTION:
                return [], f"Too many tasks in section {section_idx} (max {MAX_TASKS_PER_SECTION})."

        if not sec_dict["tasks"]:
            return [], f"Section {section_idx} must contain at least one task."

        sections.append(sec_dict)

        section_idx += 1
        if section_idx > MAX_SECTIONS:
            return [], f"Too many sections (max {MAX_SECTIONS})."

    if total_chars > MAX_TOTAL_CHARS:
        return [], f"Input too large (max total characters {MAX_TOTAL_CHARS})."

    return sections, None


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


def _parse_template_payload() -> Tuple[str, Optional[str], List[Dict[str, Any]], Optional[str]]:
    """
    Parse a create/update payload from JSON or form.

    Returns:
        (name, notes, sections, error)
    """
    if request.is_json:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        notes = (data.get("notes") or None) or None
        sections = list(data.get("sections") or [])
        # Validate metadata dates if provided
        for si, sec in enumerate(sections, start=1):
            if not isinstance(sec, dict):
                continue
            for ti, t in enumerate(list(sec.get("tasks") or []), start=1):
                if not isinstance(t, dict):
                    continue
                md = t.get("metadata") or t.get("meta")
                if isinstance(md, dict):
                    assigned = (md.get("assigned") or md.get("assigned_date") or "").strip()
                    due = (md.get("due") or md.get("due_date") or "").strip()
                    if assigned and not _valid_date_str(assigned):
                        return "", None, [], f"Invalid assigned date in section {si} task {ti}."
                    if due and not _valid_date_str(due):
                        return "", None, [], f"Invalid due date in section {si} task {ti}."
        if not name:
            return "", None, [], "Template name is required."
        # Allow DB layer to enforce strict validation; do a basic sanity check here
        return name, notes, sections, None

    # Form fallback
    name = (request.form.get("name") or request.form.get("template_name") or "").strip()
    notes = (request.form.get("notes") or request.form.get("template_notes") or "").strip() or None
    if not name:
        return "", None, [], "Template name is required."
    sections, err = _parse_sections_from_form()
    return name, notes, sections, err


@templates_bp.get("/templates")
def list_templates_route():
    """
    Return templates list.
    """
    items = dbh.list_templates()
    if _wants_json():
        return jsonify(items)
    return render_template("templates.html", templates=items)


@templates_bp.post("/templates")
def create_template_route():
    """
    Create a new template. Accepts JSON body or form with dynamic fields.
    """
    name, notes, sections, err = _parse_template_payload()
    if err:
        if _wants_json() or request.is_json:
            return {"error": err}, 400
        flash(err, "error")
        return redirect(url_for("web.index"))

    try:
        tid = dbh.create_template(name, notes, sections)  # type: ignore[arg-type]
        current_app.logger.info("Created template id=%s name=%s", tid, name)
        if _wants_json() or request.is_json:
            return {"id": tid, "name": name}, 201
        flash(f"Template '{name}' saved.", "success")
        return redirect(url_for("templates.list_templates_route"))
    except Exception as e:
        current_app.logger.exception("Create template failed: %s", e)
        if _wants_json() or request.is_json:
            return {"error": str(e)}, 400
        flash(f"Error saving template: {e!s}", "error")
        return redirect(url_for("web.index"))


@templates_bp.get("/templates/<int:template_id>")
def get_template_route(template_id: int):
    t = dbh.get_template(template_id)
    if not t:
        return {"error": "not_found"}, 404
    return jsonify(t)


@templates_bp.post("/templates/<int:template_id>/update")
def update_template_route(template_id: int):
    name, notes, sections, err = _parse_template_payload()
    if err:
        if _wants_json() or request.is_json:
            return {"error": err}, 400
        flash(err, "error")
        return redirect(url_for("templates.list_templates_route"))

    try:
        ok = dbh.update_template(template_id, name, notes, sections)  # type: ignore[arg-type]
        if not ok:
            return {"error": "not_found"}, 404
        current_app.logger.info("Updated template id=%s name=%s", template_id, name)
        if _wants_json() or request.is_json:
            return {"ok": True}
        flash(f"Template '{name}' updated.", "success")
        return redirect(url_for("templates.list_templates_route"))
    except Exception as e:
        current_app.logger.exception("Update template failed: %s", e)
        if _wants_json() or request.is_json:
            return {"error": str(e)}, 400
        flash(f"Error updating template: {e!s}", "error")
        return redirect(url_for("templates.list_templates_route"))


@templates_bp.get("/templates/<int:template_id>/edit")
def edit_template_page(template_id: int):
    """Render an edit form for a template with dynamic sections/tasks.

    The form posts back to /templates/<id>/update using multipart form data
    so users can optionally upload new images. Existing image flair values are
    preserved via hidden inputs when no new file is provided.
    """
    t = dbh.get_template(template_id)
    if not t:
        return {"error": "not_found"}, 404
    # Discover icons for the icon picker macro/UI
    try:
        from task_printer.core.assets import get_available_icons

        icons = get_available_icons()
    except Exception:
        icons = []

    return render_template(
        "template_edit.html",
        template=t,
        icons=icons,
    )


@templates_bp.post("/templates/<int:template_id>/delete")
def delete_template_route(template_id: int):
    ok = dbh.delete_template(template_id)
    if not ok:
        return {"error": "not_found"}, 404
    if _wants_json() or request.is_json:
        return {"ok": True}
    flash("Template deleted.", "success")
    return redirect(url_for("templates.list_templates_route"))


@templates_bp.post("/templates/<int:template_id>/duplicate")
def duplicate_template_route(template_id: int):
    new_name = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        new_name = (data.get("new_name") or "").strip() or None
    else:
        new_name = (request.form.get("new_name") or "").strip() or None
    new_id = dbh.duplicate_template(template_id, new_name=new_name)
    if new_id is None:
        return {"error": "not_found"}, 404
    if _wants_json() or request.is_json:
        return {"id": new_id}
    flash("Template duplicated.", "success")
    return redirect(url_for("templates.list_templates_route"))


def _template_to_print_payload(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert a stored template into the printing payload expected by the worker:
    List of {"subtitle": str, "task": str, "flair": {"type","value","size"?}, "meta"?: {...}}
    """
    payload: List[Dict[str, Any]] = []
    for sec in t.get("sections", []):
        subtitle = (sec.get("subtitle") or "") if isinstance(sec, dict) else ""
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
            meta = None
            md = task.get("metadata") if isinstance(task, dict) else None
            if isinstance(md, dict):
                assigned = (md.get("assigned") or "").strip()
                due = (md.get("due") or "").strip()
                priority = (md.get("priority") or "").strip()
                assignee = (md.get("assignee") or "").strip()
                if any([assigned, due, priority, assignee]):
                    meta = {
                        "assigned": assigned,
                        "due": due,
                        "priority": priority,
                        "assignee": assignee,
                    }
            item = {"subtitle": subtitle, "task": text, "flair": flair}
            if meta:
                item["meta"] = meta
            payload.append(item)
    return payload


@templates_bp.post("/templates/<int:template_id>/print")
def print_template_route(template_id: int):
    t = dbh.get_template(template_id)
    if not t:
        return {"error": "not_found"}, 404
    payload = _template_to_print_payload(t)
    if not payload:
        return {"error": "empty_template"}, 400
    try:
        worker.ensure_worker()
        # Use global default tear-off delay if configured
        options = None
        try:
            from task_printer.core.config import get_config_path
            cfg = load_config(get_config_path()) or {}
            raw = cfg.get("default_tear_delay_seconds", 0)
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
            job_id = worker.enqueue_tasks(payload, options=options)
        except TypeError:
            # Backward compatibility with tests that patch enqueue_tasks(payload)
            job_id = worker.enqueue_tasks(payload)
        # Update last_used_at for quick ordering/filtering
        dbh.touch_template_last_used(template_id)
        current_app.logger.info(
            "Queued print from template id=%s name=%s job=%s items=%d",
            template_id,
            t.get("name"),
            job_id,
            len(payload),
        )
        if _wants_json() or request.is_json:
            return {"job_id": job_id}
        note = ""
        if options:
            note = f" Tear-off mode: {options.get('tear_delay_seconds')}s (no cut)."
        flash(f"Queued print from template. Job: {job_id}.{note}", "success")
        return redirect(url_for("web.index", job=job_id))
    except Exception as e:
        current_app.logger.exception("Error printing template: %s", e)
        if _wants_json() or request.is_json:
            return {"error": str(e)}, 500
        flash(f"Error printing template: {e!s}", "error")
        return redirect(url_for("templates.list_templates_route"))
