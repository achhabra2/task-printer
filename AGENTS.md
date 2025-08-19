# Task Printer — Agent Guide (Refactor Edition)

This guide orients contributors and future agents to the refactored repository layout, updated application factory, and where responsibilities live after the package restructuring. Read this before making changes so you understand the new wiring, extension points, and safe ways to modify behavior.

High-level goals of the refactor
- Move from a single `app.py` monolith to a Python package `task_printer` with an application factory.
- Make bootstrapping, testing, and reuse easier by isolating concerns:
  - `task_printer.__init__` exposes `create_app(...)`
  - `task_printer.core` holds reusable helpers (config, assets, logging)
  - `task_printer.web` contains blueprints for HTTP endpoints
  - `task_printer.printing` contains rendering and the background worker
- Keep runtime behaviour identical for users while improving developer ergonomics.

If you're working on this project you should:
- Prefer editing package modules under `task_printer/` rather than top-level `app.py` unless you are changing the simple runner.
- Read `task_printer.__init__.py` to understand app creation and how blueprints/workers are registered.

Quick overview
- Purpose: A small Flask app to accept grouped “tasks” from users and print each task as an individual receipt on thermal printers (USB, network, serial).
- Rendering: Uses Pillow to render typographically-consistent images; `python-escpos` is used to talk to ESC/POS printers.
- Background worker: non-blocking queue with a worker that performs printing jobs so HTTP requests return quickly.

Repository map (refactored)
- `app.py` — thin runner script that imports `create_app` and starts Flask (keeps previous CLI/port behaviour).
- `task_printer/` — application package
  - `task_printer/__init__.py` — app factory `create_app(config_overrides=None, blueprints=None, register_worker=True)`; wires templates/static directories to repo-level `templates`/`static`.
  - `task_printer/core/` — core helpers
    - `assets.py` — static asset discovery (icons)
    - `config.py` — config helpers (path resolution, defaults)
    - `logging.py` — centralized logging configuration (JSON logging support, request ID hooks)
- `task_printer/web/` — HTTP layer (each module may register a Flask blueprint)
  - `routes.py` — main UI / index pages (blueprint `web_bp`)
  - `api.py` — versioned JSON API (`/api/v1`) for job submission and status (`api_bp`)
  - `setup.py` — setup flow & saving config (`setup_bp`)
  - `jobs.py` — jobs list and status endpoints (`jobs_bp`)
  - `health.py` — `/healthz` reporting (`health_bp`)
  - `templates.py` — templates CRUD, fetch, print (`templates_bp`)
- `task_printer/printing/` — printing and rendering
  - `render.py` — text → image rendering helpers, font resolution, image composition
  - `emoji.py` — emoji rasterization helpers
  - `metadata.py` — renders a compact metadata panel (assigned/due/priority/assignee)
  - `worker.py` — print queue + background worker (`ensure_worker`, queue API)
- `templates/` — Jinja templates (kept at repo root for easy editing).
  - `_components.html` — cohesive UI macros for a consistent look-and-feel (see “Frontend & Theming”).
  - `_form_macros.html` — form macros used by the index page to DRY up repeated markup:
    - `icon_picker(name, icons, selected=None)`
    - `flair_row(section_id, task_num, icons, flair_type='none', flair_value=None)`
    - `task_row(section_id, task_num, icons, text='', flair_type='none', flair_value=None)`
- `static/` — JS/CSS/icons and other static assets (kept at repo root).
  - `styles/app.css` — minimal custom tokens (brand colors), spinner animation, and small overrides complementing Tailwind CSS.
  - `js/app.js` — the frontend module powering dynamic form behaviors (add/remove sections/tasks, flair toggles, image preview, job polling, save-as-template, prefill, and payload_json submission).
- `docs/` — design docs such as persistence plans and deployment notes.
- `start.sh`, `install_service.sh`, `Dockerfile`, `requirements.txt` — runtime helpers remain at repo root.

Runtime & config
- Config file lookup:
  - `TASKPRINTER_CONFIG_PATH` (explicit override) → else `$XDG_CONFIG_HOME/taskprinter/config.json` → else `~/.config/taskprinter/config.json`
- Important environment variables:
  - `TASKPRINTER_SECRET_KEY` — Flask secret key used by `create_app`
  - `TASKPRINTER_CONFIG_PATH` — override config location
  - `TASKPRINTER_JSON_LOGS` — `true` to enable JSON-formatted logs in `task_printer.core.logging`
  - `TASKPRINTER_MEDIA_PATH` — storage for uploaded flair images
  - `TASKPRINTER_EMOJI_FONT_PATH` — optional path to a monochrome emoji TTF (e.g., NotoEmoji-Regular)
  - `TASKPRINTER_MAX_UPLOAD_SIZE` — bytes for upload limit (default: 5 MiB)
  - `TASKPRINTER_MAX_CONTENT_LENGTH` — Flask `MAX_CONTENT_LENGTH` override (default: 1 MiB)
  - Limits family: `TASKPRINTER_MAX_SECTIONS`, `TASKPRINTER_MAX_TASKS_PER_SECTION`, `TASKPRINTER_MAX_TASK_LEN`, `TASKPRINTER_MAX_SUBTITLE_LEN`, `TASKPRINTER_MAX_TOTAL_CHARS`, `TASKPRINTER_MAX_QR_LEN`
- App factory behavior:
  - `create_app(...)` returns a Flask app. It:
    - Sets `app.secret_key` (from env or a dev default)
    - Configures `MAX_CONTENT_LENGTH` from env
    - Initializes `CSRFProtect()` and sets a CSRF cookie on safe requests/redirects
    - Registers blueprints (a default set is attempted; each registration is non-fatal if module is missing)
    - Optionally ensures the background worker is started (`register_worker=True`)
  - Blueprints may be provided explicitly via the `blueprints` argument (list of `(import_path, attr)` tuples).

Request flow (refactored)
- Setup:
  - Before request hooks may redirect to `/setup` until a valid config exists (same gating behavior).
  - `/setup` lists detected USB devices (via `lsusb` or configured helpers), accepts manual entries, saves `config.json`, and triggers process restart flow.
  - `/restart` is still expected to return 204 and exit the process; systemd will restart the service when installed.
- Index (`/`):
  - The UI still builds dynamic form fields (now handled by `task_printer.web.routes`).
  - POST enqueues a job against the worker queue and redirects back to index with `?job=<id>` so banner polling can show status.
  - Optional per-print tear-off mode: a numeric field "Tear-off delay (seconds)" can be provided to disable cutting and add a delay between tasks for manual tear. Leave blank/0 for default behavior.
- Worker:
  - The worker consumes jobs and prints each task with configured spacing and separators. It handles:
    - Title/subtitle rendering
    - Flair printing (icon, uploaded image, QR)
    - Task rendering (image generation via `render.py`)
    - Cut/paper spacing
  - The worker module exposes `ensure_worker()` to start a singleton background thread/process and a simple queue API for the web layer to push jobs.

Printing details
- Connector selection is still driven by `printer_type` in config: `Usb`, `Network`, `Serial`. Profiles are passed through where appropriate.
- Fonts and rendering:
  - `render.py` centralizes font resolution: it prefers `TASKPRINTER_FONT_PATH` or common system fonts; fallback to Pillow default if none found.
  - `emoji.py` resolves an emoji-capable font: prefers `emoji_font_path` (config), `TASKPRINTER_EMOJI_FONT_PATH` (env), then common platform paths (Noto Emoji/OpenMoji-Black/Symbola), then falls back.
  - Text and layout are rendered to images to preserve typography before sending to the ESC/POS driver.
- Flair:
  - `icon` picks from `static/icons/<key>.(png|jpg|jpeg|gif|bmp)` discovered by `task_printer.core.assets`.
  - `image` uploads are stored under `TASKPRINTER_MEDIA_PATH` and referenced by the worker.
  - `qr` payloads are printed using the ESC/POS driver's QR routines if available, otherwise rendered as an image.
  - `emoji` is rasterized via `printing.emoji.rasterize_emoji` and composed like an icon.

Metadata (per-task)
- Optional fields: `assigned`, `due`, `priority`, `assignee`.
- UI: Toggle “Details” under each task reveals inputs.
- Payload: tasks include `metadata: {assigned, due, priority, assignee}` when provided.
- Rendering: A compact panel is rendered below the task receipt via `printing.metadata.render_metadata_block`.
 - Dates: UI uses `type="date"` inputs with quick helpers (Today, +1d/+1w/+1m). Server accepts ISO `YYYY-MM-DD` or `MM-DD`/`MM/DD`; printed as `MM-DD`.

Tear-off mode
- Per-print: the index page includes a number input "Tear-off delay (seconds)". When > 0, the worker suppresses cuts and sleeps between tasks.
- Global default: config may include `default_tear_delay_seconds` (0–60). The Templates print route uses this default when printing directly from the Templates page, and the index form preloads this value but it can be overridden at submit time.

Routes (now implemented as blueprints)
- `GET/POST /` — main UI and job enqueueing (`task_printer.web.routes:web_bp`)
- `POST /api/v1/jobs` — submit a JSON job (202 Accepted) (`task_printer.web.api:api_bp`)
- `GET /api/v1/jobs/<id>` — job status JSON (`task_printer.web.api:api_bp`)
- `GET/POST /setup` — config UI + save (`task_printer.web.setup:setup_bp`)
- `POST /setup_test_print` — test print using current setup inputs (implemented inside `setup_bp`)
- `POST /test_print` — queue a test print with saved config
- `POST /restart` — exit process after responding (systemd will restart under service install)
- `GET /jobs` — jobs list UI; `GET /jobs/<id>` — job status JSON (`task_printer.web.jobs:jobs_bp`)
- `GET /healthz` — config/worker/printer/emoji status JSON (`task_printer.web.health:health_bp`). A small health badge appears on the Index page.

Templates (blueprint: `task_printer.web.templates:templates_bp`)
- `GET /templates` — list templates (HTML by default; JSON with `?format=json` or `Accept: application/json` without `text/html`).
- `POST /templates` — create a template from JSON or form.
- `GET /templates/<id>` — fetch one template (JSON) for prefill.
- `GET /templates/<id>/edit` — edit page (HTML).
- `POST /templates/<id>/update` — replace name/notes/structure; multipart enables new image uploads.
- `POST /templates/<id>/duplicate` — duplicate with optional `new_name`.
- `POST /templates/<id>/delete` — delete.
- `POST /templates/<id>/print` — print using stored data; honors global default tear‑off delay if set.

Coding guidelines for agents
- Use `create_app(...)` when writing tests. You can pass `register_worker=False` to avoid the background worker in unit tests.
- Logging: use `app.logger.*` and the helpers in `task_printer.core.logging`. Do not use plain `print()`.
- CSRF: All POST routes (and AJAX clients) must include a CSRF token. The app sets a `csrf_token` cookie on safe responses—read it and send via header `X-CSRFToken` or include it in form fields.
- Validation: Enforce limits server-side (max sections/tasks/chars). Reject control characters and return helpful `flash()` messages to the UI.
- No blocking work inside request handlers: enqueue work to the worker and return quickly.
- Blueprint registration: `create_app` attempts to import and register known blueprints, but new endpoints should be added as blueprints under `task_printer.web` and included in the default registration list or passed explicitly to `create_app`.
- Tests: Add unit tests under `tests/` that create an app via `create_app(...)`. Use `register_worker=False` for tests that don't need the worker.

Common pitfalls (post-refactor)
- Optional imports: `create_app` intentionally swallows missing blueprint modules to keep the scaffold non-breaking — expect to see debug logs instead of hard failures for missing files.
- Restart behavior: `POST /restart` still exits the process. When running locally without systemd you must re-run `./start.sh` or `python3 app.py`.
- Fonts: If fonts are absent, the rendering falls back to Pillow default. For consistent output in Docker or CI, install DejaVu fonts or set `TASKPRINTER_FONT_PATH`.
- File paths: Templates and static files are served from repo-level `templates/` and `static/` — keep that layout to avoid surprises.
- Worker concurrency: The worker is a simple background thread/consumer. If you need higher efficiency or persistence, consider the `docs/PERSISTENCE.md` and migrating to a process-based worker (e.g., RQ/Celery) with durable storage.

## Frontend & Theming

We use Tailwind (Option A, CDN) for layout and styling consistency and provide Jinja UI macros to keep the look cohesive across pages.

- Tailwind: loaded via CDN in `templates/base.html` with `darkMode: 'class'`. A minimal `static/styles/app.css` contains tokens (brand, surface) and the spinner animation.
- Dark mode: toggled by adding/removing the `dark` class on `<html>`. The global `window.toggleDarkMode()` is defined in `base.html` and a label-sync script is embedded by the `topbar` macro. Preference is stored in `localStorage` under `taskprinter:dark` and defaults to OS preference on first load.
- UI Macros: defined in `templates/_components.html`
  - `_classes(a,b,c,d,e,f)`: safely join class strings (Jinja has no varargs).
  - `btn(label, href=None, variant, size, onclick=None, formaction=None, ...)`: unified buttons. Variants: `primary`, `secondary`, `danger`, `outline`, `ghost`. Sizes: `sm`, `md`, `lg`.
  - `flash(category, message)` / `flash_messages(messages)`: consistent flash banners for `success`, `error`, `warning`, `info`.
  - `card(title=None, subtitle=None, actions=None)`: card wrapper with optional header/actions. Use with `{% call card(...) %} ... {% endcall %}` for the body.
  - `topbar(title=None, actions=None, show_theme_toggle=True)`: page-level header. `actions` is a list of `{label, href, variant, icon, size}` dicts; includes a working theme toggle.
- Form Macros (new): defined in `templates/_form_macros.html`
  - `icon_picker(name, icons, selected=None)` — renders icon radio grid (uses files under `static/icons`).
  - `flair_row(section_id, task_num, icons, flair_type='none', flair_value=None)` — renders flair selector + inputs (icon/image/QR/emoji).
  - `task_row(section_id, task_num, icons, text='', flair_type='none', flair_value=None)` — renders a task input and its flair row.
- Usage pattern:
  - Import components: `{% from "_components.html" import topbar, btn, flash_messages, card %}`
  - Import form macros: `{% from "_form_macros.html" import task_row, flair_row, icon_picker %}`
  - Topbar: `{{ topbar(title="My Page", actions=[{'label':'Jobs','href':'/jobs','variant':'outline'}]) }}`
  - Card: `{% call card(title="Settings") %} ... {% endcall %}`
  - Button: `{{ btn("Save", variant="primary", type="submit") }}`
  - Flashes: `{{ flash_messages(get_flashed_messages(with_categories=true)) }}`

Migration notes (Option A):
- Inline `<style>` blocks have been removed or minimized from templates and replaced with Tailwind classes and macros.
- `index.html`, `jobs.html`, `templates.html`, `loading.html`, and `setup.html` have been converted to use utilities and macros for cohesive styling.
- For production builds, consider Option B (Tailwind build step with purge/minify) as described in `docs/THEMING.md`.

Frontend structure (post-refactor)
- Dynamic UI logic moved to a static module: `static/js/app.js` (loaded in `templates/base.html` via `<script type="module" src="{{ url_for('static', filename='js/app.js') }}"></script>`). This module:
  - Adds and removes subtitle sections and tasks using DOM templates and cloneNode.
  - Toggles flair controls (icon/image/QR), previews image uploads, and polls job status.
  - Saves current form as a template via JSON.
  - Rebuilds the form from saved templates (prefill) using three sources: server-injected `window.__PREFILL_TEMPLATE`, `localStorage`, or `?prefill=<id>` fetch.
  - On submit, attaches a hidden `<input name="payload_json">` containing a JSON representation of sections/tasks to simplify backend parsing. Image files remain in the multipart form and are referenced by field name in the JSON.
- Server parsing prefers `payload_json` and falls back to legacy dynamic field names for backward compatibility. Image flair resolution:
  - If `flair_type == "image"`, the backend uses `flair_value` as the upload field name (e.g., `flair_image_2_3`) to read `request.files[field]`. If missing, it falls back to `flair_image_{i}_{j}`.
  - If `flair_type == "emoji"`, the backend expects a short string value (emoji); it's rasterized server-side.

Quality & linting
- We plan to enforce template correctness using `djlint` (HTML/Jinja linter) in CI alongside `scripts/validate_templates.py`.
- We also plan to enable Jinja `StrictUndefined` to surface missing variables at render time. When adopting, prefer `|default` filters or `or ''` for optional fields in templates.
- PRs touching templates should run `uv run scripts/validate_templates.py` locally and address djlint findings.

Extending the app
- Adding new HTTP endpoints:
  - Create a blueprint module under `task_printer/web` and add it to the default blueprint list in `task_printer.__init__.py` (or pass it to `create_app` during app creation).
  - Respect CSRF/injection patterns and add tests.
- Adding a new printer connector or profile:
  - Add connector code to `task_printer.printing` (or a `connectors` submodule). Keep ESC/POS-specific calls isolated and add retries/timeouts.
- Persistence & templates:
  - See `docs/PERSISTENCE.md` for Phase 3 design. If you implement DB schema, provide bootstrapping in `create_app` or a separate `init_db` CLI helper.
- Reliability:
  - Add retries and timeouts around external IO (USB/network).
  - Surface printer errors into job status for easier debugging via `/jobs/<id>`.

Developer workflow & tips
- Before editing, inspect `task_printer/__init__.py` to understand how the app is wired.
- When adding files, prefer placing them under `task_printer/` to keep the package coherent.
- Run unit tests with the project root as working directory so template/static discovery works.
- Use `create_app(config_overrides=..., register_worker=False)` for isolated web tests.
- Logging: include `g.request_id` in logs; `task_printer.core.logging` attempts to wire this in. Use structured logs (JSON) behind `TASKPRINTER_JSON_LOGS=true` where appropriate.

Dev setup (how to run locally)
- Create a virtualenv and install deps:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
- Quick run:
  - `./start.sh` (this uses the project `app.py` runner) or:
  - `python3 app.py` — this imports `create_app()` and starts Flask on `TASKPRINTER_PORT` or `5001` by default.
- Systemd:
  - `install_service.sh` installs a hardened unit that uses `start.sh` and an `/etc/default/taskprinter` env file.
- Docker:
  - If using USB printers in containers, pass `--device=/dev/bus/usb` or run privileged. Mount `TASKPRINTER_CONFIG_PATH` and `TASKPRINTER_MEDIA_PATH` to preserve config and uploads.

Config keys (selected)
- `default_tear_delay_seconds`: Optional float (0–60). When set, template prints use this value to enable tear-off mode by default, and the index page preloads it in the tear-off input; users can override per print.
- `emoji_font_path`: Optional absolute path to a monochrome emoji TTF for ESC/POS.
- `emoji_font_size`: Optional int; defaults to `flair_target_height` when rasterizing emoji.
 - Templates DB: `TASKPRINTER_DB_PATH` for SQLite location; schema includes per-task metadata columns.

Definition of done for changes
- No `print()` statements; use `app.logger`.
- CSRF compliance for all POSTs and AJAX.
- Backend enforces input limits and rejects control characters.
- No blocking IO inside request handlers; work enqueued to the worker.
- Tests added/updated for major behavioral changes; `create_app(register_worker=False)` used for web tests.
- Docs updated: if you add env vars, blueprints, or major runtime behavior changes, update `AGENTS.md`, `README.md`, and `docs/*`.

If you plan to add persistence or templates, begin with `docs/PERSISTENCE.md` and implement a small incremental feature such as `GET/POST /templates` plus DB bootstrap. That approach keeps the change set reviewable and low-risk.

Contact
- If you're unsure where to place a change, open a small PR describing the problem and proposed file locations. Prefer small, incremental PRs that update `AGENTS.md` and docs as part of the change.

------------------------------------------------------------
A final note to you: treat `task_printer` as the canonical place for application logic. Use the thin `app.py` only for small run-time glue. This keeps imports, tests, and deployments predictable.
