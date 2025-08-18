# Phase 3 — Persistence Layer (Templates + Flair)

This document describes a detailed plan to persist reusable task groupings ("templates") with sections, tasks, and flair (icon/image/QR/emoji), using SQLite. It covers schema design, data access patterns, API routes, UI flows, printing integration, validation, security, and ops concerns.

## Goals
- Save/load reusable groupings so users don’t retype common lists.
- Persist structure: sections (aka subtitles) with multiple tasks, in order.
- Persist per-task flair (icon/image/QR) and relevant options.
- Enable quick actions: Print Now, Load to form, Duplicate, Rename, Delete.
- Keep the solution simple, portable, and robust for single-user LAN usage.

## Storage Engine & Location
- Engine: SQLite (stdlib `sqlite3`), no extra dependency.
- DB path precedence:
  1. `TASKPRINTER_DB_PATH` (env)
  2. `$XDG_DATA_HOME/taskprinter/data.db`
  3. `~/.local/share/taskprinter/data.db`
- Open with `PRAGMA foreign_keys = ON`, `journal_mode = WAL`, `synchronous = NORMAL`.
- Connection per request (via a lightweight helper); cached in `g` and closed in `teardown_request`.

## Schema

```
-- schema_version to track migrations
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

-- templates (the top-level grouping)
CREATE TABLE IF NOT EXISTS templates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  notes         TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  last_used_at  TEXT
);

-- sections (a.k.a. subtitles)
CREATE TABLE IF NOT EXISTS sections (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  template_id  INTEGER NOT NULL,
  subtitle     TEXT NOT NULL,
  position     INTEGER NOT NULL,
  FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sections_template ON sections(template_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sections_order ON sections(template_id, position);

-- tasks (with flair + metadata)
CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  section_id  INTEGER NOT NULL,
  text        TEXT NOT NULL,
  position    INTEGER NOT NULL,
  flair_type  TEXT NOT NULL DEFAULT 'none',   -- 'none' | 'icon' | 'image' | 'qr' | 'barcode' | 'emoji'
  flair_value TEXT,                           -- icon key, image path, qr payload, or JSON for barcode
  flair_size  INTEGER,                        -- optional pixel size hint
  assigned    TEXT,                           -- optional date (ISO YYYY-MM-DD), displayed as MM-DD when printing
  due         TEXT,                           -- optional date (ISO YYYY-MM-DD), displayed as MM-DD when printing
  priority    TEXT,                           -- Normal | High | Urgent (printed as ⚡ icons)
  assignee    TEXT,                           -- free-form name
  FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_section ON tasks(section_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_order ON tasks(section_id, position);
```

Notes:
- `position` controls ordering; unique constraints per parent guarantee stable order.
- `ON DELETE CASCADE` keeps child rows tidy when a template/section is removed.
- `name` is unique for convenience; we can allow duplicates later with a soft key (slug).
- All timestamps stored as ISO 8601 UTC strings.

## Migrations
- Initialize `schema_version` with `1` on bootstrap.
- v2: add metadata columns (`assigned`, `due`, `priority`, `assignee`) and permit `emoji` flair type; update code to read/write these fields.
- For future changes, run guarded `ALTER TABLE` or `CREATE INDEX IF NOT EXISTS` based on current version and bump.
- Provide a lightweight `migrate(db)` that applies steps incrementally.

## Data Access Layer (Python)
- Small helper module (e.g., `db.py`):
  - `get_db()`: open connection (row_factory to `sqlite3.Row`), set PRAGMAs.
  - `close_db(e)`: close in `teardown_request`.
  - CRUD helpers (within transactions):
    - `create_template(name, notes, sections)`
    - `get_template(id)` → `{id, name, notes, sections: [{id, subtitle, position, tasks: [...]}, ...]}`
    - `list_templates()` (with counts)
    - `update_template(id, name, notes, sections)` (replace strategy)
    - `delete_template(id)`
    - `duplicate_template(id, new_name)`
  - Replace vs patch: start with replace to keep logic simple and atomic.

### Transaction Strategy
- `create_template` and `update_template` run in a single transaction:
  1. Insert/update template row (timestamps updated accordingly).
  2. Delete old sections/tasks (for update), then re-insert with correct positions, or
  3. Insert sections first, then tasks, each with explicit `position` (0..N-1).

## API Routes
- `GET /templates` → HTML page (or JSON) listing templates: id, name, counts, updated_at.
- `POST /templates` (CSRF): Create template from current form structure.
  - Body (form or JSON): `name`, optional `notes`, and the current form’s sections/tasks flattened by the frontend.
- `GET /templates/<id>` → JSON structure for prefill:
  ```
  {
    "id": 5,
    "name": "Weekday Morning",
    "notes": "Daily morning routine",
    "sections": [
      {"subtitle": "Kitchen", "position": 0, "tasks": [
         {"text": "Wipe counter", "position": 0, "flair_type": "icon", "flair_value": "cleaning", "metadata": {"assigned": "2025-08-18", "due": "2025-08-18", "priority": "Normal", "assignee": "Aman"}},
         {"text": "Run dishwasher", "position": 1, "flair_type": "emoji", "flair_value": "✅", "metadata": {"due": "2025-08-19", "priority": "High"}}
      ]}
    ]
  }
  ```
- `POST /templates/<id>/update` (CSRF): Replace name/notes/structure.
- `POST /templates/<id>/delete` (CSRF): Delete template.
- `POST /templates/<id>/duplicate` (CSRF): Duplicate template (auto-suffix name if needed).
- `POST /templates/<id>/print` (CSRF): Queue a print job directly from stored data.

### Payload Size & Limits
- Reuse existing server-side limits (`MAX_SECTIONS`, `MAX_TASKS_PER_SECTION`, `MAX_TASK_LEN`, `MAX_TOTAL_CHARS`, `MAX_QR_LEN`).
- Reject control characters in text and QR payloads.

## UI Flows
- Index page:
  - Add “Save as Template” button: opens modal to enter `name` (and optional `notes`); submits current form to `/templates`.
  - Add “Load Template” dropdown/button: fetch `/templates/<id>` and rebuild the form (including flair controls).
  - Optional “Print Now” beside each listed template name (if a small “Templates” drawer is added).
- Templates page (`/templates`):
  - Table view: name, sections count, tasks count, updated_at.
  - Row actions: Load (prefill index), Print Now, Rename, Duplicate, Delete.

## Printing Integration
- Map stored structure → current print payload:
  - For each section: subtitle.
  - For each task: `{subtitle, task, flair, meta?}`
    - `flair`: `{type: 'icon'|'image'|'qr'|'barcode', value: string, size?: number}`
    - `meta`: `{assigned?: string, due?: string, priority?: string, assignee?: string}`
  - Enqueue as a standard `tasks` job so the worker path remains unchanged.
- Logging context: include `template_id` and `template_name` in job meta for traceability (shown in Jobs list and logs).

## Validation & Security
- CSRF on all POST routes (already enabled globally).
- Sanitize inputs: trim whitespace, collapse multiple spaces; enforce length limits.
- Flair:
  - `icon`: key must match available icon set; no path traversal.
  - `image`: stored media path only (Phase 2 engine); verify existence at print time.
  - `qr`: length bound (`MAX_QR_LEN`), reject control chars.
- Auth: none (LAN trust assumption). Document this clearly.

## Performance & Concurrency
- SQLite with WAL handles single-user writes well; reads are concurrent.
- Index pages: list queries return only metadata and counts (use `COUNT(*)` joins or precomputed counts).
- Printing worker reads a fully materialized structure to avoid DB locks during printing.

## Backups & Ops
- Backup: copy the DB file while the app is idle or use `.backup` via SQLite CLI.
- Restore: replace the DB file and restart the app.
- Paths:
  - DB: `TASKPRINTER_DB_PATH` or XDG data default.
  - Media (uploads): `TASKPRINTER_MEDIA_PATH` — ensure this is backed up if you depend on uploaded images.

## Testing Approach
- Unit tests for:
  - CRUD functions (create/list/get/update/delete/duplicate).
  - Ordering and position handling.
  - Validation failures (too many sections, long tasks, bad flair).
- Integration tests with Flask test client for routes and CSRF.
- Mock printing for `/templates/<id>/print` to assert job payload.

## Example Pseudocode (Python)

```
# db.py (sketch)
import os, sqlite3
from datetime import datetime, timezone
from flask import g

def get_db():
    if 'db' not in g:
        path = resolve_db_path()
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA journal_mode = WAL')
        g.db.execute('PRAGMA synchronous = NORMAL')
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def create_template(name, notes, sections):
    db = get_db()
    with db:
        now = iso_now()
        cur = db.execute('INSERT INTO templates (name, notes, created_at, updated_at) VALUES (?,?,?,?)',
                         (name, notes, now, now))
        tid = cur.lastrowid
        for i, sec in enumerate(sections):
            cur = db.execute('INSERT INTO sections (template_id, subtitle, position) VALUES (?,?,?)',
                             (tid, sec['subtitle'], i))
            sid = cur.lastrowid
            for j, t in enumerate(sec.get('tasks', [])):
                db.execute('INSERT INTO tasks (section_id, text, position, flair_type, flair_value, flair_size)\
                           VALUES (?,?,?,?,?,?)',
                           (sid, t['text'], j, t.get('flair_type','none'), t.get('flair_value'), t.get('flair_size')))
        return tid
```

## Rollout Plan
1. Add DB helper, schema bootstrap, and migrations.
2. Implement backend routes (list/create/get/update/delete/duplicate/print) with CSRF and validation.
3. Add Templates page and index integrations (Save as Template, Load, Print Now).
4. Wire print job creation from templates (with logging context).
5. Update docs (README, IMPLEMENTED) and add env var notes (`TASKPRINTER_DB_PATH`).

## Future Extensions
- Soft delete with `deleted_at` and an undo.
- Search/filter and tags/favorites.
- Export/import templates (JSON with embedded media references).
- Multi-user namespacing (if the app adds auth later).
- Additional flair: barcode (data + symbology + size), position options (above/below text).

---
This plan keeps persistence simple and reliable while integrating cleanly with the existing job queue and printing pipeline.
