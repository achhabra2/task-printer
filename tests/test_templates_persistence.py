import json
from typing import Dict, List

import pytest

from task_printer import create_app
from task_printer.core.config import save_config


def _make_min_config() -> Dict[str, str]:
    # Minimal config so /setup gating allows app routes
    return {
        "printer_type": "usb",
        "usb_vendor_id": "0x04b8",
        "usb_product_id": "0x0e28",
        # Other fields are optional for non-print routes
    }


def _get_csrf_token(client) -> str:
    # Trigger a GET so the app's after_request sets the csrf_token cookie
    resp = client.get("/")
    token = None

    # Prefer parsing from all Set-Cookie headers
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

    # Fallback to single Set-Cookie header if getlist isn't available/populated
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


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Route gating requires a config to exist; write it to a temp path
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("TASKPRINTER_CONFIG_PATH", str(cfg_path))
    save_config(_make_min_config(), path=str(cfg_path))

    # Point DB to a temp file for isolation
    db_path = tmp_path / "data.db"
    monkeypatch.setenv("TASKPRINTER_DB_PATH", str(db_path))

    # Create app without starting background worker
    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_db_crud_and_counts(tmp_path, monkeypatch, app):
    # Use the DB helpers directly within an app context
    from task_printer.core import db as dbh

    db_path = tmp_path / "unit.db"
    monkeypatch.setenv("TASKPRINTER_DB_PATH", str(db_path))

    with app.app_context():
        # Fresh connection for this path
        conn = dbh.get_db()
        assert conn is not None

        # Create a template with 2 sections and a few tasks (with flair)
        sections: List[dict] = [
            {
                "category": "Kitchen",
                "tasks": [{"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning"}],
            },
            {
                "category": "Living",
                "tasks": [
                    {"text": "Vacuum", "flair_type": "qr", "flair_value": "qr:vacuum"},
                    {"text": "Dust shelves", "flair_type": "none"},
                ],
            },
        ]
        tid = dbh.create_template("Morning", "Daily routine", sections)
        assert isinstance(tid, int)

        # Get the template and verify structure/order
        t = dbh.get_template(tid)
        assert t is not None
        assert t["name"] == "Morning"
        assert len(t["sections"]) == 2
        assert t["sections"][0]["category"] == "Kitchen"
        assert [tk["text"] for tk in t["sections"][1]["tasks"]] == ["Vacuum", "Dust shelves"]

        # List templates and check counts
        items = dbh.list_templates()
        assert any(i["id"] == tid and i["sections_count"] == 2 and i["tasks_count"] == 3 for i in items)

        # Update: rename and swap tasks order in section 2
        new_sections = [
            {
                "category": "Kitchen",
                "tasks": [{"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning"}],
            },
            {
                "category": "Living",
                "tasks": [
                    {"text": "Dust shelves", "flair_type": "none"},
                    {"text": "Vacuum", "flair_type": "qr", "flair_value": "qr:vacuum"},
                ],
            },
        ]
        ok = dbh.update_template(tid, "Morning Updated", "notes2", new_sections)
        assert ok is True

        t2 = dbh.get_template(tid)
        assert t2 is not None and t2["name"] == "Morning Updated"
        assert [tk["text"] for tk in t2["sections"][1]["tasks"]] == ["Dust shelves", "Vacuum"]

        # Duplicate -> name collision should auto-suffix
        dup_id = dbh.duplicate_template(tid)
        assert isinstance(dup_id, int)
        dup = dbh.get_template(dup_id)
        assert dup is not None and dup["name"].startswith("Morning Updated")

        # Delete both
        assert dbh.delete_template(dup_id) is True
        assert dbh.get_template(dup_id) is None
        assert dbh.delete_template(tid) is True
        assert dbh.get_template(tid) is None

        # Close DB to avoid leaks between tests
        dbh.close_db()


def test_routes_templates_crud_and_print_flow(app, client, monkeypatch):
    # Patch worker so printing doesn't require a real printer/worker thread
    monkeypatch.setenv("TASKPRINTER_JSON_LOGS", "false")
    monkeypatch.setenv("TASKPRINTER_JOBS_MAX", "10")
    monkeypatch.setenv("TASKPRINTER_MAX_CONTENT_LENGTH", "1048576")

    job_ids = []

    def _fake_ensure():
        return None

    def _fake_enqueue(payload):
        # Basic expectations: payload is list of dicts with keys
        assert isinstance(payload, list)
        if payload:
            assert "task" in payload[0]
        jid = f"job-{len(job_ids) + 1:03d}"
        job_ids.append(jid)
        return jid

    from task_printer.printing import worker

    monkeypatch.setattr(worker, "ensure_worker", _fake_ensure)
    monkeypatch.setattr(worker, "enqueue_tasks", _fake_enqueue)

    csrf = _get_csrf_token(client)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": csrf,
    }

    # Create template via JSON
    create_payload = {
        "name": "Weekday Morning",
        "notes": "Daily morning routine",
        "sections": [
            {
                "category": "Kitchen",
                "tasks": [
                    {"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning"},
                    {"text": "Run dishwasher", "flair_type": "none"},
                ],
            },
            {"category": "Hall", "tasks": [{"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"}]},
        ],
    }
    r = client.post("/templates", data=json.dumps(create_payload), headers=headers)
    assert r.status_code == 201, r.get_data(as_text=True)
    tid = r.get_json()["id"]
    assert isinstance(tid, int)

    # Get the template (JSON)
    r = client.get(f"/templates/{tid}")
    assert r.status_code == 200
    t = r.get_json()
    assert t["name"] == "Weekday Morning"
    assert len(t["sections"]) == 2
    assert t["sections"][0]["category"] == "Kitchen"

    # List templates (request JSON)
    r = client.get("/templates", headers={"Accept": "application/json"})
    assert r.status_code == 200
    lst = r.get_json()
    assert any(item["id"] == tid for item in lst)

    # Update template via JSON
    update_payload = {
        "name": "Weekday Morning v2",
        "notes": "Updated",
        "sections": [
            {
                "category": "Kitchen",
                "tasks": [
                    {"text": "Run dishwasher", "flair_type": "none"},
                    {"text": "Wipe counter", "flair_type": "none"},
                ],
            },
            {"category": "Hall", "tasks": [{"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"}]},
        ],
    }
    r = client.post(f"/templates/{tid}/update", data=json.dumps(update_payload), headers=headers)
    assert r.status_code == 200
    assert r.get_json().get("ok") is True

    # Duplicate template
    r = client.post(
        f"/templates/{tid}/duplicate",
        data=json.dumps({"new_name": "Weekday Morning Copy"}),
        headers=headers,
    )
    assert r.status_code == 200
    dup_id = r.get_json()["id"]
    assert isinstance(dup_id, int) and dup_id != tid

    # Print duplicated template (uses patched worker)
    r = client.post(f"/templates/{dup_id}/print", headers=headers)
    assert r.status_code == 200
    assert r.get_json()["job_id"] == "job-001"

    # Delete both templates
    r = client.post(f"/templates/{dup_id}/delete", headers=headers)
    assert r.status_code == 200
    assert r.get_json().get("ok") is True
    r = client.post(f"/templates/{tid}/delete", headers=headers)
    assert r.status_code == 200
    assert r.get_json().get("ok") is True


def test_routes_validation_errors_and_not_found(app, client):
    csrf = _get_csrf_token(client)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": csrf,
    }

    # Missing name
    bad = {"name": "", "sections": [{"category": "A", "tasks": [{"text": "t"}]}]}
    r = client.post("/templates", data=json.dumps(bad), headers=headers)
    assert r.status_code == 400
    assert "error" in r.get_json()

    # Too long QR
    long_qr = "x" * 600
    payload = {
        "name": "Bad QR",
        "sections": [{"category": "S", "tasks": [{"text": "T", "flair_type": "qr", "flair_value": long_qr}]}],
    }
    r = client.post("/templates", data=json.dumps(payload), headers=headers)
    assert r.status_code == 400
    assert "error" in r.get_json()

    # Not found: get/update/delete
    r = client.get("/templates/999999")
    assert r.status_code == 404
    r = client.post(
        "/templates/999999/update",
        data=json.dumps({"name": "x", "sections": [{"category": "S", "tasks": [{"text": "T"}]}]}),
        headers=headers,
    )
    assert r.status_code == 404
    r = client.post("/templates/999999/delete", headers=headers)
    assert r.status_code == 404
