# Phase 28b: Hex analytics with BigQuery

**Status:** Design and written spec approved by the learner on 2026-09-24. Implemented; synthetic data seeded and reconciled; learner Hex walkthrough pending.

**Context:** Based on `main` at `373bb74`, after Phase 28a. The learner will be CTO of Accountable, which uses Hex. This phase connects a **personal 14-day Hex trial** (Team plan) to the Phase 26 curated `analytics` views through a least-privilege identity, builds a shared, parameterized metrics app, tries Hex's AI assistant against written definitions, and rehearses deletion including Hex's cached copies. The sandbox holds only invented data; this phase adds more of it.

**Related:** [Implementation plan](../plans/2026-09-24-hex-analytics.md), [walkthrough](../../guides/28b-hex-analytics.md), [Phase 26 design](2026-09-23-bigquery-analytics-design.md), [Phase 28a design](2026-09-24-bigquery-analysis-tools-design.md), [curriculum](../../curriculum-roadmap.md#28b-hex-analytics-with-bigquery).

## Decisions

1. **Authentication: a dedicated, tightly scoped service account with one JSON key, recorded as an exception.** Hex's per-user BigQuery OAuth is "available upon request for workspaces on the Enterprise plan"; a trial needs a service-account key. That breaks the curriculum's no-downloaded-keys rule, so the guide records owner, scope, reason, expiry (end of trial) and deletion steps. The key is created with `gcloud`, never Terraform (keys in Terraform state are secrets in state).
2. **Hex reads only the curated `analytics` views.** No access to `analytics_raw`, practice data or anything else.
3. **Synthetic data enters through the real pipeline.** A Postgres script seeds backdated synthetic events into the `analytics_events` outbox; the normal export carries them to BigQuery. Reconciliation between Postgres and BigQuery keeps working, and cleanup doubles as a deletion drill.
4. **One Hex project published as an app**, with inputs, definitions, freshness, and a checks section kept out of the published app.
5. **Hex's AI assistant is enabled** for this lesson (learner choice; data is invented), with its data handling recorded, and is evaluated against written definitions like Gemini in 28a.

## 1. Identity and access (Terraform)

An opt-in `hex` object variable in the sandbox root, default `null`, in `infra/terraform/sandbox/hex.tf`. It requires `analytics` to be enabled.

- `google_service_account.hex_reader` (default account ID `hex-reader`).
- `google_bigquery_dataset_access`: `roles/bigquery.dataViewer` on the `analytics` dataset for the Hex account (the same pattern as Phase 26; never mixed with dataset IAM resources).
- `google_project_iam_member`: `roles/bigquery.jobUser` for the Hex account. It's required to run queries and grants no data access.
- A new view, `analytics.data_freshness`, returning one row: `MAX(loaded_at) AS last_loaded_at` from `analytics_raw.events`, authorized on the raw dataset like `events_deduped`. It lives in `analytics.tf` because it belongs to the curated surface whether or not Hex is enabled.

The Hex account gets no basic project role, so BigQuery's default project-role dataset access (Phase 26) doesn't reach it. Terraform tests assert: nothing when disabled; the dataset-scoped viewer grant; jobUser only; no access to `analytics_raw`; the freshness view authorized and exposing no event columns.

## 2. The key exception

Created outside Terraform:

1. `gcloud iam service-accounts keys create "$TMPDIR/hex-reader.json" --iam-account=...`
2. Paste it into Hex's BigQuery connection.
3. Delete the local file and verify it's gone.
4. At the end: `gcloud iam service-accounts keys delete`, delete the Hex connection, then set `hex = null` and apply.

The guide lists the key's ID, creation date and planned deletion date in its acceptance record. It includes the question to ask at Accountable: per-user OAuth, or a shared key, and if a key, how is it scoped, owned and rotated?

## 3. Synthetic data through the pipeline

- `analytics_practice/seed_outbox.sql` (PostgreSQL) inserts into `analytics_events`, using the 28a generator's rules: 400 users; 8 ISO weeks from 2026-07-27 plus a partial week to 2026-09-24; the 2026-09-07 quality dip; an incomplete final cohort; users without events after signup. Randomness comes from `md5`-based hashing, never `random()`. `user_key` values start with `00000000-0000-4000-8000-`. `event_id`s are deterministic UUIDs. `ON CONFLICT (event_id) DO NOTHING` makes a rerun harmless. It contains no duplicates (the outbox forbids them; duplicates arise only from re-export, as in Phase 26).
- It's run in Cloud SQL Studio, followed by the export (the Scheduler job or `gcloud scheduler jobs run analytics-export`).
- `analytics_practice/unseed.sql` (PostgreSQL) deletes outbox rows with the synthetic prefix. The guide pairs it with a BigQuery `DELETE` on `analytics_raw.events` for the same prefix.
- **Reference results** are recorded from a live run into `analytics_practice/expected_hex.md`, with learner approval (the seed writes to the sandbox database). They cover:
  - funnel and weekly success from the curated views
  - Postgres reconciliation (the Phase 26 SQL files)
  - totals for the checks section
- The business-state check (`todo_workflows`) excludes the synthetic prefix, and the guide says so.

## 4. The Hex project

"Product metrics (sandbox)", on the BigQuery connection:

1. **Header:** a "synthetic + real sandbox data" label and data freshness from `analytics.data_freshness`.
2. **Inputs:** a date range, and an "include incomplete periods" toggle (default off). All SQL cells use them through Hex parameters.
3. **Activation funnel:** from `analytics.activation_funnel`, as a chart and a table.
4. **Weekly suggestion success:** from `analytics.suggestion_success`, aggregated to ISO weeks, as a chart showing the dip.
5. **Definitions:** the Phase 26 definitions verbatim, with links to the view SQL in the repo.
6. **Checks (not in the published app):**
   - totals compared with `expected_hex.md`
   - **The duplicate drill:** the learner resets `exported_at` on some synthetic rows and re-exports. The raw table inflates (visible in the BigQuery console as Owner), while Hex's numbers are unchanged, and Hex can't query the raw table.
7. **AI assistant (not in the published app):** three prompts:
   - "What was the weekly suggestion success rate?"
   - "Show the activation funnel by signup week."
   - "Do users whose first AI suggestion fails complete their workflow less often?"

   For each, record the table chosen, definition fidelity (users vs events, order, 7-day window), use of inputs, agreement with the references, and presentation of uncertainty, then compare with the 28a Gemini findings.
8. **Publish and share:** publish the app, view it as a viewer, and note what's hidden. Sharing stays inside the trial workspace; no public links.

## 5. Governance, cost and retention

- **Hex AI data handling** (from Hex's docs): project code, cell outputs (query results), schema metadata, prompts and responses are sent to its LLM providers (OpenAI, Anthropic). The providers don't train on customer data and operate under zero data retention by default. Unlike Gemini in 28a, **result data is included**, which is the question to take to Accountable. The guide names where to turn AI features off.
- **Cost:** queries run as the Hex account and are billed to the sandbox project, negligible at this size. The guide shows how to find them in BigQuery job history by principal, and an optional per-user query quota. Hex scheduled runs stay off. The trial needs no card.
- **The deletion drill:**
  1. Run `unseed.sql` and the BigQuery `DELETE`.
  2. Confirm the views changed.
  3. Rerun the Hex project, so the cached results refresh.
  4. Delete the key and the connection.
  5. Let the trial lapse, or delete the workspace.

  Record what "fully deleted" required, including BigQuery time travel (up to 7 days) and fail-safe.

## Testing and acceptance

**Local:**

- Terraform mock tests for `hex` and `data_freshness`.
- PostgreSQL tests for `seed_outbox.sql`, on the existing pytest database:
  - deterministic (a second run inserts 0 rows)
  - obeys the outbox constraints
  - produces the planned shape: 400 users, the dip week lowest, the partial-week signups
- A test that `unseed.sql` removes only prefixed rows.
- Markdown and link checks.

**Live, learner-run and recorded:**

- Terraform plan reviewed and applied.
- The key created, pasted in, and the local file deletion verified.
- Seeded, exported and reconciled.
- The app built with working inputs.
- Hex's numbers match `expected_hex.md`.
- The duplicate drill passed.
- The AI assistant comparison recorded.
- Published and viewed as a viewer.
- The deletion drill done, and the key deleted.

**Deferred (not passed):** per-user OAuth (Enterprise), a separate billing project, scheduled runs and notifications, the semantic layer / dbt, and a Hex exploration notebook.

## Sources checked on 2026-09-24

- [Hex OAuth data connections](https://learn.hex.tech/docs/connect-to-data/data-connections/oauth-data-connections) and [data connections](https://learn.hex.tech/docs/category/data-connections)
- [Hex pricing](https://hex.tech/pricing/) and [compute limits](https://learn.hex.tech/docs/administration/workspace_settings/compute)
- [Hex AI data privacy](https://learn.hex.tech/docs/hex-magic/magic-data-privacy) and [data privacy FAQ](https://learn.hex.tech/docs/trust/data-privacy-and-usage-faq)
