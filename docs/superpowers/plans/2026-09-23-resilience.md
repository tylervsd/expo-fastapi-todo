# Phase 23 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship release A (expand + dual-write + backfill), the Phase 23 walkthrough and readiness questionnaire now. Then ship releases B, C1 and C2 as separate PRs, each timed to the learner's live drill.

**Architecture:** `TodoRow.is_completed` becomes the single read point for completion, so release B is a one-line read switch. The backfill is a small module using the existing SQLAlchemy engine, run on the existing migration job with overridden args, and is deliberately not an Alembic migration. The restore drill and tabletop are guide-only.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, pytest, gcloud, and the existing Phase 19 delivery pipeline.

**Spec:** [Phase 23 design](../specs/2026-09-23-resilience-design.md)

## Global Constraints

- The API contract is unchanged: `Todo.completed: bool` in every response. No mobile or web changes.
- Write semantics: completing sets `completed_at = coalesce(completed_at, now())`, reopening sets `NULL`, and new todos get `NULL`.
- Backfill: `WHERE completed AND completed_at IS NULL`, batch size 500, one commit per batch, and a second run updates 0 rows.
- The backfill must not be an Alembic migration.
- Each release is its own PR to `main`, and each later branch is cut from `main` only after the previous release has merged and deployed:

  | Release | Branch | Worktree |
  | --- | --- | --- |
  | A | `codex/phase-23-resilience` | `.worktrees/phase-23-resilience` |
  | B | `codex/phase-23-read-switch` | `.worktrees/phase-23-read-switch` |
  | C1 | `codex/phase-23-contract` | `.worktrees/phase-23-contract` |
  | C2 | `codex/phase-23-contract-drop` | `.worktrees/phase-23-contract-drop` |
- **B must not merge until the learner has released A and is at drill step 2.** C1 follows a stable B, and C2 follows a released C1.
- Use invented data only. Keep `.pi/` and the untracked root `AGENTS.md` untouched.
- Test command: `pnpm test:api` (it needs the compose test Postgres on port 5433). Lint: `uv run --directory apps/api ruff check . && uv run --directory apps/api ruff format --check .`.
- Local tests do not count as live acceptance. The guide records learner-reported results separately.

## Review Focus

1. Re-completing an already-completed todo must keep its original `completed_at`, because completion times are audit data. This is pinned in Task 1.
2. The backfill running while users toggle todos: a row reopened between batch selection and update must not get stamped. The outer `WHERE` re-checks the conditions. Pinned in Task 2.
3. Todos created by workflows (`workflow_service.create_todo`) must read correctly under B, with `completed_at` NULL. Pinned in Task 4.
4. Cross-owner `set_completed` must still return `None` and touch nothing, including `completed_at`. Pinned in Task 1.
5. A backfill on an empty or already-backfilled table exits 0 and reports 0. Pinned in Task 2.

---

## Release A (branch `codex/phase-23-resilience`)

### Task 1: Expand migration, dual-write, and a single read point

**Files:**
- Create: `apps/api/alembic/versions/2026092301_add_todo_completed_at.py`
- Modify: `apps/api/app/todo_repository.py`
- Modify: `apps/api/app/main.py:556` (`as_todo`)
- Modify: `apps/api/app/workflow_service.py:224` (`CreatedTodo(... completed=todo.completed)`)
- Modify: `apps/api/tests/test_persistence.py` (`REVISION`, the todos shape assertion, new tests)

**Interfaces:**
- Produces: `TodoRow.completed_at: datetime | None` and `TodoRow.is_completed -> bool` (a property; in A it returns `self.completed`). Every application read of completion goes through `is_completed`. `set_completed(session, public_id, completed, owner_id) -> TodoRow | None` keeps its signature.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_persistence.py`

Change `REVISION = "2026091801"` to `REVISION = "2026092301"`. In `test_migration_creates_expected_todos_shape`, replace the todos column assertions:

```python
    columns = {column["name"]: column for column in inspector.get_columns("todos")}
    assert list(columns) == [
        "id", "public_id", "title", "completed", "owner_id", "completed_at"
    ]
    assert all(
        column["nullable"] is False
        for name, column in columns.items()
        if name != "completed_at"
    )
    assert columns["completed_at"]["nullable"] is True
    assert columns["completed_at"]["type"].timezone is True
```

(Keep the existing id, public_id, title, completed and default assertions.) Then add:

```python
def test_set_completed_dual_writes_and_preserves_first_completion_time(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Pay invoice", owner.id)
    database_session.commit()
    assert todo.completed_at is None

    first = set_completed(database_session, todo.public_id, True, owner.id)
    database_session.commit()
    assert first is not None and first.completed is True
    assert first.completed_at is not None
    first_time = first.completed_at

    again = set_completed(database_session, todo.public_id, True, owner.id)
    database_session.commit()
    assert again is not None and again.completed_at == first_time

    reopened = set_completed(database_session, todo.public_id, False, owner.id)
    database_session.commit()
    assert reopened is not None
    assert reopened.completed is False and reopened.completed_at is None
    assert reopened.is_completed is False


def test_set_completed_other_owner_touches_nothing(database_session: Session) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    other = create_user(database_session, uuid4(), "other", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Mine", owner.id)
    database_session.commit()

    assert set_completed(database_session, todo.public_id, True, other.id) is None
    database_session.commit()
    database_session.refresh(todo)
    assert todo.completed is False and todo.completed_at is None


def test_add_completed_at_migration_reverses(database_engine: Engine) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    with database_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "2026091801")
        assert "completed_at" not in {
            column["name"] for column in inspect(connection).get_columns("todos")
        }
        command.upgrade(config, "head")
```

Add the imports `from alembic import command` and `from alembic.config import Config`, placed the same way as in `conftest.py`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pnpm test:api -- -k "completed or migration" -v`
Expected: FAIL. `completed_at` is missing from the table and from `TodoRow`, and the downgrade target is unknown or the column is absent.

- [ ] **Step 3: Write the migration** `apps/api/alembic/versions/2026092301_add_todo_completed_at.py`

```python
"""Phase 23 expand: add nullable todos.completed_at alongside completed."""

import sqlalchemy as sa

from alembic import op

revision = "2026092301"
down_revision = "2026091801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "todos",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("todos", "completed_at")
```

- [ ] **Step 4: Update `app/todo_repository.py`**

Add `DateTime` and `func` to the sqlalchemy import, and add `from datetime import datetime`. In `TodoRow`, add this after `owner_id`:

```python
    # Phase 23 expand/contract: dual-written with `completed` until release C.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_completed(self) -> bool:
        return self.completed
```

Replace the `.values(...)` line in `set_completed`:

```python
        .values(
            completed=completed,
            completed_at=(
                func.coalesce(TodoRow.completed_at, func.now()) if completed else None
            ),
        )
```

- [ ] **Step 5: Route reads through `is_completed`**

`app/main.py` `as_todo`: `completed=row.is_completed`. `app/workflow_service.py` line 224: `completed=todo.is_completed`.

- [ ] **Step 6: Run the full API suite and lint**

Run: `pnpm test:api` and the lint command from Global Constraints.
Expected: all pass. The `test_todos.py` assertions on `row.completed` still hold in A.

- [ ] **Step 7: Commit**

```bash
git add apps/api
git commit -m "feat(api): expand todos with dual-written completed_at (phase 23 release A)"
```

### Task 2: Idempotent batched backfill command

**Files:**
- Create: `apps/api/app/backfill_completed_at.py`
- Create: `apps/api/tests/test_backfill_completed_at.py`

**Interfaces:**
- Consumes: `create_database_engine`, `create_session_factory` and `get_database_url` from `app.database`; `TodoRow`, `create_todo` and `set_completed` from Task 1.
- Produces: `backfill(session_factory: sessionmaker[Session], batch_size: int = 500) -> int` (total rows updated), and `python -m app.backfill_completed_at`, which prints `backfill_completed_at: updated=<n> batches=<m>` and exits 0.

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_backfill_completed_at.py`

```python
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import create_user
from app.backfill_completed_at import BATCH_SQL, backfill
from app.todo_repository import TodoRow, create_todo, set_completed


def _legacy_completed(session: Session, owner_id: int, count: int) -> list[TodoRow]:
    """Simulate rows completed before release A: completed but no timestamp."""
    rows = [create_todo(session, uuid4(), f"Legacy {i}", owner_id) for i in range(count)]
    session.flush()
    session.execute(
        update(TodoRow)
        .where(TodoRow.id.in_([row.id for row in rows]))
        .values(completed=True, completed_at=None)
    )
    return rows


def test_backfill_stamps_legacy_rows_in_batches_and_is_idempotent(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    _legacy_completed(database_session, owner.id, 5)
    open_todo = create_todo(database_session, uuid4(), "Still open", owner.id)
    database_session.commit()

    assert backfill(session_factory, batch_size=2) == 5
    assert backfill(session_factory, batch_size=2) == 0

    with session_factory() as check:
        rows = check.scalars(select(TodoRow)).all()
        assert all((row.completed_at is not None) == row.completed for row in rows)
        assert check.get(TodoRow, open_todo.id).completed_at is None


def test_backfill_keeps_existing_timestamps_and_skips_reopened(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    done = create_todo(database_session, uuid4(), "Done in A", owner.id)
    database_session.commit()
    stamped = set_completed(database_session, done.public_id, True, owner.id)
    database_session.commit()
    original = stamped.completed_at
    reopened = create_todo(database_session, uuid4(), "Reopened", owner.id)
    database_session.commit()
    set_completed(database_session, reopened.public_id, True, owner.id)
    set_completed(database_session, reopened.public_id, False, owner.id)
    database_session.commit()

    assert backfill(session_factory) == 0
    with session_factory() as check:
        assert check.get(TodoRow, done.id).completed_at == original
        assert check.get(TodoRow, reopened.id).completed_at is None


def test_backfill_on_empty_table_reports_zero(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    database_session.commit()
    assert backfill(session_factory) == 0


def test_backfill_update_rechecks_conditions() -> None:
    """A row reopened after selection must not be stamped (outer WHERE re-check)."""
    assert BATCH_SQL.count("completed AND completed_at IS NULL") == 2
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pnpm test:api -- tests/test_backfill_completed_at.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backfill_completed_at'`.

- [ ] **Step 3: Implement** `apps/api/app/backfill_completed_at.py`

```python
"""Phase 23 operator backfill: stamp legacy completed todos with completed_at.

Deliberately not an Alembic migration, so releases can run ahead of it. The
timestamp is the backfill time: real historical completion times are unknown.
Run on the migration job:  python -m app.backfill_completed_at
"""

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory, get_database_url

# The outer WHERE re-checks the conditions so a row reopened concurrently is skipped.
BATCH_SQL = """
UPDATE todos SET completed_at = now()
WHERE id IN (
    SELECT id FROM todos
    WHERE completed AND completed_at IS NULL
    ORDER BY id LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
AND completed AND completed_at IS NULL
"""


def backfill(session_factory: sessionmaker[Session], batch_size: int = 500) -> int:
    total = 0
    batches = 0
    while True:
        with session_factory.begin() as session:
            updated = session.execute(text(BATCH_SQL), {"batch_size": batch_size}).rowcount
        if updated == 0:
            break
        total += updated
        batches += 1
    print(f"backfill_completed_at: updated={total} batches={batches}", flush=True)
    return total


if __name__ == "__main__":
    engine = create_database_engine(get_database_url())
    try:
        backfill(create_session_factory(engine))
    finally:
        engine.dispose()
```

- [ ] **Step 4: Run the tests and lint.** Run `pnpm test:api`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/backfill_completed_at.py apps/api/tests/test_backfill_completed_at.py
git commit -m "feat(api): add idempotent completed_at backfill command (phase 23)"
```

### Task 3: Walkthrough, questionnaire, and status

**Files:**
- Create: `docs/guides/23-resilience.md`
- Create: `docs/guides/23-readiness-questionnaire.md`
- Modify: `docs/curriculum-roadmap.md` (the intro status paragraph and the Phase 23 entry: scope and deferrals)
- Modify: `README.md` (only the phase status line or table, matching how Phase 22 is listed)

- [ ] **Step 1: Write `docs/guides/23-resilience.md`** with these sections, in this order:
  1. **Status line** linking the spec and plan, in the same style as `22-cloud-kms.md`.
  2. **Why this phase**: rehearsed versus assumed recovery. Say plainly that this is sandbox practice, not Accountable's runbook.
  3. **Part 1: Timed restore.** Objectives table (RTO 30 min, RPO 24 h). Commands:
     - `gcloud sql backups list --instance "$INSTANCE" --limit 5 --format='table(id,type,status,endTime)'`
     - Marker creation through the API with `curl`, using invented titles such as `restore-marker-<UTC time>`
     - `date -u` start and stop stamps
     - `gcloud sql backups restore "$BACKUP_ID" --restore-instance "$INSTANCE"`
     - `gcloud sql operations list --instance "$INSTANCE" --limit 1`
     - A check of `SELECT version_num FROM alembic_version`, compared with the head in `apps/api/alembic/versions`. If the schema is behind, run `gcloud run jobs execute "$MIGRATION_JOB" --region "$REGION" --wait`.

     Also include: what to read on the Phase 21 dashboard during the restore window; why PITR creates a new instance, and when "PITR clone + cut-over" is the better production runbook; and a "What we learned" prompt list.
  4. **Part 2: Expand/contract.** Copy the release table from the spec. Then give the drill steps 1–6 from the spec with exact commands:
     - `psql` or Cloud SQL Studio query: `SELECT completed, completed_at IS NOT NULL AS stamped, count(*) FROM todos GROUP BY 1,2`
     - The Phase 19 manual rollback section, linked (not copied): `19-continuous-delivery.md#manual-rollback`
     - The backfill command from the spec (`--args="python -m app.backfill_completed_at"`), run twice
     - `gcloud run services update-traffic` back to B's revision

     Add the note that backfilled timestamps are approximations, not audit evidence, and a short section on why the contract takes two releases.
  5. **Part 3: Tabletop, PII in logs.** The scenario, the roles, and the four injects with their decision prompts from the spec. Also include:
     - An incident record template: a table with time, event, decision, owner.
     - A blameless review template: what happened, impact, what went well, what was hard, and follow-ups with owners.
     - A "questions for counsel" list, stating that the guide gives no legal advice.
     - Prevention controls mapped to Phases 21 and 22.
  6. **Acceptance record**: a table with the rows below, each starting as `Pending`. Also a **Deferred (not passed)** list: HA, SCC/Artifact Analysis, secret rotation, dependency cadence, and Phase 18 steps 7–8. Rows:
     - Restore time vs RTO
     - Post-backup markers absent
     - Pre-backup data present
     - Schema version after restore
     - A released
     - B defect detected (time)
     - Rollback to A (time)
     - Backfill counts (first run / second run = 0)
     - B restored
     - C1 released
     - C2 released
     - Tabletop record completed
     - Questionnaire reviewed

- [ ] **Step 2: Write `docs/guides/23-readiness-questionnaire.md`.** Include a short "how to use this in week one" intro. Then six sections with 4–5 questions each (about 25 total), each in a table with the columns: Question | Good answer sounds like | Red flag | Rehearsed / Assumed / Unknown | Phase. Areas: backups and restore; schema changes; deploy and rollback; incidents and on-call; secrets and PII; dependencies and vulnerabilities. Example row: "When did you last restore a backup, and how long did it take?" | "Last month, 18 minutes, here's the note" | "Backups are enabled" | | 23. Close with a note that this is not a compliance checklist.

- [ ] **Step 3: Update the roadmap and README.** In the roadmap intro, mark Phase 23 as in progress and link the guide. In the Phase 23 entry, add a line naming the approved narrowed scope and the deferrals. In the README, update the status to match.

- [ ] **Step 4: Verify the docs.** Run `pnpm lint` (markdownlint + doc links). Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add docs README.md
git commit -m "docs: add Phase 23 resilience walkthrough and readiness questionnaire"
```

- [ ] **Step 6: Open PR A.** Push `codex/phase-23-resilience` and open a PR to `main`. The body covers the scope, states that B, C1 and C2 follow as separate PRs, and says the learner runs the restore drill first.

---

## Release B (branch `codex/phase-23-read-switch`, cut from `main` after A has deployed)

### Task 4: Read switch

**Files:**
- Modify: `apps/api/app/todo_repository.py` (the `is_completed` property)
- Modify: `apps/api/tests/test_persistence.py`

**Interfaces:**
- Consumes: `TodoRow.is_completed` and `completed_at` from Task 1, and `create_todo`.
- Produces: `is_completed` now returns `self.completed_at is not None`. Writes are unchanged, so both columns are still written.

- [ ] **Step 1: Write the failing tests**

```python
def test_reads_come_from_completed_at_so_unbackfilled_rows_read_open(
    database_session: Session,
) -> None:
    """Pins the drill defect: before the backfill, legacy completions read as open."""
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    legacy = create_todo(database_session, uuid4(), "Legacy done", owner.id)
    database_session.flush()
    database_session.execute(
        update(TodoRow).where(TodoRow.id == legacy.id).values(completed=True)
    )
    database_session.commit()
    database_session.refresh(legacy)
    assert legacy.completed is True and legacy.is_completed is False

    done = set_completed(database_session, legacy.public_id, True, owner.id)
    database_session.commit()
    assert done is not None and done.is_completed is True and done.completed is True


def test_dual_write_keeps_columns_consistent_for_rollback_to_a(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Workflow-made", owner.id)
    database_session.commit()
    assert todo.is_completed is False
    for value in (True, False, True):
        row = set_completed(database_session, todo.public_id, value, owner.id)
        database_session.commit()
        assert row is not None
        assert row.completed is value and row.is_completed is value
```

Add `update` to the sqlalchemy import in `test_persistence.py` if it isn't already there.

- [ ] **Step 2: Run and confirm the first test fails**

Run: `pnpm test:api -- -k "completed_at or rollback_to_a" -v`. Expected: the first test FAILS because `is_completed` still returns `True`.

- [ ] **Step 3: Implement.** In `TodoRow.is_completed`, change the body to `return self.completed_at is not None`.

- [ ] **Step 4: Run the full suite and lint.** Expected: PASS.

- [ ] **Step 5: Commit, then open PR B.** Use the commit message `feat(api): read todo completion from completed_at (phase 23 release B)`. The PR body warns: **merge only at drill step 2, and do NOT run the backfill first.**

---

## Release C1 (branch `codex/phase-23-contract`, cut after B is stable and backfilled)

### Task 5: Stop writing `completed`, remove it from the ORM

**Files:**
- Modify: `apps/api/app/todo_repository.py`
- Modify: `apps/api/tests/test_persistence.py` and `apps/api/tests/test_todos.py` (replace `row.completed` with `row.is_completed`)
- Create: `apps/api/tests/test_contract_compatibility.py`

**Interfaces:**
- Consumes: Task 4's `is_completed`.
- Produces: `TodoRow` without a `completed` attribute. `create_todo` no longer passes `completed`, and `set_completed` writes only `completed_at`.

- [ ] **Step 1: Write the failing tests** `apps/api/tests/test_contract_compatibility.py`

```python
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.auth_repository import create_user
from app.todo_repository import TodoRow, create_todo, list_todos, set_completed

# PostgreSQL DDL is transactional: drop the column inside a transaction that is
# always rolled back, so the shared test schema is untouched.


def test_c1_code_runs_on_the_c2_schema(database_engine: Engine) -> None:
    assert not hasattr(TodoRow, "completed")
    with database_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("TRUNCATE users, todos RESTART IDENTITY CASCADE"))
            connection.execute(text("ALTER TABLE todos DROP COLUMN completed"))
            with Session(bind=connection, join_transaction_mode="create_savepoint") as s:
                owner = create_user(s, uuid4(), "owner", "hash")
                s.flush()
                todo = create_todo(s, uuid4(), "Contracted", owner.id)
                done = set_completed(s, todo.public_id, True, owner.id)
                assert done is not None and done.is_completed is True
                assert [t.is_completed for t in list_todos(s, owner.id)] == [True]
        finally:
            transaction.rollback()


def test_release_b_writes_fail_on_the_c2_schema(database_engine: Engine) -> None:
    """Why the contract is two releases: B still writes `completed`."""
    with database_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("ALTER TABLE todos DROP COLUMN completed"))
            with pytest.raises(ProgrammingError, match="completed"):
                connection.execute(
                    text("UPDATE todos SET completed = true, completed_at = now()")
                )
        finally:
            transaction.rollback()
```

- [ ] **Step 2: Run and confirm it fails.** Expected: `test_c1_code_runs_on_the_c2_schema` FAILS, because `TodoRow` still has `completed`.

- [ ] **Step 3: Implement.**
  - In `TodoRow`, delete the `completed` mapped column (and the `Boolean`/`false` imports if they're now unused).
  - Update the comment to say `completed` is kept in the database only until C2.
  - `create_todo`: `TodoRow(public_id=public_id, title=title, owner_id=owner_id)`.
  - `set_completed`: remove `completed=completed,` from `.values(...)`.
  - Tests: in `test_persistence.py` and `test_todos.py`, replace `.completed is True/False` on `TodoRow` instances with `.is_completed`. Remove the dual-write-specific assertions on `row.completed` in the Task 1 and Task 4 tests, keeping their `completed_at` assertions.

- [ ] **Step 4: Run the full suite and lint.** Expected: PASS. The shape test still lists `completed`, because the database keeps it.

- [ ] **Step 5: Commit and open PR C1.** Commit message: `refactor(api): stop writing todos.completed (phase 23 release C1)`.

---

## Release C2 (branch `codex/phase-23-contract-drop`, cut after C1 has deployed)

### Task 6: Drop the column

**Files:**
- Create: `apps/api/alembic/versions/2026092302_drop_todo_completed.py`
- Modify: `apps/api/tests/test_persistence.py`
- Modify: `apps/api/tests/test_contract_compatibility.py`

- [ ] **Step 1: Write the failing tests.**
  - In `test_persistence.py`, set `REVISION = "2026092302"`. The todos columns become `["id", "public_id", "title", "owner_id", "completed_at"]`; remove the `completed` type and default assertions.
  - In `test_contract_compatibility.py`, delete both `ALTER TABLE todos DROP COLUMN completed` lines, because the schema is now contracted. Keep the `TRUNCATE`.
  - Add a reversibility test to `test_persistence.py` (it already has the `Config`, `Path`, `command` and `uuid4` imports from Task 1):

```python
def test_drop_completed_migration_reverses_from_completed_at(
    database_engine: Engine,
) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE users, todos RESTART IDENTITY CASCADE"))
        owner_id = connection.execute(
            text(
                "INSERT INTO users (public_id, username, password_hash) "
                "VALUES (:id, 'owner', 'hash') RETURNING id"
            ),
            {"id": uuid4()},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO todos (public_id, title, owner_id, completed_at) VALUES "
                "(:a, 'Done', :o, now()), (:b, 'Open', :o, NULL)"
            ),
            {"a": uuid4(), "b": uuid4(), "o": owner_id},
        )
        config.attributes["connection"] = connection
        command.downgrade(config, "2026092301")
        rows = connection.execute(
            text("SELECT title, completed FROM todos ORDER BY title")
        ).all()
        assert rows == [("Done", True), ("Open", False)]
        command.upgrade(config, "head")
```

- [ ] **Step 2: Run and confirm failure.** Expected: FAIL, because the head revision is still `2026092301` and the column still exists.

- [ ] **Step 3: Write the migration**

```python
"""Phase 23 contract: drop todos.completed; completed_at is authoritative."""

import sqlalchemy as sa

from alembic import op

revision = "2026092302"
down_revision = "2026092301"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("todos", "completed")


def downgrade() -> None:
    op.add_column(
        "todos",
        sa.Column(
            "completed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.execute("UPDATE todos SET completed = (completed_at IS NOT NULL)")
```

- [ ] **Step 4: Run the full suite and lint.** Expected: PASS.

- [ ] **Step 5: Commit and open PR C2.** Commit message: `feat(api): drop todos.completed (phase 23 release C2)`. After live acceptance, update the guide's acceptance record and the roadmap/README status on this branch or in a follow-up docs PR, as in earlier phases.
