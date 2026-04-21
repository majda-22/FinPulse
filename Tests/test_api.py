from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

import main as api_main
from app.api.v1.endpoints import health


class _FakeDb:
    def execute(self, _statement):
        return 1


@contextmanager
def _fake_get_db():
    yield _FakeDb()


def test_health_routes(monkeypatch):
    monkeypatch.setattr(api_main, "check_connection", lambda: True)
    monkeypatch.setattr(health, "get_db", _fake_get_db)

    with TestClient(api_main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "db": "connected",
            "version": "1.0.0",
        }

        api_response = client.get("/api/v1/health")
        assert api_response.status_code == 200
        assert api_response.json()["db"] == "connected"


def test_openapi_registers_expected_paths():
    schema = api_main.app.openapi()

    assert "/health" in schema["paths"]
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/score/{ticker}" in schema["paths"]
    assert "/api/v1/signals/{ticker}" in schema["paths"]
    assert "/api/v1/signals/{ticker}/history" in schema["paths"]
    assert "/api/v1/filings/{ticker}" in schema["paths"]
    assert "/api/v1/embeddings/{ticker}" in schema["paths"]
    assert "/api/v1/embeddings/{ticker}/latest" in schema["paths"]
