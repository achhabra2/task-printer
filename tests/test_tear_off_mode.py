import json
from typing import Any, Dict, List

import pytest

from task_printer import create_app
from task_printer.core.config import save_config


def _min_cfg() -> Dict[str, Any]:
    return {
        "printer_type": "usb",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
    }


def _get_csrf_token(client) -> str:
    resp = client.get("/")
    token = None
    set_cookies = resp.headers.getlist("Set-Cookie")
    for sc in set_cookies:
        if "csrf_token=" in sc:
            for seg in sc.split(";"):
                seg = seg.strip()
                if seg.startswith("csrf_token="):
                    token = seg.split("=", 1)[1]
                    break
        if token:
            break
    if not token:
        sc = resp.headers.get("Set-Cookie", "")
        for part in sc.split(","):
            if "csrf_token=" in part:
                for seg in part.split(";"):
                    seg = seg.strip()
                    if seg.startswith("csrf_token="):
                        token = seg.split("=", 1)[1]
                        break
            if token:
                break
    assert token, "Expected csrf_token cookie to be set by GET /"
    return token


def test_worker_tear_off_behavior(monkeypatch):
    from task_printer.printing import worker

    # Fake printer to capture calls
    class FakePrinter:
        def __init__(self):
            self.text_calls: List[str] = []
            self.cut_calls = 0
            self.images = 0

        def text(self, s: str):
            self.text_calls.append(s)

        def set(self, **kwargs):
            return None

        def image(self, img):
            self.images += 1

        def qr(self, data: str):
            return None

        def close(self):
            return None

        def cut(self):
            self.cut_calls += 1

    # Avoid real config/connection
    monkeypatch.setattr(worker, "load_config", lambda: _min_cfg())
    monkeypatch.setattr(worker, "_connect_printer", lambda cfg: FakePrinter())

    # Capture sleep calls
    sleeps: List[float] = []

    def _fake_sleep(x: float):
        sleeps.append(x)
        return None

    monkeypatch.setattr(worker.time, "sleep", _fake_sleep)

    items = [
        {"subtitle": "A", "task": "one"},
        {"subtitle": "B", "task": "two"},
        {"subtitle": "C", "task": "three"},
    ]

    # Tear-off enabled
    ok = worker.print_tasks(items, options={"tear_delay_seconds": 3})
    assert ok is True
    # No cuts, sleep between items (n-1 times)
    assert sleeps == [3, 3]

    # Reset and test default behavior
    sleeps.clear()
    ok = worker.print_tasks(items, options=None)
    assert ok is True
    # No sleeps in default mode
    assert sleeps == []


def test_index_route_parses_and_passes_delay(tmp_path, monkeypatch):
    # Minimal config to pass setup gate
    cfg_path = tmp_path / "cfg.json"
    save_config(_min_cfg(), path=str(cfg_path))
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Patch route-level worker functions
    captured: Dict[str, Any] = {}

    def _fake_ensure():
        return None

    def _fake_enqueue(payload, options=None):
        captured["payload"] = payload
        captured["options"] = options
        return "job-xyz"

    import task_printer.web.routes as routes

    monkeypatch.setattr(routes, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(routes, "enqueue_tasks", _fake_enqueue)

    csrf = _get_csrf_token(client)

    # Post with tear-off delay 2.5
    data = {
        "csrf_token": csrf,
        "subtitle_1": "Kitchen",
        "task_1_1": "Wipe",
        "tear_delay_seconds": "2.5",
    }
    r = client.post("/", data=data, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert captured.get("options", {}).get("tear_delay_seconds") == 2.5

    # Negative -> treated as 0 (no options)
    captured.clear()
    data["tear_delay_seconds"] = "-1"
    r = client.post("/", data=data, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert captured.get("options") in (None, {})

    # Over max -> clamped to 60
    captured.clear()
    data["tear_delay_seconds"] = "120"
    r = client.post("/", data=data, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert captured.get("options", {}).get("tear_delay_seconds") == 60.0


def test_templates_print_uses_global_default_and_index_prefills(tmp_path, monkeypatch):
    # Write config with a default tear delay
    cfg_path = tmp_path / "cfg.json"
    save_config({
        "printer_type": "usb",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
        "default_tear_delay_seconds": 4,
    }, path=str(cfg_path))
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Prefill index should include the default value in the input
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'name="tear_delay_seconds"' in html
    assert 'value="4"' in html

    # Create a template
    from task_printer.core import db as dbh
    with app.app_context():
        tid = dbh.create_template(
            "T1",
            None,
            [
                {"subtitle": "S", "tasks": [{"text": "A", "flair_type": "none"}]},
            ],
        )

    # Patch worker to capture options
    import task_printer.web.templates as tpl

    captured = {}

    def _fake_ensure():
        return None

    def _fake_enqueue(payload, options=None):
        captured["options"] = options
        return "job-1"

    monkeypatch.setattr(tpl.worker, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(tpl.worker, "enqueue_tasks", _fake_enqueue)

    csrf = _get_csrf_token(client)
    r = client.post(f"/templates/{tid}/print", data={"csrf_token": csrf})
    assert r.status_code in (302, 303)
    assert captured.get("options", {}).get("tear_delay_seconds") == 4


def test_setup_saves_default_tear_delay(tmp_path, monkeypatch):
    # Start with no config; go through setup to save one
    cfg_path = tmp_path / "cfg.json"
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Grab CSRF and POST setup with default tear delay
    csrf = _get_csrf_token(client)
    data = {
        "csrf_token": csrf,
        "printer_type": "usb",
        "usb_device": "manual",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
        "cut_feed_lines": "2",
        "print_separators": "on",
        "default_tear_delay_seconds": "7.5",
    }
    r = client.post("/setup", data=data)
    assert r.status_code == 200
    # Config should now be written with the default tear value
    from task_printer.core.config import load_config as _load

    cfg = _load(path=str(cfg_path))
    assert cfg is not None
    assert cfg.get("default_tear_delay_seconds") == 7.5
