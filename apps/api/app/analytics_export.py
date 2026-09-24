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
LOAD_TIMEOUT_SECONDS = 45  # the worker's request timeout is 60s

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
    from google.cloud import bigquery  # lazy: tests never need the client

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
