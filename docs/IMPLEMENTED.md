# Task Printer — Implemented Changes

Date: 2025-08-16 (Updated: 2025-08-18)

This document summarizes the recent improvements implemented in the Task Printer project, how they work, and how to use them.

## Overview

We focused on HTML correctness and UX, non-blocking print execution, safer configuration/secret handling, a more flexible service setup, and a leaner frontend architecture for dynamic UI without a full SPA.

## Recent Changes (August 18, 2025)

### Smart Font Sizing for Better Text Layout
- **Files**: `task_printer/printing/render.py`, `tests/test_font_optimization.py`
- **Change**: Enhanced the rendering engine to automatically adjust font sizes when text would wrap by just a few characters.
- **Key Functions**:
  - `_would_wrap_by_few_chars()`: Detects when text splitting is due to minor overflow
  - Enhanced `find_optimal_font_size()`: Tries smaller fonts for better single-line fitting
  - Integration in `render_large_text_image()` and `render_task_with_flair_image()`
- **Configuration**: 
  - `enable_dynamic_font_sizing` (default: True) - enables/disables the feature
  - `max_overflow_chars_for_dynamic_sizing` (default: 3) - threshold for "few chars"
  - `min_font_size`/`max_font_size` - bounds for font size adjustment
- **Effect**: Two-word phrases like "Mount Pegboard" now render on single lines with slightly smaller fonts instead of wrapping awkwardly to two lines.
- **Testing**: Added comprehensive test suite in `test_font_optimization.py` covering detection, optimization, and edge cases.

## Changes

1) Setup page nested form fix
- File: `templates/setup.html`
- Change: Removed an inner `<form id="usbdevs">` that was nested inside the main POST form. Nested forms are invalid HTML and can cause submission issues.

2) Index template now extends base
- File: `templates/index.html`
- Change: Converted to `{% extends "base.html" %}` for consistent layout and shared styles.
- Added: A visible “🧪 Test Print” button at the top.

3) Background worker for printing
- File: `app.py`
- Change: Added a lightweight background worker using `queue.Queue` and a daemon `Thread`.
- Effect: Print jobs no longer block the HTTP request; the UI returns immediately after queuing.
- API: Submissions on `/` now queue jobs instead of printing synchronously.

4) Test Print route
- File: `app.py`
- Route: `POST /test_print`
- Behavior: Enqueues a small test page using the current saved configuration. The index page includes a button that POSTs to this route.

5) Secret/config handling refactor
- File: `app.py`
- `app.secret_key` now reads from env var `TASKPRINTER_SECRET_KEY` with a safe dev default.
- `config.json` path resolution now supports:
  1. `TASKPRINTER_CONFIG_PATH` env var, else
  2. `$XDG_CONFIG_HOME/taskprinter/config.json`, else
  3. `~/.config/taskprinter/config.json`.
- The config directory is created automatically if it does not exist before saving.

6) Systemd service improvements
- File: `install_service.sh`
- Added `EnvironmentFile=/etc/default/taskprinter` to the unit, allowing secrets and config overrides without editing the unit.
- Creates `/etc/default/taskprinter` (if missing) with commented placeholders for `TASKPRINTER_SECRET_KEY` and `TASKPRINTER_CONFIG_PATH`.

Restart behavior:
- The “Save & Start” flow triggers a restart endpoint which now exits the process after responding. Under systemd, the service restarts automatically. When running manually (./start.sh), the app will stop and should be started again.

7) Jobs: IDs, status, and UI
- Files: `app.py`, `templates/index.html`, `templates/jobs.html`
- Added job IDs for all queued work with a JSON status endpoint `GET /jobs/<id>`.
- `index.html` shows a small status banner and polls when a `job` query param is present.
- New Jobs page (`/jobs`) lists recent jobs with auto-refresh and links to JSON.

7b) Jobs Persistence (90‑day history)
- Files: `task_printer/core/db.py`, `task_printer/printing/worker.py`, `task_printer/web/jobs.py`, `task_printer/__init__.py`
- Change: Persist jobs and their tasks to SQLite so history survives restarts.
- Schema: `jobs` (id, type, status, created_at, updated_at, total, origin, options_json, error), `job_items` (job_id, position, subtitle, task, flair fields, metadata).
- Lifecycle: jobs are recorded at enqueue; status transitions update the DB. Items mirror the payload at enqueue time.
- Retention: automatic cleanup of jobs older than 90 days (configurable via `TASKPRINTER_JOBS_RETENTION_DAYS`).
- UI: `/jobs` now lists from the DB and overlays live status from the in‑memory queue when available.
- API: `GET /jobs/<id>` returns live status if present, otherwise a minimal record from the DB.

8) Logging enhancements
- File: `app.py`
- Centralized logging with request IDs and journald fallback.
- Optional JSON logs via `TASKPRINTER_JSON_LOGS=true` for container/log-driver friendly output.

9) CSRF protection and input limits
- Files: `app.py`, `templates/index.html`, `templates/setup.html`, `templates/loading.html`
- Added Flask‑WTF CSRF across form posts (`/`, `/setup`, `/test_print`, `/setup_test_print`) and included token in the async `/restart` fetch via header.
- Implemented input limits: max sections/tasks per section, max lengths, total character cap, and rejection of control characters.

10) Health check endpoint
- File: `app.py`
- `GET /healthz` returns JSON including worker status (started/alive), queue size, config presence, and basic printer reachability.

11) Printer profile selection
- Files: `app.py`, `templates/setup.html`
- Added optional printer profile selection (e.g., `TM-P80`, `TM-T88III`, `TM-T20III`).
- Defaults to generic when not set. The selected profile is passed to the ESC/POS driver for USB/Network/Serial connections.

## Usage Guide

1) First run / setup
- Start app: `python3 app.py` (or via systemd; see below).
- Visit `/setup`, choose printer type and options, then Save & Start.

2) Test printing
- On the index page, click “🧪 Test Print” to queue a test page.

3) Printing tasks
- Enter one or more subtitle sections and tasks; submit the form.
- You will see a flash message that the job is queued; the background worker will print tasks.

## Environment Variables

- `TASKPRINTER_SECRET_KEY`: Flask secret key for sessions. Set a strong random string in production.
- `TASKPRINTER_CONFIG_PATH`: Optional absolute path to `config.json`.
- If unset, `config.json` defaults to XDG locations as described above.
- `TASKPRINTER_JSON_LOGS`: If set to `true/1/yes`, emits JSON logs instead of plain text.
- `TASKPRINTER_FONT_PATH`: Optional path to a TTF font to use when rendering text.
- `TASKPRINTER_JOBS_RETENTION_DAYS`: Days to retain job history in SQLite (default: 90). Set to `0` to disable cleanup.

## Systemd Service

Install/update the service:

```bash
sudo ./install_service.sh
```

Configure environment:

```bash
sudo nano /etc/default/taskprinter
# Set TASKPRINTER_SECRET_KEY and optionally TASKPRINTER_CONFIG_PATH
```

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart taskprinter.service
```

View logs:

```bash
journalctl -u taskprinter.service -f
```

Tip: When using JSON logs, prefer `journalctl -o json-pretty -u taskprinter.service -f`.

## Notes & Compatibility
- To view progress, click the “🧾 Jobs” button (or follow the job link in the flash message).

- Existing installs: If you previously relied on `config.json` in the repo root, the app will now look in XDG paths by default. You can set `TASKPRINTER_CONFIG_PATH` to keep using the old location if desired.
- Fonts: The app uses DejaVu Sans from the system. Ensure it is present on the target device.
12) Task flair (Phase 1)
- Files: `app.py`, `templates/index.html`
- Added optional per-task flair: `Icon` or `QR` (besides `None`).
- Icons are looked up under `static/icons/<key>.png` (e.g., `working.png`, `cleaning.png`, `family.png`, `fitness.png`, `study.png`, `errands.png`). If missing, the app prints a simple placeholder.
- QR payload length capped via `TASKPRINTER_MAX_QR_LEN` (default 512).

13) Templates persistence (Phase 3)
- Files: `task_printer/core/db.py`, `task_printer/web/templates.py`, `templates/templates.html`, `templates/index.html`, `task_printer/__init__.py`, `tests/test_templates_persistence.py`
- Summary: Adds SQLite-backed “Templates” feature to save/load/print grouped tasks (with flair), a templates UI, REST-ish endpoints, and tests.

Storage & DB
- Engine: SQLite (stdlib `sqlite3`) with PRAGMAs: `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`.
- Path: `TASKPRINTER_DB_PATH` or `$XDG_DATA_HOME/taskprinter/data.db` or `~/.local/share/taskprinter/data.db`.
- Schema: `templates`, `sections`, `tasks` with `position` ordering and `ON DELETE CASCADE`. Tracks timestamps: `created_at`, `updated_at`, `last_used_at`.
- Helper: `task_printer.core.db` exposes `get_db()`, `close_db()`, `init_app()`, CRUD helpers (`create_template`, `get_template`, `list_templates`, `update_template`, `delete_template`, `duplicate_template`, `touch_template_last_used`).
- Validation mirrors existing limits and rejects control characters.

Routes (blueprint `templates_bp`)
- `GET /templates` → HTML list (JSON only when explicitly requested via `?format=json` or `Accept: application/json` without `text/html`).
- `POST /templates` → Create from JSON or form (supports flair icon/QR/emoji; image uploads when posted as multipart).
- `GET /templates/<id>` → Full JSON structure for prefill.
- `GET /templates/<id>/edit` → HTML edit form.
- `POST /templates/<id>/update` → Replace entire structure.
- `POST /templates/<id>/delete` → Delete.
- `POST /templates/<id>/duplicate` → Duplicate (optional `new_name`; auto-suffix on conflicts).
- `POST /templates/<id>/print` → Queue print using stored data; updates `last_used_at`.

UI
- New page: `templates/templates.html` to list templates with actions: Load (prefill index), Edit, Print Now, Duplicate, Delete.
- New page: `templates/template_edit.html` to edit a saved template using the same dynamic UI as the index page.
- Index integrations (`templates/index.html`):
  - Added “📚 Templates” link and “💾 Save as Template” button.
  - Save posts JSON (icon/QR/emoji flair preserved; image flair intentionally skipped in JSON flow due to browser file input limitations).
  - Prefill logic reads a saved template from `localStorage` and rebuilds the dynamic form with flair applied.
- Content negotiation tweaked to prefer HTML by default on `/templates`.

Worker integration
- Printing uses existing queue via `worker.ensure_worker()` and `worker.enqueue_tasks(...)`.
- Stored flair types map to existing print paths (icon/image/QR).

Security & limits
- CSRF enforced for all POST routes (token read from cookie and sent via header or form).
- Server-side limits: section/task counts, text/QR length, total character cap; rejects control characters.

Tests
- `tests/test_templates_persistence.py`:
  - DB CRUD tests (create/list/get/update/duplicate/delete, ordering and counts).
  - Route tests for JSON flows and error cases.
  - Printing path mocked; CSRF token parsed from Set-Cookie.
- All tests pass alongside existing suite.

Environment
- New: `TASKPRINTER_DB_PATH` to override DB location.

14) Per‑print Tear‑Off Mode + Optional Global Default
- Files: `task_printer/printing/worker.py`, `task_printer/web/routes.py`, `templates/index.html`, `task_printer/web/templates.py`, `task_printer/web/setup.py`.
- Summary: Add a per‑print option to wait between task receipts and suppress cutter commands, and an optional global default.

Web/UI
- Index (`/`): Adds “Tear‑off delay (seconds)” input. When > 0, the worker sleeps between tasks and skips cutting; default behavior is unchanged when blank/0.
- Setup (`/setup`): Adds `Default tear‑off delay (seconds)` stored as `default_tear_delay_seconds` in `config.json`.
- Templates (`/templates/<id>/print`): Uses the global default if set. The Index form preloads this default but it can be overridden per print.

Worker
- `enqueue_tasks(payload, options=None)` accepts per‑job `options` (currently `tear_delay_seconds`).
- `print_tasks(..., options=...)` computes `tear_mode` and suppresses `cut()` while sleeping between items.
- `_print_subtitle_task_item(..., cut=True)` renders feed lines but only calls `cut()` when `cut=True`.

Logging
- Logs clearly state when tear‑off mode is enabled and sleep durations.

Tests
- Added unit tests for worker orchestration, index route parsing, setup persistence, and templates printing with default.

15) Frontend refactor: Jinja macros + static JS module + server JSON payload
- Files:
  - New: `templates/_form_macros.html` (macros: `icon_picker`, `flair_row`, `task_row`)
  - Edited: `templates/index.html` (uses macros, injects `window.__ICONS`, removes large inline JS)
  - New: `static/js/app.js` (dynamic form logic, payload_json creation, image preview, job polling, save-as-template, prefill)
  - Edited: `templates/base.html` (loads `static/js/app.js` as `type="module"`)
  - Edited: `task_printer/web/routes.py` (accepts `payload_json` with validation; legacy form parsing retained as fallback)
- Summary:
  - Removed large inline JS from `index.html`; centralized behavior in `static/js/app.js`.
  - Extracted repeated HTML into Jinja macros for maintainability and consistency.
  - Form submission now attaches a hidden `payload_json` with sections/tasks; image flair remains multipart via the file input.
  - Server prefers `payload_json` for parsing and falls back to legacy dynamic field names for compatibility.
- Validation:
  - Server validates sections/tasks against MAX_* limits and control characters.
  - For image flair, server resolves the upload via the provided field name (`flair_value`) or default `flair_image_{i}_{j}`.
  - For QR flair, validates length and characters.
- Prefill:
  - `app.js` supports prefill from: server-injected `window.__PREFILL_TEMPLATE`, localStorage, or fetch by `?prefill=<id>`.
- Backwards compatibility:
  - Legacy dynamic fields still work when `payload_json` is absent.
- Developer guidance:
  - Prefer editing macros in `_form_macros.html` for repeated markup changes.
  - Add dynamic behaviors in `static/js/app.js`; do not reintroduce large inline scripts.

16) HTML/Jinja correctness and linting plan
- Fixes:
  - Validated and corrected `_form_macros.html` to remove malformed Jinja conditions and stray/unbalanced tags.
- Tooling plan:
  - Adopt `djlint` for HTML/Jinja linting in CI (ignore long Tailwind class lines as needed).
  - Enable Jinja StrictUndefined to catch undefined variables early; audit templates using `|default` or `or ''` where appropriate.
- Follow-ups:
  - Add pre-commit hook and CI job to run `scripts/validate_templates.py` and djlint.
  - Document StrictUndefined expectations in AGENTS.md and update examples to include `|default`.
15) Emoji Flair + Emoji Rendering
- Files: `task_printer/printing/emoji.py`, `task_printer/printing/render.py`, `task_printer/printing/worker.py`, `templates/_form_macros.html`, `static/js/app.js`
- Added `emoji` as a flair type end-to-end; rasterizes emoji (monochrome preferred) and composes alongside text with a vertical separator.
- Setup UI now includes Fonts section; supports `emoji_font_path` and auto-detection on save.
- Health endpoint checks emoji rendering (`emoji_ok`); index shows a health badge (worker/printer/emoji).

16) Recent Emoji (UI)
- Files: `templates/_form_macros.html`, `static/js/app.js`
- Small “Recent…” dropdown appears next to emoji input; keeps 12 most recent emoji in localStorage for quick reuse.

17) Metadata Panel (Assigned/Due/Priority/Assignee)
- Files: `task_printer/printing/metadata.py`, `task_printer/printing/worker.py`, `templates/_form_macros.html`, `static/js/app.js`, `task_printer/web/routes.py`
- Prints a compact panel below the task with emojis: 📋 (assigned), 📅 (due), 👤 (assignee); priority as centered ⚡ icons (Normal=⚡, High=⚡⚡, Urgent=⚡⚡⚡).
- UI has a Details toggle per task; date inputs default to today and include quick buttons: Today, +1d, +1w, +1m.
- Server-side date validation accepts `YYYY-MM-DD`, `MM-DD`, or `MM/DD`.

18) Templates Persistence — Metadata
- Files: `task_printer/core/db.py`, `task_printer/web/templates.py`
- DB schema (v2): tasks table adds `assigned`, `due`, `priority`, `assignee`. Migration adds columns to existing DBs.
- Templates JSON includes `metadata` per task; printing from templates passes `meta` to the worker so metadata is rendered.

19) JSON API (v1) for Job Submission
- Files: `task_printer/web/api.py`, `task_printer/__init__.py`, `tests/test_api_jobs.py`, `README.md`, `AGENTS.md`
- Summary: Adds a versioned HTTP API to programmatically submit print jobs and fetch job status following common REST conventions.

Endpoints
- `POST /api/v1/jobs` — submit a print job asynchronously.
  - Request: `Content-Type: application/json`
    - Body shape:
      - `sections`: array of `{ subtitle: str, tasks: [ { text: str, flair_type: "none|icon|image|qr|emoji", flair_value?: str, metadata?: {assigned,due,priority,assignee} } ] }`
      - `options`: `{ tear_delay_seconds?: number }` (0–60; >0 enables tear‑off mode without cutting)
  - Response: `202 Accepted` with JSON `{ id, status: "queued", links: { self, job } }`
    - Headers: `Location: /api/v1/jobs/{id}`
  - Validation: matches web UI limits (max sections/tasks/lengths, total char cap, control characters rejected).
  - Notes: For `flair_type: "image"`, pass a server‑local image path (multipart upload is not supported by this endpoint).

- `GET /api/v1/jobs/<id>` — return job status JSON.
  - Returns live in‑memory status when available, else a minimal persisted record; `404` if not found.

Behavior
- The API is CSRF‑exempt and returns standard status codes: `202` (accepted), `400` (validation), `404` (not found), `415` (wrong content type), `500` (enqueue errors), `503` (service not configured).
- Jobs are enqueued through the existing worker (`ensure_worker`, `enqueue_tasks`).

Examples
```bash
curl -s -X POST http://localhost:5000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "sections": [
      {"subtitle": "Kitchen", "tasks": [{"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning"}]},
      {"subtitle": "Hall", "tasks": [{"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"}]}
    ],
    "options": {"tear_delay_seconds": 2.5}
  }'
```
