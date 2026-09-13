from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        scheduler_enabled=False,
        task_mode="local",
        failure_threshold=3,
        recovery_threshold=2,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
