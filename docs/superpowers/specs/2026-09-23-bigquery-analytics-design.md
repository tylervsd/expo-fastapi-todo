# Phase 26: BigQuery product analytics

**Status:** Design and written spec approved by the learner on 2026-09-23. Implemented, deployed, and signed off by the learner on 2026-09-24 with deferrals recorded in the [acceptance record](../../guides/26-bigquery-analytics.md#acceptance-record). See [amendments](#amendments-during-planning-and-implementation).

**Context:** Based on `main` at `8094722`, following Phase 23. The learner will be CTO of Accountable, a pre-launch fintech handling customer PII that uses BigQuery and Hex. The goal is to judge whether product metrics are *trustworthy*: correctly defined, deduplicated, reconciled with the source, and free of unnecessary personal data. Phase 28 (Hex) builds on the curated views defined here. Phase 25 (Pub/Sub) was skipped, so ingestion must not depend on it. Educational sandbox work, not Accountable's data design or compliance evidence. Use invented data.

**Related:** [Implementation plan](../plans/2026-09-23-bigquery-analytics.md), [walkthrough](../../guides/26-bigquery-analytics.md), [curriculum](../../curriculum-roadmap.md#26-bigquery-product-analytics).

## Scope

Core: trustworthy metrics — event identity, deduplication, written metric definitions, and reconciliation against PostgreSQL. Built in: privacy by schema (no free text), pseudonymous keys, curated views as the only analyst surface. Minimum safety mechanics: partitioning, clustering, byte caps.

**Deferred (not passed):** AI token/cost attribution (from Phase 21), latency metrics, client-side events, cancelled-workflow and todo events, account deletion feature, Sensitive Data Protection profiling, live analyst access-denial check (learner choice; Terraform tests cover IAM), BigQuery Storage Write API or streaming ingestion.

## Approaches considered

1. **Transactional outbox + scheduled batch load — selected.** Events are rows written in the same transaction as the business change; a scheduled export loads them with a free BigQuery load job. No phantom or lost events; at-least-once loading produces real duplicates handled by `event_id`.
2. **Structured logs → Cloud Logging sink → BigQuery.** Little code, but not transactional, can drop entries, has an implicit schema, and is the pattern behind the Phase 23 tabletop's PII leak. Explained in the guide as a common starting point, not used.
3. **Federated query / snapshot of PostgreSQL state.** Always matches the source but has no history, no duplicate lesson, and puts analytical load on the transactional database. Used only in spirit: reconciliation queries run directly in Cloud SQL Studio.

## 1. Event contract and outbox

Additive migration creates `analytics_events`:

| Column | Type | Rule |
| --- | --- | --- |
| `id` | bigint identity, PK | Export order only |
| `event_id` | uuid, unique, not null | Event identity; dedupe key |
| `event_name` | text, not null | Check: `user_signed_up`, `workflow_started`, `workflow_completed`, `suggestion_finished` |
| `user_key` | uuid, not null | `users.public_id`; never username, name or email |
| `workflow_key` | uuid, null | Workflow public ID where relevant |
| `outcome` | text, null | Check: non-null and one of `ready`, `failed`, `expired` exactly when `event_name = 'suggestion_finished'` |
| `occurred_at` | timestamptz, not null | Default `now()` (transaction time) |
| `schema_version` | smallint, not null | Default 1 |
| `exported_at` | timestamptz, null | Set after a successful load |

A partial index supports `WHERE exported_at IS NULL ORDER BY id`.

One helper, `record_event(session, event_name, user_key, *, workflow_key=None, outcome=None)`, adds a row to the caller's session; it never commits. It is called inside the same transaction as:

- **`user_signed_up`:** account creation in signup.
- **`workflow_started`:** workflow creation.
- **`workflow_completed`:** the transition that commits `COMPLETED`.
- **`suggestion_finished`:** every transition of a suggestion request from `pending` to `ready` or `failed`. The expiry sweep records `outcome = 'expired'`; other failures record `failed`. `superseded` records nothing.

If the transaction rolls back, the event does not exist. Every column is an identifier, enum, timestamp or integer, so free text cannot enter the pipeline. `user_key` is still pseudonymous personal data; access and retention rules apply.

## 2. Export to BigQuery

`POST /internal/analytics/export` on the worker, called by Cloud Scheduler every 15 minutes with OIDC, following the Phase 20 expiry-sweep pattern. Each run:

1. Selects up to 5000 rows `WHERE exported_at IS NULL ORDER BY id`.
2. Loads them into `analytics_raw.events` with a BigQuery load job (newline-delimited JSON, explicit schema, `WRITE_APPEND`) and waits up to 120 seconds for completion.
3. Only after the load succeeds, sets `exported_at = now()` on exactly those rows, in one transaction.
4. Deletes rows with `exported_at < now() - interval '30 days'`.
5. Logs `analytics_export` with counts only (selected, loaded, pruned) through the existing `log_event`.

A load failure or timeout leaves rows unexported; the endpoint returns 500 and Scheduler retries later. A crash between steps 2 and 3 reloads the batch next time, producing duplicates in BigQuery by design. The export is not made exactly-once; consumers deduplicate by `event_id`. Configuration: `ANALYTICS_EVENTS_TABLE` (`project.dataset.table`) on the worker only. If unset, the endpoint returns 503 and loads nothing; events still accumulate in the outbox. Adds one dependency: the official BigQuery Python client, pinned like the existing Google clients.

## 3. BigQuery layout and access

Opt-in `analytics` Terraform setting in the existing sandbox root, default off, in `infra/terraform/sandbox/analytics.tf`, located in the application's region:

- **`analytics_raw` dataset**, table `events`: schema mirrors the outbox minus `id` and `exported_at`, plus `loaded_at`. Partitioned by `DATE(occurred_at)`, clustered by `event_name`, partition expiration 400 days. The worker identity gets `roles/bigquery.dataEditor` on this dataset only, plus project `roles/bigquery.jobUser` (required to run load jobs). No human reader grants.
- **`analytics` dataset:** views authorized on `analytics_raw`:
  - `events_deduped`: one row per `event_id` (earliest `loaded_at`).
  - `activation_funnel`: per signup ISO week (UTC).
  - `suggestion_success`: per UTC day.
- **Readers:** a variable list of members gets `roles/bigquery.dataViewer` on `analytics` only (set to the learner for now; a Google Group at Accountable). Hex uses this surface in Phase 28.
- Cloud Scheduler job for the export, and the worker's `ANALYTICS_EVENTS_TABLE` environment variable.

Terraform tooling must be reinstalled (Guide 18 §3) and local `backend.hcl`/`terraform.tfvars` recreated from their examples; the guide makes this a prerequisite.

## 4. Metric definitions

Stated verbatim in the guide and implemented by the views:

- **Activation funnel.** Cohort: users with `user_signed_up` in an ISO week (UTC). *Started*: distinct cohort users with `workflow_started` within 7 days after their own signup. *Completed*: distinct cohort users with `workflow_completed` within 7 days after signup. Output per cohort: `signed_up`, `started_7d`, `completed_7d`, both rates, and `cohort_complete` (false until 7 days after the cohort week ends). Accounts created before deployment have no signup event and are in no cohort; there is no backfill because `users` has no creation timestamp.
- **Suggestion success rate.** Per UTC day of `occurred_at`: `ready / (ready + failed + expired)` over `suggestion_finished` events. Superseded requests are excluded by definition: the user asked again, the system did not fail.

## 5. Drill, reconciliation and cost

**Duplicate drill:** generate a few signups, completed workflows and suggestion outcomes; let the export run. In Cloud SQL Studio, reset `exported_at` to NULL on some already-exported rows (simulating a crash after load), then trigger the export. Compare a naive `COUNT(*)` on the raw table with the views: raw suggestion counts inflate and the rate can shift, while the distinct-user funnel does not move. The lesson: whether duplicates hurt depends on the metric definition, not only the pipeline.

**Reconciliation:** paired queries in the guide — BigQuery views versus Cloud SQL Studio queries on `analytics_events`, and versus business state (for example, completed workflows since deployment). They must agree.

**Cost:** every guide query runs with `--maximum_bytes_billed=100000000`; the guide includes one query that exceeds the cap to show rejection. A per-user daily query quota is a manual console step. Sandbox costs are negligible; the guide explains why caps matter at scale.

## 6. Retention and deletion

Raw partitions expire at 400 days; exported outbox rows are pruned after 30 days. No account deletion feature exists; the guide documents what one would require: delete by `user_key` from the raw table and outbox, account for BigQuery time travel (up to 7 days) and fail-safe (7 more days), and find downstream copies (scheduled queries, exports, Hex caches).

## Testing and acceptance

Local, test-first on the existing pytest + PostgreSQL setup:

- Each event is written with its business change and absent after rollback; exact counts per path, including every suggestion terminal path, `expired` from the sweep, and nothing for `superseded`.
- The database rejects unknown event names and invalid outcome combinations.
- Export, with the BigQuery client faked at its boundary: marks rows only after a successful load, leaves them on failure/timeout, respects the batch limit, prunes old exported rows, returns 503 when unconfigured, and requires the worker's existing OIDC authentication.
- Reconciliation SQL for PostgreSQL runs against fixture events, including an incomplete cohort and superseded suggestions.
- Terraform mock tests: disabled by default creates nothing; worker is the only raw writer; readers only on `analytics`; views authorized on the raw dataset; the view SQL deduplicates by `event_id`.

BigQuery view SQL cannot run locally; it is validated live (dry run, then results matched against reconciliation queries).

Live acceptance, learner-run and recorded like prior phases: Terraform reinstalled and a reviewed plan applied; events flowing and views returning results; reconciliation matching; duplicate drill observed; byte cap rejection observed. The analyst access-denial check is deferred by learner choice.

## Amendments during planning and implementation

- **Load wait is 45 seconds, not 120.** The worker's Cloud Run request timeout is 60 seconds, so the load must complete inside it. Scheduler's attempt deadline is 60 seconds.
- **`expired` means "passed its deadline or claim window" on any path.** The same condition is detected either by the expiry sweep or when a worker claims the row, so both record `expired`. Provider and validation failures record `failed`.
- **`record_event` takes the internal `owner_id`** and resolves `user_key` from `users.public_id` inside the insert. The stored data is unchanged.
- **Worker authentication is Cloud Run IAM** (Scheduler's OIDC identity is the only invoker). Terraform tests check the Scheduler identity; the application has no in-app authentication check to unit test.
- **All dataset grants use `google_bigquery_dataset_access`**, and only `events_deduped` is an authorized view on the raw dataset. The other views read `events_deduped` inside the curated dataset.
- **The load job relies on the Terraform-owned table schema** instead of repeating it in the job configuration. Appending JSON that doesn't match the table fails the load, so rows stay unexported.
- **Rollout order:** apply Terraform first with Guide 20's worker revision workaround, then release the code, so the promoted worker revision carries `ANALYTICS_EVENTS_TABLE`.
- **Raw dataset access:** Terraform adds no human grants, but BigQuery's default project-role access (Viewer reads, Editor writes) still applies to both datasets. The guide states this instead of claiming analysts cannot read raw data.
- **Reconciliation window:** exact matching holds only within the 30-day outbox retention window and after pending exports reach 0. The business-state check compares BigQuery (400-day retention) with `todo_workflows`.
