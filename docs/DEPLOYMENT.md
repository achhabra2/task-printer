# Deployment Guide

This guide covers systemd hardening, uv/virtualenv usage, and containerization.

## Systemd Service (Hardened)

Install/update the service:

```bash
sudo ./install_service.sh
```

Hardening options included in the unit:
- `Restart=on-failure`, `RestartSec=3`
- `NoNewPrivileges=true`
- `ProtectSystem=full`
- `PrivateTmp=true`
- `DynamicUser=` (configurable via env file)

Environment file: `/etc/default/taskprinter` (created by the installer) lets you configure:

```bash
# Secrets & config path
TASKPRINTER_SECRET_KEY=change_me
# TASKPRINTER_CONFIG_PATH=/var/lib/taskprinter/config.json

# Logging
TASKPRINTER_JSON_LOGS=false

# Runtime selection
USE_UV=false           # If true and 'uv' is available, use uv run
# VENV_PATH=/opt/taskprinter/.venv  # Use this venv if present

# Systemd dynamic user sandboxing
DYNAMIC_USER=no        # Set to 'yes' to enable DynamicUser
```

The unit calls `start.sh`, which decides how to run the app based on the above variables:
1. If `USE_UV=true` and `uv` is present → `uv run app.py`
2. Else if `VENV_PATH` (or `./.venv`) exists → `<venv>/bin/python app.py`
3. Else → `python3 app.py`

After editing `/etc/default/taskprinter`:

```bash
sudo systemctl daemon-reload
sudo systemctl restart taskprinter.service
```

## Using uv

Install `uv` (see https://github.com/astral-sh/uv for platform instructions).

Create a project venv and install dependencies:

```bash
# From project root
uv venv                # creates .venv
uv pip install -r requirements.txt
```

Run locally with uv:

```bash
USE_UV=true ./start.sh
```

For systemd, set in `/etc/default/taskprinter`:

```bash
USE_UV=true
TASKPRINTER_SECRET_KEY="your-strong-secret"
```

## Virtualenv (without uv)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
./start.sh
```

To use via systemd, set:

```bash
VENV_PATH=/path/to/project/.venv
```

## Containerization

A Dockerfile is included. Build and run:

```bash
docker build -t task-printer .
docker run --rm -p 5000:5000 -e TASKPRINTER_SECRET_KEY=change_me task-printer
```

USB printers require device access. Options:
- Pass specific USB buses/devices: `--device=/dev/bus/usb`
- Or (less secure) `--privileged`

Network printers require only TCP connectivity to the printer IP/port.

Persisting config: mount a host path as the config location and point `TASKPRINTER_CONFIG_PATH` to it, e.g.:

```bash
docker run --rm -p 5000:5000 \
  -e TASKPRINTER_SECRET_KEY=change_me \
  -e TASKPRINTER_CONFIG_PATH=/data/config.json \
  -v $(pwd)/data:/data \
  task-printer
```

## Templates database and backups

Templates and their sections/tasks are stored in a SQLite database.

- Path precedence:
  1. `TASKPRINTER_DB_PATH` (env)
  2. `$XDG_DATA_HOME/taskprinter/data.db`
  3. `~/.local/share/taskprinter/data.db`

- Docker persistence example:

```bash
docker run --rm -p 5000:5000 \
  -e TASKPRINTER_SECRET_KEY=change_me \
  -e TASKPRINTER_DB_PATH=/data/data.db \
  -e TASKPRINTER_MEDIA_PATH=/data/media \
  -v $(pwd)/data:/data \
  task-printer
```

- Backups:
  - Prefer copying the DB while the app is idle, or use `sqlite3`'s `.backup` command for a consistent snapshot.
  - If you use image flair, also back up `TASKPRINTER_MEDIA_PATH`.

- Restore:
  - Replace the DB file on disk and restart the app (systemd or `./start.sh`).

Logs: set `TASKPRINTER_JSON_LOGS=true` for JSON logs (better with log drivers).

Fonts: The app requires a TTF font for rendering task text. The Docker image installs DejaVu Sans (`fonts-dejavu-core`). If running outside Docker, ensure a TTF font exists and either:
- Set `TASKPRINTER_FONT_PATH=/path/to/YourFont.ttf`, or
- Rely on common system paths (DejaVuSans, FreeSans, LiberationSans, NotoSans).
