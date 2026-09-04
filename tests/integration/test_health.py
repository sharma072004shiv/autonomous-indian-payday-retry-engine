"""
tests/integration/test_health.py
─────────────────────────────────
Integration test: FastAPI app starts cleanly and /health returns 200.

This is the scaffold-level smoke test.  It verifies that:
  - The app factory (create_app) runs without import errors
  - The /health endpoint responds with status "ok"
  - The response contains the expected fields
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Set env vars BEFORE any app module is imported so pydantic-settings reads them.
os.environ["APP_ENV"] = "test"
os.environ["LLM_USE_MOCK"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"

from app.config import get_settings  # noqa: E402
from app.main import create_app       # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Clear the lru_cache so the test env vars above take effect.
    get_settings.cache_clear()
    application = create_app()
    with TestClient(application, raise_server_exceptions=True) as c:
        yield c
    # Restore cache after the module so other tests aren't affected.
    get_settings.cache_clear()


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_structure(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["service"] == "payday-retry-engine"
    assert data["version"] == "0.1.0"
    assert "env" in data
    assert "llm_use_mock" in data


def test_health_env_is_test(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["env"] == "test"


def test_health_llm_use_mock_is_true(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["llm_use_mock"] is True


def test_docs_endpoint_reachable(client: TestClient) -> None:
    """OpenAPI docs must be served (important for Buildathon demo)."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_json_reachable(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Autonomous Indian PayDay & Mandate Retry Engine"
