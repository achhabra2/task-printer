import json

from task_printer import create_app


def test_templates_api_crud_flow(tmp_path, monkeypatch):
    # Ensure in-memory DB is used by test app (no TASKPRINTER_DB_PATH set)
    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Create
    payload = {
        "name": "Morning Routine",
        "notes": "Daily checklist",
        "sections": [
            {
                "category": "Kitchen",
                "tasks": [
                    {"text": "Make coffee", "flair_type": "icon", "flair_value": "cooking"},
                ],
            }
        ],
    }
    r = client.post(
        "/api/v1/templates",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    tid = r.get_json()["id"]

    # Get
    r = client.get(f"/api/v1/templates/{tid}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "Morning Routine"
    assert body["sections"][0]["category"] == "Kitchen"

    # List
    r = client.get("/api/v1/templates")
    assert r.status_code == 200
    items = r.get_json()
    assert any(i["id"] == tid for i in items)

    # Update
    upd = {
        "name": "Morning Routine v2",
        "sections": [
            {
                "category": "Hall",
                "tasks": [
                    {"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"},
                ],
            }
        ],
    }
    r = client.put(
        f"/api/v1/templates/{tid}",
        data=json.dumps(upd),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.get_json().get("ok") is True

    r = client.get(f"/api/v1/templates/{tid}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "Morning Routine v2"
    assert body["sections"][0]["category"] == "Hall"

    # Delete
    r = client.delete(f"/api/v1/templates/{tid}")
    assert r.status_code == 200
    assert r.get_json().get("ok") is True
    r = client.get(f"/api/v1/templates/{tid}")
    assert r.status_code == 404


def test_templates_api_validation_errors(tmp_path):
    app = create_app(register_worker=False)
    app.config.update(TESTING=True)
    client = app.test_client()

    # Missing name
    bad = {"sections": [{"category": "A", "tasks": [{"text": "T"}]}]}
    r = client.post("/api/v1/templates", data=json.dumps(bad), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.get_json()

    # Too long QR
    long_qr = "x" * 600
    bad2 = {
        "name": "X",
        "sections": [{"category": "A", "tasks": [{"text": "T", "flair_type": "qr", "flair_value": long_qr}]}],
    }
    r = client.post("/api/v1/templates", data=json.dumps(bad2), headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert "error" in r.get_json()

