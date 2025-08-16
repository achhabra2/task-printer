"""
Config utilities for Task Printer.

Responsibilities:
- Resolve config/media paths with environment and XDG support
- Provide JSON load/save helpers for the app's config
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def default_config_path() -> str:
    """
    Resolve the default config path using:
    1) $XDG_CONFIG_HOME/taskprinter/config.json
    2) ~/.config/taskprinter/config.json
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return str(Path(xdg) / "taskprinter" / "config.json")
    return str(Path.home() / ".config" / "taskprinter" / "config.json")


def default_media_path() -> str:
    """
    Resolve the default media path using:
    1) $XDG_DATA_HOME/taskprinter/media
    2) ~/.local/share/taskprinter/media
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return str(Path(xdg) / "taskprinter" / "media")
    return str(Path.home() / ".local" / "share" / "taskprinter" / "media")


def get_config_path() -> str:
    """
    Return the config path honoring TASKPRINTER_CONFIG_PATH override.
    """
    return os.environ.get("TASKPRINTER_CONFIG_PATH", default_config_path())


def get_media_path() -> str:
    """
    Return the media path honoring TASKPRINTER_MEDIA_PATH override.
    """
    return os.environ.get("TASKPRINTER_MEDIA_PATH", default_media_path())


def ensure_dir(path: str) -> str:
    """
    Ensure a directory exists and return the path.
    """
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def ensure_media_dir(path: Optional[str] = None) -> str:
    """
    Ensure the media directory exists and return its path.
    """
    return ensure_dir(path or get_media_path())


def load_config(path: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Load the JSON config if it exists; return None if missing.

    Raises:
        json.JSONDecodeError if the file exists but contains invalid JSON.
        OSError for I/O errors other than missing file.
    """
    cfg_path = Path(path or CONFIG_PATH)
    if not cfg_path.exists():
        return None
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data: dict[str, Any], path: Optional[str] = None) -> None:
    """
    Save the JSON config, creating parent directories as needed.

    Writes atomically by using a temporary file and os.replace().
    Raises OSError on I/O failures.
    """
    cfg_path = Path(path or CONFIG_PATH)
    cfg_dir = cfg_path.parent
    cfg_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, cfg_path)


# Module-level resolved paths (kept for convenience with existing code)
CONFIG_PATH: str = get_config_path()
MEDIA_PATH: str = get_media_path()

# Ensure media directory at import so uploads don't fail later.
ensure_media_dir(MEDIA_PATH)

__all__ = [
    "CONFIG_PATH",
    "MEDIA_PATH",
    "default_config_path",
    "default_media_path",
    "ensure_dir",
    "ensure_media_dir",
    "get_config_path",
    "get_media_path",
    "load_config",
    "save_config",
]
