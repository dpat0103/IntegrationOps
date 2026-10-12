"""Exercise API requests, probes, stored history, and incident transitions together."""

import httpx
import pytest


def test_full_monitoring_lifecycle(client, monkeypatch):
    from app.services import checker

    original_client = httpx.AsyncClient
    upstream = {"status": 200, "body": {"status": "healthy"}}

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(upstream["status"], json=upstream["body"])
        )
        return original_client(*args, **kwargs)

    monkeypatch.setattr(checker.httpx, "AsyncClient", make_client)
    response = client.post(
        "/api/integrations",
        json={
            "name": "Example service",
            "endpoint": "https://upstream.test/health",
            "expected_json_key": "status",
            "expected_json_value": "healthy",
        },
    )
    assert response.status_code == 201
    url = f"/api/integrations/{response.json()['id']}"
    assert client.post(url + "/check").json()["outcome"] == "HEALTHY"
    upstream["status"] = 503
    for number in range(3):
        result = client.post(url + "/check")
        assert result.status_code == 200
        assert result.json()["failure_type"] == "UPSTREAM_FAILURE"
        assert client.get("/api/overview").json()["active_incidents"] == (
            1 if number == 2 else 0
        )
    upstream["status"] = 200
    client.post(url + "/check")
    assert client.get("/api/overview").json()["active_incidents"] == 1
    client.post(url + "/check")
    assert client.get("/api/overview").json()["active_incidents"] == 0
    incident = client.get("/api/incidents").json()[0]
    assert incident["status"] == "RESOLVED"
    assert incident["resolved_at"] is not None
    assert len(client.get(url + "/checks").json()) == 6
    assert client.get("/api/overview").json()["availability_24h"] == 50
    assert client.patch(url, json={"active": False}).status_code == 200
    assert client.get("/api/status").json() == []
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get("/api/incidents").json() == []


@pytest.mark.parametrize(
    "exception,classification",
    [(httpx.ReadTimeout, "TIMEOUT"), (httpx.ConnectError, "NETWORK_ERROR")],
)
def test_network_failures_are_recorded_through_api(
    client, monkeypatch, exception, classification
):
    from app.services import checker

    original_client = httpx.AsyncClient

    def fail(request):
        raise exception("Simulated network failure", request=request)

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fail)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(checker.httpx, "AsyncClient", make_client)
    integration = client.post(
        "/api/integrations",
        json={"name": "Network test", "endpoint": "https://upstream.test/health"},
    ).json()
    response = client.post(f"/api/integrations/{integration['id']}/check")
    assert response.status_code == 200
    assert response.json()["outcome"] == "FAILED"
    assert response.json()["failure_type"] == classification
    assert len(client.get(f"/api/integrations/{integration['id']}/checks").json()) == 1
