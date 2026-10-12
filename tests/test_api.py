def test_create_list_and_overview(client):
    payload = {
        "name": "Example",
        "endpoint": "https://example.com/health",
        "expected_status": 200,
        "timeout_ms": 1000,
        "latency_threshold_ms": 500,
        "check_interval_seconds": 60,
    }
    r = client.post("/api/integrations", json=payload)
    assert r.status_code == 201
    integration_id = r.json()["id"]

    r = client.get("/api/integrations")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == integration_id

    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["total_integrations"] == 1
    assert body["active_incidents"] == 0


def test_simulator_state(client):
    r = client.post(
        "/api/simulator/state", json={"mode": "server_error", "delay_seconds": 1}
    )
    assert r.status_code == 200
    assert client.get("/api/simulator/state").json()["mode"] == "server_error"
    assert client.get("/simulator/status").status_code == 503


def test_duplicate_rename_returns_conflict_and_preserves_records(client):
    first = client.post(
        "/api/integrations", json={"name": "A", "endpoint": "https://example.com"}
    ).json()
    second = client.post(
        "/api/integrations", json={"name": "B", "endpoint": "https://example.com"}
    ).json()
    response = client.patch(
        f"/api/integrations/{second['id']}", json={"name": first["name"]}
    )
    assert response.status_code == 409
    assert client.get(f"/api/integrations/{second['id']}").json()["name"] == "B"


def test_required_fields_cannot_be_cleared_but_optional_fields_can(client):
    integration = client.post(
        "/api/integrations", json={"name": "A", "endpoint": "https://example.com"}
    ).json()
    url = f"/api/integrations/{integration['id']}"
    for field in (
        "name",
        "endpoint",
        "timeout_ms",
        "expected_status",
        "check_interval_seconds",
        "active",
    ):
        assert client.patch(url, json={field: None}).status_code == 422
    assert client.patch(url, json={"latency_threshold_ms": None}).status_code == 200
    assert client.get(url).json()["timeout_ms"] == 3000
