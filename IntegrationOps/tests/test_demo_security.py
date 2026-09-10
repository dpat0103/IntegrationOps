from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.models import Integration
from app.main import create_app
from app.services.orchestrator import DEMO_INTEGRATION_NAME, _allow_private_for_integration


def test_demo_mode_does_not_enable_arbitrary_private_targets(client):
    response = client.post(
        "/api/integrations",
        json={"name": "private-target", "endpoint": "http://127.0.0.1:9999/health"},
    )
    assert response.status_code == 422
    assert "Private" in response.json()["detail"]


def test_server_created_demo_uses_configured_worker_reachable_url(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        scheduler_enabled=False,
        demo_mode=True,
        demo_integration_url="http://api:8000/simulator/status",
        allow_private_endpoints=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/demo/integration")
        assert response.status_code == 200
        assert response.json()["name"] == DEMO_INTEGRATION_NAME
        assert response.json()["endpoint"] == "http://api:8000/simulator/status"


def test_only_exact_server_demo_gets_private_network_exception():
    real_demo = Integration(name=DEMO_INTEGRATION_NAME, endpoint="http://api:8000/simulator/status")
    impostor = Integration(name="Anything Else", endpoint="http://api:8000/simulator/status")
    stale_demo = Integration(name=DEMO_INTEGRATION_NAME, endpoint="http://localhost:8000/simulator/status")

    assert _allow_private_for_integration(
        real_demo,
        allow_private_endpoints=False,
        demo_mode=True,
        demo_integration_url="http://api:8000/simulator/status",
    )
    assert not _allow_private_for_integration(
        impostor,
        allow_private_endpoints=False,
        demo_mode=True,
        demo_integration_url="http://api:8000/simulator/status",
    )
    assert not _allow_private_for_integration(
        stale_demo,
        allow_private_endpoints=False,
        demo_mode=True,
        demo_integration_url="http://api:8000/simulator/status",
    )


def test_public_demo_blocks_general_writes_but_allows_demo_seed(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'public.db'}",
        scheduler_enabled=False,
        demo_mode=True,
        public_write_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        blocked = client.post(
            "/api/integrations",
            json={"name": "Example", "endpoint": "https://example.com/health"},
        )
        assert blocked.status_code == 403
        assert client.post("/api/demo/integration").status_code == 200


def test_demo_routes_are_hidden_when_demo_mode_is_off(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'prod.db'}",
        scheduler_enabled=False,
        demo_mode=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/api/demo/integration").status_code == 404
        assert client.get("/api/simulator/state").status_code == 404
        assert client.get("/simulator/status").status_code == 404
