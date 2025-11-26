#!/bin/bash
# Task Printer Startup Script
# Run this script to start the Task Printer application and MCP server

set -euo pipefail

# Env overrides:
# USE_UV=true          # Use uv to run inside managed venv
# VENV_PATH=/path/.venv  # Use specific venv path

# Function to cleanup background processes on exit
cleanup() {
  echo "Shutting down services..."
  kill 0
}
trap cleanup EXIT

run_with_uv() {
  if command -v uv >/dev/null 2>&1; then
    echo "Starting MCP server with uv..."
    uv run mcp_server.py --host 0.0.0.0 &
    echo "Starting main application with uv..."
    exec uv run app.py --host 0.0.0.0
  fi
  return 1
}

run_with_venv() {
  local venv_bin="${VENV_PATH:-"$PWD/.venv"}/bin/python"
  if [ -x "$venv_bin" ]; then
    echo "Starting MCP server with venv: $venv_bin"
    "$venv_bin" mcp_server.py --host 0.0.0.0 &
    echo "Starting main application with venv: $venv_bin"
    exec "$venv_bin" app.py --host 0.0.0.0
  fi
  return 1
}

if [ "${USE_UV:-false}" = "true" ]; then
  run_with_uv || echo "uv not found; falling back"
fi

run_with_venv || echo "venv not found; falling back to system python"

echo "Starting MCP server with system python..."
python3 mcp_server.py --host 0.0.0.0 &
echo "Starting main application with system python..."
exec python3 app.py --host 0.0.0.0
