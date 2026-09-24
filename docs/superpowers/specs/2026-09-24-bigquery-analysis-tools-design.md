# Phase 28a: BigQuery analysis tools

**Status:** Design and written spec approved by the learner on 2026-09-24. Implemented; learner walkthrough pending. Amendment: the generator clusters suggestions (0–8 within 5 days of starting) so the exercise 5 median varies; see [`expected.md`](../../../analytics_practice/expected.md).

**Context:** Based on `main` at `8396811`, after Phase 26. The learner will be CTO of Accountable, a pre-launch fintech that uses BigQuery and Hex. The original roadmap Phase 28 (Hex) is split: **28a** gives hands-on exposure to BigQuery's own analysis tools, and **28b** keeps the Hex scope. The goal of 28a is judgement, not tool mastery: verify a number yourself, know when a notebook is worth it, and catch AI-generated SQL that quietly changes a metric definition. Educational sandbox work with invented data only.

**Related:** [Implementation plan](../plans/2026-09-24-bigquery-analysis-tools.md), [walkthrough](../../guides/28a-bigquery-analysis-tools.md), [Phase 26 design](2026-09-23-bigquery-analytics-design.md), [curriculum](../../curriculum-roadmap.md).

## Scope and weighting

- **Part A, SQL in BigQuery Studio (about 60%):** six exercises with reference answers.
- **Part B, notebook (about 20%):** one BigQuery Studio (Colab Enterprise) notebook.
- **Part C, data canvas with Gemini (about 20%):** three natural-language questions whose generated SQL is checked against the reference answers.
- **Part D, real data:** the learner's own metric from Part A run against `analytics.events_deduped`, plus a "which tool when" table.

**Deferred (not passed):** a separate practice project for Gemini (learner choice; recommended for Accountable), scheduled queries and scheduled notebooks, BigQuery ML, Gemini Python code assist and data preparation, and Hex (Phase 28b).

## Decisions

1. **Practice data is synthetic and deterministic, in BigQuery**, not generated through the app and not a public dataset. The real pipeline and app database stay untouched.
2. **Exercises have fixed reference answers.** Randomness comes from `FARM_FINGERPRINT` of generated identifiers, never `RAND()`, so every run of the generator produces identical rows.
3. **Gemini in BigQuery is enabled in the existing sandbox project** (learner choice) by adding `cloudaicompanion.googleapis.com` to the local `enabled_services`. The control is a habit, not a boundary: practice prompts reference only `analytics_practice`, and every dataset in the sandbox holds invented data. The guide records the decision and the stronger recommendation for real data.
4. **The practice dataset is script-owned, not Terraform-owned.** It's disposable, created by `generate.sql` and removed by `drop.sql`. Terraform code is unchanged; only the learner's local tfvars and `terraform.tfvars.example` (a commented line) change.
5. **Exercises use a declared as-of date (`2026-09-24`)** instead of `CURRENT_DATE()`, so answers stay fixed and the guide can teach why "now" belongs in a metric's definition.

## Synthetic data

`analytics_practice.events` has the same columns and types as `analytics_raw.events`: `event_id`, `event_name`, `user_key`, `workflow_key`, `outcome`, `occurred_at`, `schema_version`, `loaded_at`. It is not partitioned (well under 1 MB; the guide explains that partitioning matters at scale).

- **Period:** 8 complete ISO weeks, Monday 2026-07-27 through Sunday 2026-09-20, plus a partial week 2026-09-21 to 2026-09-24.
- **Users:** about 400 synthetic users, with signups spread across the period. Each user's later behavior is derived from hashes of their key: some never start a workflow; of those who start, some complete; users request suggestions whose outcomes are mostly `ready`, with `failed` and occasional `expired`.
- **Deliberate messiness:**
  - about 5% of events duplicated with the same `event_id` and a later `loaded_at`
  - one week with a sharp suggestion-quality dip
  - the final cohort incomplete relative to the as-of date
  - some users with no events after signup
- All `event_name` and `outcome` values follow the Phase 26 contract.

## Files

| Path | Purpose |
| --- | --- |
| `analytics_practice/generate.sql` | Creates `analytics_practice` (in the sandbox region) and `events` with `CREATE OR REPLACE`; idempotent and deterministic |
| `analytics_practice/answers.sql` | Reference SQL for each exercise, labelled by exercise number |
| `analytics_practice/expected.md` | The reference results, recorded from a live run |
| `analytics_practice/drop.sql` | `DROP SCHEMA ... CASCADE` for the practice dataset only |
| `docs/guides/28a-bigquery-analysis-tools.md` | Walkthrough, exercises, notebook cells, canvas tasks, governance, cost, acceptance |

Plus the roadmap split (Phase 28 → 28a and 28b), README status, a commented `enabled_services` line in `terraform.tfvars.example`, and this spec and its plan.

## Exercises

**Part A, SQL:**

1. **Orientation and cost habits:** schema, row count, the bytes-processed estimate, and setting the console's maximum bytes billed.
2. **Duplicates:** naive row count vs `COUNT(DISTINCT event_id)`, then a reusable deduplicating CTE using `QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1`.
3. **Activation funnel:** the Phase 26 definition rebuilt on practice data, using the as-of date for cohort completeness.
4. **Week-over-week suggestion success:** `LAG()` for the change, find the dip week, and compare with a non-deduplicated version.
5. **A new metric, defined first:** "median suggestions requested per active user per week". The learner writes the definition before the SQL (`APPROX_QUANTILES`). `expected.md` gives the reference definition's result, and the guide shows how reasonable alternative definitions differ.
6. **Save and share:** a saved query, query history, and how a saved query differs from a view.

**Part B, notebook:** load the exercise 4 result with the BigQuery cell magic into a DataFrame, chart it, plot the per-user suggestion distribution as a histogram, then stop the runtime explicitly.

**Part C, data canvas:** three plain-English questions matching exercises 2–4. For each, record the SQL, whether it deduplicated, whether it counted events or users, how it treated "now", and whether its numbers match `expected.md`.

**Part D, real data:** run the exercise 5 metric against `analytics.events_deduped`, then fill in "which tool when" (SQL console, notebook, data canvas, Hex placeholder) for ad hoc questions, deep analysis, exploration, and shared reporting.

## Governance and cost

- **Gemini access:** enabling Gemini in BigQuery gives it access to the project's tables and query history within the user's permissions. Google states that prompts, responses, schema and data are not used for training unless the customer opts in, and lists SOC 1/2/3, ISO/IEC 27001 and HIPAA coverage for generally available features, with three named gaps: no per-location data residency, no audit logs of prompts and responses, and no Assured Workloads inclusion. The guide cites these, names how to turn features off (Gemini settings, or `gcloud services disable`; removing the API from Terraform alone leaves it enabled because `disable_on_destroy = false`), and recommends a separate approved-data project plus compliance review at Accountable.
- **Cost:** Gemini in BigQuery's generally available features carry no additional charge; queries are tiny and use a byte cap; the notebook runtime is billed while it runs and is stopped explicitly; `drop.sql` removes the practice data.

## Verification and acceptance

Implementation verification: markdown and link lint. With the learner's explicit approval (a write to the sandbox project), run `generate.sql` twice and compare a checksum query for identical output; confirm the duplicates, dip week and incomplete cohort exist; run `answers.sql` and record `expected.md` from the real output.

Learner acceptance, recorded in the guide: Gemini API enabled through a reviewed plan; exercises 1–6 matched or explained; notebook chart produced and runtime stopped; three canvas comparisons recorded; the learner's metric run on real data; "which tool when" completed; practice dataset optionally dropped.

## Sources checked on 2026-09-24

- [Gemini in BigQuery overview](https://docs.cloud.google.com/bigquery/docs/gemini-overview) and [Gemini for Google Cloud pricing](https://cloud.google.com/products/gemini/pricing)
- [Set up Gemini in BigQuery](https://docs.cloud.google.com/bigquery/docs/gemini-set-up) and [security, privacy, and compliance](https://docs.cloud.google.com/bigquery/docs/gemini-security-privacy-compliance)
- [How Gemini for Google Cloud uses your data](https://docs.cloud.google.com/gemini/docs/discover/data-governance)
- [Data canvas](https://docs.cloud.google.com/bigquery/docs/data-canvas)
- [BigQuery notebooks](https://docs.cloud.google.com/bigquery/docs/notebooks-introduction) and [Colab Enterprise pricing](https://cloud.google.com/colab/pricing)
