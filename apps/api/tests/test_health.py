from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_exact_contract() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_allows_documented_expo_web_origin() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_health_does_not_allow_unlisted_origin() -> None:
    response = client.get(
        "/health", headers={"Origin": "http://localhost:9999"}
    )

    assert "access-control-allow-origin" not in response.headers
