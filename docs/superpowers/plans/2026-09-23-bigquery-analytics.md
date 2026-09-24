# Phase 26 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transactional product events, a scheduled export to BigQuery, deduplicating metric views with written definitions, and a walkthrough with a duplicate drill and reconciliation.

**Architecture:** An `analytics_events` outbox row is written in the same transaction as each business change. A worker endpoint, called by Cloud Scheduler, batch-loads unexported rows into a partitioned raw BigQuery table and marks them exported only after the load succeeds. Curated views in a separate dataset deduplicate by `event_id` and define the metrics, and PostgreSQL reconciliation queries encode the same definitions against the source.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, the BigQuery Python client, Terraform 1.14.7 with Google provider 8.2.0, pytest, and `terraform test` with the mock provider.

**Spec:** [Phase 26 design](../specs/2026-09-23-bigquery-analytics-design.md)

## Global Constraints

- Event names: exactly `user_signed_up`, `workflow_started`, `workflow_completed`, `suggestion_finished`. Outcome: `ready`, `failed` or `expired`, present if and only if the event is `suggestion_finished`.
- No free-text columns anywhere in the pipeline. `user_key` = `users.public_id`, never the username, name or email.
- Export batch: 5000 rows. Outbox pruning: rows exported more than 30 days ago. Scheduler: every 15 minutes. Raw partition expiration: 400 days (34560000000 ms).
- **Load wait: 45 seconds** (the spec says 120). The worker's request timeout is 60s, so the load must finish inside it. The spec is amended in Task 6.
- Worker environment variable: `ANALYTICS_EVENTS_TABLE` = `project.analytics_raw.events`. If it's unset, the endpoint returns 503. A load failure returns 500.
- Datasets `analytics_raw` and `analytics`, in the app region. Views: `events_deduped`, `activation_funnel`, `suggestion_success`.
- Guide queries use `--maximum_bytes_billed=100000000`.
- One new Python dependency: `google-cloud-bigquery`, pinned with `==` to the version `uv` resolves, as with the existing Google clients. No new Terraform providers (the lockfile is read-only in CI).
- All BigQuery dataset grants use `google_bigquery_dataset_access`. Never mix it with `google_bigquery_dataset_iam_*` on the same dataset, because the provider warns that the two conflict.
- Keep `.pi/` and the untracked root `AGENTS.md` untouched. Use invented data only.
- Test commands:
  - `pnpm test:api` (needs `pnpm db:test:up`)
  - `pnpm lint:api`
  - `terraform -chdir=infra/terraform/sandbox init -backend=false -lockfile=readonly && terraform -chdir=infra/terraform/sandbox test`
  - `pnpm lint:markdown && pnpm lint:links`

## Review Focus

1. **Idempotent replays emit no event.** A replayed `start_workflow` request ID and a replayed `advance_workflow` action must not add a second event. Pinned in Task 1.
2. **A workflow action that doesn't complete adds no event.** For example, REVIEW → COLLECT_TASKS. Pinned in Task 1.
3. **Signup with a taken username** rolls back, so it leaves no `user_signed_up` event. Pinned in Task 1.
4. **An export with an empty outbox** makes no load call and still prunes. Pinned in Task 3.
5. **A load that raises after rows were selected** leaves every selected row unexported, and the next run retries the same rows. Pinned in Task 3.

---

### Task 1: Outbox table, `record_event`, and signup/workflow events

**Files:**

- Create: `apps/api/alembic/versions/2026092601_add_analytics_events.py`
- Create: `apps/api/app/analytics_events.py`
- Create: `apps/api/tests/test_analytics_events.py`
- Modify: `apps/api/tests/conftest.py` (add `analytics_events` to the TRUNCATE list)
- Modify: `apps/api/tests/test_persistence.py` (update `REVISION` to `"2026092601"`; add `"analytics_events"` to the sorted table list in `test_migration_creates_expected_todos_shape`)
- Modify: `apps/api/app/main.py` (`signup`, about line 644)
- Modify: `apps/api/app/workflow_service.py` (`start_workflow`, `advance_workflow`)

**Interfaces:**

- Produces:
  - `AnalyticsEventRow` (ORM, table `analytics_events`)
  - `EVENT_NAMES: frozenset[str]`
  - `record_event(session: Session, event_name: str, owner_id: int, *, workflow_key: UUID | None = None, outcome: str | None = None) -> None`

  The function adds a row to the caller's open transaction and never commits. It resolves `user_key` from `users.public_id` with a scalar subquery on `owner_id`, so callers pass the internal `owner_id` they already hold.

  *Ruling vs. the spec:* the spec's signature takes `user_key`. Taking `owner_id` avoids threading public IDs through every layer, and the stored column is the same.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_analytics_events.py`

```python
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.analytics_events import AnalyticsEventRow, record_event
from app.auth_repository import create_user
from app.workflow_service import advance_workflow, start_workflow


def _events(session_factory: sessionmaker[Session]) -> list[tuple[str, str | None]]:
    with session_factory() as s:
        return [
            (row.event_name, row.outcome)
            for row in s.scalars(select(AnalyticsEventRow).order_by(AnalyticsEventRow.id))
        ]


def test_record_event_resolves_user_key_and_defaults(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    record_event(database_session, "user_signed_up", user.id)
    database_session.commit()
    with session_factory() as s:
        row = s.scalars(select(AnalyticsEventRow)).one()
    assert row.user_key == user.public_id
    assert row.event_id is not None and row.schema_version == 1
    assert row.occurred_at is not None and row.exported_at is None


def test_event_is_absent_after_rollback(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.commit()
    record_event(database_session, "workflow_started", user.id, workflow_key=uuid4())
    database_session.rollback()
    assert _events(session_factory) == []


@pytest.mark.parametrize(
    ("name", "outcome"),
    [
        ("page_viewed", None),
        ("suggestion_finished", None),
        ("suggestion_finished", "superseded"),
        ("workflow_started", "ready"),
    ],
)
def test_database_rejects_invalid_events(
    database_session: Session, name: str, outcome: str | None
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.commit()
    with pytest.raises(IntegrityError):
        database_session.execute(
            text(
                "INSERT INTO analytics_events (event_id, event_name, user_key, outcome) "
                "VALUES (:id, :name, :key, :outcome)"
            ),
            {"id": uuid4(), "name": name, "key": user.public_id, "outcome": outcome},
        )
        database_session.flush()
```

Then add API-level tests that use the existing app test client fixture. Find its name with `grep -n "def client\|def auth_headers" apps/api/tests/conftest.py apps/api/tests/test_workflows.py`, and use the same fixtures as `test_workflows.py` for signup and starting and advancing a workflow. Required cases, each asserting `_events(...)` exactly:

```python
def test_signup_records_one_event_and_taken_username_records_none(client, session_factory):
    body = {"username": "analyst-a", "password": "correct horse battery"}
    assert client.post("/auth/signup", json=body).status_code == 201
    assert client.post("/auth/signup", json=body).status_code == 422
    assert _events(session_factory) == [("user_signed_up", None)]
```

- **`test_start_workflow_records_once_and_replay_records_nothing`:** call `start_workflow(session, owner_id, "Plan a party", request_id)` twice with the same `request_id`. Expect `[("workflow_started", None)]`, with `workflow_key` equal to the returned snapshot `id`.
- **`test_only_the_completing_action_records_workflow_completed`:** drive a workflow to `COMPLETED` using the same command sequence as the existing completion test in `tests/test_workflows.py`. Find it with `grep -n "COMPLETED" apps/api/tests/test_workflows.py`. Assert that exactly one `workflow_completed` event exists, and that it appears only after the final action, by checking the event list after each `advance_workflow` call. Then replay the final action with the same `request_id` and assert that the count is unchanged.

Import the workflow command classes the completion test needs from `app.workflow_domain`, exactly as `tests/test_workflows.py` does.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run --directory apps/api python -m pytest tests/test_analytics_events.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analytics_events'`.

- [ ] **Step 3: Write the migration** `apps/api/alembic/versions/2026092601_add_analytics_events.py`

```python
"""Phase 26: transactional analytics event outbox (no free-text columns)."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "2026092601"
down_revision = "2026092301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("user_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "schema_version", sa.SmallInteger(), server_default="1", nullable=False
        ),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_analytics_events_event_id"),
        sa.CheckConstraint(
            "event_name IN ('user_signed_up', 'workflow_started', "
            "'workflow_completed', 'suggestion_finished')",
            name="ck_analytics_events_name",
        ),
        sa.CheckConstraint(
            "(event_name = 'suggestion_finished') = "
            "(outcome IS NOT NULL AND outcome IN ('ready', 'failed', 'expired'))",
            name="ck_analytics_events_outcome",
        ),
    )
    op.create_index(
        "ix_analytics_events_unexported",
        "analytics_events",
        ["id"],
        postgresql_where=sa.text("exported_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_events_unexported", table_name="analytics_events")
    op.drop_table("analytics_events")
```

Also check the outcome constraint's NULL behavior. For `suggestion_finished` with a NULL outcome, the right side is `false`, so the comparison is `true = false`, which is `false`, and the row is rejected. For another event with a NULL outcome, it's `false = false`, which is `true`, and the row is accepted. The parametrized test covers both cases.

- [ ] **Step 4: Write** `apps/api/app/analytics_events.py`

```python
"""Phase 26 analytics outbox. Events commit with their business change.

Every column is an identifier, enum, timestamp or integer: no free text can
enter the pipeline. user_key is users.public_id (pseudonymous, not anonymous).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, Identity, SmallInteger, Text, select
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.auth_repository import UserRow
from app.database import Base

EVENT_NAMES = frozenset(
    {"user_signed_up", "workflow_started", "workflow_completed", "suggestion_finished"}
)


class AnalyticsEventRow(Base):
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), unique=True)
    event_name: Mapped[str] = mapped_column(Text)
    user_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    workflow_key: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    schema_version: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def record_event(
    session: Session,
    event_name: str,
    owner_id: int,
    *,
    workflow_key: UUID | None = None,
    outcome: str | None = None,
) -> None:
    """Add one event to the caller's transaction; never commits."""
    if event_name not in EVENT_NAMES:
        raise ValueError(f"unknown analytics event {event_name!r}")
    session.add(
        AnalyticsEventRow(
            event_id=uuid4(),
            event_name=event_name,
            user_key=select(UserRow.public_id)
            .where(UserRow.id == owner_id)
            .scalar_subquery(),
            workflow_key=workflow_key,
            outcome=outcome,
        )
    )
```

If SQLAlchemy rejects a scalar subquery as an ORM attribute value on insert, replace `session.add(...)` with `session.execute(insert(AnalyticsEventRow).values(...))` using the same values, and record the change as a ruling. The subquery must stay inside the database statement.

- [ ] **Step 5: Emit events at the three call sites**
  - `main.py` `signup`: inside `with session.begin():`, after `create_user(...)` returns, flush and record the event. Assign the result of `create_user` to a variable first:

    ```python
                created = create_user(
                    session, public_id, payload.username, hash_password(payload.password), ciphertext
                )
                session.flush()
                record_event(session, "user_signed_up", created.id)
                user = as_user(created)
    ```

  - `workflow_service.start_workflow`: in the `if inserted is not None:` branch, after `create_workflow(...)`, add `record_event(session, "workflow_started", owner_id, workflow_key=snapshot.id)`.
  - `workflow_service.advance_workflow`: after `session.refresh(row)` and before building `accepted`, add:

    ```python
        if decision.state is WorkflowState.COMPLETED:
            record_event(session, "workflow_completed", owner_id, workflow_key=workflow_id)
    ```

  Add the imports `from app.analytics_events import record_event`, and `WorkflowState` if it isn't already imported.

- [ ] **Step 6: Update conftest and the persistence tests.** Add `analytics_events` to the TRUNCATE statement in `tests/conftest.py`. Apply the `test_persistence.py` changes listed under Files.

- [ ] **Step 7: Run the full suite and lint**

Run: `pnpm test:api` and `pnpm lint:api`. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add apps/api
git commit -m "feat(api): record signup and workflow analytics events in a transactional outbox (phase 26)"
```

### Task 2: `suggestion_finished` on every final path

**Files:**

- Modify: `apps/api/app/suggestion_service.py` (`finish_suggestion` about line 481, `_claim_inner` lines 619 and 633, `finish_claimed_suggestion` about line 778, `_fail_row` line 790, `expire_suggestions_with_context` line 887)
- Test: `apps/api/tests/test_analytics_events.py` (append)

**Interfaces:**

- Consumes: `record_event` from Task 1.
- Produces:
  - `_set_result(session, row, canonical_titles, error_code) -> None`: replaces the two identical READY/FAILED blocks, and records `ready` or `failed`.
  - `_fail_row(session, row) -> None`: now takes `session` and records `expired`.

  *Ruling vs. the spec:* every `_fail_row` call is a deadline or claim-window expiry, whether the sweep finds it or a claim does. So `expired` means "passed its deadline", not "found by the sweep". That's a sharper metric definition. It's recorded in Task 6's spec amendment.

- [ ] **Step 1: Write the failing tests.** Reuse the suggestion helpers in `tests/test_suggestion_worker.py`:
  - `reserve_for_worker(session_factory)` returns a pending cloud row ID.
  - `worker_client(session_factory, provider)` is the worker test client.
  - The provider fakes live in that file.

  Import them with `from tests.test_suggestion_worker import reserve_for_worker, worker_client, RecordingProvider`. If `tests` isn't a package, copy the minimal helper instead and note it. Then write these cases, each asserting the `suggestion_finished` outcomes list exactly:

```python
def _outcomes(session_factory):
    return [o for n, o in _events(session_factory) if n == "suggestion_finished"]
```

  1. **Worker success:** a worker delivery with a provider returning valid titles gives `["ready"]`.
  2. **Provider failure:** the provider raises or returns invalid output, giving `["failed"]`.
  3. **Sweep expiry:** set `queued_at`/`expires_at` into the past, as `test_worker_expire_route_sweeps_once_and_rejects_nonempty` does, then POST `/internal/suggestions/expire` with `{}`. That gives `["expired"]`.
  4. **Claim of an expired row:** set `expires_at` into the past, then deliver the task. `_claim_inner` line 619 gives `["expired"]`.
  5. **Superseded:** request a second suggestion for the same workflow so that the first is superseded, following the existing supersession test in `tests/test_workflow_suggestions.py` (find it with `grep -n superseded`). The superseded row records nothing.
  6. **Replayed terminal:** delivering an already-finished row again changes nothing, so the count is unchanged.
  7. **Local path:** `finish_suggestion(...)` with titles gives `["ready"]`. Use the existing `finish_suggestion` test setup in `tests/test_workflow_suggestions.py`.

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: the outcome lists are empty.

- [ ] **Step 3: Implement.** Add these to `suggestion_service.py`:

```python
def _set_result(
    session: Session,
    row: WorkflowSuggestionRequestRow,
    canonical_titles: tuple[str, ...] | None,
    error_code: "SuggestionErrorCode | None",
) -> None:
    if canonical_titles is not None:
        row.status = SuggestionStatus.READY.value
        row.proposed_titles = list(canonical_titles)
        row.error_code = None
    else:
        row.status = SuggestionStatus.FAILED.value
        row.proposed_titles = []
        row.error_code = error_code.value if error_code is not None else None
    record_event(
        session,
        "suggestion_finished",
        row.owner_id,
        workflow_key=row.workflow_id,
        outcome="ready" if canonical_titles is not None else "failed",
    )


def _fail_row(session: Session, row: WorkflowSuggestionRequestRow) -> None:
    row.status = SuggestionStatus.FAILED.value
    row.proposed_titles = []
    row.error_code = SuggestionErrorCode.TIMEOUT.value
    record_event(
        session,
        "suggestion_finished",
        row.owner_id,
        workflow_key=row.workflow_id,
        outcome="expired",
    )
```

Replace both inline `if canonical_titles is not None: ... else: ...` blocks (in `finish_suggestion` and `finish_claimed_suggestion`) with `_set_result(session, row, canonical_titles, error_code)`. Change all three `_fail_row(row)` calls to `_fail_row(session, row)`. Leave `_supersede_row` unchanged.

- [ ] **Step 4: Run the full suite and lint.** Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat(api): record suggestion_finished on every terminal suggestion path (phase 26)"
```

### Task 3: Export to BigQuery and the worker endpoint

**Files:**

- Modify: `apps/api/pyproject.toml`, `apps/api/uv.lock` (run `uv add --directory apps/api google-cloud-bigquery`, then change the added specifier to `==<resolved version>`, then run `uv lock`)
- Create: `apps/api/app/analytics_export.py`
- Modify: `apps/api/app/worker.py` (`create_worker_app` parameter and lifespan, new route)
- Modify: `apps/api/app/observability.py` (`SAFE_LOG_FIELDS` += `selected`, `loaded`, `pruned`; `EVENT_MESSAGES["analytics_export"] = "Analytics export finished."`)
- Create: `apps/api/tests/test_analytics_export.py`

**Interfaces:**

- Consumes: `AnalyticsEventRow` from Task 1.
- Produces:
  - `LoadRows = Callable[[list[dict[str, Any]]], None]`
  - `ExportResult(selected: int, loaded: int, pruned: int)`
  - `export_events(session_factory, load: LoadRows) -> ExportResult`
  - `bigquery_loader(table: str) -> LoadRows`
  - `create_worker_app(..., analytics_load: LoadRows | None = None)`
  - Route `POST /internal/analytics/export`, taking an empty JSON body `{}`

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_analytics_export.py`

```python
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.analytics_events import AnalyticsEventRow, record_event
from app.analytics_export import EXPORT_BATCH_LIMIT, export_events
from app.auth_repository import create_user


def _seed(session: Session, count: int) -> None:
    user = create_user(session, uuid4(), f"u{uuid4().hex[:8]}", "hash")
    session.flush()
    for _ in range(count):
        record_event(session, "workflow_started", user.id, workflow_key=uuid4())
    session.commit()


def _unexported(factory) -> int:
    with factory() as s:
        return s.scalar(
            select(func.count()).where(AnalyticsEventRow.exported_at.is_(None))
        )


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


def test_empty_outbox_skips_load_and_prunes_old_exported(database_session, session_factory):
    _seed(database_session, 2)
    database_session.execute(
        update(AnalyticsEventRow).values(
            exported_at=func.now() - timedelta(days=31)
        )
    )
    database_session.commit()
    calls: list = []
    result = export_events(session_factory, calls.append)
    assert calls == [] and result == type(result)(selected=0, loaded=0, pruned=2)


def test_recent_exported_rows_are_kept(database_session, session_factory):
    _seed(database_session, 1)
    export_events(session_factory, lambda rows: None)
    assert export_events(session_factory, lambda rows: None).pruned == 0
```

Worker route tests use the `worker_client` pattern from `tests/test_suggestion_worker.py`, building the app with `create_worker_app(session_factory=..., analytics_load=...)`:

- A non-empty body or no body returns 422, and GET returns 405.
- With `analytics_load=None`, the route returns 503 and loads nothing.
- A loader that raises gives a 500 response with the rows still unexported.
- On success it returns `{"selected": n, "loaded": n, "pruned": 0}`, and the serialized log contains `analytics_export` without any `user_key` value. Check the log the same way the existing `maintenance_finished` log assertions do.

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: `ModuleNotFoundError: app.analytics_export`.

- [ ] **Step 3: Implement** `apps/api/app/analytics_export.py`

```python
"""Phase 26: at-least-once export of the analytics outbox to BigQuery.

Rows are marked exported only after the load job succeeds. A crash between
load and mark reloads the batch next run; BigQuery views dedupe by event_id.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.analytics_events import AnalyticsEventRow

EXPORT_BATCH_LIMIT = 5000
PRUNE_AFTER = timedelta(days=30)
LOAD_TIMEOUT_SECONDS = 45  # worker request timeout is 60s

LoadRows = Callable[[list[dict[str, Any]]], None]


@dataclass(frozen=True)
class ExportResult:
    selected: int
    loaded: int
    pruned: int


def _as_json(row: AnalyticsEventRow, loaded_at: str) -> dict[str, Any]:
    return {
        "event_id": str(row.event_id),
        "event_name": row.event_name,
        "user_key": str(row.user_key),
        "workflow_key": str(row.workflow_key) if row.workflow_key else None,
        "outcome": row.outcome,
        "occurred_at": row.occurred_at.isoformat(),
        "schema_version": row.schema_version,
        "loaded_at": loaded_at,
    }


def export_events(
    session_factory: sessionmaker[Session], load: LoadRows
) -> ExportResult:
    with session_factory() as session:
        rows = session.scalars(
            select(AnalyticsEventRow)
            .where(AnalyticsEventRow.exported_at.is_(None))
            .order_by(AnalyticsEventRow.id)
            .limit(EXPORT_BATCH_LIMIT)
        ).all()
    loaded = 0
    if rows:
        loaded_at = datetime.now(UTC).isoformat()
        load([_as_json(row, loaded_at) for row in rows])  # raises on failure
        with session_factory.begin() as session:
            session.execute(
                update(AnalyticsEventRow)
                .where(AnalyticsEventRow.id.in_([row.id for row in rows]))
                .values(exported_at=func.now())
            )
        loaded = len(rows)
    with session_factory.begin() as session:
        pruned = session.execute(
            delete(AnalyticsEventRow).where(
                AnalyticsEventRow.exported_at < func.now() - PRUNE_AFTER
            )
        ).rowcount
    return ExportResult(selected=len(rows), loaded=loaded, pruned=pruned)


def bigquery_loader(table: str) -> LoadRows:
    from google.cloud import bigquery  # imported lazily: tests never need it

    client = bigquery.Client()
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    def load(rows: list[dict[str, Any]]) -> None:
        client.load_table_from_json(rows, table, job_config=config).result(
            timeout=LOAD_TIMEOUT_SECONDS
        )

    return load
```

The table schema is owned by Terraform. Loading JSON with no explicit schema appends to the existing table and fails on a mismatch, which is what we want.

In `worker.py`:

- Add the keyword `analytics_load: LoadRows | None = None` to `create_worker_app`.
- In the lifespan, set `app.state.analytics_load = analytics_load if analytics_load is not None else (bigquery_loader(table) if (table := os.environ.get("ANALYTICS_EVENTS_TABLE")) else None)`.
- Add the route below, mirroring `expire`'s body validation and threadpool use:

```python
    @app.post("/internal/analytics/export")
    async def analytics_export(request: Request) -> dict[str, int]:
        raw = await read_bounded_body(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(status_code=422, detail="Export body must be JSON.") from None
        if payload != {}:
            raise HTTPException(status_code=422, detail="Export body must be an empty object.")
        load = request.app.state.analytics_load
        factory = get_session_factory(request)
        if load is None or factory is None:
            raise worker_unavailable()
        started = time.monotonic()
        try:
            result = await run_in_threadpool(export_events, factory, load)
        except Exception:  # noqa: BLE001 - sanitized; rows stay unexported for retry
            log_event("analytics_export", outcome="failed",
                      duration_ms=int((time.monotonic() - started) * 1000))
            raise HTTPException(status_code=500, detail="Analytics export failed.") from None
        log_event("analytics_export", outcome="success", selected=result.selected,
                  loaded=result.loaded, pruned=result.pruned,
                  duration_ms=int((time.monotonic() - started) * 1000))
        return {"selected": result.selected, "loaded": result.loaded, "pruned": result.pruned}
```

Check that `worker_unavailable()` returns 503. If it doesn't, raise `HTTPException(status_code=503, detail="Analytics export not configured.")` for the unconfigured case.

- [ ] **Step 4: Run the full suite and lint.** Expected: PASS. If an observability test pins `SAFE_LOG_FIELDS` or `EVENT_MESSAGES` exactly, update it to include the new entries. That's expected, not a regression.

- [ ] **Step 5: Commit**

```bash
git add apps/api
git commit -m "feat(worker): export analytics outbox to BigQuery at least once (phase 26)"
```

### Task 4: Metric definitions as SQL (PostgreSQL reconciliation and BigQuery views)

**Files:**

- Create: `apps/api/analytics_sql/postgres_activation_funnel.sql`
- Create: `apps/api/analytics_sql/postgres_suggestion_success.sql`
- Create: `infra/terraform/sandbox/analytics/events_deduped.sql.tftpl`
- Create: `infra/terraform/sandbox/analytics/activation_funnel.sql.tftpl`
- Create: `infra/terraform/sandbox/analytics/suggestion_success.sql.tftpl`
- Create: `apps/api/tests/test_analytics_metrics.py`

**Interfaces:**

- Produces: the SQL files. The guide (Task 6) and Terraform (Task 5) reference them by path. The BigQuery templates take `project` and `raw_dataset` (for `events_deduped`) or `project` and `dataset` (for the other two).

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_analytics_metrics.py`. Insert fixture events with explicit `occurred_at` values through raw SQL, run each `.sql` file's text with `session.execute(text(sql))`, and assert on the rows:

```python
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

SQL = Path(__file__).parents[1] / "analytics_sql"


def _event(s, name, user, at, outcome=None, workflow=None):
    s.execute(
        text(
            "INSERT INTO analytics_events (event_id, event_name, user_key, workflow_key, outcome, occurred_at) "
            "VALUES (:id, :n, :u, :w, :o, CAST(:at AS timestamptz))"
        ),
        {"id": uuid4(), "n": name, "u": user, "w": workflow, "o": outcome, "at": at},
    )


def test_activation_funnel_counts_distinct_users_within_7_days(database_session):
    a, b, c = uuid4(), uuid4(), uuid4()
    for u in (a, b, c):
        _event(database_session, "user_signed_up", u, "2026-08-03T10:00:00Z")  # Monday
    _event(database_session, "workflow_started", a, "2026-08-04T10:00:00Z")
    _event(database_session, "workflow_started", a, "2026-08-05T10:00:00Z")  # repeat: still 1 user
    _event(database_session, "workflow_completed", a, "2026-08-05T11:00:00Z")
    _event(database_session, "workflow_started", b, "2026-08-11T10:00:00Z")  # day 8: outside window
    database_session.commit()
    rows = database_session.execute(text((SQL / "postgres_activation_funnel.sql").read_text())).mappings().all()
    assert len(rows) == 1
    r = rows[0]
    assert str(r["cohort_week"]) == "2026-08-03"
    assert (r["signed_up"], r["started_7d"], r["completed_7d"]) == (3, 1, 1)
    assert r["cohort_complete"] is True


def test_current_week_cohort_is_marked_incomplete(database_session):
    _event(database_session, "user_signed_up", uuid4(), "now")
    database_session.commit()
    rows = database_session.execute(text((SQL / "postgres_activation_funnel.sql").read_text())).mappings().all()
    assert rows[-1]["cohort_complete"] is False


def test_suggestion_success_excludes_nothing_but_counts_outcomes(database_session):
    u = uuid4()
    for outcome in ("ready", "ready", "failed", "expired"):
        _event(database_session, "suggestion_finished", u, "2026-08-03T10:00:00Z", outcome)
    database_session.commit()
    r = database_session.execute(text((SQL / "postgres_suggestion_success.sql").read_text())).mappings().one()
    assert (str(r["day"]), r["ready"], r["failed"], r["expired"]) == ("2026-08-03", 2, 1, 1)
    assert float(r["success_rate"]) == 0.5
```

(`CAST('now' AS timestamptz)` is valid PostgreSQL. Superseded requests never produce events, per Task 2, so the success rate needs no exclusion clause. The test documents this.)

- [ ] **Step 2: Run the tests and confirm they fail** because the files are missing (`FileNotFoundError`).

- [ ] **Step 3: Write the SQL files.**

`postgres_activation_funnel.sql`:

```sql
-- Activation funnel (Phase 26 definition). Cohort: ISO week (UTC) of
-- user_signed_up. Started/completed: distinct cohort users with the event
-- within 7 days after their own signup. Complete once 14 days past week start.
WITH signups AS (
    SELECT user_key, occurred_at AS signed_up_at,
           date_trunc('week', occurred_at AT TIME ZONE 'UTC')::date AS cohort_week
    FROM analytics_events
    WHERE event_name = 'user_signed_up'
),
reached AS (
    SELECT s.user_key, s.cohort_week,
           bool_or(e.event_name = 'workflow_started') AS started,
           bool_or(e.event_name = 'workflow_completed') AS completed
    FROM signups s
    LEFT JOIN analytics_events e
      ON e.user_key = s.user_key
     AND e.event_name IN ('workflow_started', 'workflow_completed')
     AND e.occurred_at >= s.signed_up_at
     AND e.occurred_at < s.signed_up_at + interval '7 days'
    GROUP BY s.user_key, s.cohort_week
)
SELECT cohort_week,
       count(*) AS signed_up,
       count(*) FILTER (WHERE started) AS started_7d,
       count(*) FILTER (WHERE completed) AS completed_7d,
       round(count(*) FILTER (WHERE started)::numeric / count(*), 4) AS started_rate,
       round(count(*) FILTER (WHERE completed)::numeric / count(*), 4) AS completed_rate,
       cohort_week + 14 <= (now() AT TIME ZONE 'UTC')::date AS cohort_complete
FROM reached
GROUP BY cohort_week
ORDER BY cohort_week
```

`postgres_suggestion_success.sql`:

```sql
-- Suggestion success (Phase 26 definition): ready / (ready + failed + expired)
-- per UTC day. Superseded requests emit no event, so they are excluded.
SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day,
       count(*) FILTER (WHERE outcome = 'ready') AS ready,
       count(*) FILTER (WHERE outcome = 'failed') AS failed,
       count(*) FILTER (WHERE outcome = 'expired') AS expired,
       round(count(*) FILTER (WHERE outcome = 'ready')::numeric / count(*), 4) AS success_rate
FROM analytics_events
WHERE event_name = 'suggestion_finished'
GROUP BY 1
ORDER BY 1
```

`events_deduped.sql.tftpl`:

```sql
SELECT * EXCEPT (loaded_at)
FROM `${project}.${raw_dataset}.events`
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
```

`activation_funnel.sql.tftpl`:

```sql
WITH signups AS (
  SELECT user_key, occurred_at AS signed_up_at,
         DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS cohort_week
  FROM `${project}.${dataset}.events_deduped`
  WHERE event_name = 'user_signed_up'
),
reached AS (
  SELECT s.user_key, s.cohort_week,
         LOGICAL_OR(e.event_name = 'workflow_started') AS started,
         LOGICAL_OR(e.event_name = 'workflow_completed') AS completed
  FROM signups s
  LEFT JOIN `${project}.${dataset}.events_deduped` e
    ON e.user_key = s.user_key
   AND e.event_name IN ('workflow_started', 'workflow_completed')
   AND e.occurred_at >= s.signed_up_at
   AND e.occurred_at < TIMESTAMP_ADD(s.signed_up_at, INTERVAL 7 DAY)
  GROUP BY s.user_key, s.cohort_week
)
SELECT cohort_week,
       COUNT(*) AS signed_up,
       COUNTIF(started) AS started_7d,
       COUNTIF(completed) AS completed_7d,
       ROUND(SAFE_DIVIDE(COUNTIF(started), COUNT(*)), 4) AS started_rate,
       ROUND(SAFE_DIVIDE(COUNTIF(completed), COUNT(*)), 4) AS completed_rate,
       DATE_ADD(cohort_week, INTERVAL 14 DAY) <= CURRENT_DATE('UTC') AS cohort_complete
FROM reached
GROUP BY cohort_week
```

`suggestion_success.sql.tftpl`:

```sql
SELECT DATE(occurred_at) AS day,
       COUNTIF(outcome = 'ready') AS ready,
       COUNTIF(outcome = 'failed') AS failed,
       COUNTIF(outcome = 'expired') AS expired,
       ROUND(SAFE_DIVIDE(COUNTIF(outcome = 'ready'), COUNT(*)), 4) AS success_rate
FROM `${project}.${dataset}.events_deduped`
WHERE event_name = 'suggestion_finished'
GROUP BY day
```

- [ ] **Step 4: Run the tests and lint.** Expected: PASS. (The BigQuery templates are checked in Task 5 and live.)

- [ ] **Step 5: Commit**

```bash
git add apps/api/analytics_sql apps/api/tests/test_analytics_metrics.py infra/terraform/sandbox/analytics
git commit -m "feat(analytics): define funnel and suggestion success metrics in SQL (phase 26)"
```

### Task 5: Terraform datasets, table, views, access and schedule

**Prerequisite:** Terraform 1.14.7 installed from Guide 18 §3 into the gitignored `infra/terraform/.local/bin` in this worktree. This downloads `terraform_1.14.7_darwin_arm64.zip` from `releases.hashicorp.com` and verifies its checksum. **The learner must approve the download first.** If it isn't approved, run Steps 1–3 anyway and rely on CI's `terraform` job for Step 4, recording that as a ruling.

**Files:**

- Create: `infra/terraform/sandbox/analytics.tf`
- Modify: `infra/terraform/sandbox/variables.tf` (the `analytics` variable)
- Modify: `infra/terraform/sandbox/tasks.tf` (worker environment variable)
- Modify: `infra/terraform/sandbox/terraform.tfvars.example` (commented `analytics` example, and `bigquery.googleapis.com` in `enabled_services`)
- Create: `infra/terraform/sandbox/tests/analytics.tftest.hcl`

**Interfaces:**

- Consumes: the Task 4 templates, and the existing `google_service_account.async_worker[0]`, `async_invoker[0]`, `google_cloud_run_v2_service.worker[0]` and `google_project_service.required`.
- Produces: `var.analytics` (object or null) and the resources below.

- [ ] **Step 1: Write the failing tests** `tests/analytics.tftest.hcl`. Copy lines 1–182 of `tests/tasks.tftest.hcl` (the mock provider, overrides, and `variables` block, which includes `async_suggestions`). Add `"bigquery.googleapis.com"` to the `enabled_services` in that variables block. Then add:

```hcl
run "analytics_disabled_by_default" {
  command = plan
  assert {
    condition     = length(google_bigquery_dataset.analytics_raw) == 0 && length(google_cloud_scheduler_job.analytics_export) == 0
    error_message = "Analytics must create nothing unless enabled."
  }
}

run "analytics_enabled" {
  command = plan
  variables {
    analytics = { readers = ["user:learner@example.test"] }
  }
  assert {
    condition     = google_bigquery_table.events[0].time_partitioning[0].field == "occurred_at" && google_bigquery_table.events[0].time_partitioning[0].expiration_ms == 34560000000
    error_message = "Raw events must be day-partitioned on occurred_at with 400-day expiration."
  }
  assert {
    condition     = google_bigquery_table.events[0].clustering == tolist(["event_name"]) && google_bigquery_table.events[0].deletion_protection
    error_message = "Raw events must cluster by event_name and be deletion-protected."
  }
  assert {
    condition     = google_bigquery_dataset_access.raw_writer[0].role == "roles/bigquery.dataEditor" && google_bigquery_dataset_access.raw_writer[0].iam_member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Only the worker identity may write raw events."
  }
  assert {
    condition     = google_bigquery_dataset_access.readers["user:learner@example.test"].dataset_id == "analytics" && google_bigquery_dataset_access.readers["user:learner@example.test"].role == "roles/bigquery.dataViewer"
    error_message = "Readers must be granted on the curated dataset only."
  }
  assert {
    condition     = google_bigquery_dataset_access.authorized_view[0].dataset_id == "analytics_raw" && google_bigquery_dataset_access.authorized_view[0].view[0].table_id == "events_deduped"
    error_message = "events_deduped must be an authorized view on the raw dataset."
  }
  assert {
    condition     = strcontains(google_bigquery_table.events_deduped[0].view[0].query, "PARTITION BY event_id")
    error_message = "events_deduped must deduplicate by event_id."
  }
  assert {
    condition     = google_cloud_scheduler_job.analytics_export[0].schedule == "*/15 * * * *" && endswith(google_cloud_scheduler_job.analytics_export[0].http_target[0].uri, "/internal/analytics/export")
    error_message = "The export must run every 15 minutes against the worker route."
  }
  assert {
    condition     = contains([for e in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : e.name if e.value == "example-phase18-project.analytics_raw.events"], "ANALYTICS_EVENTS_TABLE")
    error_message = "The worker must receive ANALYTICS_EVENTS_TABLE."
  }
}

run "analytics_requires_async_worker" {
  command = plan
  variables {
    async_suggestions = null
    analytics         = { readers = [] }
  }
  expect_failures = [var.analytics]
}
```

- [ ] **Step 2: Run and confirm failure.** Run `terraform -chdir=infra/terraform/sandbox test -filter=tests/analytics.tftest.hcl`. Expected: errors about an unknown variable `analytics` and missing resources.

- [ ] **Step 3: Implement.**

In `variables.tf`:

```hcl
variable "analytics" {
  description = "Opt-in Phase 26 product analytics: BigQuery datasets, curated views, and the scheduled outbox export. Requires async_suggestions (the worker) and bigquery.googleapis.com in enabled_services."
  type = object({
    readers        = list(string)
    raw_dataset    = optional(string, "analytics_raw")
    dataset        = optional(string, "analytics")
    scheduler_name = optional(string, "analytics-export")
  })
  default = null

  validation {
    condition     = var.analytics == null || (var.async_suggestions != null && contains(var.enabled_services, "bigquery.googleapis.com"))
    error_message = "analytics requires async_suggestions and bigquery.googleapis.com in enabled_services."
  }
}
```

`analytics.tf`: all resources have `count = local.analytics_enabled ? 1 : 0`, except `readers`, which uses `for_each = local.analytics_enabled ? toset(var.analytics.readers) : toset([])`.

```hcl
locals {
  analytics_enabled = var.analytics != null
  analytics_table   = local.analytics_enabled ? "${var.project_id}.${var.analytics.raw_dataset}.events" : null
}

resource "google_bigquery_dataset" "analytics_raw" {
  count                      = local.analytics_enabled ? 1 : 0
  project                    = var.project_id
  dataset_id                 = var.analytics.raw_dataset
  location                   = var.region
  description                = "Phase 26 raw product events; worker-written, no direct readers."
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.required]
}

resource "google_bigquery_table" "events" {
  count               = local.analytics_enabled ? 1 : 0
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics_raw[0].dataset_id
  table_id            = "events"
  deletion_protection = true
  clustering          = ["event_name"]
  time_partitioning {
    type          = "DAY"
    field         = "occurred_at"
    expiration_ms = 34560000000
  }
  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_name", type = "STRING", mode = "REQUIRED" },
    { name = "user_key", type = "STRING", mode = "REQUIRED" },
    { name = "workflow_key", type = "STRING", mode = "NULLABLE" },
    { name = "outcome", type = "STRING", mode = "NULLABLE" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "schema_version", type = "INTEGER", mode = "REQUIRED" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_dataset" "analytics" {
  count                      = local.analytics_enabled ? 1 : 0
  project                    = var.project_id
  dataset_id                 = var.analytics.dataset
  location                   = var.region
  description                = "Phase 26 curated, deduplicated analytics views; the only analyst surface."
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.required]
}
```

Also add these resources:

- **Three views** (`google_bigquery_table` named `events_deduped`, `activation_funnel`, `suggestion_success`), each in the `analytics` dataset with `deletion_protection = false` and `view { use_legacy_sql = false, query = templatefile("${path.module}/analytics/<name>.sql.tftpl", {...}) }`.
  - `events_deduped` passes `{ project = var.project_id, raw_dataset = var.analytics.raw_dataset }`. The other two pass `{ project = var.project_id, dataset = var.analytics.dataset }` and `depends_on = [google_bigquery_table.events_deduped]`.
- **`google_bigquery_dataset_access` resources:**
  - `raw_writer`: dataset `analytics_raw`, `role = "roles/bigquery.dataEditor"`, `iam_member = "serviceAccount:${google_service_account.async_worker[0].email}"`.
  - `readers`: for each reader, dataset `analytics`, `role = "roles/bigquery.dataViewer"`, `iam_member = each.value`.
  - `authorized_view`: dataset `analytics_raw`, `view { project_id = var.project_id, dataset_id = var.analytics.dataset, table_id = "events_deduped" }`, with `depends_on` on that view.
- **`google_project_iam_member.analytics_job_user`:** `roles/bigquery.jobUser` for the worker service account. It's required to run load jobs, and it's the only project-level grant.
- **`google_cloud_scheduler_job.analytics_export`:** copy `suggestion_expiry` from `tasks.tf` with `name = var.analytics.scheduler_name`, `schedule = "*/15 * * * *"`, `attempt_deadline = "60s"`, the same `retry_config`, `oidc_token` and `{}` body, and the URI `.../internal/analytics/export`.

In `tasks.tf`, in the worker container, next to the other `dynamic "env"` blocks, add:

```hcl
      dynamic "env" {
        for_each = local.analytics_enabled ? [local.analytics_table] : []
        content {
          name  = "ANALYTICS_EVENTS_TABLE"
          value = env.value
        }
      }
```

In `terraform.tfvars.example`, add `"bigquery.googleapis.com"` to `enabled_services`, and a commented block:

```hcl
# Phase 26 analytics (requires async_suggestions):
# analytics = {
#   readers = ["user:you@example.com"]
# }
```

- [ ] **Step 4: Run the tests.** Run `terraform -chdir=infra/terraform/sandbox fmt -check -recursive`, then `validate`, then the whole `test` suite. Expected: all pass, and the existing test files are unaffected. If the provider rejects an attribute (for example `iam_member` on `google_bigquery_dataset_access`), check the provider 8.2.0 docs, use the supported equivalent (`user_by_email` for service accounts), and record it as a ruling.

- [ ] **Step 5: Commit**

```bash
git add infra/terraform/sandbox
git commit -m "feat(terraform): opt-in BigQuery analytics datasets, views, access and export schedule (phase 26)"
```

### Task 6: Walkthrough, spec amendments and status

**Files:**

- Create: `docs/guides/26-bigquery-analytics.md`
- Modify: `docs/superpowers/specs/2026-09-23-bigquery-analytics-design.md` (amendments: load wait 45s; `expired` = deadline expiry on any path; `record_event` takes `owner_id`; worker authentication is Cloud Run IAM, checked by Terraform tests rather than app tests)
- Modify: `docs/curriculum-roadmap.md`, `README.md` (Phase 26 status)

- [ ] **Step 1: Write the guide.** Use the same structure and style as `docs/guides/23-resilience.md`. Sections, in order:
  1. **Status line** linking the spec and plan.
  2. **Why this phase:** trustworthy metrics; what a CTO should ask about any number on a dashboard.
  3. **Prerequisites:**
     - Reinstall Terraform with Guide 18 §3.
     - Recreate `backend.hcl` and `terraform.tfvars` from the examples.
     - Enable `bigquery.googleapis.com`.
     - Set `analytics = { readers = ["user:<you>"] }`.
     - Review the plan: expect 2 datasets, 1 table, 3 views, 3 dataset access grants plus 1 per reader, 1 project IAM member, 1 scheduler job, and a worker update.
     - Deploy the API/worker image containing this phase through the Phase 19 pipeline, **before** applying Terraform, so the worker has the new route when Scheduler first calls it.
  4. **Event contract:** the event table and the privacy notes from the spec, plus why logs aren't used (approach 2) and why state snapshots aren't used (approach 3).
  5. **Metric definitions:** verbatim from the spec, linking the SQL files.
  6. **Generate data and check it's flowing:**
     - Sign up a synthetic user, run two workflows to completion, and request suggestions.
     - Trigger an export now with `gcloud scheduler jobs run analytics-export --location="$CLOUD_REGION" --project="$CLOUD_PROJECT"`.
     - Query with `bq query --use_legacy_sql=false --maximum_bytes_billed=100000000 'SELECT event_name, COUNT(*) FROM \`PROJECT.analytics.events_deduped\` GROUP BY 1'`.
  7. **Reconcile:** run each `apps/api/analytics_sql/postgres_*.sql` in Cloud SQL Studio next to the matching `analytics.*` view. The numbers must match. Also compare completed workflows since deployment: `SELECT count(*) FROM todo_workflows WHERE state = 'COMPLETED'` against `workflow_completed` events. Explain that workflows completed before deployment have no event.
  8. **Duplicate drill:**
     - In Cloud SQL Studio, run `UPDATE analytics_events SET exported_at = NULL WHERE event_name = 'suggestion_finished'`, then run the scheduler job again.
     - Compare the naive raw query `SELECT outcome, COUNT(*) FROM \`PROJECT.analytics_raw.events\` WHERE event_name='suggestion_finished' GROUP BY 1` with `analytics.suggestion_success`, and the naive raw funnel with`analytics.activation_funnel`.
     - Record what changed and what didn't, and why distinct-user metrics resist duplicates.
     - Note that the learner can read the raw dataset only as project Owner; analysts can't.
  9. **Cost:**
     - Show the byte cap rejecting a query: run a query with `--maximum_bytes_billed=1` and observe the error.
     - Include the per-user daily quota console path, marked "verify in the current console".
     - Add a short note that costs are negligible at sandbox scale.
  10. **Deletion and retention:** from the spec, including the time travel and fail-safe windows and Hex caches.
  11. **Acceptance record:** a table with these rows, each starting as `Pending`:
      - Terraform reinstalled; plan reviewed and applied
      - Events flowing
      - Views return results
      - Funnel reconciles
      - Suggestion success reconciles
      - Duplicate drill: raw inflated / views unchanged
      - Byte cap rejection

      Add **Deferred, not passed:**
      - The analyst access-denial check (learner choice)
      - AI token/cost attribution
      - Latency metrics
      - Client events
      - Account deletion feature
      - Sensitive Data Protection
      - Streaming ingestion
  12. **Local verification** with test counts, and **Sources**: BigQuery partitioned tables, authorized views, load jobs, time travel, custom quotas, and the `bq` `--maximum_bytes_billed` flag.

- [ ] **Step 2: Amend the spec** with the four rulings listed under Files, in one "Amendments during planning" section. Update the spec's status line.

- [ ] **Step 3: Update the roadmap and README**, following Phase 23's pattern: implemented locally, with live acceptance pending.

- [ ] **Step 4: Verify.** Run `pnpm lint:markdown && pnpm lint:links`. Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add docs README.md
git commit -m "docs: add Phase 26 BigQuery analytics walkthrough"
```
