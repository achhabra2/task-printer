from __future__ import annotations

"""
Setup and restart endpoints for Task Printer.

This blueprint provides:
- GET/POST /setup: Printer configuration UI and persistence
- POST /restart: Graceful app restart (systemd or manual run)
- POST /setup_test_print: Test print using unsaved setup form values
"""

import os
import subprocess
import threading
from time import sleep
from typing import Any, Dict, List

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from task_printer.core.assets import get_available_icons
from task_printer.core.config import CONFIG_PATH, load_config, save_config, get_config_path
from task_printer.printing.worker import enqueue_test_print, ensure_worker

setup_bp = Blueprint("setup", __name__)


def get_usb_devices() -> List[Dict[str, Any]]:
    """
    Enumerate USB devices via lsusb, attempting to identify printers.
    Returns a list of dicts containing 'vendor', 'product', 'desc', and 'is_printer'.
    """
    try:
        output = subprocess.check_output(["lsusb"]).decode()
        devices = []
        for line in output.strip().split("\n"):
            parts = line.split()
            if "ID" in parts:
                idx = parts.index("ID")
                id_pair = parts[idx + 1]
                vendor, product = id_pair.split(":")
                desc = " ".join(parts[idx + 2 :])
                is_printer = any(x in desc.lower() for x in ["epson", "printer", "star", "citizen", "bixolon", "seiko"])
                devices.append(
                    {
                        "vendor": vendor,
                        "product": product,
                        "desc": desc,
                        "is_printer": is_printer,
                    },
                )
        return devices
    except Exception:
        return []


@setup_bp.route("/setup", methods=["GET", "POST"])
def setup():
    usb_devices = get_usb_devices()
    show_close = os.path.exists(CONFIG_PATH)

    if request.method == "POST":
        current_app.logger.info(
            "POST /setup received: form_keys=%s files=%s",
            list(request.form.keys()),
            list(request.files.keys()),
        )
        form = request.form
        printer_type = form.get("printer_type", "usb")

        if printer_type == "usb":
            selected_usb = form.get("usb_device", "")
            if selected_usb and selected_usb != "manual":
                usb_vendor_id, usb_product_id = selected_usb.split(":")
            else:
                usb_vendor_id = form.get("usb_vendor_id", "0x04b8")
                usb_product_id = form.get("usb_product_id", "0x0e28")
        else:
            usb_vendor_id = form.get("usb_vendor_id", "0x04b8")
            usb_product_id = form.get("usb_product_id", "0x0e28")

        network_ip = form.get("network_ip", "")
        network_port = form.get("network_port", "9100")
        serial_port = form.get("serial_port", "")
        serial_baudrate = form.get("serial_baudrate", "19200")

        # Determine width and font size
        # Prefer explicit form-provided receipt_width; fall back to heuristics
        def _to_int(val, default):
            try:
                return int(val)
            except Exception:
                return default

        provided_width_raw = (form.get("receipt_width", "") or "").strip()
        provided_width = _to_int(provided_width_raw, 0) if provided_width_raw != "" else 0

        if provided_width > 0:
            # Reasonable clamp to supported printer widths
            receipt_width = max(280, min(1024, provided_width))
        else:
            # Heuristics by vendor/product for a decent default
            receipt_width = 512
            if printer_type == "usb":
                if usb_vendor_id.lower() == "0x04b8":
                    if usb_product_id.lower() in ["0x0e28", "0x0202", "0x020a", "0x0e15", "0x0e03"]:
                        receipt_width = 512
                    else:
                        receipt_width = 576

        task_font_size = 72
        if receipt_width >= 576:
            task_font_size = 90
        elif receipt_width >= 512:
            task_font_size = 72
        else:
            task_font_size = 60

        # Optional profile selection
        printer_profile = form.get("printer_profile", "").strip()
        if printer_profile.lower() == "generic":
            printer_profile = ""

        # Spacing and separators
        try:
            cut_feed_lines = int(form.get("cut_feed_lines", "2"))
        except ValueError:
            cut_feed_lines = 2
        cut_feed_lines = max(0, min(10, cut_feed_lines))

        # Separate feed lines to use when cutting is disabled (tear-off mode)
        try:
            tear_feed_lines = int(form.get("tear_feed_lines", str(cut_feed_lines)))
        except ValueError:
            tear_feed_lines = cut_feed_lines
        tear_feed_lines = max(0, min(10, tear_feed_lines))
        print_separators = form.get("print_separators") == "on"

        # Global default tear-off delay (optional)
        raw_delay = (form.get("default_tear_delay_seconds", "") or "").strip()
        try:
            default_tear_delay_seconds = float(raw_delay) if raw_delay != "" else 0.0
        except Exception:
            default_tear_delay_seconds = 0.0
        if default_tear_delay_seconds < 0:
            default_tear_delay_seconds = 0.0
        if default_tear_delay_seconds > 60:
            default_tear_delay_seconds = 60.0

        # Flair layout parameters (optional tuning)
        def _to_float(val, default):
            try:
                return float(val)
            except Exception:
                return default

        flair_separator_width = _to_int(form.get("flair_separator_width", "3"), 3)
        flair_separator_width = max(1, min(10, flair_separator_width))

        flair_separator_gap = _to_int(form.get("flair_separator_gap", "14"), 14)
        flair_separator_gap = max(0, min(64, flair_separator_gap))

        flair_col_width = _to_int(form.get("flair_col_width", "256"), 256)
        flair_col_width = max(96, min(512, flair_col_width))

        flair_target_height = _to_int(form.get("flair_target_height", "256"), 256)
        flair_target_height = max(96, min(512, flair_target_height))

        flair_icon_scale_max = _to_float(form.get("flair_icon_scale_max", "2.0"), 2.0)
        flair_icon_scale_max = max(1.0, min(4.0, flair_icon_scale_max))

        # Default min_text_width to ~45% of paper width if not provided
        default_min_text = max(180, int(receipt_width * 0.45))
        min_text_width = _to_int(form.get("min_text_width", str(default_min_text)), default_min_text)
        min_text_width = max(100, min(receipt_width - 100, min_text_width))

        # Print margins (new anti-cutoff settings)
        print_left_margin = _to_int(form.get("print_left_margin", "16"), 16)
        print_left_margin = max(0, min(50, print_left_margin))

        print_right_margin = _to_int(form.get("print_right_margin", "16"), 16)
        print_right_margin = max(0, min(50, print_right_margin))

        print_top_margin = _to_int(form.get("print_top_margin", "12"), 12)
        print_top_margin = max(0, min(50, print_top_margin))

        print_bottom_margin = _to_int(form.get("print_bottom_margin", "16"), 16)
        print_bottom_margin = max(0, min(50, print_bottom_margin))

        text_safety_margin = _to_int(form.get("text_safety_margin", "8"), 8)
        text_safety_margin = max(0, min(20, text_safety_margin))

        # Dynamic font sizing settings
        enable_dynamic_font_sizing = form.get("enable_dynamic_font_sizing") == "on"
        
        min_font_size = _to_int(form.get("min_font_size", "32"), 32)
        min_font_size = max(16, min(96, min_font_size))
        
        max_font_size = _to_int(form.get("max_font_size", "96"), 96)
        max_font_size = max(32, min(128, max_font_size))
        
        # Ensure max >= min
        if max_font_size < min_font_size:
            max_font_size = min_font_size + 8

        # Optional font paths
        font_path = (form.get("font_path", "") or "").strip()
        emoji_font_path = (form.get("emoji_font_path", "") or "").strip()
        if not emoji_font_path:
            # Try to auto-detect a reasonable monochrome emoji font across platforms
            home = os.path.expanduser("~")
            common_emoji_paths = [
                # Linux
                "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoEmoji.ttf",
                "/usr/local/share/fonts/NotoEmoji-Regular.ttf",
                "/usr/share/fonts/opentype/openmoji/OpenMoji-Black.ttf",
                "/usr/share/fonts/truetype/ancient-scripts/Symbola.ttf",
                # macOS (Font Book / system)
                "/Library/Fonts/NotoEmoji-Regular.ttf",
                "/Library/Fonts/Noto Emoji.ttf",
                os.path.join(home, "Library/Fonts/NotoEmoji-Regular.ttf"),
                os.path.join(home, "Library/Fonts/Noto Emoji.ttf"),
            ]
            for p in common_emoji_paths:
                try:
                    if p and os.path.exists(p):
                        emoji_font_path = p
                        break
                except Exception:
                    continue

        config = {
            "printer_type": printer_type,
            "usb_vendor_id": usb_vendor_id,
            "usb_product_id": usb_product_id,
            "network_ip": network_ip,
            "network_port": network_port,
            "serial_port": serial_port,
            "serial_baudrate": serial_baudrate,
            "receipt_width": receipt_width,
            "task_font_size": task_font_size,
            "printer_profile": printer_profile,
            "cut_feed_lines": cut_feed_lines,
            "tear_feed_lines": tear_feed_lines,
            "print_separators": print_separators,
            "default_tear_delay_seconds": default_tear_delay_seconds,
            # Flair layout tuning
            "flair_separator_width": flair_separator_width,
            "flair_separator_gap": flair_separator_gap,
            "flair_col_width": flair_col_width,
            "flair_target_height": flair_target_height,
            "flair_icon_scale_max": flair_icon_scale_max,
            "min_text_width": min_text_width,
            # Print margins (anti-cutoff)
            "print_left_margin": print_left_margin,
            "print_right_margin": print_right_margin,
            "print_top_margin": print_top_margin,
            "print_bottom_margin": print_bottom_margin,
            "text_safety_margin": text_safety_margin,
            # Dynamic font sizing
            "enable_dynamic_font_sizing": enable_dynamic_font_sizing,
            "min_font_size": min_font_size,
            "max_font_size": max_font_size,
            # Optional font paths
            "font_path": font_path or None,
            "emoji_font_path": emoji_font_path or None,
        }

        # Persist to the current resolved config path to honor per-test env overrides
        save_config(config, path=get_config_path())

        auto_startup = form.get("auto_startup") == "on"
        # Show loading page which triggers a restart request via JS
        return render_template("loading.html", auto_startup=auto_startup)

    # GET: render setup page
    cfg = load_config(get_config_path())
    return render_template(
        "setup.html",
        usb_devices=usb_devices,
        show_close=show_close,
        config=cfg,
        icons=get_available_icons(),
    )


@setup_bp.route("/restart", methods=["POST"])
def restart():
    """
    Exit the process after responding 204, allowing systemd to restart the service
    (or the user to manually re-run the app).
    Optionally installs the systemd unit if auto_startup is requested.
    """
    current_app.logger.info("POST /restart received; headers=%s", dict(request.headers))
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        data = None
    data = data or {}
    auto_startup = bool(data.get("auto_startup", False))

    if auto_startup:
        try:
            subprocess.run(["bash", "./install_service.sh"], capture_output=True, text=True, timeout=30, check=False)
        except Exception:
            # Non-fatal; continue with restart regardless of install outcome
            pass

    def _exit_soon():
        try:
            sleep(0.3)
        finally:
            # Exit with non-zero to ensure systemd treats this as a failure and
            # restarts the unit (Restart=on-failure).
            os._exit(1)

    threading.Thread(target=_exit_soon, daemon=True).start()
    return "", 204


@setup_bp.route("/setup_test_print", methods=["POST"])
def setup_test_print():
    """
    Queue a test print using form-provided config values without saving them.
    """
    current_app.logger.info(
        "POST /setup_test_print received: form_keys=%s files=%s",
        list(request.form.keys()),
        list(request.files.keys()),
    )
    form = request.form

    printer_type = form.get("printer_type", "usb")
    if printer_type == "usb":
        selected_usb = form.get("usb_device", "")
        if selected_usb and selected_usb != "manual":
            usb_vendor_id, usb_product_id = selected_usb.split(":")
        else:
            usb_vendor_id = form.get("usb_vendor_id", "0x04b8")
            usb_product_id = form.get("usb_product_id", "0x0e28")
    else:
        usb_vendor_id = form.get("usb_vendor_id", "0x04b8")
        usb_product_id = form.get("usb_product_id", "0x0e28")

    network_ip = form.get("network_ip", "")
    network_port = form.get("network_port", "9100")
    serial_port = form.get("serial_port", "")
    serial_baudrate = form.get("serial_baudrate", "19200")

    # Match width/font size selection used in setup(); prefer explicit width
    def _to_int(val, default):
        try:
            return int(val)
        except Exception:
            return default

    def _to_float(val, default):
        try:
            return float(val)
        except Exception:
            return default

    provided_width_raw = (form.get("receipt_width", "") or "").strip()
    provided_width = _to_int(provided_width_raw, 0) if provided_width_raw != "" else 0
    if provided_width > 0:
        receipt_width = max(280, min(1024, provided_width))
    else:
        receipt_width = 512
        if printer_type == "usb":
            if usb_vendor_id.lower() == "0x04b8":
                if usb_product_id.lower() in ["0x0e28", "0x0202", "0x020a", "0x0e15", "0x0e03"]:
                    receipt_width = 512
                else:
                    receipt_width = 576
    task_font_size = 72
    if receipt_width >= 576:
        task_font_size = 90
    elif receipt_width >= 512:
        task_font_size = 72
    else:
        task_font_size = 60

    config = {
        "printer_type": printer_type,
        "usb_vendor_id": usb_vendor_id,
        "usb_product_id": usb_product_id,
        "network_ip": network_ip,
        "network_port": network_port,
        "serial_port": serial_port,
        "serial_baudrate": serial_baudrate,
        "receipt_width": receipt_width,
        "task_font_size": task_font_size,
        # Pass-through flair layout tuning for setup test prints (optional)
        "flair_separator_width": _to_int(form.get("flair_separator_width", "3"), 3),
        "flair_separator_gap": _to_int(form.get("flair_separator_gap", "14"), 14),
        "flair_col_width": _to_int(form.get("flair_col_width", "256"), 256),
        "flair_target_height": _to_int(form.get("flair_target_height", "256"), 256),
        "flair_icon_scale_max": _to_float(form.get("flair_icon_scale_max", "2.0"), 2.0),
        "min_text_width": _to_int(
            form.get("min_text_width", str(max(180, int(receipt_width * 0.45)))),
            max(180, int(receipt_width * 0.45)),
        ),
    }

    try:
        ensure_worker()
        job_id = enqueue_test_print(config_override=config, origin="setup")
        flash(f"Setup Test Print queued. Job: {job_id}", "success")
    except Exception as e:
        flash(f"Error queuing setup test print: {e!s}", "error")

    return redirect(url_for("setup.setup"))
