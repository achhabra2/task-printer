# Task Printer — Implemented Changes

Date: 2025-08-16

This document summarizes the recent improvements implemented in the Task Printer project, how they work, and how to use them.

## Overview

We focused on HTML correctness and UX, non-blocking print execution, safer configuration/secret handling, and a more flexible service setup.

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

7) Jobs: IDs, status, and UI
- Files: `app.py`, `templates/index.html`, `templates/jobs.html`
- Added job IDs for all queued work with a JSON status endpoint `GET /jobs/<id>`.
- `index.html` shows a small status banner and polls when a `job` query param is present.
- New Jobs page (`/jobs`) lists recent jobs with auto-refresh and links to JSON.

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
