#!/usr/bin/env python3
"""
Template validator for Task Printer.

Renders all Jinja2 templates with a minimal Flask app and synthetic context
so we can catch syntax/runtime errors (e.g., missing variables, bad macros)
without running the server.

Usage:
  python task-printer/scripts/validate_templates.py
  python task-printer/scripts/validate_templates.py --include 'index.html' --include 'setup.html'
  python task-printer/scripts/validate_templates.py --exclude '_components.html'
  python task-printer/scripts/validate_templates.py --fail-fast --verbose

Exit code:
  0  if all templates render successfully
  1  if one or more templates fail to render
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Tuple


def _repo_root() -> Path:
    # This script is saved at: task-printer/scripts/validate_templates.py
    # repo root is the parent of task-printer
    here = Path(__file__).resolve()
    return here.parents[2]  # .../<repo_root>


def _project_root() -> Path:
    # task-printer folder
    here = Path(__file__).resolve()
    return here.parents[1]


def _ensure_sys_path():
    """
    Ensure the project root (the directory containing 'task_printer') is on
    sys.path so `import task_printer` works regardless of where the script
    is run from.
    """
    # This script lives at: <repo>/task-printer/scripts/validate_templates.py
    # The project root (containing 'task_printer' package) is: <repo>/task-printer
    project_root = _project_root()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def _build_app():
    """
    Build a minimal Flask app via task_printer.create_app(register_worker=False).
    We rely on the app factory to wire template/static folders.
    """
    from task_printer import create_app

    # Avoid background threads and keep minimal setup
    app = create_app(config_overrides={}, register_worker=False)
    return app


def _list_templates(app, include_patterns: List[str], exclude_patterns: List[str]) -> List[str]:
    """
    List template names from the Jinja loader, respecting include/exclude patterns.
    """
    names = []
    for name in app.jinja_env.list_templates(filter_func=lambda x: x.endswith(".html")):
        # include rules (if provided)
        if include_patterns:
            if not any(fnmatch(name, pat) for pat in include_patterns):
                continue
        # exclude rules
        if exclude_patterns and any(fnmatch(name, pat) for pat in exclude_patterns):
            continue
        names.append(name)
    return sorted(names)


def _dummy_icons() -> List[Dict]:
    # Minimal icons for templates referencing icons + url_for('static', filename=ic.filename)
    return [
        {"name": "sample", "filename": "icons/sample.png"},
        {"name": "gear", "filename": "icons/gear.png"},
    ]


def _dummy_config() -> Dict:
    return {
        "printer_type": "usb",
        "printer_profile": "",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
        "receipt_width": 512,
        "cut_feed_lines": 2,
        "print_separators": True,
        # Flair defaults
        "flair_separator_width": 3,
        "flair_separator_gap": 14,
        "flair_col_width": 256,
        "flair_target_height": 256,
        "flair_icon_scale_max": 2.0,
        "min_text_width": 230,
    }


def _dummy_usb_devices() -> List[Dict]:
    return [
        {"vendor": "04b8", "product": "0e28", "desc": "Demo Epson TM", "is_printer": True},
        {"vendor": "1234", "product": "5678", "desc": "Other USB device", "is_printer": False},
    ]


def _dummy_jobs() -> List[Dict]:
    return [
        {
            "id": "deadbeefcafebabe12345678",
            "type": "print",
            "status": "queued",
            "created_at": "2025-01-01T10:00:00Z",
            "updated_at": "2025-01-01T10:00:00Z",
            "total": 1,
            "origin": "validator",
        },
        {
            "id": "abcd1234ef567890",
            "type": "print",
            "status": "success",
            "created_at": "2025-01-01T10:05:00Z",
            "updated_at": "2025-01-01T10:06:00Z",
            "total": 3,
            "origin": "validator",
        },
    ]


def _dummy_templates() -> List[Dict]:
    return [
        {
            "id": 1,
            "name": "Kitchen Chores",
            "notes": "Daily cleanup",
            "sections_count": 2,
            "tasks_count": 5,
            "updated_at": "2025-01-01 10:00",
            "created_at": "2025-01-01 09:50",
        },
        {
            "id": 2,
            "name": "Errands",
            "notes": "",
            "sections_count": 1,
            "tasks_count": 3,
            "updated_at": "2025-01-01 10:10",
            "created_at": "2025-01-01 10:00",
        },
    ]


def _csrf_token_stub():
    # Flask-WTF typically injects csrf_token() in templates; we can stub it.
    return "dummy-csrf-token"


def _default_context_for(name: str) -> Dict:
    """
    Provide a conservative, synthetic context that satisfies references
    used across templates. Add stubs for common helpers like csrf_token().
    """
    base = {
        "csrf_token": _csrf_token_stub,  # callable
    }

    if name == "index.html":
        base.update(
            {
                "job_id": "deadbeefcafebabe12345678",
                "icons": _dummy_icons(),
                # StrictUndefined guards
                "prefill_template": None,
                "default_tear_delay": 0,
            },
        )
    elif name == "setup.html":
        cfg = _dummy_config()
        # Provide extra keys accessed in setup.html under StrictUndefined
        cfg.setdefault("tear_feed_lines", cfg.get("cut_feed_lines", 2))
        cfg.setdefault("default_tear_delay_seconds", 0)
        cfg.setdefault("print_separators", True)
        # Margins used in setup form when StrictUndefined is enabled
        cfg.setdefault("print_left_margin", 0)
        cfg.setdefault("print_right_margin", 0)
        cfg.setdefault("print_top_margin", 0)
        cfg.setdefault("print_bottom_margin", 0)
        cfg.setdefault("text_safety_margin", 0)
        # Font and sizing defaults referenced in setup.html
        cfg.setdefault("min_font_size", 18)
        cfg.setdefault("max_font_size", 48)
        cfg.setdefault("enable_dynamic_font_sizing", True)
        cfg.setdefault("max_overflow_chars_for_dynamic_sizing", 3)
        cfg.setdefault("flair_separator_width", cfg.get("flair_separator_width", 3))
        cfg.setdefault("flair_separator_gap", cfg.get("flair_separator_gap", 14))
        cfg.setdefault("flair_col_width", cfg.get("flair_col_width", 256))
        cfg.setdefault("flair_target_height", cfg.get("flair_target_height", 256))
        cfg.setdefault("min_text_width", cfg.get("min_text_width", 230))
        # Network and Serial defaults for setup form
        cfg.setdefault("network_ip", "")
        cfg.setdefault("network_port", 9100)
        cfg.setdefault("serial_port", "/dev/ttyUSB0")
        cfg.setdefault("serial_baudrate", 19200)
        base.update(
            {
                "config": cfg,
                "usb_devices": _dummy_usb_devices(),
                "icons": _dummy_icons(),
                "show_close": True,
            },
        )
    elif name == "jobs.html":
        base.update({"jobs": _dummy_jobs()})
    elif name == "jobs_view.html":
        base.update(
            {
                "job": {
                    "id": "deadbeefcafebabe12345678",
                    "type": "tasks",
                    "status": "success",
                    "created_at": "2025-01-01T10:00:00Z",
                    "updated_at": "2025-01-01T10:05:00Z",
                    "total": 2,
                    "origin": "validator",
                    "options": {"tear_delay_seconds": 0},
                    "items": [
                        {
                            "position": 1,
                            "category": "Kitchen",
                            "task": "Wipe counters",
                            "flair_type": "icon",
                            "flair_value": "sample",
                            "assigned": "2025-01-02",
                            "due": "2025-01-03",
                            "priority": "H",
                            "assignee": "Aman",
                        },
                        {
                            "position": 2,
                            "category": "Kitchen",
                            "task": "Sweep floor",
                            "flair_type": "qr",
                            "flair_value": "https://example.com",
                        },
                    ],
                },
            },
        )
    elif name == "templates.html":
        base.update({"templates": _dummy_templates()})
    elif name == "loading.html":
        base.update({"auto_startup": True})
    elif name == "help.html":
        # Help page doesn't need special context beyond base
        pass
    else:
        # For other files (including base.html and _components.html), defaults are enough
        pass

    return base


def _render_template(app, template_name: str, verbose: bool = False) -> Tuple[bool, str]:
    """
    Try to render a template with the default context. Returns (ok, message).
    """
    ctx = _default_context_for(template_name)

    try:
        tmpl = app.jinja_env.get_template(template_name)
    except Exception as e:
        return False, f"load failed: {e!r}"

    # Use request context so url_for works in templates
    with app.test_request_context("/"):
        try:
            _ = tmpl.render(ctx)
            if verbose:
                return True, "rendered"
            return True, ""
        except Exception as e:
            return False, f"render failed: {e.__class__.__name__}: {e}"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Jinja templates by rendering them in a minimal Flask context.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob of template names to include (e.g., 'index.html' or 'setup*.html'). Can be repeated.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob of template names to exclude (e.g., '_components.html'). Can be repeated.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first error.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-template status messages.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Make sure we can import task_printer
    _ensure_sys_path()

    # Optionally run djlint (if installed) to lint templates before rendering
    try:
        templates_dir = _project_root() / "templates"
        djlint_bin = shutil.which("djlint")
        if djlint_bin and templates_dir.exists():
            cmd = [djlint_bin, str(templates_dir), "--profile=jinja"]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                print("[djlint] Lint failed:", file=sys.stderr)
                if proc.stdout:
                    print(proc.stdout.strip(), file=sys.stderr)
                if proc.stderr:
                    print(proc.stderr.strip(), file=sys.stderr)
                return 1
        else:
            # djlint not installed or templates dir missing; skip lint step
            pass
    except Exception as e:
        print(f"[djlint] Skipped due to error: {e}", file=sys.stderr)

    # Build app
    try:
        app = _build_app()
    except Exception as e:
        print(f"[fatal] Failed to create app: {e}", file=sys.stderr)
        return 1

    names = _list_templates(app, include_patterns=args.include, exclude_patterns=args.exclude)

    if not names:
        print("No templates found matching filters.")
        return 0

    total = 0
    failures: List[Tuple[str, str]] = []

    for name in names:
        ok, msg = _render_template(app, name, verbose=args.verbose)
        total += 1
        if ok:
            if args.verbose:
                print(f"[ok]   {name} {('- ' + msg) if msg else ''}")
        else:
            failures.append((name, msg))
            print(f"[fail] {name} - {msg}", file=sys.stderr)
            if args.fail_fast:
                break

    print()
    print("Summary:")
    print(f"  Total:    {total}")
    print(f"  Passed:   {total - len(failures)}")
    print(f"  Failed:   {len(failures)}")

    if failures:
        print()
        print("Failures:")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
