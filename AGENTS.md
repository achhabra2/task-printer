# Task Printer — Agent Guide

This document orients future agents to the codebase, how the app works end‑to‑end, where things live, and how to extend it safely. Skim this before making changes.

## Overview
- Purpose: A small Flask app that lets users enter grouped “tasks” and prints each task as its own receipt on a thermal printer (USB, network, or serial). Designed for Raspberry Pi but portable to Linux.
- Printer driver: `python-escpos` (ESC/POS). Text is rendered via Pillow to image for consistent typography. Optional printer “profiles” (e.g., Epson TM‑P80) can be selected.

## Key Features
- Setup gating: First run redirects to `/setup`; config persisted to `config.json` (path resolved via env/XDG).
- Print queue + worker: Print requests are queued and processed in a background thread (non‑blocking HTTP).
- Jobs: ID’d jobs, `/jobs/<id>` status API, Jobs page (`/jobs`), banner on home.
- Logging: Python `logging` with request IDs, journald fallback; optional JSON logs via env.
- Security & limits: Flask‑WTF CSRF across forms; input length/section/task caps; control‑character rejection.
- Health: `/healthz` reports config presence, worker status, queue size, basic printer reachability.
- Test Print: From index and setup (pre‑save) using current config/inputs.
- Printer profile: Optional selection (e.g., `TM-P80`, `TM-T88III`, `TM-T20III`), generic otherwise.
- Paper usage: Configurable blank lines before cut; optional dashed separators.
- Flair per task (Phase 1–2): Icon (from `static/icons`), QR payload, or Image upload with live preview.

## Repository Map
- `app.py` — Flask app, routes, config, queue worker, printing logic, logging.
- `templates/` — Jinja templates:
  - `index.html` — main UI (dynamic sections/tasks, flair, status banner, topbar).
  - `setup.html` — printer configuration (type, connection, profile, spacing/separators).
  - `loading.html` — shows while restarting after saving settings.
  - `jobs.html` — jobs list (auto‑refresh).
  - `base.html` — shared base.
- `static/icons/` — optional icon PNG/JPG/etc. Auto‑scanned for icon picker.
- `requirements.txt` — Flask, python‑escpos, Pillow, pyusb, Flask‑WTF.
- `start.sh` — picks uv/venv/system python to run the app.
- `install_service.sh` — installs a hardened systemd unit with `EnvironmentFile`.
- `scripts/setup_fedora.sh` — local setup helper for Fedora.
- `Dockerfile` — minimal container (installs DejaVu fonts).
- `docs/` — project docs:
  - `IMPLEMENTED.md` — shipped features.
  - `IMPROVEMENTS.md` — roadmap.
  - `DEPLOYMENT.md` — systemd, uv/venv, Docker.
  - `PERSISTENCE.md` — Phase 3 SQLite templates design.

## Runtime & Config
- Config file path resolution:
  - `TASKPRINTER_CONFIG_PATH` → else `$XDG_CONFIG_HOME/taskprinter/config.json` → else `~/.config/taskprinter/config.json`.
- Important env vars:
  - `TASKPRINTER_SECRET_KEY` — Flask secret key.
  - `TASKPRINTER_CONFIG_PATH` — override config file path.
  - `TASKPRINTER_JSON_LOGS` — `true` for JSON logs.
  - `TASKPRINTER_MEDIA_PATH` — where uploads (flair images) are stored.
  - `TASKPRINTER_MAX_UPLOAD_SIZE` — max upload size (bytes, default 5 MiB).
  - `TASKPRINTER_MAX_CONTENT_LENGTH` — request body cap (default 1 MiB).
  - Limits: `TASKPRINTER_MAX_SECTIONS`, `TASKPRINTER_MAX_TASKS_PER_SECTION`, `TASKPRINTER_MAX_TASK_LEN`, `TASKPRINTER_MAX_SUBTITLE_LEN`, `TASKPRINTER_MAX_TOTAL_CHARS`, `TASKPRINTER_MAX_QR_LEN`.
- Systemd unit:
  - Uses `start.sh` as `ExecStart`. Hardened with `NoNewPrivileges`, `ProtectSystem`, `PrivateTmp`, `Restart=on-failure`, optional `DynamicUser`.
  - Env file: `/etc/default/taskprinter` controls runtime/env.
- Docker:
  - USB printers require `--device=/dev/bus/usb` or `--privileged`.
  - Map config/media via env/volumes.

## Request Flow
- Setup:
  - `@before_request` redirects to `/setup` until config exists. `/setup` lists USB via `lsusb` and supports manual entry. Saves config.json then calls `/restart`.
  - `/restart` responds 204 and exits the process (systemd restarts; manual runs require re‑launch).
- Index:
  - Dynamic form builds `subtitle_{i}` and `task_{i}_{j}` (plus flair fields). POST enqueues a job and redirects with `?job=id` for banner polling.
- Worker:
  - Consumes jobs and prints per task: top spacing/separator → subtitle text → flair (icon/image/QR) → rendered task image → bottom separator/spacing → cut.

## Printing Details
- Driver connector chosen by `printer_type`: `Usb`, `Network`, `Serial`. Optional `profile` is passed when set.
- Fonts: `render_large_text_image` picks a font via `_resolve_font_path` (config override, env, common paths) or loads default.
- Flair:
  - `icon`: resolve from `static/icons/<key>.(png|jpg|jpeg|gif|bmp)`; fallback placeholder if missing.
  - `image`: uploaded file stored under `MEDIA_PATH` and printed via `p.image(path)`.
  - `qr`: printed via `p.qr(payload)`.

## Routes (current)
- `GET/POST /` — main UI, queues print job.
- `GET/POST /setup` — config UI + save.
- `POST /setup_test_print` — test print using current setup inputs.
- `POST /test_print` — queue a test print with saved config.
- `POST /restart` — exits the process after responding.
- `GET /jobs` — jobs list; `GET /jobs/<id>` — job status JSON.
- `GET /healthz` — config/worker/printer status JSON.

## Coding Guidelines
- Logging: use `app.logger.*`; do not use `print()`. Request IDs are auto‑injected; JSON logs via env.
- CSRF: All forms and AJAX must include tokens (Jinja `csrf_token()` or `X-CSRFToken`).
- Input limits: enforce in backend; reject control characters; surface errors via `flash`.
- Keep UI JS self‑contained; avoid nested template literals in JS (build strings safely).
- Avoid blocking work in routes; enqueue jobs; update `JOBS` state.
- Keep changes scoped; preserve style and patterns used (e.g., banner polling, dynamic forms).

## Common Pitfalls
- Restart behavior: In manual runs, `/restart` will stop the process; user must re‑run `./start.sh`.
- Fonts: If system fonts are missing, app falls back to Pillow default; set `TASKPRINTER_FONT_PATH` or install DejaVu.
- Icon picker build: Template strings must not embed nested `${...}` expressions that themselves contain `${}`.
- USB permissions: user may need `lp`/`plugdev`; see `README > Troubleshooting`.

## Extending the App
- Phase 3 persistence: See `docs/PERSISTENCE.md` for schema, API, and UI plan to save/load/print templates (with flair).
- Reliability: Add retries/timeouts around ESC/POS operations, lsusb fallback via `pyusb`.
- UX: Accessibility improvements, CSS variables for theme, better validation messages.
- Jobs: Cancel pending jobs, detailed errors, retention controls.

## Dev Setup
- Quick run:
  - `./scripts/setup_fedora.sh --yes` (Fedora) or manual venv/uv + `pip install -r requirements.txt`.
  - `./start.sh` (uses uv/venv if present) or `python3 app.py`.
- Icons: drop images into `static/icons/` (auto‑scanned on page render).
- Media uploads: stored under `TASKPRINTER_MEDIA_PATH` (ensure writable).

## Definition of Done (typical changes)
- Logging in place; no `print()`; request IDs visible in logs.
- CSRF respected for all new POSTs; inputs validated with existing limits.
- No blocking work in routes; jobs enqueued where appropriate.
- UI changes work on narrow screens; no overlap with the topbar; hard refresh tested.
- Docs updated when adding features or env vars (README and docs/*).

If you’re about to add persistence, start with `docs/PERSISTENCE.md` and implement DB bootstrap + `GET/POST /templates` first to land value incrementally.

