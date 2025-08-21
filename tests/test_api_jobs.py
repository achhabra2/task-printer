import json
from typing import Any, Dict, List

from task_printer import create_app
from task_printer.core.config import save_config


def _min_cfg() -> Dict[str, Any]:
    return {
        "printer_type": "usb",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
    }


def test_api_submit_job_success(tmp_path, monkeypatch):
    # Minimal config to pass setup gate
    cfg_path = tmp_path / "cfg.json"
    save_config(_min_cfg(), path=str(cfg_path))
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Patch worker helpers used by the API blueprint
    captured: Dict[str, Any] = {}

    def _fake_ensure():
        return None

    def _fake_enqueue(payload, options=None):
        # Validate payload shape roughly
        assert isinstance(payload, list) and len(payload) == 2
        assert payload[0]["category"] == "Kitchen"
        assert payload[0]["task"] == "Wipe counter"
        assert payload[1]["flair"]["type"] == "qr"
        captured["options"] = options
        return "job-abc"

    import task_printer.web.api as api

    monkeypatch.setattr(api, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(api, "enqueue_tasks", _fake_enqueue)

    payload = {
        "sections": [
            {
                "category": "Kitchen",
                "tasks": [
                    {"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning", "metadata": {"assigned": "2024-01-01"}},
                ],
            },
            {
                "category": "Hall",
                "tasks": [
                    {"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"},
                ],
            },
        ],
        "options": {"tear_delay_seconds": 2.5},
    }

    r = client.post("/api/v1/jobs", data=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert r.status_code == 202, r.get_data(as_text=True)
    body = r.get_json()
    assert body["id"] == "job-abc"
    assert body["status"] == "queued"
    assert "links" in body and "self" in body["links"]
    assert captured.get("options", {}).get("tear_delay_seconds") == 2.5


def test_api_submit_job_validation(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg.json"
    save_config(_min_cfg(), path=str(cfg_path))
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))

    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Missing sections
    r = client.post("/api/v1/jobs", data=json.dumps({}), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.get_json()

    # Bad QR length
    long_qr = "x" * 600
    payload = {
        "sections": [
            {"category": "S", "tasks": [{"text": "T", "flair_type": "qr", "flair_value": long_qr}]}
        ]
    }
    r = client.post("/api/v1/jobs", data=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.get_json()
