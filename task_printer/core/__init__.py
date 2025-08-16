"""
Core utilities for Task Printer.

This package groups non-Flask helpers used across the app:
- config: paths, JSON load/save, media directory helpers
- logging: Request ID aware logging filters/formatters and root logger config
- assets: icon discovery and image validation utilities

Exports are explicit to keep static analyzers (e.g., Pyright) happy.
"""

from .assets import (
    ICON_EXTS,
    IMAGE_EXTS,
    get_available_icons,
    get_icons_dir,
    is_supported_image,
    resolve_icon_path,
)
from .config import (
    CONFIG_PATH,
    MEDIA_PATH,
    default_config_path,
    default_media_path,
    ensure_dir,
    ensure_media_dir,
    get_config_path,
    get_media_path,
    load_config,
    save_config,
)
from .logging import (
    JsonFormatter,
    RequestIdFilter,
    configure_logging,
)

__all__ = [
    # config
    "CONFIG_PATH",
    "MEDIA_PATH",
    "default_config_path",
    "default_media_path",
    "get_config_path",
    "get_media_path",
    "ensure_dir",
    "ensure_media_dir",
    "load_config",
    "save_config",
    # logging
    "configure_logging",
    "RequestIdFilter",
    "JsonFormatter",
    # assets
    "ICON_EXTS",
    "IMAGE_EXTS",
    "get_available_icons",
    "get_icons_dir",
    "is_supported_image",
    "resolve_icon_path",
]
