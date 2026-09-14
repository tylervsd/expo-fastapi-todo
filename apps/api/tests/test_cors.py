import json

import pytest
from fastapi.testclient import TestClient

from app.cors import LOCAL_ORIGIN, get_cors_origins
from app.main import create_app


@pytest.mark.parametrize(
    "origin",
    [
        "https://project.pages.dev",
        "https://trusted.example.pages.dev",
    ],
)
def test_configured_origin_preflight(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps([origin]))

    with TestClient(create_app()) as client:
        response = client.options(
            "/todos",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


def test_unset_configuration_preserves_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    assert get_cors_origins() == [LOCAL_ORIGIN]


def test_explicit_empty_array_denies_browser_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "[]")

    with TestClient(create_app()) as client:
        preflight = client.options(
            "/health",
            headers={
                "Origin": "https://project.pages.dev",
                "Access-Control-Request-Method": "GET",
            },
        )
        simple = client.get(
            "/health", headers={"Origin": "https://project.pages.dev"}
        )

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert simple.status_code == 200
    assert "access-control-allow-origin" not in simple.headers


def test_two_configured_origins_are_allowed_and_duplicates_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origins = ["https://one.pages.dev", "https://two.pages.dev", "https://one.pages.dev"]
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps(origins))

    assert get_cors_origins() == ["https://one.pages.dev", "https://two.pages.dev"]

    with TestClient(create_app()) as client:
        responses = [
            client.options(
                "/health",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                },
            )
            for origin in origins[:2]
        ]

    assert [response.status_code for response in responses] == [200, 200]
    assert [
        response.headers["access-control-allow-origin"] for response in responses
    ] == origins[:2]


@pytest.mark.parametrize(
    "origin",
    [
        LOCAL_ORIGIN,
        "https://unlisted.pages.dev",
        "https://project.pages.dev.evil.example",
    ],
)
def test_configured_hosted_origin_excludes_other_origins(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    configured = "https://project.pages.dev"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps([configured]))

    with TestClient(create_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_unlisted_origin_has_no_allow_origin_on_simple_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps(["https://project.pages.dev"]))

    with TestClient(create_app()) as client:
        response = client.get(
            "/health", headers={"Origin": "https://preview.pages.dev"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "access-control-allow-origin" not in response.headers


def test_non_cors_health_request_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "[]")

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "raw",
    [
        "[",
        json.dumps("https://project.pages.dev"),
        json.dumps({"origin": "https://project.pages.dev"}),
        json.dumps([1]),
        json.dumps(["*"]),
        json.dumps(["http://example.com"]),
        json.dumps(["https://user:pass@example.com"]),
        json.dumps(["https://example.com/path"]),
        json.dumps(["https://example.com/"]),
        json.dumps(["https://example.com?query=1"]),
        json.dumps(["https://example.com#fragment"]),
        json.dumps(["https://example .com"]),
        json.dumps(["https://example.com\\evil"]),
        json.dumps(["https://example.com:invalid"]),
        json.dumps([""]),
    ],
)
def test_invalid_configuration_raises_generic_value_error(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", raw)

    with pytest.raises(ValueError, match="^Invalid CORS_ALLOWED_ORIGINS configuration$") as exc_info:
        get_cors_origins()

    assert raw not in str(exc_info.value)


def test_configuration_is_read_when_each_app_is_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = "https://first.pages.dev"
    second = "https://second.pages.dev"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps([first]))
    first_app = create_app()
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps([second]))
    second_app = create_app()

    with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
        first_response = first_client.options(
            "/health",
            headers={"Origin": first, "Access-Control-Request-Method": "GET"},
        )
        second_response = second_client.options(
            "/health",
            headers={"Origin": second, "Access-Control-Request-Method": "GET"},
        )

    assert first_response.headers["access-control-allow-origin"] == first
    assert second_response.headers["access-control-allow-origin"] == second
