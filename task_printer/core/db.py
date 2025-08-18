from __future__ import annotations

"""
SQLite persistence helper for Task Printer templates.

Features:
- DB path resolution with env/XDG defaults
- Per-request connection lifecycle (cached on Flask `g`)
- PRAGMAs for reliability: foreign_keys=ON, WAL, synchronous=NORMAL
- Schema bootstrap and simple migrations (schema_version = 1)
- CRUD helpers for templates, sections, and tasks
- Validation aligned with existing server limits and control char checks
"""

import logging
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

try:
    # Flask is available in this project; we integrate with app context when present.
    from flask import g, has_app_context, current_app
except Exception:  # pragma: no cover - fallback if Flask import ever fails
    g = None  # type: ignore
    has_app_context = lambda: False  # type: ignore
    current_app = None  # type: ignore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Shared test connection for in-memory DB when running under Flask test app
_DB_TEST_CONN: Optional[sqlite3.Connection] = None

# ----- Limits and validation -------------------------------------------------


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


def _has_control_chars(s: str) -> bool:
    return any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in s)


ALLOWED_FLAIR_TYPES = {"none", "icon", "image", "qr", "barcode", "emoji"}


class Flair(TypedDict, total=False):
    flair_type: str
    flair_value: Optional[str]
    flair_size: Optional[int]


class TaskInput(TypedDict, total=False):
    text: str
    flair_type: str
    flair_value: Optional[str]
    flair_size: Optional[int]


class SectionInput(TypedDict, total=False):
    subtitle: str
    tasks: List[TaskInput]


@dataclass
class Limits:
    max_sections: int = MAX_SECTIONS
    max_tasks_per_section: int = MAX_TASKS_PER_SECTION
    max_task_len: int = MAX_TASK_LEN
    max_subtitle_len: int = MAX_SUBTITLE_LEN
    max_total_chars: int = MAX_TOTAL_CHARS
    max_qr_len: int = MAX_QR_LEN


def _validate_structure(name: str, notes: Optional[str], sections: Iterable[SectionInput], limits: Limits) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("Template name is required.")
    if _has_control_chars(name):
        raise ValueError("Template name cannot contain control characters.")
    if notes is not None and _has_control_chars(str(notes)):
        raise ValueError("Template notes cannot contain control characters.")

    # Normalize to list for counting/iteration without consuming an iterator multiple times
    sec_list: List[SectionInput] = list(sections or [])
    if len(sec_list) == 0:
        raise ValueError("Template must have at least one section.")
    if len(sec_list) > limits.max_sections:
        raise ValueError(f"Too many sections (max {limits.max_sections}).")

    total_chars = 0
    for si, sec in enumerate(sec_list, start=1):
        subtitle = (sec.get("subtitle") or "").strip()
        if not subtitle:
            raise ValueError(f"Section {si} subtitle is required.")
        if len(subtitle) > limits.max_subtitle_len:
            raise ValueError(f"Subtitle in section {si} is too long (max {limits.max_subtitle_len}).")
        if _has_control_chars(subtitle):
            raise ValueError("Subtitles cannot contain control characters.")
        total_chars += len(subtitle)

        tasks = list(sec.get("tasks") or [])
        if len(tasks) == 0:
            raise ValueError(f"Section {si} must contain at least one task.")
        if len(tasks) > limits.max_tasks_per_section:
            raise ValueError(f"Too many tasks in section {si} (max {limits.max_tasks_per_section}).")

        for ti, task in enumerate(tasks, start=1):
            text = (task.get("text") or "").strip()
            if not text:
                raise ValueError(f"Task {ti} in section {si} is required.")
            if len(text) > limits.max_task_len:
                raise ValueError(f"Task {ti} in section {si} is too long (max {limits.max_task_len}).")
            if _has_control_chars(text):
                raise ValueError("Tasks cannot contain control characters.")
            total_chars += len(text)

            ftype = (task.get("flair_type") or "none").strip().lower()
            if ftype not in ALLOWED_FLAIR_TYPES:
                raise ValueError(f"Invalid flair_type in section {si} task {ti}: {ftype!r}")
            fval = task.get("flair_value")
            if ftype == "qr" and fval:
                if len(str(fval)) > limits.max_qr_len:
                    raise ValueError(
                        f"QR data too long in section {si} task {ti} (max {limits.max_qr_len}).",
                    )
                if _has_control_chars(str(fval)):
                    raise ValueError("QR data cannot contain control characters.")

    if total_chars > limits.max_total_chars:
        raise ValueError(f"Input too large (max total characters {limits.max_total_chars}).")


# ----- Path resolution -------------------------------------------------------


def get_db_path() -> str:
    """
    Resolve the database path using:
    1) TASKPRINTER_DB_PATH (env)
    2) $XDG_DATA_HOME/taskprinter/data.db
    3) ~/.local/share/taskprinter/data.db
    """
    if "TASKPRINTER_DB_PATH" in os.environ:
        return os.environ["TASKPRINTER_DB_PATH"]
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return str(Path(xdg) / "taskprinter" / "data.db")
    return str(Path.home() / ".local" / "share" / "taskprinter" / "data.db")


def _ensure_parent_dir(p: str) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)


# ----- Connection management -------------------------------------------------


def _apply_pragmas(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys = ON")
    # journal_mode change must be queried via cursor.fetchone(); but executing is sufficient to switch.
    try:
        db.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
    db.execute("PRAGMA synchronous = NORMAL")


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    db_path = path or get_db_path()
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def get_db(path: Optional[str] = None) -> sqlite3.Connection:
    """
    Return a sqlite3 connection; per-request if Flask app context is active, otherwise a module-level singleton.
    """
    if has_app_context():
        # In testing, prefer a shared in-memory DB across requests unless an explicit path is provided
        use_path = path
        try:
            is_testing = bool(current_app and current_app.config.get("TESTING"))
        except Exception:
            is_testing = False
        if is_testing and not use_path and "TASKPRINTER_DB_PATH" not in os.environ:
            global _DB_TEST_CONN
            if _DB_TEST_CONN is None:
                _DB_TEST_CONN = _connect(":memory:")
                _ensure_schema(_DB_TEST_CONN)
            return _DB_TEST_CONN

        if not hasattr(g, "db"):
            g.db = _connect(use_path)
            _ensure_schema(g.db)
        return g.db  # type: ignore[attr-defined]

    # Fallback: module-level singleton for non-Flask contexts (e.g., CLI/tests)
    global _DB_SINGLETON
    try:
        _DB_SINGLETON  # type: ignore[name-defined]
    except Exception:
        _DB_SINGLETON = _connect(path)  # type: ignore[attr-defined]
        _ensure_schema(_DB_SINGLETON)  # type: ignore[attr-defined]
    return _DB_SINGLETON  # type: ignore[attr-defined]


def close_db(e: Optional[BaseException] = None) -> None:
    """
    Close the active DB connection, if any.
    """
    if has_app_context() and hasattr(g, "db"):
        try:
            g.db.close()  # type: ignore[attr-defined]
        finally:
            try:
                del g.db  # type: ignore[attr-defined]
            except Exception:
                pass
        return

    # Close module-level singleton
    global _DB_SINGLETON
    try:
        if _DB_SINGLETON:  # type: ignore[name-defined]
            _DB_SINGLETON.close()  # type: ignore[attr-defined]
    except Exception:
        pass
    finally:
        try:
            _DB_SINGLETON = None  # type: ignore[attr-defined]
        except Exception:
            pass


def init_app(app) -> None:
    """
    Optionally register teardown hook on a Flask app.
    """
    app.teardown_request(close_db)


# ----- Schema and migrations -------------------------------------------------


def _ensure_schema(db: sqlite3.Connection) -> None:
    """
    Create tables if not present and ensure schema_version is initialized.
    """
    with db:  # implicit transaction
        # schema_version
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
              version INTEGER NOT NULL
            )
            """,
        )

        # templates (top-level)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
              id            INTEGER PRIMARY KEY AUTOINCREMENT,
              name          TEXT NOT NULL UNIQUE,
              notes         TEXT,
              created_at    TEXT NOT NULL,
              updated_at    TEXT NOT NULL,
              last_used_at  TEXT
            )
            """,
        )

        # sections
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS sections (
              id           INTEGER PRIMARY KEY AUTOINCREMENT,
              template_id  INTEGER NOT NULL,
              subtitle     TEXT NOT NULL,
              position     INTEGER NOT NULL,
              FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
            )
            """,
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_sections_template ON sections(template_id)")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sections_order ON sections(template_id, position)",
        )

        # tasks
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              section_id  INTEGER NOT NULL,
              text        TEXT NOT NULL,
              position    INTEGER NOT NULL,
              flair_type  TEXT NOT NULL DEFAULT 'none',
              flair_value TEXT,
              flair_size  INTEGER,
              assigned    TEXT,
              due         TEXT,
              priority    TEXT,
              assignee    TEXT,
              FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE
            )
            """,
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_section ON tasks(section_id)")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_order ON tasks(section_id, position)",
        )

        # Initialize schema_version if empty
        cur = db.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            db.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            ver = int(row["version"])
            if ver < SCHEMA_VERSION:
                _migrate(db, ver, SCHEMA_VERSION)


def _migrate(db: sqlite3.Connection, current: int, target: int) -> None:
    """
    Incremental migrations from `current` to `target`. Currently schema_version=1.
    """
    logger.info("Migrating DB schema from v%s to v%s", current, target)
    ver = int(current)
    with db:
        while ver < target:
            if ver == 1:
                # Add metadata columns to tasks
                try:
                    db.execute("ALTER TABLE tasks ADD COLUMN assigned TEXT")
                except Exception:
                    pass
                try:
                    db.execute("ALTER TABLE tasks ADD COLUMN due TEXT")
                except Exception:
                    pass
                try:
                    db.execute("ALTER TABLE tasks ADD COLUMN priority TEXT")
                except Exception:
                    pass
                try:
                    db.execute("ALTER TABLE tasks ADD COLUMN assignee TEXT")
                except Exception:
                    pass
                ver = 2
                db.execute("INSERT INTO schema_version (version) VALUES (?)", (ver,))
                continue
            # No other migrations
            ver = target
            db.execute("INSERT INTO schema_version (version) VALUES (?)", (ver,))


# ----- Utilities -------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----- CRUD operations -------------------------------------------------------


def create_template(name: str, notes: Optional[str], sections: Iterable[SectionInput]) -> int:
    """
    Create a template with the provided nested structure.
    Returns the new template id.
    """
    _validate_structure(name, notes, sections, Limits())
    db = get_db()
    with db:
        now = _iso_now()
        cur = db.execute(
            "INSERT INTO templates (name, notes, created_at, updated_at) VALUES (?,?,?,?)",
            (name.strip(), (notes or "").strip() or None, now, now),
        )
        tid = int(cur.lastrowid)
        for i, sec in enumerate(sections):
            subtitle = (sec.get("subtitle") or "").strip()
            cur = db.execute(
                "INSERT INTO sections (template_id, subtitle, position) VALUES (?,?,?)",
                (tid, subtitle, i),
            )
            sid = int(cur.lastrowid)
            for j, t in enumerate(list(sec.get("tasks") or [])):
                text = (t.get("text") or "").strip()
                flair_type = (t.get("flair_type") or "none").strip().lower()
                flair_value = t.get("flair_value") if t.get("flair_value") not in ("", None) else None
                flair_size = t.get("flair_size")
                db.execute(
                    """
                    INSERT INTO tasks (section_id, text, position, flair_type, flair_value, flair_size, assigned, due, priority, assignee)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        sid,
                        text,
                        j,
                        flair_type,
                        flair_value,
                        flair_size,
                        (t.get("metadata", {}) or {}).get("assigned") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("due") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("priority") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("assignee") if isinstance(t.get("metadata"), dict) else None,
                    ),
                )
        return tid


def _rows_to_template_dict(trow: sqlite3.Row, sections_rows: List[sqlite3.Row]) -> Dict[str, Any]:
    # Group by section_id keeping order
    sections: Dict[int, Dict[str, Any]] = {}
    for r in sections_rows:
        sid = int(r["section_id"])
        if sid not in sections:
            sections[sid] = {
                "id": sid,
                "subtitle": r["subtitle"],
                "position": int(r["s_pos"] or 0),
                "tasks": [],
            }
        if r["task_id"] is not None:
            sections[sid]["tasks"].append(
                {
                    "id": int(r["task_id"]),
                    "text": r["text"],
                    "position": int(r["t_pos"] or 0),
                    "flair_type": r["flair_type"],
                    "flair_value": r["flair_value"],
                    "flair_size": r["flair_size"],
                    "metadata": {
                        "assigned": r["assigned"],
                        "due": r["due"],
                        "priority": r["priority"],
                        "assignee": r["assignee"],
                    },
                },
            )
    ordered_sections = sorted(sections.values(), key=lambda s: s["position"])
    return {
        "id": int(trow["id"]),
        "name": trow["name"],
        "notes": trow["notes"],
        "created_at": trow["created_at"],
        "updated_at": trow["updated_at"],
        "last_used_at": trow["last_used_at"],
        "sections": ordered_sections,
    }


def get_template(template_id: int) -> Optional[Dict[str, Any]]:
    """
    Return a nested template dict or None if not found.
    """
    db = get_db()
    cur = db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
    trow = cur.fetchone()
    if trow is None:
        return None

    cur = db.execute(
        """
        SELECT
            s.id AS section_id, s.subtitle, s.position AS s_pos,
            t.id AS task_id, t.text, t.position AS t_pos, t.flair_type, t.flair_value, t.flair_size
        FROM sections s
        LEFT JOIN tasks t ON t.section_id = s.id
        WHERE s.template_id = ?
        ORDER BY s.position ASC, t.position ASC
        """,
        (template_id,),
    )
    srows = cur.fetchall()
    return _rows_to_template_dict(trow, list(srows))


def list_templates() -> List[Dict[str, Any]]:
    """
    Return a list of templates and counts, ordered by updated_at desc.
    """
    db = get_db()
    cur = db.execute(
        """
        SELECT
            t.id, t.name, t.notes, t.created_at, t.updated_at, t.last_used_at,
            (SELECT COUNT(*) FROM sections s WHERE s.template_id = t.id) AS sections_count,
            (
              SELECT COUNT(*)
              FROM tasks tk
              JOIN sections s2 ON tk.section_id = s2.id
              WHERE s2.template_id = t.id
            ) AS tasks_count
        FROM templates t
        ORDER BY t.updated_at DESC
        """,
    )
    items: List[Dict[str, Any]] = []
    for r in cur.fetchall():
        items.append(
            {
                "id": int(r["id"]),
                "name": r["name"],
                "notes": r["notes"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "last_used_at": r["last_used_at"],
                "sections_count": int(r["sections_count"] or 0),
                "tasks_count": int(r["tasks_count"] or 0),
            },
        )
    return items


def update_template(template_id: int, name: str, notes: Optional[str], sections: Iterable[SectionInput]) -> bool:
    """
    Replace the template name/notes/structure atomically. Returns True if updated, False if not found.
    """
    _validate_structure(name, notes, sections, Limits())
    db = get_db()
    with db:
        # Ensure the template exists
        cur = db.execute("SELECT id FROM templates WHERE id = ?", (template_id,))
        if cur.fetchone() is None:
            return False

        now = _iso_now()
        db.execute(
            "UPDATE templates SET name = ?, notes = ?, updated_at = ? WHERE id = ?",
            (name.strip(), (notes or "").strip() or None, now, template_id),
        )
        # Delete old sections (tasks will cascade)
        db.execute("DELETE FROM sections WHERE template_id = ?", (template_id,))
        # Insert new sections/tasks with positions
        for i, sec in enumerate(sections):
            subtitle = (sec.get("subtitle") or "").strip()
            cur = db.execute(
                "INSERT INTO sections (template_id, subtitle, position) VALUES (?,?,?)",
                (template_id, subtitle, i),
            )
            sid = int(cur.lastrowid)
            for j, t in enumerate(list(sec.get("tasks") or [])):
                text = (t.get("text") or "").strip()
                flair_type = (t.get("flair_type") or "none").strip().lower()
                flair_value = t.get("flair_value") if t.get("flair_value") not in ("", None) else None
                flair_size = t.get("flair_size")
                db.execute(
                    """
                    INSERT INTO tasks (section_id, text, position, flair_type, flair_value, flair_size, assigned, due, priority, assignee)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        sid,
                        text,
                        j,
                        flair_type,
                        flair_value,
                        flair_size,
                        (t.get("metadata", {}) or {}).get("assigned") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("due") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("priority") if isinstance(t.get("metadata"), dict) else None,
                        (t.get("metadata", {}) or {}).get("assignee") if isinstance(t.get("metadata"), dict) else None,
                    ),
                )
        return True


def delete_template(template_id: int) -> bool:
    """
    Delete a template and its children. Returns True if deleted, False if not found.
    """
    db = get_db()
    with db:
        cur = db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


def duplicate_template(template_id: int, new_name: Optional[str] = None) -> Optional[int]:
    """
    Duplicate a template. If new_name is None or collides, auto-suffix " Copy", " Copy 2", etc.
    Returns the new template id, or None if original not found.
    """
    src = get_template(template_id)
    if not src:
        return None

    base_name = new_name.strip() if new_name else f"{src['name']} Copy"
    candidate = base_name

    db = get_db()
    with db:
        # Find a non-colliding name
        idx = 2
        while True:
            cur = db.execute("SELECT 1 FROM templates WHERE name = ?", (candidate,))
            if cur.fetchone() is None:
                break
            candidate = f"{base_name} {idx}"
            idx += 1

        # Insert duplicate
        now = _iso_now()
        cur = db.execute(
            "INSERT INTO templates (name, notes, created_at, updated_at) VALUES (?,?,?,?)",
            (candidate, src.get("notes"), now, now),
        )
        new_tid = int(cur.lastrowid)

        # Copy sections/tasks preserving positions
        for sec in src.get("sections", []):
            cur = db.execute(
                "INSERT INTO sections (template_id, subtitle, position) VALUES (?,?,?)",
                (
                    new_tid,
                    sec.get("subtitle"),
                    (int(sec.get("position")) if isinstance(sec.get("position"), int) else 0),
                ),
            )
            new_sid = int(cur.lastrowid)
            for t in sec.get("tasks", []):
                md = t.get("metadata") if isinstance(t, dict) else None
                db.execute(
                    """
                    INSERT INTO tasks (section_id, text, position, flair_type, flair_value, flair_size, assigned, due, priority, assignee)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        new_sid,
                        t.get("text"),
                        (int(t.get("position")) if isinstance(t.get("position"), int) else 0),
                        t.get("flair_type"),
                        t.get("flair_value"),
                        t.get("flair_size"),
                        (md or {}).get("assigned") if isinstance(md, dict) else None,
                        (md or {}).get("due") if isinstance(md, dict) else None,
                        (md or {}).get("priority") if isinstance(md, dict) else None,
                        (md or {}).get("assignee") if isinstance(md, dict) else None,
                    ),
                )
        return new_tid


def touch_template_last_used(template_id: int) -> None:
    """
    Update last_used_at to now (UTC). Useful when printing directly from a template.
    """
    db = get_db()
    with db:
        db.execute("UPDATE templates SET last_used_at = ? WHERE id = ?", (_iso_now(), template_id))


__all__ = [
    "Limits",
    "close_db",
    "create_template",
    "delete_template",
    "duplicate_template",
    "get_db",
    "get_db_path",
    "get_template",
    "init_app",
    "list_templates",
    "touch_template_last_used",
    "update_template",
]
