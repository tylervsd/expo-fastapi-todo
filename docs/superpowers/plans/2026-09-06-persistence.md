# Phase 4 Persistence Implementation Plan

**Status:** Proposed

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the existing todo API in a durable local PostgreSQL database
without changing its user-visible web/iOS behavior.

**Architecture:** Synchronous FastAPI todo routes own transactions around three
concrete SQLAlchemy repository functions. Alembic creates one ordered todo
table; Docker Compose separates durable development data from disposable test
data, and CI runs the same PostgreSQL integration boundary.

**Tech Stack:** Python 3.14.7, FastAPI 0.141.1, PostgreSQL 18.6,
SQLAlchemy 2.x, psycopg 3.3, Alembic, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-persistence-design.md`

## Global constraints

- Start from integrated tag `phase-03-api-vertical-slice` (`17c96a4`).
- Preserve GET/POST/PATCH paths, JSON, statuses, UUIDs, order, duplicate titles,
  PATCH semantics, `404`, OpenAPI, CORS, and all existing Expo behavior.
- Reject U+0000 in create titles with `422`; match it in the TypeScript response
  guard. Make no TodoScreen behavior or copy change.
- Use synchronous SQLAlchemy 2.x and psycopg 3.3 with sync FastAPI todo routes.
  Add no async database stack, generic repository/service interface, or retry.
- Commit POST/PATCH before success. Map SQLAlchemy `OperationalError` and pool
  `TimeoutError` to exact `503 {"detail":"Database unavailable."}`; leave other
  SQLAlchemy/programming errors 500.
- Keep exact DB-independent `GET /health` liveness at `200 {"status":"ok"}`.
- Use three-second connection and pool checkout timeouts. Each app lifespan owns
  and disposes its default engine; callers own injected test engines.
- Implement PATCH as one `UPDATE ... RETURNING` statement so every successful
  request writes its requested Boolean even after a stale read or when the ORM
  would otherwise see no net change.
- Use explicit Alembic migrations only; never call `create_all` at startup.
- Tests may migrate/truncate only database `todo_test`, never development data.
- Preserve the untracked root `AGENTS.md`. Sol owns architecture/review; Luna
  implementers return any scope or architecture concern to Sol.

## File map

- `compose.yaml`, `package.json`, `.github/workflows/quality.yml`, and
  `tests/repository_contract.bats`: local/CI database services and commands.
- `apps/api/pyproject.toml` and `uv.lock`: SQLAlchemy, Alembic, and psycopg.
- `apps/api/app/database.py`: engine/sessionmaker builders and URL rule.
- `apps/api/app/todo_repository.py`: one ORM row and three concrete operations.
- `apps/api/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, and
  `alembic/versions/2026090601_create_todos.py`: explicit schema history.
- `apps/api/tests/conftest.py`, `test_persistence.py`, and `test_validation.py`:
  opt-in migrated PostgreSQL fixtures, repository integration, and DB-free input.
- `apps/api/app/main.py` and `tests/test_todos.py`: transactional HTTP adapter and
  actual-PostgreSQL API contract tests; `test_health.py` remains DB-free.
- `apps/mobile/src/todos/todoApi.ts` and `.test.ts`: NUL response guard only.
- `docs/guides/04-persistence.md`, `README.md`, and roadmap: teaching and observed
  acceptance; update these spec/plan status lines when completed.

### Task 1: Establish the isolated PostgreSQL boundary

**Files:** Create `compose.yaml`, `apps/api/app/database.py`,
`apps/api/app/todo_repository.py`, `apps/api/alembic.ini`,
`apps/api/alembic/env.py`, `apps/api/alembic/script.py.mako`,
`apps/api/alembic/versions/2026090601_create_todos.py`,
`apps/api/tests/conftest.py`, and `apps/api/tests/test_persistence.py`; modify
`package.json`, `apps/api/pyproject.toml`, `apps/api/uv.lock`,
`.github/workflows/quality.yml`, and `tests/repository_contract.bats`.

**Interfaces:** Produce `Base`, `get_database_url()`,
`create_database_engine(url: str) -> Engine`,
`create_session_factory(engine: Engine) -> sessionmaker[Session]`, `TodoRow`,
and the three repository signatures from the spec. Repository functions execute
SQL and flush created rows but do not commit.

- [ ] **Write the failing infrastructure and repository checks.** In Bats, assert
  these exact package values:
  `docker compose up -d --wait db`,
  `docker compose --profile test up -d --wait db-test`, and
  `uv run --directory apps/api alembic upgrade head`. Assert Compose has durable
  `db` at `127.0.0.1:5432` plus profile-only tmpfs `db-test` at
  `127.0.0.1:5433`. In pytest, migrate guarded `todo_test` to `2026090601`,
  inspect columns/constraints, and test ordered duplicates, persistence, PATCH,
  missing UUID, database length rejection, and transaction rollback. For the
  stale-session PATCH race, have session A read `false`, session B commit `true`,
  session A request `false`, and a fresh session observe persisted `false`.

- [ ] **Run the red checks.** Run `bats tests/repository_contract.bats`, then
  start the future fixture service directly with
  `docker compose --profile test up -d --wait db-test` and run
  `uv run --directory apps/api python -m pytest tests/test_persistence.py -v`.
  Expect missing commands/modules/migration failures.

- [ ] **Add the minimum database infrastructure.** Pin `postgres:18.6` in both
  Compose and the CI application service. Mount only development `db` at
  `/var/lib/postgresql`; give `db-test` tmpfs, user/password/database `todo_test`,
  and port 5433. The dev user/password/database are `todo`; use exact default URL
  `postgresql+psycopg://todo:todo@127.0.0.1:5432/todo`. Resolve current
  Python-3.14-compatible SQLAlchemy 2.x and Alembic releases with psycopg 3.3,
  express those bounds in `pyproject.toml`, and commit the exact uv lock.

- [ ] **Add the model, repository, and explicit migration.** Map internal
  `id: Mapped[int]`, `public_id: Mapped[UUID]`, `title: Mapped[str]`, and
  `completed: Mapped[bool]`. Revision `2026090601` creates/drops only `todos`.
  Add named `CHECK (char_length(title) BETWEEN 1 AND 120)`. Configure Alembic's
  command-line path from `DATABASE_URL`; do not call `create_all`. Implement the
  ordered select and add-and-flush functions. Implement `set_completed` with one
  SQLAlchemy `update(...).returning(TodoRow)` execution, not an ORM read followed
  by assignment, and return the resulting row or `None`.

- [ ] **Build guarded database fixtures and CI.** The engine builder uses
  `pool_pre_ping=True`, `connect_args={"connect_timeout": 3}`, and
  `pool_timeout=3`; the sessionmaker uses `expire_on_commit=False`.
  `conftest.py` defaults to
  `postgresql+psycopg://todo_test:todo_test@127.0.0.1:5433/todo_test`, accepts a
  CI override, and before connecting, migrating, or truncating rejects query
  parameters, a driver other than exactly `postgresql+psycopg`, a database other
  than `todo_test`, or a target equal to the resolved development URL. Connect
  and verify `current_database() = 'todo_test'`, then run Alembic programmatically
  through that same connection via `Config.attributes["connection"]`; `env.py`
  must honor that supplied connection and use `DATABASE_URL` only for the CLI
  path. Put the database check and upgrade in one `engine.begin()` block so the
  migration commits before app sessions use it. Only requested DB fixtures
  migrate and truncate; commit truncation in a separate `engine.begin()` block
  before each database test opens sessions. Keep these shared-database tests
  serial. Configure CI service user/password/database `todo_test` on 5432, set
  `TEST_DATABASE_URL` to
  `postgresql+psycopg://todo_test:todo_test@127.0.0.1:5432/todo_test`, and dispose
  the fixture engine at session end.

- [ ] **Verify and commit.** Run `pnpm db:test:up`, the two focused checks above,
  `pnpm lint:api`, and `git diff --check`. Stage only Task 1 files and commit
  `feat: add PostgreSQL persistence foundation`.

### Task 2: Persist the existing HTTP contract

**Files:** Create `apps/api/tests/test_validation.py`; modify
`apps/api/app/main.py`, `apps/api/tests/test_todos.py`,
`apps/mobile/src/todos/todoApi.ts`, and
`apps/mobile/src/todos/todoApi.test.ts`.

**Interfaces:** `create_app` accepts an optional `sessionmaker[Session]`; tests
pass the Task 1 factory. When none is injected, the app lifespan builds and owns
one default engine and factory without opening a connection, then disposes that
engine at shutdown. An injected factory remains caller-owned. The dependency
yields and closes one session per todo request. Public response models still
expose exactly `id`, `title`, `completed`.

- [ ] **Separate validation and write failing API tests.** Move the exhaustive
  title type/trim/length/surrogate matrix to direct `TodoCreate` tests in
  `test_validation.py`, adding NUL, so it stays DB-free. Keep representative
  canonical `201` and invalid `422` cases plus all other Phase 3 HTTP contracts
  against PostgreSQL. Replace process isolation with persistence across two app
  instances, verify POST/PATCH from an independent session, and use an engine at
  an unreachable localhost port to assert each todo operation returns exact 503
  while `/health` remains exact 200.

- [ ] **Add one failing mobile guard case.** A successful response whose title
  contains `\u0000` must reject as `invalid-data`; retain all existing injected
  fetch and component tests without a database.

- [ ] **Run the red checks.** Run
  `uv run --directory apps/api python -m pytest tests/test_todos.py tests/test_health.py tests/test_validation.py -v`
  and
  `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts`.
  Expect persistence, 503, and NUL assertions to fail.

- [ ] **Implement the transactional adapter.** Add NUL to `TodoCreate` validation.
  Replace the dict with the injected/default session dependency and convert only
  todo routes to synchronous `def`. Wire the default engine and factory into the
  app lifespan; creation does not connect, shutdown disposes only the engine that
  lifespan created, and injected factories remain externally owned. Map ORM rows
  explicitly to `Todo`; GET calls the ordered repository function. POST generates
  UUID4 and PATCH retains the exact absent-row `404`, each inside
  `with session.begin()`, returning only after the context commits. Let that
  context roll back failed writes; catch `OperationalError` and SQLAlchemy's pool
  `TimeoutError` around todo database work and raise exact 503 without exposing
  driver prose. Retain the surrogate-safe `422` handler, and reject NUL before
  any SQL or write.

- [ ] **Match the response guard and verify.** Reject NUL in `isTodo`, then run
  the two focused commands, `pnpm test:mobile`, `pnpm lint:api`,
  `pnpm lint:mobile`, `pnpm typecheck`, and `git diff --check`. Stage only Task 2
  files and commit `feat: persist todo API transactions`.

### Task 3: Teach, accept, integrate, and checkpoint persistence

**Files:** Create `docs/guides/04-persistence.md`; modify `README.md`,
`docs/curriculum-roadmap.md`, this spec, and this plan.

**Interfaces:** Produce the Phase 4 startup/recovery guide and observed web/iOS
acceptance record. No source contract changes.

- [ ] **Write Guide 04 and update entry points.** Explain durable versus test
  services, named-volume safety, migration-first startup, schema/order, sessions
  and transactions, liveness/503 behavior, NUL `422`, focused checks, and exact
  recovery commands. Advance README to Phase 4 and Guide 04; mark only Phase 4's
  roadmap spec gate approved. Start the acceptance table unchecked:

  ```text
  | Web | date/runtime | ☐ | ☐ | ☐ |
  | iOS Simulator | date/runtime | ☐ | ☐ | ☐ |
  ```

- [ ] **Run automated acceptance.** From a clean test service run
  `pnpm db:test:up`, `pnpm test:api`, and `pnpm quality`; also run
  `git diff --check`. Confirm API tests fail loudly if the test database is
  unavailable and never inspect or clear development rows.

- [ ] **Perform the manual journey.** Run `pnpm db:up`, `pnpm db:migrate`,
  `pnpm dev:api`, and `pnpm dev:mobile`. On web create duplicates and complete
  one; restart API and then the database container, verifying IDs/order/state
  survive. On iOS refresh, reactivate one, and verify web sees it. Stop only the
  database; confirm `/health` stays 200, todo UI shows existing unavailable
  behavior, and Refresh recovers after restart. Record actual date/runtime and
  replace checkboxes only for observed results.

- [ ] **Finalize documentation and review.** Change spec/plan status to locally
  accepted with the observed date, run Markdown/link lint and `pnpm quality`, and
  commit `docs: add persistence guide`. Obtain final whole-branch Sol review and
  resolve all findings before integration.

- [ ] **Checkpoint only after integrated CI.** Integrate the reviewed commits,
  wait for the GitHub `quality` workflow to pass on that exact integrated commit,
  then create annotated tag `phase-04-persistence`. Never tag a feature head or
  an integrated commit whose CI is pending or failing.

## Spec coverage check

- PostgreSQL schema, ordering, repositories, and test boundary: Task 1.
- App-owned database lifecycle and route transactions: Task 2.
- Preserved HTTP/Expo contracts, commit-before-success, 503, NUL: Task 2.
- Isolated local/CI database testing: Tasks 1–3.
- Guide, manual web/iOS acceptance, review, integration, checkpoint: Task 3.

CRUD expansion, caching, retries, authentication, and automated E2E remain in
their roadmap phases.
