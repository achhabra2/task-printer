#!/bin/bash
# Task Printer Startup Script
# Run this script to start the Task Printer application

set -euo pipefail

# Env overrides:
# USE_UV=true          # Use uv to run inside managed venv
# VENV_PATH=/path/.venv  # Use specific venv path

run_with_uv() {
  if command -v uv >/dev/null 2>&1; then
    echo "Using uv run"
    exec uv run app.py
  fi
  return 1
}

run_with_venv() {
  local venv_bin="${VENV_PATH:-"$PWD/.venv"}/bin/python"
  if [ -x "$venv_bin" ]; then
    echo "Using venv: $venv_bin"
    exec "$venv_bin" app.py
  fi
  return 1
}

if [ "${USE_UV:-false}" = "true" ]; then
  run_with_uv || echo "uv not found; falling back"
fi

run_with_venv || echo "venv not found; falling back to system python"

exec python3 app.py
