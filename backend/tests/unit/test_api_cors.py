"""CORS for the browser frontend. The SPA (Vite dev server, or the nginx
container) runs on a different origin than the API, so without these headers
the browser blocks every `fetch` before the request reaches an endpoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ALLOWED_ORIGIN = "http://localhost:5173"


def test_preflight_from_allowed_origin_is_accepted():
    response = client.options(
        "/api/chat",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_simple_request_from_allowed_origin_gets_cors_header():
    response = client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_unlisted_origin_gets_no_cors_header():
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers
