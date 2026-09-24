# Phase 26: BigQuery product analytics

**Status:** Implemented and locally verified. Live acceptance is pending. [Spec](../superpowers/specs/2026-09-23-bigquery-analytics-design.md) and [implementation plan](../superpowers/plans/2026-09-23-bigquery-analytics.md).

## Why this phase

Every board deck has an activation rate. The useful question for a CTO isn't "what is the number?" but "can I trust it?":

- **Definition:** is the metric written down precisely enough that two people would compute the same answer?
- **Identity:** can one real-world event be counted twice?
- **Completeness:** can an event be lost, or invented by a request that later failed?
- **Reconciliation:** does the warehouse agree with the system of record?
- **Privacy:** what personal data had to be copied to answer the question?

This phase builds a small pipeline where you can answer each of these, then breaks it on purpose. It's sandbox practice, not Accountable's data design. Use invented data. [Phase 28](../curriculum-roadmap.md#28-hex-analytics-with-bigquery) puts Hex on top of the curated views built here.

```text
API / worker transaction ──► analytics_events (PostgreSQL outbox)
                                   │  every 15 min, Cloud Scheduler → worker
                                   ▼
                 BigQuery analytics_raw.events (at-least-once; may hold duplicates)
                                   │  authorized view, dedupe by event_id
                                   ▼
          analytics.events_deduped ─► activation_funnel, suggestion_success
```

Shared shell variables, matching earlier phases:

```sh
export CLOUD_PROJECT='<project-id>'
export CLOUD_REGION='<region>'
export API_URL='<stable API URL>'
```

## 1. Prerequisites

1. **Reinstall Terraform.** The Phase 18 binary lived in a removed worktree. Follow [Guide 18 §3](18-terraform.md#3-tooling-adc-and-backend-bootstrap) in your main checkout, so `terraform version` reports 1.14.7.
2. **Recreate local configuration.** Copy `infra/terraform/sandbox/backend.hcl.example` and `terraform.tfvars.example` to their ignored real names, and fill in real values from the live project. Run `terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl`, then `plan`. Before adding anything for this phase, the plan must show **no changes**. If it doesn't, stop and reconcile your tfvars with reality first. That no-change plan is also the Terraform drift check deferred in Phase 23.
3. **Deploy the code first.** Merge this phase's PR and approve the Phase 19 release. The migration adds `analytics_events`, and events start accumulating in PostgreSQL immediately. The worker gets the export route. Doing this before Terraform means the route already exists when Scheduler first calls it.
4. **Enable analytics.** In your tfvars, add `"bigquery.googleapis.com"` to `enabled_services`, and add:

   ```hcl
   analytics = {
     readers = ["user:<your Google account>"]
   }
   ```

5. **Review and apply the plan.** Expect exactly these, and reject anything else:
   - The BigQuery API service
   - 2 datasets: `analytics_raw` and `analytics`
   - 1 table: `analytics_raw.events`
   - 3 views
   - 3 dataset access grants (worker writer, your reader, authorized view)
   - 1 project IAM member: the worker gets `roles/bigquery.jobUser`
   - 1 Scheduler job: `analytics-export`
   - An in-place worker update adding `ANALYTICS_EVENTS_TABLE`

   Because the delivery pipeline owns the worker's image, the worker update must not change the image. Check that the image digest in the plan matches what's deployed.

## 2. The event contract

| Event | Written in the same transaction as | Extra fields |
| --- | --- | --- |
| `user_signed_up` | Account creation | — |
| `workflow_started` | A new guided workflow (not idempotent replays) | `workflow_key` |
| `workflow_completed` | The action that commits `COMPLETED` | `workflow_key` |
| `suggestion_finished` | A suggestion leaving `pending` for `ready` or `failed` | `workflow_key`, `outcome` |

`outcome` is `ready`, `failed` (provider or validation failure) or `expired` (passed its deadline or claim window, whether the sweep or a claim noticed). Superseded requests emit nothing.

Every column is an ID, an enum, a timestamp or an integer. The database has **no place to put a title, name or email**, so privacy is enforced by the table's structure, not by reviewers remembering. `user_key` is `users.public_id`. It's pseudonymous, not anonymous: it links back to a person, so it's still personal data.

**Why not log-based events?** Routing Phase 21 log lines to BigQuery takes almost no code, and many teams start there. But logs aren't transactional (a request can log "completed" and then roll back), they can be dropped or sampled, their schema is whatever JSON was written, and it's the path that leaked PII in the Phase 23 tabletop.

**Why not query PostgreSQL state directly?** State gives you "now", not history, and analytical scans compete with users for the transactional database. It remains a useful *reconciliation* tool, which is how section 5 uses it.

## 3. Metric definitions

These are the definitions. The SQL implements them; it doesn't replace them.

**Activation funnel**, per signup cohort:

- **Cohort:** users whose `user_signed_up` falls in an ISO week (Monday start, UTC).
- **Started:** distinct cohort users with `workflow_started` within 7 days after *their own* signup.
- **Completed:** distinct cohort users with `workflow_completed` within 7 days after their own signup.
- **Rates:** started ÷ signed up and completed ÷ signed up.
- **`cohort_complete`:** false until 14 days after the cohort week starts, when every member has had a full 7 days. Never compare an incomplete cohort with complete ones.
- **Not included:** accounts created before this phase was deployed have no signup event, and `users` has no creation timestamp to backfill from. The metric starts on the deployment date.

**Suggestion success rate**, per UTC day: `ready ÷ (ready + failed + expired)` over `suggestion_finished` events. Superseded requests are **excluded by definition**, because the user asked again and the system didn't fail. That's a choice a team should make explicitly and write down.

Implementations:

- BigQuery: [`events_deduped`](../../infra/terraform/sandbox/analytics/events_deduped.sql.tftpl), [`activation_funnel`](../../infra/terraform/sandbox/analytics/activation_funnel.sql.tftpl), [`suggestion_success`](../../infra/terraform/sandbox/analytics/suggestion_success.sql.tftpl)
- PostgreSQL reconciliation: [`postgres_activation_funnel.sql`](../../apps/api/analytics_sql/postgres_activation_funnel.sql), [`postgres_suggestion_success.sql`](../../apps/api/analytics_sql/postgres_suggestion_success.sql)

## 4. Generate data and check it flows

1. In the hosted app, sign up **two** new synthetic users. Complete two guided workflows with one user and start (but don't finish) one with the other. Request a few AI suggestions.
2. Check the outbox in Cloud SQL Studio:

   ```sql
   SELECT event_name, outcome, count(*), count(*) FILTER (WHERE exported_at IS NULL) AS pending
   FROM analytics_events GROUP BY 1, 2 ORDER BY 1, 2;
   ```

3. Run the export now instead of waiting up to 15 minutes:

   ```sh
   gcloud scheduler jobs run analytics-export --location="$CLOUD_REGION" --project="$CLOUD_PROJECT"
   ```

   The worker logs `analytics_export` with `selected`, `loaded` and `pruned` counts, never IDs. Rerun the outbox query: `pending` should be 0.
4. Query the curated view. Every query in this guide carries a byte cap:

   ```sh
   bq query --project_id="$CLOUD_PROJECT" --use_legacy_sql=false --maximum_bytes_billed=100000000 \
     "SELECT event_name, outcome, COUNT(*) AS n FROM \`$CLOUD_PROJECT.analytics.events_deduped\` GROUP BY 1, 2 ORDER BY 1, 2"
   ```

## 5. Reconcile against the source

Run each pair and compare the numbers. They must match exactly.

| BigQuery (curated view) | Cloud SQL Studio |
| --- | --- |
| `SELECT * FROM analytics.activation_funnel ORDER BY cohort_week` | Contents of `apps/api/analytics_sql/postgres_activation_funnel.sql` |
| `SELECT * FROM analytics.suggestion_success ORDER BY day` | Contents of `apps/api/analytics_sql/postgres_suggestion_success.sql` |

For the BigQuery side, prefix each view with your project, for example `` `PROJECT.analytics.activation_funnel` ``, and use the same `bq query ... --maximum_bytes_billed=100000000` form as above.

Then cross-check against **business state**, not just the outbox:

```sql
SELECT
  (SELECT count(*) FROM todo_workflows WHERE state = 'COMPLETED') AS completed_workflows,
  (SELECT count(*) FROM analytics_events WHERE event_name = 'workflow_completed') AS completed_events;
```

These differ by exactly the workflows completed before this phase was deployed. Explaining a difference like that is what reconciliation is for. A difference you *can't* explain means the pipeline is losing or inventing events.

## 6. Duplicate drill

A crash between "BigQuery load succeeded" and "PostgreSQL marked the rows exported" makes the next run load the same rows again. Simulate it:

1. In Cloud SQL Studio:

   ```sql
   UPDATE analytics_events SET exported_at = NULL
   WHERE event_name IN ('suggestion_finished', 'workflow_started');
   ```

2. Run `gcloud scheduler jobs run analytics-export ...` again.
3. Compare naive counts on the **raw** table (you can read it as project Owner; analysts can't) with the curated views:

   ```sh
   bq query --project_id="$CLOUD_PROJECT" --use_legacy_sql=false --maximum_bytes_billed=100000000 \
     "SELECT outcome, COUNT(*) AS naive, COUNT(DISTINCT event_id) AS distinct_events FROM \`$CLOUD_PROJECT.analytics_raw.events\` WHERE event_name = 'suggestion_finished' GROUP BY 1"
   ```

   - **Raw suggestion counts doubled.** If you'd reset only some outcomes, the naive success *rate* would have shifted too.
   - **`analytics.suggestion_success` is unchanged**, because it reads `events_deduped`.
   - **The funnel is unchanged even when computed from raw rows**, because it counts *distinct users*. Duplicated `workflow_started` events can't create a second user.

Record what changed and what didn't. The lesson: whether duplicates hurt depends on the metric's definition, not only on the pipeline. Ask any team which of their metrics are event counts and how those are deduplicated.

## 7. Cost controls

At sandbox volume, every query here scans kilobytes and costs effectively nothing. The controls matter when tables reach terabytes:

- **Byte cap per query.** Watch one get rejected:

  ```sh
  bq query --project_id="$CLOUD_PROJECT" --use_legacy_sql=false --maximum_bytes_billed=1 \
    "SELECT COUNT(*) FROM \`$CLOUD_PROJECT.analytics_raw.events\`"
  ```

  Expected result: an error saying the query exceeds the bytes-billed limit. The query doesn't run and costs nothing.
- **Partitioning and clustering.** The raw table is partitioned by `DATE(occurred_at)` and clustered by `event_name`, so queries that filter on those columns scan less.
- **Per-user daily quota.** In the console, go to **IAM & Admin → Quotas & System Limits**, filter for BigQuery "Query usage per day per user", and set a custom value. This is a project-level setting, so it's done manually. Check the exact console path in the current UI.

## 8. Retention and deletion

- Raw partitions expire after **400 days**. Exported outbox rows are pruned after **30 days**.
- The app has no account deletion feature. A real deletion request would need all of the following:
  1. Delete the user's rows by `user_key` from `analytics_raw.events` and from `analytics_events`.
  2. Account for BigQuery **time travel** (deleted data stays recoverable for up to 7 days) and **fail-safe** (a further 7 days).
  3. Find downstream copies: scheduled queries, exports, and Hex caches (Phase 28).

  Ask a team how long "deleted" actually takes in their warehouse.

## Acceptance record

| Check | Result |
| --- | --- |
| Terraform 1.14.7 reinstalled; pre-change plan shows no changes | Pending |
| Analytics plan reviewed (only expected resources) and applied | Pending |
| Events flowing: outbox `pending` reaches 0 after export | Pending |
| Curated views return results | Pending |
| Activation funnel reconciles with PostgreSQL | Pending |
| Suggestion success reconciles with PostgreSQL | Pending |
| Business-state difference explained | Pending |
| Duplicate drill: raw inflated, views unchanged, funnel unchanged | Pending |
| Byte cap rejection observed | Pending |

### Deferred, not passed

- Analyst access-denial check with a second account (learner choice). The Terraform tests check the grants.
- AI token/cost attribution (deferred from Phase 21).
- Latency metrics and client-side events.
- Account deletion feature.
- Sensitive Data Protection profiling of analytics and log datasets.
- Streaming ingestion (Storage Write API).

## Local verification

Observed on 2026-09-23 on `codex/phase-26-bigquery-analytics`: `pnpm test:api` 747 passed (event recording and rollback, database constraints, every suggestion terminal path, export marking/retry/batching/pruning, the worker route, and the PostgreSQL metric SQL); `pnpm lint:api` clean; `terraform test` for the sandbox root 53 passed, including disabled-by-default, grants, authorized view, dedupe SQL, schedule and worker environment. The BigQuery view SQL is not executed locally; it is verified during live acceptance.

## Sources

- [BigQuery partitioned tables](https://cloud.google.com/bigquery/docs/partitioned-tables) and [clustered tables](https://cloud.google.com/bigquery/docs/clustered-tables)
- [Authorized views](https://cloud.google.com/bigquery/docs/authorized-views)
- [Batch loading data](https://cloud.google.com/bigquery/docs/batch-loading-data)
- [Time travel and fail-safe](https://cloud.google.com/bigquery/docs/time-travel)
- [Custom cost controls](https://cloud.google.com/bigquery/docs/custom-quotas)
- [`bq query` flags](https://cloud.google.com/bigquery/docs/reference/bq-cli-reference#bq_query)
