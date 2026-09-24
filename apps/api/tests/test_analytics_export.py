import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.analytics_events import AnalyticsEventRow, record_event
from app.analytics_export import ExportResult, export_events
from app.auth_repository import create_user
from app.worker import create_worker_app


def _seed(session: Session, count: int) -> None:
    user = create_user(session, uuid4(), f"u{uuid4().hex[:8]}", "hash")
    session.flush()
    for _ in range(count):
        record_event(session, "workflow_started", user.id, workflow_key=uuid4())
    session.commit()


def _unexported(factory: sessionmaker[Session]) -> int:
    with factory() as s:
        return s.scalar(
            select(func.count()).where(AnalyticsEventRow.exported_at.is_(None))
        )


def _client(factory, load: Callable[[list[dict[str, Any]]], None] | None):
    return TestClient(create_worker_app(session_factory=factory, analytics_load=load))


def test_marks_exported_only_after_successful_load(database_session, session_factory):
    _seed(database_session, 3)
    loaded: list[list[dict]] = []
    result = export_events(session_factory, loaded.append)
    assert (result.selected, result.loaded) == (3, 3)
    assert _unexported(session_factory) == 0
    row = loaded[0][0]
    assert set(row) == {
        "event_id", "event_name", "user_key", "workflow_key", "outcome",
        "occurred_at", "schema_version", "loaded_at",
    }
    assert isinstance(row["event_id"], str) and row["outcome"] is None


def test_load_failure_leaves_rows_for_retry(database_session, session_factory):
    _seed(database_session, 2)

    def boom(rows):
        raise TimeoutError("load timed out")

    with pytest.raises(TimeoutError):
        export_events(session_factory, boom)
    assert _unexported(session_factory) == 2
    retried: list[list[dict]] = []
    export_events(session_factory, retried.append)
    assert len(retried[0]) == 2 and _unexported(session_factory) == 0


def test_batch_limit(database_session, session_factory, monkeypatch):
    monkeypatch.setattr("app.analytics_export.EXPORT_BATCH_LIMIT", 2)
    _seed(database_session, 3)
    sizes: list[int] = []
    export_events(session_factory, lambda rows: sizes.append(len(rows)))
    assert sizes == [2] and _unexported(session_factory) == 1


def test_empty_outbox_skips_load_and_prunes_old_exported(
    database_session, session_factory
):
    _seed(database_session, 2)
    database_session.execute(
        update(AnalyticsEventRow).values(exported_at=func.now() - timedelta(days=31))
    )
    database_session.commit()
    calls: list = []
    result = export_events(session_factory, calls.append)
    assert calls == [] and result == ExportResult(selected=0, loaded=0, pruned=2)


def test_recent_exported_rows_are_kept(database_session, session_factory):
    _seed(database_session, 1)
    export_events(session_factory, lambda rows: None)
    assert export_events(session_factory, lambda rows: None).pruned == 0


def test_route_rejects_bad_bodies_and_methods(database_session, session_factory):
    del database_session
    with _client(session_factory, lambda rows: None) as client:
        assert client.post("/internal/analytics/export", json={"x": 1}).status_code == 422
        assert client.post("/internal/analytics/export").status_code == 422
        assert client.get("/internal/analytics/export").status_code == 405


def test_route_unconfigured_returns_503_and_loads_nothing(
    database_session, session_factory, monkeypatch
):
    monkeypatch.delenv("ANALYTICS_EVENTS_TABLE", raising=False)
    _seed(database_session, 1)
    with _client(session_factory, None) as client:
        assert client.post("/internal/analytics/export", json={}).status_code == 503
    assert _unexported(session_factory) == 1


def test_route_load_failure_returns_500_and_keeps_rows(database_session, session_factory):
    _seed(database_session, 2)

    def boom(rows):
        raise RuntimeError("bigquery said no: secret detail")

    with _client(session_factory, boom) as client:
        response = client.post("/internal/analytics/export", json={})
    assert response.status_code == 500
    assert "secret detail" not in response.text
    assert _unexported(session_factory) == 2


def test_route_success_reports_counts_and_logs_no_user_key(
    database_session, session_factory, capsys
):
    _seed(database_session, 2)
    with session_factory() as s:
        user_key = str(s.scalars(select(AnalyticsEventRow.user_key)).first())
    with _client(session_factory, lambda rows: None) as client:
        response = client.post("/internal/analytics/export", json={})
    assert response.status_code == 200
    assert response.json() == {"selected": 2, "loaded": 2, "pruned": 0}
    output = capsys.readouterr()
    lines = [
        json.loads(line)
        for line in (output.out + output.err).splitlines()
        if line.startswith("{")
    ]
    exports = [line for line in lines if line.get("event") == "analytics_export"]
    assert exports and exports[-1]["outcome"] == "success"
    assert exports[-1]["loaded"] == 2
    assert user_key not in output.out + output.err
