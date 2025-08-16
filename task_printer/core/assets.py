"""
Asset helpers for Task Printer.

Responsibilities:
- Icon discovery from the repository's static/icons directory
- Resolve an icon key to an absolute filesystem path
- Basic image extension helpers for input validation

These functions are intentionally independent of Flask so they can be used
from both web and worker contexts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

# Supported image extensions for icons and uploads
ICON_EXTS: List[str] = [".png", ".jpg", ".jpeg", ".gif", ".bmp"]
IMAGE_EXTS: List[str] = ICON_EXTS[:]  # may diverge in the future if needed


def _repo_root() -> Path:
    """
    Return the repository root directory (project root).

    It walks up from this file looking for a directory that contains 'static/icons'.
    Falls back to the grandparent heuristic when not found.
    """
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        if (parent / "static" / "icons").exists():
            return parent
    # Heuristic fallback for source layout: <repo>/task_printer/core/assets.py
    try:
        return current.parents[2]
    except IndexError:
        return current.parent


def get_icons_dir() -> Path:
    """
    Absolute path to the static/icons directory.
    """
    return _repo_root() / "static" / "icons"


def is_supported_image(filename: str) -> bool:
    """
    True if the filename has a supported image extension.
    """
    ext = os.path.splitext(filename)[1].lower()
    return ext in IMAGE_EXTS


def get_available_icons() -> List[Dict[str, str]]:
    """
    Discover available icons under static/icons.

    Returns a list of dicts:
      - name: the icon base name (without extension)
      - filename: relative path under the static folder (e.g., "icons/foo.png")

    If multiple files share the same base name, prefer .png over other formats.
    Returns an empty list if the directory is missing or unreadable.
    """
    icons_path = get_icons_dir()
    mapping: Dict[str, str] = {}
    try:
        if not icons_path.exists():
            return []
        for entry in icons_path.iterdir():
            if not entry.is_file():
                continue
            base, ext = os.path.splitext(entry.name)
            if ext.lower() in ICON_EXTS:
                # Prefer PNG if multiple variants exist
                prev = mapping.get(base)
                if prev is None or (os.path.splitext(prev)[1].lower() != ".png" and ext.lower() == ".png"):
                    mapping[base] = entry.name
    except Exception:
        # Be defensive; return empty list on failure
        return []

    icons: List[Dict[str, str]] = []
    for base, fname in sorted(mapping.items()):
        icons.append({"name": base, "filename": f"icons/{fname}"})
    return icons


def resolve_icon_path(key: str) -> Optional[str]:
    """
    Resolve an icon key (base name without extension) to an absolute file path.
    Tries supported extensions in a deterministic order.

    Returns:
        Absolute path string, or None if not found.
    """
    icons_path = get_icons_dir()
    for ext in ICON_EXTS:
        candidate = icons_path / f"{key}{ext}"
        if candidate.exists():
            return str(candidate)
    return None


__all__ = [
    "ICON_EXTS",
    "IMAGE_EXTS",
    "get_available_icons",
    "get_icons_dir",
    "is_supported_image",
    "resolve_icon_path",
]
