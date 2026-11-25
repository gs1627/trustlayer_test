from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app


def test_root_endpoint(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "TRUSTLAYER Backend"
    assert payload["docs"] == "/docs"
    assert payload["health"] == "/api/v1/health"


def test_health_endpoint_reports_missing_detectif_key_without_crashing(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["detectif_configured"] is False


def test_health_endpoint_reports_detectif_configured_when_key_present(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setenv("DETECTIF_API_KEY", "test-placeholder-value")
    get_settings.cache_clear()

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "connected"
    assert payload["detectif_configured"] is True


def test_health_endpoint_reports_degraded_when_database_unavailable(client: TestClient):
    class FailingSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("Simulated database outage")

    async def override_failing_db():
        yield FailingSession()

    app.dependency_overrides[get_db] = override_failing_db
    try:
        response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "unavailable"


def test_swagger_docs_and_openapi_available(client: TestClient):
    docs_response = client.get("/docs")
    assert docs_response.status_code == 200

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    paths = openapi_response.json().get("paths", {})
    assert "/api/v1/health" in paths
