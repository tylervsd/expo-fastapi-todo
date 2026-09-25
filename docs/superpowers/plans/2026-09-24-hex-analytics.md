# Phase 28b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a Hex trial least-privilege access to the curated `analytics` views, seed synthetic events through the real pipeline, and write the Hex walkthrough (app, AI assistant, checks, deletion drill).

**Architecture:** Terraform adds an opt-in `hex-reader` identity (dataset-scoped read plus query jobs) and an `analytics.data_freshness` view. Deterministic PostgreSQL scripts seed and remove synthetic outbox events, marked by a user-key prefix, and the existing export carries them to BigQuery. The Hex project itself is built by the learner from the guide.

**Tech Stack:** Terraform 1.14.7 with Google provider 8.2.0 (mock tests), PostgreSQL, pytest, BigQuery, Hex (Team trial), Markdown.

**Spec:** [Phase 28b design](../specs/2026-09-24-hex-analytics-design.md)

## Global Constraints

- **Synthetic prefix:** user keys `00000000-0000-4000-8000-` followed by 12 digits (`lpad(n, 12, '0')`), for n = 1…400.
- **Period:** from 2026-07-27T00:00:00Z. No seeded event at or after 2026-09-25T00:00:00Z. Dip week: ISO week starting 2026-09-07.
- **Randomness:** only `md5`-based. `pg_temp.u(seed)` = the first 7 hex characters of `md5(seed)` read as 28 bits, divided by 2^28. Never `random()`.
- **Deterministic IDs:** `event_id` = `md5('hex-seed-' || <seed>)::uuid` and `workflow_key` = `md5('hex-seed-workflow-' || n)::uuid`.
- **Hex identity:** `roles/bigquery.dataViewer` on the `analytics` dataset only (via `google_bigquery_dataset_access`, `iam_member`), plus project `roles/bigquery.jobUser`. No basic role, and no raw-dataset access.
- **No service-account key in Terraform.** Keys are created and deleted with `gcloud` only, and never written inside the repo.
- **`hex` requires `analytics`**, enforced by variable validation.
- **Stop and ask the learner** before anything writes to cloud resources or the sandbox database. The learner runs the seed in Cloud SQL Studio.
- **Invented data only.** Keep `.pi/` and the untracked root `AGENTS.md` untouched.
- **Commands:**
  - `pnpm test:api` (needs `pnpm db:test:up`)
  - `pnpm lint:api`
  - `PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox test -no-color`: symlink `infra/terraform/.local/bin` to the main checkout's binary, as in 28a, and run `init -backend=false -lockfile=readonly` first.
  - `pnpm lint:markdown && pnpm lint:links`

## Review Focus

1. **Running the seed twice** must insert zero rows the second time and leave counts unchanged. Pinned in Task 2.
2. **`unseed.sql` must never delete real rows.** A non-prefixed event survives it. Pinned in Task 2.
3. **The freshness view must expose no event data.** Its query contains only `MAX(loaded_at)`. Pinned in Task 1.
4. **Enabling `hex` without `analytics`** must fail at plan, not create an identity with nothing to read. Pinned in Task 1.
5. **Seeded rows must satisfy the outbox constraints** (the outcome only for `suggestion_finished`), or the whole seed rolls back. Pinned in Task 2 by running against the real migrated schema.

---

### Task 1: Terraform: freshness view and Hex identity

**Files:**

- Create: `infra/terraform/sandbox/analytics/data_freshness.sql.tftpl`
- Modify: `infra/terraform/sandbox/analytics.tf` (the freshness view and its authorized-view access)
- Create: `infra/terraform/sandbox/hex.tf`
- Modify: `infra/terraform/sandbox/variables.tf` (`hex` variable)
- Modify: `infra/terraform/sandbox/terraform.tfvars.example` (commented `hex` block)
- Modify: `infra/terraform/sandbox/tests/analytics.tftest.hcl` (new override and runs)

**Interfaces:**

- Produces:
  - `google_bigquery_table.data_freshness[0]`, the view `analytics.data_freshness` with the single column `last_loaded_at`
  - `google_bigquery_dataset_access.freshness_authorized_view[0]`
  - `var.hex` (object or null)
  - `google_service_account.hex_reader[0]`
  - `google_bigquery_dataset_access.hex_reader[0]`
  - `google_project_iam_member.hex_job_user[0]`
  - output `hex_reader_email` (null when disabled)

- [ ] **Step 1: Write the failing tests.**

  1. In `tests/analytics.tftest.hcl`, add a file-level override after the existing `override_resource` blocks:

  ```hcl
  override_resource {
    target          = google_service_account.hex_reader
    override_during = plan
    values = {
      email = "example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
    }
  }
  ```

  1. In `run "analytics_enabled"`, add:

  ```hcl
    assert {
      condition     = strcontains(google_bigquery_table.data_freshness[0].view[0].query, "MAX(loaded_at) AS last_loaded_at") && !strcontains(google_bigquery_table.data_freshness[0].view[0].query, "user_key") && !strcontains(google_bigquery_table.data_freshness[0].view[0].query, "event_id")
      error_message = "data_freshness must expose only the latest load time."
    }
    assert {
      condition     = google_bigquery_dataset_access.freshness_authorized_view[0].dataset_id == "analytics_raw" && google_bigquery_dataset_access.freshness_authorized_view[0].view[0].table_id == "data_freshness"
      error_message = "data_freshness must be an authorized view on the raw dataset."
    }
    assert {
      condition     = length(google_service_account.hex_reader) == 0
      error_message = "Hex identity must not exist unless hex is enabled."
    }
  ```

  1. Append new runs:

  ```hcl
  run "hex_enabled" {
    command = plan

    variables {
      analytics = { readers = ["user:learner@example.test"] }
      hex       = {}
    }

    assert {
      condition     = google_service_account.hex_reader[0].account_id == "hex-reader"
      error_message = "The Hex identity must use the default account id."
    }
    assert {
      condition     = google_bigquery_dataset_access.hex_reader[0].dataset_id == "analytics" && google_bigquery_dataset_access.hex_reader[0].role == "roles/bigquery.dataViewer" && google_bigquery_dataset_access.hex_reader[0].iam_member == "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
      error_message = "Hex must read only the curated analytics dataset."
    }
    assert {
      condition     = google_project_iam_member.hex_job_user[0].role == "roles/bigquery.jobUser" && google_project_iam_member.hex_job_user[0].member == "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
      error_message = "Hex needs project jobUser to run queries, nothing broader."
    }
    assert {
      condition     = google_bigquery_dataset_access.raw_writer[0].iam_member != "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
      error_message = "Hex must have no access to the raw dataset."
    }
  }

  run "hex_requires_analytics" {
    command = plan

    variables {
      analytics = null
      hex       = {}
    }

    expect_failures = [var.hex]
  }
  ```

- [ ] **Step 2: Run and confirm failure.** Run `terraform test -filter=tests/analytics.tftest.hcl`. Expected: errors for the undeclared resource `data_freshness` and the variable `hex`.

- [ ] **Step 3: Implement.**

  `analytics/data_freshness.sql.tftpl`:

  ```sql
  -- Latest load time only: no event data leaves the raw dataset through this view.
  SELECT MAX(loaded_at) AS last_loaded_at
  FROM `${project}.${raw_dataset}.events`
  ```

  In `analytics.tf`, after the `suggestion_success` view:

  ```hcl
  resource "google_bigquery_table" "data_freshness" {
    count = local.analytics_enabled ? 1 : 0

    project             = var.project_id
    dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
    table_id            = "data_freshness"
    deletion_protection = false

    view {
      use_legacy_sql = false
      query = templatefile("${path.module}/analytics/data_freshness.sql.tftpl", {
        project     = var.project_id
        raw_dataset = var.analytics.raw_dataset
      })
    }

    depends_on = [google_bigquery_table.events]
  }

  resource "google_bigquery_dataset_access" "freshness_authorized_view" {
    count = local.analytics_enabled ? 1 : 0

    project    = var.project_id
    dataset_id = google_bigquery_dataset.analytics_raw[0].dataset_id

    view {
      project_id = var.project_id
      dataset_id = google_bigquery_dataset.analytics[0].dataset_id
      table_id   = google_bigquery_table.data_freshness[0].table_id
    }
  }
  ```

  In `variables.tf`:

  ```hcl
  variable "hex" {
    description = "Opt-in Phase 28b Hex access: a service account that reads only the curated analytics dataset. Its key is created and deleted with gcloud, never Terraform. Requires analytics."
    type = object({
      account_id = optional(string, "hex-reader")
    })
    default = null

    validation {
      condition     = var.hex == null || var.analytics != null
      error_message = "hex requires analytics to be enabled."
    }
  }
  ```

  `hex.tf`:

  ```hcl
  # Phase 28b: least-privilege identity for a Hex BigQuery connection.
  # Reads only the curated analytics views; runs query jobs; nothing else.
  # The JSON key is created/deleted with gcloud (a documented exception to the
  # no-keys rule: Hex OAuth is Enterprise-only). Never create keys in Terraform.

  locals {
    hex_enabled = var.hex != null && local.analytics_enabled
  }

  resource "google_service_account" "hex_reader" {
    count = local.hex_enabled ? 1 : 0

    project      = var.project_id
    account_id   = var.hex.account_id
    display_name = "Hex reader (curated analytics only)"
  }

  resource "google_bigquery_dataset_access" "hex_reader" {
    count = local.hex_enabled ? 1 : 0

    project    = var.project_id
    dataset_id = google_bigquery_dataset.analytics[0].dataset_id
    role       = "roles/bigquery.dataViewer"
    iam_member = "serviceAccount:${google_service_account.hex_reader[0].email}"
  }

  # Required to run queries; grants no data access.
  resource "google_project_iam_member" "hex_job_user" {
    count = local.hex_enabled ? 1 : 0

    project = var.project_id
    role    = "roles/bigquery.jobUser"
    member  = "serviceAccount:${google_service_account.hex_reader[0].email}"
  }

  output "hex_reader_email" {
    description = "Hex reader service account email, for creating its key with gcloud."
    value       = local.hex_enabled ? google_service_account.hex_reader[0].email : null
  }
  ```

  In `terraform.tfvars.example`, after the `analytics` comment block:

  ```hcl
  # Phase 28b Hex (requires analytics). Key: gcloud only, never Terraform.
  # hex = {}
  ```

- [ ] **Step 4: Run all Terraform tests and the format check.** Run `terraform fmt -check analytics.tf hex.tf variables.tf tests/analytics.tftest.hcl` and the full `terraform test`. Expected: all pass (the previous 53 plus the new ones).
- [ ] **Step 5: Commit.** `feat(terraform): add analytics freshness view and least-privilege Hex identity (phase 28b)`

### Task 2: Seed and unseed scripts with PostgreSQL tests

**Files:**

- Create: `analytics_practice/seed_outbox.sql`
- Create: `analytics_practice/unseed.sql`
- Create: `apps/api/tests/test_hex_seed.py`

**Interfaces:**

- Consumes: the `analytics_events` table (Phase 26 migration `2026092601`).
- Produces: SQL scripts runnable as one batch in Cloud SQL Studio. Tests read them from `<repo>/analytics_practice/`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_hex_seed.py`:

```python
"""Phase 28b synthetic outbox seed: deterministic, constraint-valid, removable."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.analytics_events import record_event
from app.auth_repository import create_user

SCRIPTS = Path(__file__).parents[3] / "analytics_practice"
PREFIX = "00000000-0000-4000-8000-"


def _run(engine: Engine, name: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql((SCRIPTS / name).read_text())


def _scalar(session: Session, sql: str):
    return session.execute(text(sql)).scalar_one()


def test_seed_is_deterministic_and_rerun_inserts_nothing(
    database_session: Session, database_engine: Engine
) -> None:
    _run(database_engine, "seed_outbox.sql")
    first = _scalar(database_session, "SELECT count(*) FROM analytics_events")
    fingerprint = _scalar(
        database_session,
        "SELECT md5(string_agg(event_id::text || event_name || occurred_at::text, ',' "
        "ORDER BY event_id)) FROM analytics_events",
    )
    _run(database_engine, "seed_outbox.sql")
    assert _scalar(database_session, "SELECT count(*) FROM analytics_events") == first
    assert first > 1000
    assert fingerprint == _scalar(
        database_session,
        "SELECT md5(string_agg(event_id::text || event_name || occurred_at::text, ',' "
        "ORDER BY event_id)) FROM analytics_events",
    )


def test_seed_shape(database_session: Session, database_engine: Engine) -> None:
    _run(database_engine, "seed_outbox.sql")
    row = database_session.execute(
        text(
            "SELECT "
            "count(DISTINCT user_key) FILTER (WHERE event_name = 'user_signed_up') AS users, "
            "count(*) FILTER (WHERE occurred_at >= '2026-09-25T00:00:00Z') AS after_cutoff, "
            "count(*) FILTER (WHERE event_name = 'user_signed_up' "
            "  AND occurred_at >= '2026-09-21T00:00:00Z') AS partial_week_signups, "
            "count(*) FILTER (WHERE user_key::text NOT LIKE :prefix) AS unprefixed "
            "FROM analytics_events"
        ),
        {"prefix": PREFIX + "%"},
    ).mappings().one()
    assert row["users"] == 400
    assert row["after_cutoff"] == 0
    assert row["partial_week_signups"] > 0
    assert row["unprefixed"] == 0


def test_dip_week_has_lowest_success_rate(
    database_session: Session, database_engine: Engine
) -> None:
    _run(database_engine, "seed_outbox.sql")
    weeks = database_session.execute(
        text(
            "SELECT date_trunc('week', occurred_at AT TIME ZONE 'UTC')::date AS week, "
            "avg((outcome = 'ready')::int) AS rate "
            "FROM analytics_events WHERE event_name = 'suggestion_finished' "
            "AND occurred_at < '2026-09-21T00:00:00Z' GROUP BY 1"
        )
    ).all()
    lowest = min(weeks, key=lambda w: w.rate)
    assert str(lowest.week) == "2026-09-07"
    others = [w.rate for w in weeks if str(w.week) != "2026-09-07"]
    assert float(min(others)) - float(lowest.rate) >= 0.2


def test_unseed_removes_only_synthetic_rows(
    database_session: Session, database_engine: Engine
) -> None:
    real_user = create_user(database_session, uuid4(), "real-user", "hash")
    database_session.flush()
    record_event(database_session, "user_signed_up", real_user.id)
    database_session.commit()
    _run(database_engine, "seed_outbox.sql")
    _run(database_engine, "unseed.sql")
    assert _scalar(database_session, "SELECT count(*) FROM analytics_events") == 1
    assert (
        _scalar(database_session, "SELECT user_key FROM analytics_events")
        == real_user.public_id
    )
```

- [ ] **Step 2: Run and confirm failure.** `uv run --directory apps/api python -m pytest tests/test_hex_seed.py -q`. Expected: `FileNotFoundError` for `seed_outbox.sql`.

- [ ] **Step 3: Write `analytics_practice/seed_outbox.sql`.**

```sql
-- Phase 28b: seed deterministic synthetic events into the analytics outbox.
-- Invented users only (user_key prefix 00000000-0000-4000-8000-). The normal
-- export then loads them into BigQuery. Safe to rerun: existing events are skipped.
-- Remove with unseed.sql (plus the BigQuery DELETE in the Phase 28b guide).
CREATE OR REPLACE FUNCTION pg_temp.u(seed text) RETURNS double precision
LANGUAGE sql IMMUTABLE
AS $$ SELECT ('x' || substr(md5(seed), 1, 7))::bit(28)::int / 268435456.0 $$;

WITH
users AS (
  SELECT n,
    ('00000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid AS user_key,
    timestamptz '2026-07-27 00:00:00+00'
      + floor(pg_temp.u('signup-' || n) * 60 * 86400) * interval '1 second' AS signed_up_at
  FROM generate_series(1, 400) AS n
),
starts AS (
  SELECT n, user_key,
    signed_up_at + floor(pg_temp.u('start-delay-' || n) * 10 * 86400) * interval '1 second' AS started_at
  FROM users WHERE pg_temp.u('starts-' || n) < 0.7
),
completions AS (
  SELECT n, user_key,
    started_at + floor(pg_temp.u('complete-delay-' || n) * 3 * 86400) * interval '1 second' AS completed_at
  FROM starts WHERE pg_temp.u('completes-' || n) < 0.6
),
suggestions AS (
  SELECT s.n, s.user_key, k,
    s.started_at + floor(pg_temp.u('sugg-at-' || s.n || '-' || k) * 5 * 86400) * interval '1 second' AS suggested_at
  FROM starts AS s
  CROSS JOIN LATERAL generate_series(1, floor(pg_temp.u('sugg-count-' || s.n) * 9)::int) AS k
),
suggestion_outcomes AS (
  SELECT n, user_key, k, suggested_at,
    CASE
      WHEN pg_temp.u('outcome-' || n || '-' || k)
        < CASE WHEN date_trunc('week', suggested_at AT TIME ZONE 'UTC')::date = date '2026-09-07'
               THEN 0.45 ELSE 0.85 END THEN 'ready'
      WHEN pg_temp.u('failure-kind-' || n || '-' || k) < 0.8 THEN 'failed'
      ELSE 'expired'
    END AS outcome
  FROM suggestions
),
events AS (
  SELECT md5('hex-seed-user_signed_up-' || n)::uuid AS event_id, 'user_signed_up' AS event_name,
    user_key, NULL::uuid AS workflow_key, NULL::text AS outcome, signed_up_at AS occurred_at
  FROM users
  UNION ALL
  SELECT md5('hex-seed-workflow_started-' || n)::uuid, 'workflow_started', user_key,
    md5('hex-seed-workflow-' || n)::uuid, NULL, started_at
  FROM starts
  UNION ALL
  SELECT md5('hex-seed-workflow_completed-' || n)::uuid, 'workflow_completed', user_key,
    md5('hex-seed-workflow-' || n)::uuid, NULL, completed_at
  FROM completions
  UNION ALL
  SELECT md5('hex-seed-suggestion_finished-' || n || '-' || k)::uuid, 'suggestion_finished',
    user_key, md5('hex-seed-workflow-' || n)::uuid, outcome, suggested_at
  FROM suggestion_outcomes
)
INSERT INTO analytics_events (event_id, event_name, user_key, workflow_key, outcome, occurred_at)
SELECT event_id, event_name, user_key, workflow_key, outcome, occurred_at
FROM events
WHERE occurred_at < timestamptz '2026-09-25 00:00:00+00'
ON CONFLICT (event_id) DO NOTHING;
```

- [ ] **Step 4: Write `analytics_practice/unseed.sql`.**

```sql
-- Phase 28b: remove only synthetic seeded events from the outbox (prefix match).
DELETE FROM analytics_events
WHERE user_key::text LIKE '00000000-0000-4000-8000-%';
```

- [ ] **Step 5: Run the tests, then the full suite and lint.**

  Run `uv run --directory apps/api python -m pytest tests/test_hex_seed.py -q`, then `pnpm test:api` and `pnpm lint:api`. Expected: PASS.

  If the dip-week assertion fails on the generated distribution, adjust only the dip probability (0.45) and record a ruling. (`CREATE OR REPLACE FUNCTION pg_temp.u` already makes reruns in the same session safe, both in tests and in Cloud SQL Studio.)

- [ ] **Step 6: Commit.** `feat(analytics): add deterministic synthetic outbox seed and unseed scripts (phase 28b)`

### Task 3: Live seed and reference results

**Gate:** the learner runs the seed (it writes to the sandbox database) and triggers the export. This task needs the learner's confirmation at each step.

**Files:**

- Create: `analytics_practice/expected_hex.md`

- [ ] **Step 1:** Ask the learner to paste `seed_outbox.sql` into Cloud SQL Studio, run it, and report the inserted row count. Then have them run `gcloud scheduler jobs run analytics-export --location=us-west1 --project=fullstack-sandbox-tylervsd`, repeating it until the outbox `pending` count is 0. The export batch is 5000, so one run should do.
- [ ] **Step 2 (read-only BigQuery):** Query the curated views with the byte cap:
  - `SELECT * FROM analytics.activation_funnel ORDER BY cohort_week`
  - weekly success: `SELECT DATE_TRUNC(day, ISOWEEK) AS week, SUM(ready) AS ready, SUM(ready + failed + expired) AS finished, ROUND(SAFE_DIVIDE(SUM(ready), SUM(ready + failed + expired)), 4) AS success_rate FROM analytics.suggestion_success GROUP BY week ORDER BY week`
  - `SELECT * FROM analytics.data_freshness` (after the Terraform apply)
- [ ] **Step 3:** Ask the learner to run the two Phase 26 PostgreSQL reconciliation files in Cloud SQL Studio and paste the results. Confirm they match Step 2 exactly (real and synthetic events together).
- [ ] **Step 4:** Write `analytics_practice/expected_hex.md` with:
  - the funnel table
  - the weekly success table
  - the reconciliation confirmation
  - the checks-section totals: synthetic users 400; total distinct events from `SELECT COUNT(*) FROM analytics.events_deduped`
  - a note that real sandbox events are included, so small differences from these numbers are expected if the learner has used the app since
- [ ] **Step 5: Verify and commit.** Run `pnpm lint:markdown`, then commit `docs(analytics): record Phase 28b reference results from live seed`.

### Task 4: Walkthrough

**Files:**

- Create: `docs/guides/28b-hex-analytics.md`

- [ ] **Step 1: Write the guide** in the style of `28a-bigquery-analysis-tools.md`. Sections, in order:
  1. **Status** and links.
  2. **Why Hex** (versus 28a's tools): shared, parameterized apps on reviewed views.
  3. **The key exception (read first):**
     - why a key is needed (OAuth is Enterprise-only, with the source link)
     - scope, owner, expiry and deletion
     - the Accountable question
  4. **Setup:**
     1. Terraform: set `hex = {}`, plan (expect the service account, the dataset access, jobUser, the freshness view with its authorized access, and the dashboard normalization), and apply.
     2. Create the key:

        ```sh
        KEY="$(mktemp -d)/hex-reader.json"
        gcloud iam service-accounts keys create "$KEY" --iam-account="$(terraform -chdir=infra/terraform/sandbox output -raw hex_reader_email)"
        ```

     3. In Hex, go to **Settings → Data sources → Add → BigQuery**: project `fullstack-sandbox-tylervsd`, and paste the key JSON.
     4. Delete the key file: `rm -P "$KEY" && test ! -e "$KEY" && echo "key file deleted"`.
     5. Record the key ID from `gcloud iam service-accounts keys list --iam-account=... --managed-by=user`.
     6. In Hex, test the connection. Confirm that `analytics` tables appear and `analytics_raw` doesn't.
  5. **Seed synthetic data:** run `seed_outbox.sql` in Cloud SQL Studio, trigger the export, check `pending` = 0, and reconcile, pointing to `expected_hex.md`.
  6. **Build the app:**
     - Inputs: `start_date`, `end_date` (date inputs, defaults 2026-07-27 and today) and `include_incomplete` (checkbox, off).
     - Header SQL cell: `SELECT last_loaded_at FROM analytics.data_freshness`, shown with a single-value cell.
     - Funnel SQL cell:

       ```sql
       SELECT * FROM analytics.activation_funnel
       WHERE cohort_week BETWEEN {{ start_date }} AND {{ end_date }}
       {% if not include_incomplete %} AND cohort_complete {% endif %}
       ORDER BY cohort_week
       ```

       Add a chart of `completed_rate` by `cohort_week`, and the table.
     - Weekly success SQL cell (the Task 3 weekly query, filtered by the inputs, plus the `{% if not include_incomplete %} HAVING DATE_ADD(week, INTERVAL 7 DAY) <= CURRENT_DATE() {% endif %}` pattern), with a line chart.
     - Note: a live dashboard legitimately uses `CURRENT_DATE()`, unlike a reproducible reference answer. The inputs make the window explicit.
     - Markdown cell with the Phase 26 definitions verbatim, linking to the repo view SQL.
     - Note that the Jinja syntax (`{{ }}`, `{% if %}`) is Hex's SQL parameter syntax; confirm it in Hex's editor if the UI has changed.
  7. **Checks section:**
     - Totals compared with `expected_hex.md`.
     - **The duplicate drill:** in Cloud SQL Studio, run `UPDATE analytics_events SET exported_at = NULL WHERE user_key::text LIKE '00000000-0000-4000-8000-%' AND event_name = 'suggestion_finished'`, then re-export. Then:
       - the raw count inflates, seen in the BigQuery console as Owner
       - Hex's numbers are unchanged after a rerun
       - trying `SELECT COUNT(*) FROM analytics_raw.events` in Hex fails with access denied, which is expected
  8. **AI assistant:**
     - the data-handling paragraph from the spec
     - where to find and toggle AI in the workspace settings
     - the three prompts verbatim
     - a comparison table with the columns: prompt | table chosen | definition fidelity | used inputs? | matches reference? | uncertainty shown?
     - a "compared with Gemini (28a)" prompt list
  9. **Publish and share:** publish, open the app as a viewer, and note what's hidden. No public links.
  10. **Cost:**
      - BigQuery job history filtered by the `hex-reader` principal (**BigQuery → Job history → Project history**, filtered by user)
      - an optional per-user quota
      - no Hex schedules
  11. **Deletion drill:**
      1. `unseed.sql` in Cloud SQL Studio.
      2. BigQuery: `DELETE FROM analytics_raw.events WHERE STARTS_WITH(user_key, '00000000-0000-4000-8000-')`, byte-capped.
      3. Confirm the views dropped the synthetic rows.
      4. Rerun Hex, so its cached results refresh.
      5. `gcloud iam service-accounts keys delete KEY_ID --iam-account=...`
      6. Delete the Hex connection.
      7. Set `hex = null` and apply.
      8. Let the trial lapse or delete the workspace.
      9. Note BigQuery time travel and fail-safe.
  12. **Acceptance record** (the spec's rows, each `Pending`, with a key-lifecycle row: key ID, created, deleted), **Deferred, not passed**, and **Sources**.
- [ ] **Step 2: Verify.** `pnpm lint:markdown && pnpm lint:links`. Expected: clean.
- [ ] **Step 3: Commit.** `docs: add Phase 28b Hex analytics walkthrough`

### Task 5: Status updates

**Files:**

- Modify: `docs/curriculum-roadmap.md` (add a status line to the 28b entry with a spec and walkthrough link; update the intro sentence's 28b status to "implemented; learner walkthrough pending")
- Modify: `README.md` (status sentence)
- Modify: `docs/superpowers/specs/2026-09-24-hex-analytics-design.md` (status line)

- [ ] **Step 1: Make the edits.** Keep the 28b bullets unchanged; add one `- **Spec:**` line, as the 28a entry has.
- [ ] **Step 2: Verify.** `pnpm lint:markdown && pnpm lint:links`.
- [ ] **Step 3: Commit.** `docs: record Phase 28b status`
