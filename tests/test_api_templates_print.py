import json
from typing import Any, Dict

from task_printer import create_app
from uuid import uuid4
from task_printer.core import db as dbh
from task_printer.core.config import save_config


def _create_template(app, name: str | None = None) -> int:
    with app.app_context():
        tpl_name = name or f"T_API_{uuid4().hex[:8]}"
        return dbh.create_template(
            tpl_name,
            None,
            [
                {"category": "S", "tasks": [{"text": "A", "flair_type": "none"}]},
            ],
        )


def test_api_print_template_with_options(monkeypatch):
    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    tid = _create_template(app)

    captured: Dict[str, Any] = {}

    def _fake_ensure():
        return None

    def _fake_enqueue(payload, options=None):
        captured["options"] = options
        return "job-tpl-1"

    import task_printer.web.api_templates as api_tpl

    monkeypatch.setattr(api_tpl.worker, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(api_tpl.worker, "enqueue_tasks", _fake_enqueue)

    r = client.post(
        f"/api/v1/templates/{tid}/print",
        data=json.dumps({"options": {"tear_delay_seconds": 3.5}}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["job_id"] == "job-tpl-1"
    assert captured.get("options", {}).get("tear_delay_seconds") == 3.5


def test_api_print_template_uses_global_default(tmp_path, monkeypatch):
    # Write config with a default tear delay
    cfg_path = tmp_path / "cfg.json"
    save_config(
        {
            "printer_type": "usb",
            "usb_vendor_id": "0x04b8",
            "usb_product_id": "0x0e28",
            "default_tear_delay_seconds": 4,
        },
        path=str(cfg_path),
    )

    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    tid = _create_template(app)

    captured: Dict[str, Any] = {}

    def _fake_ensure():
        return None

    def _fake_enqueue(payload, options=None):
        captured["options"] = options
        return "job-tpl-2"

    import task_printer.web.api_templates as api_tpl

    monkeypatch.setattr(api_tpl.worker, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(api_tpl.worker, "enqueue_tasks", _fake_enqueue)

    r = client.post(f"/api/v1/templates/{tid}/print", data=json.dumps({}), headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.get_json()["job_id"] == "job-tpl-2"
    assert captured.get("options", {}).get("tear_delay_seconds") == 4


def test_api_print_template_not_found():
    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    r = client.post("/api/v1/templates/999/print", data=json.dumps({}), headers={"Content-Type": "application/json"})
    assert r.status_code == 404
