from __future__ import annotations

"""
Health endpoints for Task Printer.

This blueprint exposes `/healthz`, reporting:
- Overall status ("ok" or "degraded")
- Background worker status and queue size (via task_printer.printing.worker.worker_status)
- Presence of saved config
- Basic printer reachability (connect + close)
"""

from typing import Any, Dict, Optional

from flask import Blueprint

from task_printer.core.config import load_config
from task_printer.printing.emoji import rasterize_emoji
from task_printer.printing.worker import worker_status

health_bp = Blueprint("health", __name__)


def _check_printer(cfg: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Attempt to connect to the configured printer and close immediately.

    Returns:
        (ok, reason)
        ok: True if the printer is reachable, False otherwise.
        reason: A short code string describing the failure, or None on success.
    """
    try:
        ptype = str(cfg.get("printer_type", "usb")).lower()
        profile = cfg.get("printer_profile") or None

        if ptype == "usb":
            from escpos.printer import Usb

            vendor = int(str(cfg.get("usb_vendor_id", "0x04b8")), 16)
            product = int(str(cfg.get("usb_product_id", "0x0e28")), 16)
            p = Usb(vendor, product, profile=profile) if profile else Usb(vendor, product)
        elif ptype == "network":
            from escpos.printer import Network

            ip = str(cfg.get("network_ip", ""))
            port = int(str(cfg.get("network_port", "9100")))
            p = Network(ip, port, profile=profile) if profile else Network(ip, port)
        elif ptype == "serial":
            from escpos.printer import Serial

            port = str(cfg.get("serial_port", ""))
            baud = int(str(cfg.get("serial_baudrate", "19200")))
            p = Serial(port, baudrate=baud, profile=profile) if profile else Serial(port, baudrate=baud)
        else:
            return False, "unsupported_printer_type"

        try:
            p.close()
        except Exception:
            # Ignore close errors; connection succeeded if we got this far
            pass

        return True, None
    except Exception as e:
        return False, f"printer_unreachable: {type(e).__name__}"


@health_bp.get("/healthz")
def healthz():
    status: Dict[str, Any] = {"status": "ok"}
    # Worker/queue status
    status.update(worker_status())

    cfg = load_config()
    if not cfg:
        status["status"] = "degraded"
        status["reason"] = "no_config"
        return status, 200

    ok, reason = _check_printer(cfg)
    status["printer_ok"] = ok
    if not ok:
        status["status"] = "degraded"
        if reason:
            status["reason"] = reason

    # Emoji font/glyph sanity check
    try:
        sample = str(cfg.get("emoji_health_sample", "✅"))
        img = rasterize_emoji(sample, target_height=64, config=cfg)
        ok_emoji = bool(img and img.getbbox())
        status["emoji_ok"] = ok_emoji
        if not ok_emoji and status.get("status") == "ok":
            status["status"] = "degraded"
            status["reason"] = "emoji_unavailable"
        # Surface configured path if present
        if cfg.get("emoji_font_path"):
            status["emoji_font_path"] = cfg.get("emoji_font_path")
    except Exception:
        status["emoji_ok"] = False
        if status.get("status") == "ok":
            status["status"] = "degraded"
            status["reason"] = "emoji_check_failed"

    return status, 200
