"""Focused checks for the Phase 12 isolated E2E harness."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import pytest

from e2e.support import validated_database_url

E2E_URL = "postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "sqlite:///todo_e2e",
        "postgresql+psycopg://todo:todo@127.0.0.1:5432/todo",
        "postgresql+psycopg://todo_test:todo_test@127.0.0.1:5433/todo_test",
        "postgresql+psycopg://todo_e2e:x@db.example:5432/todo_e2e",
        "postgresql+psycopg://todo_e2e:x@localhost/todo_e2e?options=x",
    ],
)
def test_rejects_unsafe_target(value):
    with pytest.raises(ValueError):
        validated_database_url(value)


def test_accepts_loopback_e2e_target():
    url = validated_database_url(
        "postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e"
    )
    assert "todo_e2e" in url


def test_fixture_callables_are_deterministic_without_providers(monkeypatch):
    """The fixtures must not delegate to the real provider functions."""
    import app.agent
    import app.suggestion_provider
    from app.suggestion_service import Clarification
    from e2e.support import choice, suggestions

    def _fail(*args, **kwargs):
        raise AssertionError("real provider must not be called")

    monkeypatch.setattr(app.suggestion_provider, "request_todo_suggestions", _fail)
    monkeypatch.setattr(app.agent, "choose_clarification", _fail)

    async def _run():
        titles = await suggestions("Prepare weekend", None)
        field = await choice("Prepare weekend", None)
        clarified = await suggestions(
            "Prepare weekend",
            None,
            clarification=Clarification(
                field="constraints", value="Use supplies already available"
            ),
        )
        return titles, field, clarified

    titles, field, clarified = asyncio.run(_run())
    assert titles == ("Gather supplies", "Prepare workspace", "Complete the task")
    assert field == "constraints"
    assert clarified == titles


def test_fixture_rejects_unexpected_clarification():
    from app.suggestion_service import Clarification
    from e2e.support import suggestions

    async def _run():
        await suggestions(
            "Prepare weekend",
            None,
            clarification=Clarification(field="budget", value="100"),
        )

    with pytest.raises(ValueError):
        asyncio.run(_run())


def test_prepare_refuses_wrong_database_without_migrating(monkeypatch):
    """A current_database() mismatch must fail before Alembic runs."""
    from e2e import support

    upgraded: list[bool] = []
    monkeypatch.setattr(
        support.command, "upgrade", lambda *args, **kwargs: upgraded.append(True)
    )

    class _Result:
        def scalar_one(self):
            return "todo"

    class _Connection:
        def execute(self, statement):
            del statement
            return _Result()

    class _Transaction:
        def __enter__(self):
            return _Connection()

        def __exit__(self, *args):
            return False

    class _Engine:
        def begin(self):
            return _Transaction()

        def dispose(self):
            pass

    monkeypatch.setattr(support, "create_database_engine", lambda url: _Engine())
    with pytest.raises(ValueError):
        support.prepare_database(E2E_URL)
    assert upgraded == []


def test_seed_prints_single_credentials_line(monkeypatch, capsys):
    from e2e import support

    class _Response:
        status_code = 201

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, json=None):
            assert path == "/auth/signup"
            return _Response()

    monkeypatch.setattr(support.httpx, "Client", _Client)
    monkeypatch.setenv("E2E_DATABASE_URL", E2E_URL)
    assert support.main(["seed", "--prefix", "web"]) == 0
    out, _ = capsys.readouterr()
    lines = out.splitlines()
    assert len(lines) == 1
    assert set(json.loads(lines[0])) == {"username", "password"}


def test_assert_todos_rejects_duplicate_rows(monkeypatch, capsys):
    """An extra persisted row must fail through cardinality."""
    from e2e import support

    class _Login:
        status_code = 200

        def json(self):
            return {"token": "synthetic"}

    class _Todos:
        status_code = 200

        def json(self):
            return [
                {"title": "Pack bag", "completed": False},
                {"title": "Pack bag", "completed": False},
            ]

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, json=None):
            assert path == "/auth/login"
            return _Login()

        def get(self, path, headers=None):
            assert path == "/todos"
            return _Todos()

    monkeypatch.setattr(support.httpx, "Client", _Client)
    monkeypatch.setenv("E2E_USERNAME", "web-user")
    monkeypatch.setenv("E2E_PASSWORD", "synthetic-password")
    assert (
        support.main(
            [
                "assert-todos",
                "--expected",
                '[{"title": "Pack bag", "completed": false}]',
            ]
        )
        == 1
    )
    _, err = capsys.readouterr()
    assert "mismatch" in err


def test_lifespan_disposes_engine_on_error(monkeypatch):
    """The owned engine is disposed even when lifespan body raises."""
    monkeypatch.setenv("E2E_DATABASE_URL", E2E_URL)
    import e2e.app as e2e_app

    class _Engine:
        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

    engine = _Engine()
    monkeypatch.setattr(e2e_app, "_engine", engine)

    @asynccontextmanager
    async def _inner(app_):
        del app_
        yield

    monkeypatch.setattr(e2e_app, "_e2e_lifespan", _inner)

    async def _run():
        with pytest.raises(RuntimeError, match="boom"):
            async with e2e_app._lifespan_with_e2e_engine(None):
                raise RuntimeError("boom")

    asyncio.run(_run())
    assert engine.disposed is True


def _ingress_http_scope():
    return {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [
            (b"authorization", b"Bearer secret-token"),
            (b"content-type", b"application/json"),
        ],
    }


async def _run_ingress_middleware(middleware, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def test_ingress_middleware_emits_start_and_end(monkeypatch, caplog):
    """A trivial inner app yields matching start/end lines with valid timing."""
    monkeypatch.setenv("E2E_DATABASE_URL", E2E_URL)
    import e2e.app as e2e_app

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    with caplog.at_level(logging.INFO, logger="e2e.ingress"):
        sent = asyncio.run(
            _run_ingress_middleware(
                e2e_app._IngressTimingMiddleware(inner), _ingress_http_scope()
            )
        )

    assert [message["type"] for message in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 2
    assert lines[0].startswith("e2e-ingress start method=POST path=/auth/login t=")
    assert "status=200" in lines[1]
    assert lines[1].startswith("e2e-ingress end method=POST path=/auth/login ")
    elapsed = float(lines[1].rsplit("dt=", 1)[1])
    assert elapsed >= 0.0
    assert "secret-token" not in "\n".join(lines)


def test_slow_inner_app_still_emits_start(monkeypatch, caplog):
    """START is logged on receipt even when the handler stalls before responding."""
    monkeypatch.setenv("E2E_DATABASE_URL", E2E_URL)
    import e2e.app as e2e_app

    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_inner(scope, receive, send):
        entered.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def scenario():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            sent.append(message)

        middleware = e2e_app._IngressTimingMiddleware(slow_inner)
        task = asyncio.create_task(middleware(_ingress_http_scope(), receive, send))
        await asyncio.wait_for(entered.wait(), timeout=5)
        await asyncio.sleep(0)
        stalled_lines = [record.getMessage() for record in caplog.records]
        assert any(line.startswith("e2e-ingress start ") for line in stalled_lines)
        assert not any(line.startswith("e2e-ingress end ") for line in stalled_lines)
        release.set()
        await asyncio.wait_for(task, timeout=5)

    with caplog.at_level(logging.INFO, logger="e2e.ingress"):
        asyncio.run(scenario())

    lines = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("e2e-ingress end ") for line in lines)
