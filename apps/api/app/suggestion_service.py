from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.title_validation import ECMASCRIPT_TRIM_CHARS, canonicalize_title
from app.workflow_domain import (
    CURRENT_WORKFLOW_DEFINITION_VERSION,
    MAX_WORKFLOW_REVISION,
    WorkflowState,
    create_submit_tasks,
)
from app.workflow_repository import (
    WorkflowRow,
    WorkflowSuggestionRequestRow,
    find_workflow,
    lock_workflow,
)
from app.workflow_service import (
    RequestIdReused,
    StaleWorkflowStep,
    current_step_id,
    fingerprint_payload,
)


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class SuggestionErrorCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"


class SuggestionInProgress(ValueError):
    """The active request for this workflow is still calling the provider."""


class StaleSuggestion(ValueError):
    """A request no longer owns the current workflow suggestion proposal."""


class InvalidSuggestionState(ValueError):
    """Suggestions are only available in the COLLECT_TASKS workflow state."""


class InvalidStoredSuggestion(ValueError):
    """A persisted suggestion record failed closed validation."""


ClarificationField = Literal["date", "location", "people", "budget", "constraints"]

# Cloud execution bounds from the Phase 20 spec: a reservation stays useful
# for 15 minutes, while a committed provider claim lapses after 2 minutes.
# The claim lapse never grants a replacement claim; it only lets cleanup and
# duplicate delivery record a timeout.
SUGGESTION_RESERVATION_TTL = timedelta(minutes=15)
SUGGESTION_CLAIM_TTL = timedelta(minutes=2)
SUGGESTION_EXPIRE_BATCH_LIMIT = 100

_CLARIFICATION_FIELDS = frozenset({"date", "location", "people", "budget", "constraints"})

MAX_CLARIFICATION_CODE_POINTS = 200


@dataclass(frozen=True)
class Clarification:
    """One bounded answer to a server-chosen clarification question."""

    field: ClarificationField
    value: str


def normalize_clarification(clarification: Clarification) -> Clarification:
    """Validate and canonicalize a clarification exactly once.

    The field must be one of the fixed catalog values and the value must
    hold 1 to 200 code points after trimming. Surrounding whitespace is not
    significant and is removed so retries hash identically.
    """
    field = clarification.field
    value = clarification.value
    if not isinstance(field, str) or field not in _CLARIFICATION_FIELDS:
        raise ValueError("clarification field is not in the catalog")
    if not isinstance(value, str):
        raise TypeError("clarification value must be a string")
    canonical = value.strip(ECMASCRIPT_TRIM_CHARS)
    if "\x00" in canonical:
        raise ValueError("clarification value must not contain NUL")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in canonical):
        raise ValueError("clarification value must not contain an unpaired surrogate")
    if not 1 <= len(canonical) <= MAX_CLARIFICATION_CODE_POINTS:
        raise ValueError("clarification value must contain 1 to 200 code points")
    return Clarification(field, canonical)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SuggestionSnapshot:
    workflow_id: UUID
    request_id: UUID
    base_revision: int
    step_id: str
    status: SuggestionStatus
    proposed_titles: tuple[str, ...]
    error_code: SuggestionErrorCode | None


@dataclass(frozen=True)
class SuggestionReservation:
    workflow_id: UUID
    request_id: UUID
    base_revision: int
    step_id: str
    goal: str
    request_fingerprint: str
    clarification: Clarification | None = None

    @property
    def goal_title(self) -> str:
        return self.goal

    @property
    def expected_revision(self) -> int:
        return self.base_revision


def _suggestion_fingerprint(
    workflow_id: UUID,
    expected_revision: int,
    step_id: str,
    goal: str,
    clarification: Clarification | None = None,
) -> str:
    """Hash the canonical suggestion identity.

    `clarification` must already be normalized (reserve_suggestion does this
    once before calling); it is consumed verbatim so omission keeps the exact
    Phase 10 payload.
    """
    payload: dict[str, Any] = {
        "operation": "suggest",
        "workflow_id": str(workflow_id),
        "expected_revision": expected_revision,
        "step_id": step_id,
        "title": goal,
    }
    if clarification is not None:
        payload["clarification"] = {
            "field": clarification.field,
            "value": clarification.value,
        }
    return fingerprint_payload(payload)


def _validate_active_workflow(
    row: Any, workflow_id: UUID, expected_revision: int, step_id: str
) -> None:
    if row.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
        from app.workflow_domain import UnsupportedWorkflowDefinition

        raise UnsupportedWorkflowDefinition(
            f"unsupported workflow definition version {row.definition_version}"
        )
    if row.state != WorkflowState.COLLECT_TASKS.value:
        raise InvalidSuggestionState(
            "suggestions are only available while collecting todo titles"
        )
    if step_id != current_step_id(workflow_id, row.state):
        raise StaleWorkflowStep(
            "submitted step does not match the current workflow step"
        )
    if expected_revision != row.revision:
        raise StaleWorkflowStep(
            "submitted revision does not match the current workflow revision"
        )


def suggestion_snapshot_from_row(
    row: WorkflowSuggestionRequestRow,
) -> SuggestionSnapshot:
    if not isinstance(row.request_id, UUID) or not isinstance(row.workflow_id, UUID):
        raise InvalidStoredSuggestion("stored suggestion has invalid identity")
    if (
        not isinstance(row.base_revision, int)
        or isinstance(row.base_revision, bool)
        or not 0 <= row.base_revision <= MAX_WORKFLOW_REVISION
    ):
        raise InvalidStoredSuggestion("stored suggestion has invalid revision")
    if not isinstance(row.step_id, str) or not row.step_id:
        raise InvalidStoredSuggestion("stored suggestion has invalid step_id")
    if (
        not isinstance(row.request_fingerprint, str)
        or len(row.request_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in row.request_fingerprint)
    ):
        raise InvalidStoredSuggestion("stored suggestion has invalid fingerprint")
    try:
        status = SuggestionStatus(row.status)
    except (TypeError, ValueError) as exc:
        raise InvalidStoredSuggestion("stored suggestion has invalid status") from exc
    try:
        error_code = (
            None if row.error_code is None else SuggestionErrorCode(row.error_code)
        )
    except (TypeError, ValueError) as exc:
        raise InvalidStoredSuggestion("stored suggestion has invalid error code") from exc
    titles = row.proposed_titles
    if not isinstance(titles, list):
        raise InvalidStoredSuggestion("stored suggestion has invalid titles")
    if status is SuggestionStatus.READY:
        if error_code is not None:
            raise InvalidStoredSuggestion("ready suggestion has an error")
        if any(not isinstance(title, str) for title in titles):
            raise InvalidStoredSuggestion("stored suggestion has invalid titles")
        try:
            validated = create_submit_tasks(titles)
        except (TypeError, ValueError) as exc:
            raise InvalidStoredSuggestion("stored suggestion has invalid titles") from exc
        if tuple(titles) != validated.titles:
            raise InvalidStoredSuggestion("stored suggestion has noncanonical titles")
        canonical_titles = validated.titles
    else:
        if titles:
            raise InvalidStoredSuggestion(
                "non-ready suggestion must have no proposed titles"
            )
        if status is SuggestionStatus.FAILED:
            if error_code is None:
                raise InvalidStoredSuggestion("failed suggestion has no error")
        elif error_code is not None:
            raise InvalidStoredSuggestion("non-failed suggestion has an error")
        canonical_titles = ()
    return SuggestionSnapshot(
        workflow_id=row.workflow_id,
        request_id=row.request_id,
        base_revision=row.base_revision,
        step_id=row.step_id,
        status=status,
        proposed_titles=canonical_titles,
        error_code=error_code,
    )


# This name is useful to repository/API callers and keeps the mapper discoverable.
row_to_suggestion_snapshot = suggestion_snapshot_from_row


def _latest_suggestion(
    session: Session, owner_id: int, workflow_id: UUID
) -> WorkflowSuggestionRequestRow | None:
    return session.scalar(
        select(WorkflowSuggestionRequestRow)
        .where(
            WorkflowSuggestionRequestRow.owner_id == owner_id,
            WorkflowSuggestionRequestRow.workflow_id == workflow_id,
        )
        .order_by(WorkflowSuggestionRequestRow.id.desc())
        .limit(1)
    )


def reserve_suggestion(
    session: Session,
    owner_id: int,
    workflow_id: UUID,
    request_id: UUID,
    expected_revision: int,
    step_id: str,
    clarification: Clarification | None = None,
    *,
    queued: bool = False,
) -> SuggestionReservation | SuggestionSnapshot | None:
    canonical_clarification = (
        normalize_clarification(clarification) if clarification is not None else None
    )
    with session.begin():
        workflow = lock_workflow(session, workflow_id, owner_id)
        if workflow is None:
            return None
        fingerprint = _suggestion_fingerprint(
            workflow_id,
            expected_revision,
            step_id,
            workflow.title,
            canonical_clarification,
        )
        existing = session.scalar(
            select(WorkflowSuggestionRequestRow).where(
                WorkflowSuggestionRequestRow.owner_id == owner_id,
                WorkflowSuggestionRequestRow.workflow_id == workflow_id,
                WorkflowSuggestionRequestRow.request_id == request_id,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise RequestIdReused(
                    "request_id was already used with different suggestion details"
                )
            snapshot = suggestion_snapshot_from_row(existing)
            if snapshot.status in (
                SuggestionStatus.READY,
                SuggestionStatus.FAILED,
            ):
                return snapshot
            latest = _latest_suggestion(session, owner_id, workflow_id)
            if (
                snapshot.status is SuggestionStatus.PENDING
                and latest is not None
                and latest.id == existing.id
            ):
                # A cloud replay returns the saved snapshot so the caller can
                # retry enqueue against the original deadlines; the row is
                # never rewritten here. Legacy inline pending keeps the
                # existing conflict behavior.
                if _is_cloud_row(existing):
                    return snapshot
                raise SuggestionInProgress(
                    "the current suggestion request is still in progress"
                )
            raise StaleSuggestion("the suggestion request is no longer current")

        _validate_active_workflow(workflow, workflow_id, expected_revision, step_id)
        session.execute(
            update(WorkflowSuggestionRequestRow)
            .where(
                WorkflowSuggestionRequestRow.owner_id == owner_id,
                WorkflowSuggestionRequestRow.workflow_id == workflow_id,
                WorkflowSuggestionRequestRow.status == SuggestionStatus.PENDING.value,
            )
            .values(status=SuggestionStatus.SUPERSEDED.value)
        )
        # No provider or cloud call runs inside this transaction: cloud mode
        # only persists the immutable input snapshots and database-clock
        # deadlines alongside the reservation row.
        queued_at: datetime | None = None
        expires_at: datetime | None = None
        goal_snapshot: str | None = None
        clarification_snapshot: dict[str, str] | None = None
        if queued:
            goal_snapshot = _require_canonical_goal(workflow.title)
            clarification_snapshot = (
                {
                    "field": canonical_clarification.field,
                    "value": canonical_clarification.value,
                }
                if canonical_clarification is not None
                else None
            )
            queued_at = session.scalar(select(func.now()))
            assert queued_at is not None
            expires_at = queued_at + SUGGESTION_RESERVATION_TTL
        row = WorkflowSuggestionRequestRow(
            owner_id=owner_id,
            workflow_id=workflow_id,
            request_id=request_id,
            request_fingerprint=fingerprint,
            base_revision=expected_revision,
            step_id=step_id,
            status=SuggestionStatus.PENDING.value,
            proposed_titles=[],
            error_code=None,
            queued_at=queued_at,
            expires_at=expires_at,
            provider_started_at=None,
            goal_snapshot=goal_snapshot,
            clarification_snapshot=clarification_snapshot,
        )
        session.add(row)
        session.flush()
        return SuggestionReservation(
            workflow_id=workflow_id,
            request_id=request_id,
            base_revision=expected_revision,
            step_id=step_id,
            goal=workflow.title,
            request_fingerprint=fingerprint,
            clarification=canonical_clarification,
        )


def finish_suggestion(
    session: Session,
    owner_id: int,
    workflow_id: UUID,
    request_id: UUID,
    *,
    titles: tuple[str, ...] | None,
    error_code: SuggestionErrorCode | None,
) -> SuggestionSnapshot | None:
    if titles is not None and error_code is not None:
        raise ValueError("a suggestion result cannot have titles and an error")
    if titles is None and error_code is None:
        raise ValueError("a suggestion result needs titles or an error")
    if error_code is not None:
        error_code = SuggestionErrorCode(error_code)
    canonical_titles: tuple[str, ...] | None = None
    if titles is not None:
        validated = create_submit_tasks(titles)
        if validated.titles != titles:
            raise ValueError("suggestion titles must be canonical")
        canonical_titles = validated.titles

    with session.begin():
        workflow = lock_workflow(session, workflow_id, owner_id)
        if workflow is None:
            return None
        row = session.scalar(
            select(WorkflowSuggestionRequestRow).where(
                WorkflowSuggestionRequestRow.owner_id == owner_id,
                WorkflowSuggestionRequestRow.workflow_id == workflow_id,
                WorkflowSuggestionRequestRow.request_id == request_id,
            )
        )
        if row is None:
            raise StaleSuggestion("the suggestion request was not found")
        snapshot = suggestion_snapshot_from_row(row)
        if snapshot.status in (SuggestionStatus.READY, SuggestionStatus.FAILED):
            return snapshot
        latest = _latest_suggestion(session, owner_id, workflow_id)
        if (
            snapshot.status is not SuggestionStatus.PENDING
            or latest is None
            or latest.id != row.id
        ):
            raise StaleSuggestion("the suggestion request is no longer current")
        if (
            workflow.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION
            or workflow.state != WorkflowState.COLLECT_TASKS.value
            or workflow.revision != row.base_revision
            or row.step_id != current_step_id(workflow_id, workflow.state)
        ):
            raise StaleSuggestion("the workflow changed before suggestions were ready")
        if canonical_titles is not None:
            row.status = SuggestionStatus.READY.value
            row.proposed_titles = list(canonical_titles)
            row.error_code = None
        else:
            row.status = SuggestionStatus.FAILED.value
            row.proposed_titles = []
            row.error_code = error_code.value if error_code is not None else None
        session.flush()
        return suggestion_snapshot_from_row(row)


@dataclass(frozen=True)
class ClaimedSuggestion:
    suggestion_id: int
    owner_id: int
    reservation: SuggestionReservation
    provider_started_at: datetime


def _is_cloud_row(row: WorkflowSuggestionRequestRow) -> bool:
    return row.queued_at is not None


def _require_canonical_goal(goal: object) -> str:
    if not isinstance(goal, str):
        raise InvalidStoredSuggestion("stored suggestion has invalid goal")
    try:
        canonical = canonicalize_title(goal)
    except ValueError as exc:
        raise InvalidStoredSuggestion(
            "stored suggestion has invalid goal"
        ) from exc
    if goal != canonical:
        raise InvalidStoredSuggestion("stored suggestion has invalid goal")
    return goal


def _decode_stored_clarification(stored: object) -> Clarification | None:
    if stored is None:
        return None
    if not isinstance(stored, dict) or set(stored) != {"field", "value"}:
        raise InvalidStoredSuggestion("stored suggestion has invalid clarification")
    try:
        return normalize_clarification(
            Clarification(stored["field"], stored["value"])
        )
    except (TypeError, ValueError) as exc:
        raise InvalidStoredSuggestion(
            "stored suggestion has invalid clarification"
        ) from exc


def _validate_claimed_workflow(
    workflow: WorkflowRow | None,
    row: WorkflowSuggestionRequestRow,
) -> bool:
    if workflow is None:
        return False
    if workflow.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
        return False
    if workflow.state != WorkflowState.COLLECT_TASKS.value:
        return False
    if workflow.revision != row.base_revision:
        return False
    return row.step_id == current_step_id(row.workflow_id, workflow.state)


def _claim_fingerprint_matches(
    row: WorkflowSuggestionRequestRow,
    goal: str,
    clarification: Clarification | None,
) -> bool:
    return row.request_fingerprint == _suggestion_fingerprint(
        row.workflow_id, row.base_revision, row.step_id, goal, clarification
    )


def claim_suggestion(session: Session, suggestion_id: int) -> ClaimedSuggestion | None:
    # Discover ownership with a plain read first, then close that read
    # transaction before taking locks in the existing workflow-then-row order.
    # No provider or cloud call runs in either transaction.
    with session.begin():
        discovered = session.execute(
            select(
                WorkflowSuggestionRequestRow.owner_id,
                WorkflowSuggestionRequestRow.workflow_id,
            ).where(WorkflowSuggestionRequestRow.id == suggestion_id)
        ).one_or_none()
    if discovered is None:
        return None
    owner_id, workflow_id = discovered
    with session.begin():
        workflow = lock_workflow(session, workflow_id, owner_id)
        row = session.scalar(
            select(WorkflowSuggestionRequestRow)
            .where(WorkflowSuggestionRequestRow.id == suggestion_id)
            .with_for_update()
        )
        if (
            row is None
            or row.owner_id != owner_id
            or row.workflow_id != workflow_id
            or row.status != SuggestionStatus.PENDING.value
            or not _is_cloud_row(row)
        ):
            return None
        goal = _require_canonical_goal(row.goal_snapshot)
        clarification = _decode_stored_clarification(row.clarification_snapshot)
        now = session.scalar(select(func.now()))
        assert now is not None
        if row.expires_at is None or now >= row.expires_at:
            _fail_row(row)
            return None
        if row.provider_started_at is not None:
            if now < row.provider_started_at + SUGGESTION_CLAIM_TTL:
                raise SuggestionInProgress(
                    "the suggestion request already has a live provider claim"
                )
            # ponytail: the claim marker is permanent and never reset or
            # reclaimed, so a duplicate past the claim window records a
            # timeout instead of granting replacement provider work. Users
            # explicitly retry uncertain work with a new request.
            _fail_row(row)
            return None
        latest = _latest_suggestion(session, owner_id, workflow_id)
        if (
            not _validate_claimed_workflow(workflow, row)
            or latest is None
            or latest.id != row.id
            or not _claim_fingerprint_matches(row, goal, clarification)
        ):
            _supersede_row(row)
            return None
        row.provider_started_at = now
        session.flush()
        return ClaimedSuggestion(
            suggestion_id=row.id,
            owner_id=row.owner_id,
            reservation=SuggestionReservation(
                workflow_id=row.workflow_id,
                request_id=row.request_id,
                base_revision=row.base_revision,
                step_id=row.step_id,
                goal=goal,
                request_fingerprint=row.request_fingerprint,
                clarification=clarification,
            ),
            provider_started_at=now,
        )


def finish_claimed_suggestion(
    session: Session,
    claim: ClaimedSuggestion,
    *,
    titles: tuple[str, ...] | None,
    error_code: SuggestionErrorCode | None,
) -> SuggestionSnapshot | None:
    if titles is not None and error_code is not None:
        raise ValueError("a suggestion result cannot have titles and an error")
    if titles is None and error_code is None:
        raise ValueError("a suggestion result needs titles or an error")
    if error_code is not None:
        error_code = SuggestionErrorCode(error_code)
    canonical_titles: tuple[str, ...] | None = None
    if titles is not None:
        validated = create_submit_tasks(titles)
        if validated.titles != titles:
            raise ValueError("suggestion titles must be canonical")
        canonical_titles = validated.titles

    # No provider or cloud call runs inside this transaction; only the
    # guarded result write below touches the database.
    with session.begin():
        row = session.scalar(
            select(WorkflowSuggestionRequestRow)
            .where(WorkflowSuggestionRequestRow.id == claim.suggestion_id)
            .with_for_update()
        )
        if (
            row is None
            or row.owner_id != claim.owner_id
            or row.provider_started_at is None
            or row.provider_started_at != claim.provider_started_at
            or row.status != SuggestionStatus.PENDING.value
            or not _is_cloud_row(row)
        ):
            return None
        _decode_stored_clarification(row.clarification_snapshot)
        now = session.scalar(select(func.now()))
        assert now is not None
        if (
            row.expires_at is None
            or now >= row.expires_at
            or now >= row.provider_started_at + SUGGESTION_CLAIM_TTL
        ):
            return None
        workflow = lock_workflow(session, row.workflow_id, row.owner_id)
        latest = _latest_suggestion(session, row.owner_id, row.workflow_id)
        if (
            not _validate_claimed_workflow(workflow, row)
            or latest is None
            or latest.id != row.id
        ):
            _supersede_row(row)
            return None
        if canonical_titles is not None:
            row.status = SuggestionStatus.READY.value
            row.proposed_titles = list(canonical_titles)
            row.error_code = None
        else:
            row.status = SuggestionStatus.FAILED.value
            row.proposed_titles = []
            row.error_code = error_code.value if error_code is not None else None
        session.flush()
        return suggestion_snapshot_from_row(row)


def _fail_row(row: WorkflowSuggestionRequestRow) -> None:
    row.status = SuggestionStatus.FAILED.value
    row.proposed_titles = []
    row.error_code = SuggestionErrorCode.TIMEOUT.value


def _supersede_row(row: WorkflowSuggestionRequestRow) -> None:
    row.status = SuggestionStatus.SUPERSEDED.value
    row.proposed_titles = []
    row.error_code = None


def expire_suggestions(session: Session) -> int:
    # One bounded sweep: at most SUGGESTION_EXPIRE_BATCH_LIMIT pending cloud
    # rows past either database-clock expiry become failed/timeout. No
    # provider or cloud call runs inside this transaction.
    with session.begin():
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        now = session.scalar(select(func.now()))
        assert now is not None
        candidate_ids = list(
            session.scalars(
                select(WorkflowSuggestionRequestRow.id)
                .where(
                    WorkflowSuggestionRequestRow.status
                    == SuggestionStatus.PENDING.value,
                    WorkflowSuggestionRequestRow.queued_at.is_not(None),
                    or_(
                        WorkflowSuggestionRequestRow.expires_at <= now,
                        WorkflowSuggestionRequestRow.provider_started_at
                        <= now - SUGGESTION_CLAIM_TTL,
                    ),
                )
                .order_by(WorkflowSuggestionRequestRow.id)
                .limit(SUGGESTION_EXPIRE_BATCH_LIMIT)
            )
        )
        expired = 0
        for row_id in candidate_ids:
            target = session.execute(
                select(
                    WorkflowSuggestionRequestRow.owner_id,
                    WorkflowSuggestionRequestRow.workflow_id,
                ).where(WorkflowSuggestionRequestRow.id == row_id)
            ).one_or_none()
            if target is None:
                continue
            owner_id, workflow_id = target
            workflow = session.scalar(
                select(WorkflowRow)
                .where(
                    WorkflowRow.public_id == workflow_id,
                    WorkflowRow.owner_id == owner_id,
                )
                .with_for_update(skip_locked=True)
            )
            if workflow is None:
                continue
            row = session.scalar(
                select(WorkflowSuggestionRequestRow)
                .where(WorkflowSuggestionRequestRow.id == row_id)
                .with_for_update()
            )
            if (
                row is None
                or row.status != SuggestionStatus.PENDING.value
                or row.queued_at is None
                or row.expires_at is None
                or (
                    row.expires_at > now
                    and (
                        row.provider_started_at is None
                        or row.provider_started_at > now - SUGGESTION_CLAIM_TTL
                    )
                )
            ):
                continue
            _fail_row(row)
            expired += 1
        return expired


def get_current_suggestion(
    session: Session, owner_id: int, workflow_id: UUID
) -> SuggestionSnapshot | None:
    workflow = find_workflow(session, workflow_id, owner_id)
    if workflow is None:
        return None
    if workflow.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
        from app.workflow_domain import UnsupportedWorkflowDefinition

        raise UnsupportedWorkflowDefinition(
            f"unsupported workflow definition version {workflow.definition_version}"
        )
    if workflow.state != WorkflowState.COLLECT_TASKS.value:
        return None
    row = _latest_suggestion(session, owner_id, workflow_id)
    if row is None:
        return None
    if (
        row.base_revision != workflow.revision
        or row.step_id != current_step_id(workflow_id, workflow.state)
    ):
        return None
    return suggestion_snapshot_from_row(row)
