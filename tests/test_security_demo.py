import asyncio
import socket
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.models import Integration
from app.core.security import (
    CredentialError,
    PublicNetworkBackend,
    UnsafeTarget,
    decrypted_headers,
    encrypted_headers,
    validate_url,
)
from app.main import create_app
from app.services.checker import probe_integration


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://localhost",
        "http://foo.localhost",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://[fe80::1]",
        "http://100.64.0.1",
        "file:///etc/passwd",
        "https://example.com/?token=private",
        "https://example.com/#fragment",
        "http://user:password@example.com",
    ],
)
def test_restricted_targets_are_rejected(url):
    with pytest.raises(UnsafeTarget):
        validate_url(url)


@pytest.mark.asyncio
async def test_dns_is_validated_and_connection_uses_pinned_ip(monkeypatch):
    backend = PublicNetworkBackend()
    addresses = ["93.184.216.34"]
    connected = []

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in addresses
        ]

    async def connect(host, port, *args, **kwargs):
        connected.append(host)
        return object()

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    await backend.connect_tcp("provider.example", 443, timeout=1)
    assert connected == ["93.184.216.34"]
    addresses[:] = ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(UnsafeTarget):
        await backend.connect_tcp("provider.example", 443, timeout=1)
    assert connected == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_body_is_bounded():
    service = Integration(
        name="A",
        endpoint="https://provider.test",
        method="GET",
        expected_status=200,
        timeout_ms=1000,
        latency_threshold_ms=500,
        expected_json_key="status",
    )
    calls = []

    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    result = await probe_integration(service, httpx.MockTransport(redirect))
    assert result.outcome == "FAILED" and len(calls) == 1
    result = await probe_integration(
        service,
        httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 70000)),
    )
    assert result.failure_type == "RESPONSE_VALIDATION_FAILURE"


def test_headers_are_encrypted_and_wrong_key_fails_closed():
    settings = Settings(integration_secret_key=Fernet.generate_key().decode())
    stored = encrypted_headers({"Authorization": "Bearer private-value"}, settings)
    assert "private-value" not in stored
    assert decrypted_headers(stored, settings) == {
        "Authorization": "Bearer private-value"
    }
    with pytest.raises(CredentialError):
        decrypted_headers(
            stored, Settings(integration_secret_key=Fernet.generate_key().decode())
        )
    with pytest.raises(CredentialError):
        decrypted_headers('{"Authorization":"legacy"}', settings)


def test_public_demo_is_isolated_and_cannot_configure_real_targets(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'demo.db'}",
            scheduler_enabled=False,
            operator_token="operator",
            demo_session_secret="stable-test-secret",
        )
    )
    with TestClient(app) as first, TestClient(app) as second:
        examples = first.post("/api/demo").json()
        assert len(examples) == 3
        payment = next(item for item in examples if item["demo_key"] == "payment")
        assert (
            first.post(
                "/api/integrations",
                json={"name": "bad", "endpoint": "http://127.0.0.1"},
            ).status_code
            == 401
        )
        assert (
            first.patch(
                f"/api/integrations/{payment['id']}",
                json={"endpoint": "https://example.com"},
            ).status_code
            == 401
        )
        assert second.get(f"/api/integrations/{payment['id']}").status_code == 404
        assert (
            second.get(f"/api/integrations/{payment['id']}/checks").status_code == 404
        )
        assert (
            second.post(f"/api/integrations/{payment['id']}/check").status_code == 404
        )
        assert second.get("/api/status").json() == []
        other = second.post("/api/demo").json()
        assert {item["id"] for item in other}.isdisjoint(
            item["id"] for item in examples
        )
        assert (
            first.post(
                "/api/demo/scenario",
                json={"service": "payment", "mode": "server_error"},
            ).status_code
            == 200
        )
        result = first.post(f"/api/integrations/{payment['id']}/check").json()
        assert result["failure_type"] == "UPSTREAM_FAILURE"
        other_payment = next(item for item in other if item["demo_key"] == "payment")
        assert (
            second.post(f"/api/integrations/{other_payment['id']}/check").json()[
                "outcome"
            ]
            == "HEALTHY"
        )
        assert (
            first.post(
                "/api/demo/scenario",
                json={"service": "payment", "mode": "healthy"},
                headers={"Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )
        assert first.get("/about").status_code == 200
        assert "default-src 'self'" in first.get("/").headers["content-security-policy"]


def test_demo_action_limit_is_enforced(client):
    from app.services.limits import demo_budget
    from fastapi import HTTPException

    with client.app.state.session_factory() as session:
        demo_budget(session, "budget-test", limit=2)
        demo_budget(session, "budget-test", limit=2)
        with pytest.raises(HTTPException) as exc:
            demo_budget(session, "budget-test", limit=2)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_demo_timeout_is_a_recorded_failure(client):
    client.headers.clear()
    service = next(
        item
        for item in client.post("/api/demo").json()
        if item["demo_key"] == "payment"
    )
    assert (
        client.post(
            "/api/demo/scenario", json={"service": "payment", "mode": "timeout"}
        ).status_code
        == 200
    )
    result = client.post(f"/api/integrations/{service['id']}/check").json()
    assert result["failure_type"] == "TIMEOUT"


def test_scenario_cannot_change_under_a_pending_probe(client):
    from app.core.models import DemoState
    from app.services.jobs import reserve_run

    client.headers.clear()
    payment = next(
        item
        for item in client.post("/api/demo").json()
        if item["demo_key"] == "payment"
    )
    with client.app.state.session_factory() as session:
        reserve_run(session, payment["id"], client.app.state.settings, scheduled=True)
    response = client.post(
        "/api/demo/scenario", json={"service": "payment", "mode": "server_error"}
    )
    assert response.status_code == 409
    assert "current check" in response.json()["detail"]
    with client.app.state.session_factory() as session:
        service = session.get(Integration, payment["id"])
        assert session.get(DemoState, (service.demo_owner, "payment")).mode == "healthy"


def test_operator_auth_is_documented_and_scheme_is_case_insensitive(client):
    response = client.post(
        "/api/integrations",
        json={"name": "Auth check", "endpoint": "https://example.com"},
        headers={"Authorization": "bearer test-operator-token"},
    )
    assert response.status_code == 201
    schema = client.get("/openapi.json").json()
    assert (
        schema["components"]["securitySchemes"]["OperatorBearer"]["scheme"] == "bearer"
    )
