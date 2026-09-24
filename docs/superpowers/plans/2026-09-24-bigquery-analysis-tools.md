# Phase 28a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic synthetic practice data, reference answers and a walkthrough for hands-on BigQuery Studio SQL, a notebook, and data canvas with Gemini, and split the roadmap's Phase 28 into 28a and 28b.

**Architecture:** One BigQuery script generates `analytics_practice.events` (same schema as `analytics_raw.events`) from hashes of generated identifiers, so every run yields identical rows. Reference SQL and recorded results give each exercise a known answer. No application or Terraform code changes.

**Tech Stack:** BigQuery Standard SQL scripting, `bq` CLI, BigQuery Studio (console, Colab Enterprise notebook, data canvas), Markdown.

**Spec:** [Phase 28a design](../specs/2026-09-24-bigquery-analysis-tools-design.md)

## Global Constraints

- **Project and region:** `fullstack-sandbox-tylervsd`, dataset location `us-west1`. **Dataset:** `analytics_practice`, table `events`.
- **Schema, same as `analytics_raw.events`:** `event_id STRING`, `event_name STRING`, `user_key STRING`, `workflow_key STRING`, `outcome STRING`, `occurred_at TIMESTAMP`, `schema_version INT64`, `loaded_at TIMESTAMP`.
- **Period:** from 2026-07-27T00:00:00Z. No event at or after 2026-09-25T00:00:00Z. **As-of date:** `DATE '2026-09-24'`.
- **Randomness:** only `FARM_FINGERPRINT`-based, never `RAND()`.
- **Users:** exactly 400, `user_key = FORMAT('00000000-0000-4000-8000-%012d', n)`.
- **Dip week:** ISO week starting 2026-09-07.
- **Duplicate share:** about 5%, same `event_id`, `loaded_at` 60 minutes later.
- **Event names and outcomes** follow the Phase 26 contract: `user_signed_up`, `workflow_started`, `workflow_completed`, `suggestion_finished` with `ready`/`failed`/`expired`.
- **Every `bq` command** uses `--project_id=fullstack-sandbox-tylervsd --use_legacy_sql=false --maximum_bytes_billed=100000000`.
- **Stop and ask the learner before the first command that writes to the project** (`generate.sql` without `--dry_run`). Dry runs are read-only.
- **Invented data only.** Keep `.pi/` and the untracked root `AGENTS.md` untouched.
- **Checks:** `pnpm lint:markdown && pnpm lint:links`.

## Review Focus

1. **Re-running the generator** must produce byte-identical results (the same checksum). Pinned in Task 2.
2. **No event after the as-of cut-off.** No `workflow_completed` or `suggestion_finished` may fall after 2026-09-24 even though delays extend past it. Pinned in Task 2.
3. **Duplicates must not change deduplicated answers.** Reference answers read deduplicated data except where the exercise compares naive with deduplicated. Pinned in Task 3.
4. **The dip must be visible in the deduplicated weekly success rate**, not only in raw counts. Pinned in Task 2.
5. **`drop.sql` must only drop `analytics_practice`**, never another dataset. Pinned in Task 1 by inspection and dry run.

---

### Task 1: Generator and drop scripts (validated by dry run)

**Files:**

- Create: `analytics_practice/generate.sql`
- Create: `analytics_practice/drop.sql`

**Interfaces:**

- Produces: the table `analytics_practice.events` with the schema from Global Constraints. The seed strings `signup-`, `starts-`, `start-delay-`, `completes-`, `complete-delay-`, `sugg-count-`, `sugg-at-`, `outcome-`, `failure-kind-` and `duplicate-` are all part of the deterministic contract.

- [ ] **Step 1: Write `analytics_practice/generate.sql`**

```sql
-- Phase 28a practice data: deterministic synthetic events, invented users only.
-- Same schema as analytics_raw.events. Re-running rebuilds identical rows.
-- Randomness comes from FARM_FINGERPRINT of fixed seeds (never RAND()).
CREATE SCHEMA IF NOT EXISTS analytics_practice
OPTIONS (
  location = 'us-west1',
  description = 'Phase 28a synthetic practice data; disposable (drop.sql).'
);

CREATE TEMP FUNCTION u(seed STRING) AS (
  ABS(MOD(FARM_FINGERPRINT(seed), 1000000)) / 1000000
);

CREATE TEMP FUNCTION uuid_of(seed STRING) AS (
  FORMAT(
    '%s-%s-%s-%s-%s',
    SUBSTR(TO_HEX(MD5(seed)), 1, 8),
    SUBSTR(TO_HEX(MD5(seed)), 9, 4),
    SUBSTR(TO_HEX(MD5(seed)), 13, 4),
    SUBSTR(TO_HEX(MD5(seed)), 17, 4),
    SUBSTR(TO_HEX(MD5(seed)), 21, 12)
  )
);

CREATE TEMP FUNCTION add_days_fraction(ts TIMESTAMP, fraction FLOAT64, days INT64) AS (
  TIMESTAMP_ADD(ts, INTERVAL CAST(FLOOR(fraction * days * 86400) AS INT64) SECOND)
);

CREATE OR REPLACE TABLE analytics_practice.events AS
WITH
users AS (
  SELECT
    n,
    FORMAT('00000000-0000-4000-8000-%012d', n) AS user_key,
    add_days_fraction(TIMESTAMP '2026-07-27 00:00:00+00', u(CONCAT('signup-', n)), 60) AS signed_up_at
  FROM UNNEST(GENERATE_ARRAY(1, 400)) AS n
),
starts AS (
  SELECT n, user_key, add_days_fraction(signed_up_at, u(CONCAT('start-delay-', n)), 10) AS started_at
  FROM users
  WHERE u(CONCAT('starts-', n)) < 0.7
),
completions AS (
  SELECT n, user_key, add_days_fraction(started_at, u(CONCAT('complete-delay-', n)), 3) AS completed_at
  FROM starts
  WHERE u(CONCAT('completes-', n)) < 0.6
),
suggestions AS (
  SELECT
    s.n,
    s.user_key,
    k,
    add_days_fraction(s.started_at, u(CONCAT('sugg-at-', s.n, '-', k)), 14) AS at
  FROM starts AS s,
    UNNEST(GENERATE_ARRAY(1, CAST(FLOOR(u(CONCAT('sugg-count-', s.n)) * 6) AS INT64))) AS k
),
suggestion_outcomes AS (
  SELECT
    n, user_key, k, at,
    CASE
      WHEN u(CONCAT('outcome-', n, '-', k))
        < IF(DATE_TRUNC(DATE(at), ISOWEEK) = DATE '2026-09-07', 0.45, 0.85) THEN 'ready'
      WHEN u(CONCAT('failure-kind-', n, '-', k)) < 0.8 THEN 'failed'
      ELSE 'expired'
    END AS outcome
  FROM suggestions
),
events AS (
  SELECT uuid_of(CONCAT('user_signed_up-', n)) AS event_id, 'user_signed_up' AS event_name,
    user_key, CAST(NULL AS STRING) AS workflow_key, CAST(NULL AS STRING) AS outcome,
    signed_up_at AS occurred_at
  FROM users
  UNION ALL
  SELECT uuid_of(CONCAT('workflow_started-', n)), 'workflow_started',
    user_key, uuid_of(CONCAT('workflow-', n)), NULL, started_at
  FROM starts
  UNION ALL
  SELECT uuid_of(CONCAT('workflow_completed-', n)), 'workflow_completed',
    user_key, uuid_of(CONCAT('workflow-', n)), NULL, completed_at
  FROM completions
  UNION ALL
  SELECT uuid_of(CONCAT('suggestion_finished-', n, '-', k)), 'suggestion_finished',
    user_key, uuid_of(CONCAT('workflow-', n)), outcome, at
  FROM suggestion_outcomes
),
as_of AS (
  SELECT * FROM events WHERE occurred_at < TIMESTAMP '2026-09-25 00:00:00+00'
)
SELECT event_id, event_name, user_key, workflow_key, outcome, occurred_at,
  1 AS schema_version, TIMESTAMP_ADD(occurred_at, INTERVAL 10 MINUTE) AS loaded_at
FROM as_of
UNION ALL
SELECT event_id, event_name, user_key, workflow_key, outcome, occurred_at,
  1, TIMESTAMP_ADD(occurred_at, INTERVAL 70 MINUTE)
FROM as_of
WHERE u(CONCAT('duplicate-', event_id)) < 0.05;
```

`CONCAT` with an `INT64` argument relies on BigQuery's implicit coercion. If the dry run rejects it, wrap each integer in `CAST(... AS STRING)` and record that as a ruling.

- [ ] **Step 2: Write `analytics_practice/drop.sql`**

```sql
-- Removes only the Phase 28a practice dataset. Never edit this to another dataset.
DROP SCHEMA IF EXISTS analytics_practice CASCADE;
```

- [ ] **Step 3: Dry-run both scripts** (read-only):

```bash
bq query --project_id=fullstack-sandbox-tylervsd --use_legacy_sql=false --maximum_bytes_billed=100000000 --dry_run < analytics_practice/generate.sql
bq query --project_id=fullstack-sandbox-tylervsd --use_legacy_sql=false --dry_run < analytics_practice/drop.sql
```

Expected: both report a successful validation with no syntax errors. A multi-statement script may report only 0 bytes.

- [ ] **Step 4: Commit**

```bash
git add analytics_practice/generate.sql analytics_practice/drop.sql
git commit -m "feat(analytics): add deterministic Phase 28a practice data generator"
```

### Task 2: Live generation, determinism and property checks

**Gate:** ask the learner for explicit approval before Step 2. It creates the dataset `analytics_practice` in `fullstack-sandbox-tylervsd`.

**Files:**

- Create: `analytics_practice/checks.sql`

**Interfaces:**

- Consumes: the Task 1 table.
- Produces: `checks.sql`, a checksum query plus four property queries. The guide references it, and the determinism result is recorded in the ledger for Task 3.

- [ ] **Step 1: Write `analytics_practice/checks.sql`.** Before generation it fails with "Not found: Dataset". That's the RED state.

```sql
-- Phase 28a generator checks. Run after generate.sql.
-- 1. Determinism checksum: identical across regenerations.
SELECT 'checksum' AS check_name, COUNT(*) AS n_rows,
  BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(e))) AS checksum
FROM analytics_practice.events AS e;

-- 2. Cut-off: must be 0.
SELECT 'after_cutoff' AS check_name, COUNTIF(occurred_at >= TIMESTAMP '2026-09-25 00:00:00+00') AS n
FROM analytics_practice.events;

-- 3. Duplicates: expect roughly 5% of distinct events.
SELECT 'duplicates' AS check_name, COUNT(*) - COUNT(DISTINCT event_id) AS duplicate_rows,
  ROUND((COUNT(*) - COUNT(DISTINCT event_id)) / COUNT(DISTINCT event_id), 3) AS duplicate_share
FROM analytics_practice.events;

-- 4. Dip: the 2026-09-07 week's deduplicated success rate is clearly below every other complete week.
WITH d AS (
  SELECT * FROM analytics_practice.events
  WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
)
SELECT 'weekly_success' AS check_name, DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS week,
  ROUND(SAFE_DIVIDE(COUNTIF(outcome = 'ready'), COUNT(*)), 3) AS success_rate, COUNT(*) AS n
FROM d WHERE event_name = 'suggestion_finished'
GROUP BY week ORDER BY week;

-- 5. Shape: users, starters, completers, users without events after signup, partial-week signups.
WITH d AS (
  SELECT * FROM analytics_practice.events
  WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
)
SELECT 'shape' AS check_name,
  COUNT(DISTINCT IF(event_name = 'user_signed_up', user_key, NULL)) AS users,
  COUNT(DISTINCT IF(event_name = 'workflow_started', user_key, NULL)) AS starters,
  COUNT(DISTINCT IF(event_name = 'workflow_completed', user_key, NULL)) AS completers,
  COUNT(DISTINCT IF(event_name = 'user_signed_up' AND DATE(occurred_at) >= DATE '2026-09-21', user_key, NULL)) AS partial_week_signups
FROM d;
```

Run it: `bq query ... < analytics_practice/checks.sql`. Expected: FAIL with `Not found: Dataset fullstack-sandbox-tylervsd:analytics_practice`.

- [ ] **Step 2 (after approval): Generate**

`bq query --project_id=fullstack-sandbox-tylervsd --use_legacy_sql=false --maximum_bytes_billed=100000000 < analytics_practice/generate.sql`

- [ ] **Step 3: Run the checks and record the output** (the full `bq` output goes to the ledger workspace). Expected:
  - `after_cutoff` is 0.
  - `duplicate_share` is between 0.03 and 0.07.
  - The 2026-09-07 week's success rate is at least 0.2 below every other week's.
  - `users = 400`.
  - `0 < completers < starters < users`.
  - `partial_week_signups > 0`.

  If any check fails, adjust only the generator's probabilities, rerun Steps 2–3, and record a ruling.
- [ ] **Step 4: Regenerate and compare checksums.** Run Step 2 again, then check 1. Expected: identical `n_rows` and `checksum`.
- [ ] **Step 5: Commit `checks.sql`.** Record both checksums in the ledger.

### Task 3: Reference answers and expected results

**Files:**

- Create: `analytics_practice/answers.sql`
- Create: `analytics_practice/expected.md`

**Interfaces:**

- Consumes: `analytics_practice.events` from Task 2, and the real `analytics.events_deduped` (Phase 26) for exercise 5R.
- Produces: exercise labels E1–E5 and E5R, which Task 4's guide references.

- [ ] **Step 1: Write `analytics_practice/answers.sql`.** Each exercise is a standalone statement, starting with `DECLARE as_of DATE DEFAULT DATE '2026-09-24';`.

```sql
-- Phase 28a reference answers. Try each exercise yourself first.
DECLARE as_of DATE DEFAULT DATE '2026-09-24';

-- E1 Orientation: rows and date range.
SELECT COUNT(*) AS n_rows, MIN(occurred_at) AS first_event, MAX(occurred_at) AS last_event
FROM analytics_practice.events;

-- E2 Duplicates: naive rows vs distinct events.
SELECT COUNT(*) AS n_rows, COUNT(DISTINCT event_id) AS distinct_events,
  COUNT(*) - COUNT(DISTINCT event_id) AS duplicate_rows
FROM analytics_practice.events;

-- E3 Activation funnel (Phase 26 definition, as-of date instead of CURRENT_DATE).
WITH d AS (
  SELECT * FROM analytics_practice.events
  WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
),
signups AS (
  SELECT user_key, occurred_at AS signed_up_at,
    DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS cohort_week
  FROM d WHERE event_name = 'user_signed_up'
),
reached AS (
  SELECT s.user_key, s.cohort_week,
    LOGICAL_OR(e.event_name = 'workflow_started') AS started,
    LOGICAL_OR(e.event_name = 'workflow_completed') AS completed
  FROM signups AS s
  LEFT JOIN d AS e
    ON e.user_key = s.user_key
   AND e.event_name IN ('workflow_started', 'workflow_completed')
   AND e.occurred_at >= s.signed_up_at
   AND e.occurred_at < TIMESTAMP_ADD(s.signed_up_at, INTERVAL 7 DAY)
  GROUP BY s.user_key, s.cohort_week
)
SELECT cohort_week, COUNT(*) AS signed_up, COUNTIF(started) AS started_7d,
  COUNTIF(completed) AS completed_7d,
  ROUND(SAFE_DIVIDE(COUNTIF(completed), COUNT(*)), 4) AS completed_rate,
  DATE_ADD(cohort_week, INTERVAL 14 DAY) <= as_of AS cohort_complete
FROM reached GROUP BY cohort_week ORDER BY cohort_week;

-- E4 Week-over-week suggestion success, deduplicated vs naive.
WITH weekly AS (
  SELECT DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS week,
    COUNT(DISTINCT IF(outcome = 'ready', event_id, NULL)) AS ready_dedup,
    COUNT(DISTINCT event_id) AS total_dedup,
    COUNTIF(outcome = 'ready') AS ready_naive,
    COUNT(*) AS total_naive
  FROM analytics_practice.events
  WHERE event_name = 'suggestion_finished'
  GROUP BY week
)
SELECT week,
  ROUND(SAFE_DIVIDE(ready_dedup, total_dedup), 4) AS success_rate,
  ROUND(SAFE_DIVIDE(ready_dedup, total_dedup)
    - LAG(SAFE_DIVIDE(ready_dedup, total_dedup)) OVER (ORDER BY week), 4) AS change_vs_prior_week,
  ROUND(SAFE_DIVIDE(ready_naive, total_naive), 4) AS naive_success_rate,
  DATE_ADD(week, INTERVAL 7 DAY) <= as_of AS week_complete
FROM weekly ORDER BY week;

-- E5 Reference definition: in each ISO week, an active user is one with at least
-- one suggestion_finished event that week; report the median count per active user.
WITH d AS (
  SELECT * FROM analytics_practice.events
  WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
),
per_user_week AS (
  SELECT DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS week, user_key, COUNT(*) AS suggestions
  FROM d WHERE event_name = 'suggestion_finished'
  GROUP BY week, user_key
)
SELECT week, COUNT(*) AS active_users,
  APPROX_QUANTILES(suggestions, 2)[OFFSET(1)] AS median_suggestions,
  DATE_ADD(week, INTERVAL 7 DAY) <= as_of AS week_complete
FROM per_user_week GROUP BY week ORDER BY week;

-- E5R The same definition on real data (already deduplicated by the view).
WITH per_user_week AS (
  SELECT DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS week, user_key, COUNT(*) AS suggestions
  FROM analytics.events_deduped WHERE event_name = 'suggestion_finished'
  GROUP BY week, user_key
)
SELECT week, COUNT(*) AS active_users,
  APPROX_QUANTILES(suggestions, 2)[OFFSET(1)] AS median_suggestions
FROM per_user_week GROUP BY week ORDER BY week;
```

- [ ] **Step 2: Run `answers.sql` and write `analytics_practice/expected.md`.** Record each exercise's output as a Markdown table, headed `E1`…`E5`. For E5R, write "varies with your real data; compare with your own run". Add a line recording the generator checksum from Task 2. Also note that `APPROX_QUANTILES` is approximate and exact at this size, and that E4's naive and deduplicated rates may differ only slightly, because duplicates are spread evenly across outcomes (the Phase 26 lesson).
- [ ] **Step 3: Consistency checks.** E2's `distinct_events` plus `duplicate_rows` must equal E1's `n_rows`. E3's total `signed_up` must be 400. E4's lowest `success_rate` must be the 2026-09-07 week. Expected: all three hold.
- [ ] **Step 4: Commit** `answers.sql` and `expected.md`.

### Task 4: Walkthrough

**Files:**

- Create: `docs/guides/28a-bigquery-analysis-tools.md`

- [ ] **Step 1: Write the guide.** Sections, in this order:
  1. **Status line** linking the spec, plan and `analytics_practice/`.
  2. **Why this phase:** judgement over mastery.
  3. **Setup:**
     - **Gemini decision:** what's enabled; what Gemini can access (tables and query history within your permissions); no training use unless opted in; the compliance caveat; the habit relied on; how to turn it off; the Accountable recommendation (a separate approved-data project plus a compliance review).
     - **Enable the API:** add `"cloudaicompanion.googleapis.com"` to local `enabled_services`, then plan and apply. Expected: exactly one `google_project_service` addition, plus the known dashboard normalization.
     - **Run `generate.sql`** with the `bq` command from Task 2, or paste it into the console.
     - **Set the console's maximum bytes billed.**
  4. **The as-of date:** why "now" belongs in a metric definition.
  5. **Part A: exercises 1–6.** Each gets the question, hints (including `QUALIFY`, `LAG`, `APPROX_QUANTILES`) and a pointer to `answers.sql` / `expected.md`. Exercise 5 asks for the written definition first and lists alternative definitions: count requests instead of terminal outcomes; count started users with zero suggestions as active; weekly vs 7-day rolling windows. Exercise 6 covers saved queries vs views and query history.
  6. **Part B: notebook.**
     - Create a notebook in BigQuery Studio.
     - Cell 1: `%%bigquery weekly` with the E4 deduplicated SELECT.
     - Cell 2: `weekly.plot(x="week", y="success_rate", marker="o", ylim=(0, 1))`.
     - Cell 3: `%%bigquery per_user`, counting deduplicated `suggestion_finished` events per `user_key`.
     - Cell 4: `per_user["suggestions"].plot.hist(bins=range(0, 8))`.
     - How to stop the runtime and confirm it's stopped.
     - When notebooks beat SQL.
  7. **Part C: data canvas.** Three verbatim prompts:
     - "How many rows and how many unique event_id values are in analytics_practice.events?"
     - "For each signup week in analytics_practice.events, how many users signed up, and how many started and completed a workflow within 7 days of their own signup?"
     - "What was the weekly suggestion success rate in analytics_practice.events?"

     Include a table to fill in: prompt | SQL deduplicated? | events or users? | how "now" was handled | matches expected.md?
  8. **Part D:** run E5R on real data, then the "which tool when" table (rows: SQL console, notebook, data canvas, Hex (28b); columns: ad hoc question, deep analysis, exploration, shared reporting). Its cells start blank for the learner.
  9. **Cost and cleanup:** negligible query cost; notebook runtime billed while running; Gemini's generally available features cost nothing extra; `drop.sql`.
  10. **Acceptance record** (rows from the spec, each `Pending`), **Deferred, not passed** (from the spec), and **Sources** (from the spec).
- [ ] **Step 2: Verify.** `pnpm lint:markdown && pnpm lint:links`. Expected: clean.
- [ ] **Step 3: Commit.**

### Task 5: Roadmap split, status and examples

**Files:**

- Modify: `docs/curriculum-roadmap.md` (rename section 28 to "28a. BigQuery analysis tools" with a Learning goal / Visible outcome / Verification entry drawn from the spec; add "28b. Hex analytics with BigQuery" carrying the existing Phase 28 bullets unchanged; update the intro sentence mentioning Phase 28, and add a 28a status line)
- Modify: `README.md` (status sentence)
- Modify: `infra/terraform/sandbox/terraform.tfvars.example` (after `"bigquery.googleapis.com"`, add `# "cloudaicompanion.googleapis.com", # Phase 28a Gemini in BigQuery (optional)`)
- Modify: `docs/superpowers/specs/2026-09-24-bigquery-analysis-tools-design.md` (status line)

- [ ] **Step 1: Make the edits.** Keep existing anchors that other documents link to working, and check with `grep -rn "28-hex-analytics-with-bigquery" docs README.md`. Update each link to the new 28b anchor.
- [ ] **Step 2: Verify.** `pnpm lint:markdown && pnpm lint:links`. Expected: clean. The tfvars example is only a comment change, so there's nothing for Terraform to validate.
- [ ] **Step 3: Commit.**
