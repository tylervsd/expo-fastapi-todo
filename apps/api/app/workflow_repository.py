from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.title_validation import canonicalize_title
from app.workflow_domain import (
    CURRENT_WORKFLOW_DEFINITION_VERSION,
    MAX_BREAKDOWN_TITLES,
    MAX_WORKFLOW_REVISION,
    CreatedTodo,
    WorkflowSnapshot,
    WorkflowState,
)

SNAPSHOT_RECORD_KEYS = frozenset(
    {
        "workflow_id",
        "revision",
        "definition_version",
        "state",
        "title",
        "involves_multiple_steps",
        "proposed_todo_titles",
        "created_todos",
    }
)

FINGERPRINT_HEX_PATTERN = "^[0-9a-f]{64}$"


class InvalidStoredSnapshot(ValueError):
    """A persisted workflow snapshot record failed closed validation."""


class WorkflowRow(Base):
    __tablename__ = "todo_workflows"
    __table_args__ = (
        UniqueConstraint(
            "public_id", "owner_id", name="uq_todo_workflows_public_owner"
        ),
        CheckConstraint(
            f"revision BETWEEN 0 AND {MAX_WORKFLOW_REVISION}",
            name="ck_todo_workflows_revision_range",
        ),
        CheckConstraint(
            "definition_version >= 1",
            name="ck_todo_workflows_definition_version",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    involves_multiple_steps: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    proposed_todo_titles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    completion_result: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    definition_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )


class WorkflowStartRequestRow(Base):
    __tablename__ = "todo_workflow_start_requests"
    __table_args__ = (
        PrimaryKeyConstraint(
            "owner_id", "request_id", name="pk_todo_workflow_start_requests"
        ),
        ForeignKeyConstraint(
            ["workflow_id"],
            ["todo_workflows.public_id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"request_fingerprint ~ '{FINGERPRINT_HEX_PATTERN}'",
            name="ck_start_requests_fingerprint_hex",
        ),
        CheckConstraint(
            "jsonb_typeof(accepted_snapshot) = 'object'",
            name="ck_start_requests_snapshot_object",
        ),
    )

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    accepted_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )


class WorkflowActionRequestRow(Base):
    __tablename__ = "todo_workflow_action_requests"
    __table_args__ = (
        PrimaryKeyConstraint(
            "owner_id",
            "workflow_id",
            "request_id",
            name="pk_todo_workflow_action_requests",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "owner_id"],
            ["todo_workflows.public_id", "todo_workflows.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"request_fingerprint ~ '{FINGERPRINT_HEX_PATTERN}'",
            name="ck_action_requests_fingerprint_hex",
        ),
        CheckConstraint(
            "jsonb_typeof(accepted_snapshot) = 'object'",
            name="ck_action_requests_snapshot_object",
        ),
    )

    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )


class WorkflowSuggestionRequestRow(Base):
    __tablename__ = "todo_workflow_suggestion_requests"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_suggestion_requests"),
        UniqueConstraint(
            "owner_id",
            "workflow_id",
            "request_id",
            name="uq_suggestion_requests_owner_workflow_request",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "owner_id"],
            ["todo_workflows.public_id", "todo_workflows.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"request_fingerprint ~ '{FINGERPRINT_HEX_PATTERN}'",
            name="ck_suggestion_requests_fingerprint_hex",
        ),
        CheckConstraint(
            f"base_revision BETWEEN 0 AND {MAX_WORKFLOW_REVISION}",
            name="ck_suggestion_requests_revision_range",
        ),
        CheckConstraint(
            "char_length(step_id) >= 1",
            name="ck_suggestion_requests_step_id",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'superseded')",
            name="ck_suggestion_requests_status",
        ),
        CheckConstraint(
            "jsonb_typeof(proposed_titles) = 'array'",
            name="ck_suggestion_requests_titles_array",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('not_configured', 'timeout', 'provider_unavailable', 'invalid_output')",
            name="ck_suggestion_requests_error_code",
        ),
        CheckConstraint(
            "(status = 'ready' AND error_code IS NULL AND "
            "CASE WHEN jsonb_typeof(proposed_titles) = 'array' "
            "THEN jsonb_array_length(proposed_titles) ELSE -1 END BETWEEN 2 AND 10) "
            "OR (status = 'failed' AND error_code IS NOT NULL AND "
            "proposed_titles = '[]'::jsonb) OR (status IN ('pending', 'superseded') "
            "AND error_code IS NULL AND proposed_titles = '[]'::jsonb)",
            name="ck_suggestion_requests_status_fields",
        ),
        Index(
            "ix_suggestion_requests_owner_workflow_id",
            "owner_id",
            "workflow_id",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    step_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_titles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)


# Short aliases keep the journal row discoverable to service and persistence callers.
SuggestionRequestRow = WorkflowSuggestionRequestRow
SuggestionRow = WorkflowSuggestionRequestRow


def create_workflow(
    session: Session, public_id: UUID, owner_id: int, title: str
) -> WorkflowRow:
    row = WorkflowRow(
        public_id=public_id,
        owner_id=owner_id,
        state="ASSESS_TASK",
        title=title,
        involves_multiple_steps=None,
        proposed_todo_titles=[],
        completion_result=None,
        revision=0,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )
    session.add(row)
    session.flush()
    return row


def find_workflow(
    session: Session, public_id: UUID, owner_id: int
) -> WorkflowRow | None:
    return session.scalar(
        select(WorkflowRow).where(
            WorkflowRow.public_id == public_id, WorkflowRow.owner_id == owner_id
        )
    )


def lock_workflow(
    session: Session, public_id: UUID, owner_id: int
) -> WorkflowRow | None:
    return session.scalar(
        select(WorkflowRow)
        .where(WorkflowRow.public_id == public_id, WorkflowRow.owner_id == owner_id)
        .with_for_update()
    )


def update_workflow(
    session: Session,
    row: WorkflowRow,
    *,
    state: str,
    involves_multiple_steps: bool | None,
    proposed_todo_titles: list[str],
    completion_result: dict[str, object] | None,
) -> WorkflowRow:
    row.state = state
    row.involves_multiple_steps = involves_multiple_steps
    row.proposed_todo_titles = list(proposed_todo_titles)
    if completion_result is None:
        row.completion_result = None
    elif isinstance(completion_result, dict):
        row.completion_result = dict(completion_result)
    else:
        # Pass through so the database object check rejects it.
        row.completion_result = completion_result
    session.flush()
    return row


def snapshot_to_record(snapshot: WorkflowSnapshot) -> dict[str, object]:
    return {
        "workflow_id": str(snapshot.id),
        "revision": snapshot.revision,
        "definition_version": snapshot.definition_version,
        "state": snapshot.state.value,
        "title": snapshot.title,
        "involves_multiple_steps": snapshot.involves_multiple_steps,
        "proposed_todo_titles": list(snapshot.proposed_todo_titles),
        "created_todos": (
            [
                {"id": str(item.id), "title": item.title, "completed": item.completed}
                for item in snapshot.created_todos
            ]
            if snapshot.created_todos is not None
            else None
        ),
    }


def _require_canonical_title(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidStoredSnapshot(f"stored snapshot has invalid {field}")
    try:
        canonical = canonicalize_title(value)
    except ValueError as exc:
        raise InvalidStoredSnapshot(
            f"stored snapshot has invalid {field}"
        ) from exc
    if value != canonical:
        raise InvalidStoredSnapshot(f"stored snapshot has invalid {field}")
    return value


def snapshot_from_record(record: Mapping[str, object]) -> WorkflowSnapshot:
    if not isinstance(record, dict) or set(record) != SNAPSHOT_RECORD_KEYS:
        raise InvalidStoredSnapshot("stored snapshot has unexpected keys")
    try:
        workflow_id = UUID(str(record["workflow_id"]))
    except (ValueError, AttributeError) as exc:
        raise InvalidStoredSnapshot("stored snapshot has invalid workflow_id") from exc
    revision = record["revision"]
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 0 <= revision <= MAX_WORKFLOW_REVISION
    ):
        raise InvalidStoredSnapshot("stored snapshot has invalid revision")
    definition_version = record["definition_version"]
    if (
        isinstance(definition_version, bool)
        or not isinstance(definition_version, int)
        or definition_version < 1
    ):
        raise InvalidStoredSnapshot("stored snapshot has invalid definition_version")
    try:
        state = WorkflowState(str(record["state"]))
    except ValueError as exc:
        raise InvalidStoredSnapshot("stored snapshot has invalid state") from exc
    title = _require_canonical_title(record["title"], field="title")
    involves = record["involves_multiple_steps"]
    if involves is not None and not isinstance(involves, bool):
        raise InvalidStoredSnapshot("stored snapshot has invalid flag")
    proposals = record["proposed_todo_titles"]
    if not isinstance(proposals, list):
        raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
    canonical_proposals = tuple(
        _require_canonical_title(item, field="proposed_todo_titles")
        for item in proposals
    )
    if state == WorkflowState.ASSESS_TASK:
        # create_initial_snapshot is the only producer: (None, ()).
        if involves is not None or canonical_proposals:
            raise InvalidStoredSnapshot("stored snapshot has invalid context")
    elif state in (WorkflowState.OFFER_BREAKDOWN, WorkflowState.COLLECT_TASKS):
        # Both states are only entered with involves_multiple_steps=True
        # (ASSESS_TASK answered "yes") and carry no proposals yet.
        if involves is not True or canonical_proposals:
            raise InvalidStoredSnapshot("stored snapshot has invalid context")
    elif state in (WorkflowState.REVIEW, WorkflowState.COMPLETED):
        # Mirror the domain's flag/count rule: involves_multiple_steps=False
        # yields exactly the single title proposal, while True yields one
        # proposal (OFFER_BREAKDOWN answered "no") or 2..10 breakdown
        # titles. A lone proposal only ever comes from the no-breakdown
        # path, where it equals the workflow title. A missing flag never
        # occurs at these states.
        if involves is False:
            if len(canonical_proposals) != 1:
                raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
        elif involves is True:
            if not 1 <= len(canonical_proposals) <= MAX_BREAKDOWN_TITLES:
                raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
        else:
            raise InvalidStoredSnapshot("stored snapshot has invalid flag")
        if len(canonical_proposals) == 1 and canonical_proposals[0] != title:
            raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
    elif state == WorkflowState.CANCELLED:
        # Cancellation preserves the exact flag/proposals of the cancelled
        # state: None pairs only with empty proposals (ASSESS_TASK),
        # False only with the single workflow title (no-breakdown REVIEW),
        # True with empty (OFFER/COLLECT), the single title (OFFER "no" or
        # no-breakdown REVIEW), or 2..10 breakdown titles.
        if involves is None:
            if canonical_proposals:
                raise InvalidStoredSnapshot("stored snapshot has invalid context")
        elif involves is False:
            if (
                len(canonical_proposals) != 1
                or canonical_proposals[0] != title
            ):
                raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
        elif len(canonical_proposals) > MAX_BREAKDOWN_TITLES or (
            len(canonical_proposals) == 1 and canonical_proposals[0] != title
        ):
            raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
    elif len(canonical_proposals) > MAX_BREAKDOWN_TITLES:
        raise InvalidStoredSnapshot("stored snapshot has invalid proposals")
    created: tuple[CreatedTodo, ...] | None = None
    stored_todos = record["created_todos"]
    if state == WorkflowState.COMPLETED:
        if not isinstance(stored_todos, list) or not stored_todos:
            raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
        items: list[CreatedTodo] = []
        for entry in stored_todos:
            if not isinstance(entry, dict) or set(entry) != {
                "id",
                "title",
                "completed",
            }:
                raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
            try:
                todo_id = UUID(str(entry["id"]))
            except (ValueError, AttributeError) as exc:
                raise InvalidStoredSnapshot(
                    "stored snapshot has invalid created_todos"
                ) from exc
            todo_title = _require_canonical_title(entry["title"], field="created_todos")
            if not isinstance(entry["completed"], bool):
                raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
            # Confirm preserves the accepted proposals and the service
            # creates one incomplete todo per proposal, in order.
            if entry["completed"]:
                raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
            items.append(
                CreatedTodo(
                    id=todo_id, title=todo_title, completed=entry["completed"]
                )
            )
        if len(items) != len(canonical_proposals):
            raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
        if any(item.title != proposal for item, proposal in zip(items, canonical_proposals)):
            raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
        created = tuple(items)
    elif stored_todos is not None:
        raise InvalidStoredSnapshot("stored snapshot has invalid created_todos")
    return WorkflowSnapshot(
        id=workflow_id,
        state=state,
        title=title,
        involves_multiple_steps=involves,
        proposed_todo_titles=canonical_proposals,
        created_todos=created,
        revision=revision,
        definition_version=definition_version,
    )
