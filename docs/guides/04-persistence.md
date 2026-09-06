# Phase 4: PostgreSQL persistence

Phase 4 replaces the FastAPI process's in-memory todo collection with a local
PostgreSQL database. The existing web and iOS experience stays the same, while
todos now survive API and database-container restarts. This phase introduces one
SQLAlchemy model, an explicit Alembic migration, request-scoped sessions, and
route-owned transactions.

## Development and test databases

The repository defines two PostgreSQL 18.6 services in `compose.yaml`:

- `db` listens on `127.0.0.1:5432` and stores the development database in a
  named Docker volume. Stopping or recreating the container keeps that volume.
- `db-test` listens on `127.0.0.1:5433`, runs only with the Compose `test`
  profile, and stores data in tmpfs. It is disposable and has no development
  volume.

The services use different database names and credentials. Automated tests
refuse to migrate or clear anything except a verified `todo_test` database, and
they also refuse a URL that resolves to the development database. Routine
commands never use `docker compose down -v`; removing the development volume
would erase local todos.

## Start the persisted application

Install the repository dependencies as described in the earlier guides. Then
run these commands from the repository root:

```bash
pnpm db:up
pnpm db:migrate
pnpm dev:api
```

`db:up` starts the durable development database and waits for its health check.
`db:migrate` applies every Alembic revision through `head`. Run the migration
before FastAPI: the application never creates tables automatically.

In a second terminal, start Expo:

```bash
pnpm dev:mobile
```

Use `w` for `http://localhost:8081` or `i` for the designated iPhone Simulator.
The API remains at `http://127.0.0.1:8000`.

## Schema, ordering, and transactions

The first migration creates one `todos` table. Its internal identity column
provides stable insertion order. The public UUID remains the JSON `id`; the
internal identity never appears in API responses. Duplicate titles remain
independent rows, and completing or reactivating a todo does not reorder it.

Each todo request opens and closes one SQLAlchemy session. POST and PATCH own an
explicit transaction and finish the commit before returning success. A failed
write rolls back. PATCH uses one database update that both writes the requested
Boolean and returns the row, so a stale session cannot report a value that was
not persisted.

PostgreSQL text cannot contain U+0000. The create model rejects a NUL code point
with `422` before opening a database transaction. Existing trimming, length,
surrogate, response, status, OpenAPI, and CORS behavior remains unchanged.

## Liveness and database availability

`GET /health` remains a database-independent liveness check:

```json
{"status":"ok"}
```

A healthy response proves that FastAPI can answer; it does not prove PostgreSQL
is available. When PostgreSQL cannot connect or a connection cannot be checked
out, todo routes return exactly:

```json
{"detail":"Database unavailable."}
```

The existing app unavailable and unknown-write states handle this `503`
response. The app does not add retries in this phase.

## Run focused checks

Start the disposable database once before API integration tests:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_persistence.py -v
uv run --directory apps/api python -m pytest tests/test_todos.py tests/test_health.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts
```

Run the complete repository gate after focused work:

```bash
pnpm quality
```

Database tests migrate only their guarded `todo_test` target and truncate the
`todos` table before each database test. They fail immediately when that test
database is unavailable; they never skip silently or inspect development rows.

## Recover a stopped database

If todo operations report database unavailable, first confirm FastAPI remains
live:

```bash
curl http://127.0.0.1:8000/health
```

Restart the development database, wait for it to become healthy, and reapply
pending migrations:

```bash
pnpm db:up
pnpm db:migrate
```

Keep FastAPI running or restart it with `pnpm dev:api`, then select **Refresh**
in the app. The named volume keeps previously committed development rows.

## Manual persistence journey

Begin with the migrated development database and preserve any rows already in
it. Use the recognizable duplicate title `Phase 4 duplicate` so the acceptance
rows remain easy to distinguish from existing data.

1. On web, create two `Phase 4 duplicate` todos and complete one.
2. Restart FastAPI, refresh, and confirm both UUID-backed rows, their order, and
   completion state remain.
3. Restart the development database container without deleting its volume,
   refresh, and confirm the same rows and order remain.
4. On iOS, refresh, reactivate the completed row, and confirm web observes the
   change.
5. Stop PostgreSQL only. Confirm `/health` remains `200` while todo requests use
   the existing unavailable UI.
6. Restart PostgreSQL, select **Refresh**, and confirm both targets recover with
   the committed rows intact.

## Phase 4 acceptance record

| Target | Date/runtime | API restart persists | Database restart persists | Outage recovery |
| --- | --- | --- | --- | --- |
| Web | 2026-09-06 / `http://localhost:8081` | ☑ | ☑ | ☑ |
| iOS Simulator | 2026-09-06 / iPhone 17, iOS 26.5, Expo SDK 57 | ☑ | ☑ | ☑ |

Web acceptance used two `Phase 4 duplicate` rows. Restarting FastAPI and then
the development database container preserved their exact UUIDs, order, and
completed/active states. With PostgreSQL stopped, `/health` remained exact
`200 {"status":"ok"}`, todo requests returned exact `503 {"detail":"Database
unavailable."}`, and the browser kept its old rows with writes disabled. After
`pnpm db:up`, **Refresh** restored the same rows and writes.

iOS acceptance passed on retry after the user force-quit Simulator. Expo opened
on iPhone 17 running iOS 26.5. Reactivating the first duplicate on iOS was
observed on web after Refresh. The same rows and state survived an API restart.
Stopping PostgreSQL produced the native refresh error with writes disabled;
starting it again and selecting Refresh restored the saved rows and controls.
The earlier Simulator controller timeouts are resolved.
