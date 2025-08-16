#!/usr/bin/env bash
set -euo pipefail

# Fedora local setup script for Task Printer
# - Checks/installs system dependencies via dnf (optional)
# - Creates/validates a local .venv using uv if available, else python venv
# - Installs Python requirements
# - Performs basic validation (imports, font availability, lsusb)

usage() {
  cat <<USAGE
Usage: $0 [--yes] [--no-uv]

Options:
  --yes      Non-interactive; auto-install required dnf packages with sudo
  --no-uv    Do not use 'uv' even if available; use python venv instead

Environment:
  TASKPRINTER_FONT_PATH  Optional path to a TTF font for printing
USAGE
}

CONFIRM=no
USE_UV=yes
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --yes) CONFIRM=yes ;;
    --no-uv) USE_UV=no ;;
    *) echo "Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

if ! command -v dnf >/dev/null 2>&1; then
  echo "This script targets Fedora (dnf not found). Aborting."
  exit 1
fi

echo "==> Checking system dependencies"
PKGS=(python3 gcc libusb1 usbutils dejavu-sans-fonts libjpeg-turbo-devel zlib-devel freetype-devel)
MISSING=()
for p in "${PKGS[@]}"; do
  if ! rpm -q "$p" >/dev/null 2>&1; then
    MISSING+=("$p")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "Missing packages: ${MISSING[*]}"
  if [ "$CONFIRM" = "yes" ]; then
    sudo dnf install -y "${MISSING[@]}"
  else
    read -r -p "Install missing packages with sudo dnf? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      sudo dnf install -y "${MISSING[@]}"
    else
      echo "Skipping system package installation. You may encounter build/runtime errors."
    fi
  fi
else
  echo "All required packages already installed."
fi

echo "==> Setting up Python environment (.venv)"
if [ "$USE_UV" = "yes" ] && command -v uv >/dev/null 2>&1; then
  echo "Using uv to create/manage venv"
  uv venv
  uv pip install -r requirements.txt
else
  if [ "$USE_UV" = "yes" ]; then
    echo "uv not found; falling back to python venv"
  fi
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "Virtualenv not found at .venv; something went wrong."
  exit 1
fi

echo "==> Validating Python imports and font availability"
"$VENV_PY" - <<'PY'
import os, sys
ok = True
def check(mod):
  global ok
  try:
    __import__(mod)
    print(f"[ok] import {mod}")
  except Exception as e:
    ok = False
    print(f"[err] import {mod}: {e}")

for m in ["flask", "escpos", "PIL", "usb"]:
  check(m)

try:
  from PIL import ImageFont
  font_env = os.environ.get("TASKPRINTER_FONT_PATH")
  tried = []
  if font_env:
    tried.append(font_env)
  tried += [
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
  ]
  loaded = False
  for p in tried:
    try:
      ImageFont.truetype(p, 24)
      print(f"[ok] found TTF font: {p}")
      loaded = True
      break
    except Exception:
      pass
  if not loaded:
    print("[warn] No TTF font found; app will fall back to PIL default font. Set TASKPRINTER_FONT_PATH to a TTF for best output.")
except Exception as e:
  ok = False
  print(f"[err] PIL font check failed: {e}")

sys.exit(0 if ok else 1)
PY

echo "==> Checking lsusb availability"
if ! command -v lsusb >/dev/null 2>&1; then
  echo "[warn] lsusb not found (usbutils). USB printer auto-detection may be limited."
else
  echo "[ok] lsusb present"
fi

echo "\nSetup complete. Next steps:"
echo "  1) Activate venv:    source .venv/bin/activate"
echo "  2) Run the app:      ./start.sh    (or: python3 app.py)"
echo "  3) Open in browser:  http://localhost:5000"
echo "\nOptional:"
echo "  - Set TASKPRINTER_FONT_PATH to a TTF path for clearer prints"
echo "  - Use ./install_service.sh to run as a systemd service"

