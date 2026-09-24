# Phase 28a: BigQuery analysis tools

**Status:** Implemented; learner walkthrough pending. [Spec](../superpowers/specs/2026-09-24-bigquery-analysis-tools-design.md), [implementation plan](../superpowers/plans/2026-09-24-bigquery-analysis-tools.md), and practice files in [`analytics_practice/`](../../analytics_practice/).

## Why this phase

Phase 26 built trustworthy metrics. This phase is about **using** them: answering a question yourself, knowing when a notebook is worth opening, and recognizing when AI-written SQL quietly answers a *different* question. The goal is judgement, not mastery of every console button. [Phase 28b](../curriculum-roadmap.md#28b-hex-analytics-with-bigquery) then puts Hex on the same foundations.

You'll work mostly in **BigQuery Studio** ([console](https://console.cloud.google.com/bigquery?project=fullstack-sandbox-tylervsd)) against a **synthetic practice dataset** with known answers, then run your own metric on the real Phase 26 views.

| Part | Tool | Share |
| --- | --- | --- |
| A | SQL in BigQuery Studio: six exercises | ~60% |
| B | A BigQuery Studio notebook | ~20% |
| C | Data canvas with Gemini: checking AI-generated SQL | ~20% |
| D | Your metric on real data, plus "which tool when" | short |

## 1. Setup

### 1.1 The Gemini decision (read before enabling)

Data canvas's natural-language features and BigQuery's SQL generation use **Gemini in BigQuery**. You're enabling it in the sandbox project. Know what that means:

- **What it can access:** the project's tables and query history, limited only by the permissions of whoever is using it. You're project Owner, so that includes `analytics_raw` and `analytics`, not just the practice data.
- **Training:** Google states that prompts, responses, schema and data aren't used to train its models unless you opt in.
- **Compliance:** Google notes that Gemini in BigQuery doesn't support the same compliance and security offerings as BigQuery itself.
- **The control you're relying on:** a habit. Prompts reference only `analytics_practice`, and every dataset in this sandbox holds invented data. It's a habit, not a boundary.
- **Turning it off:** use **Gemini settings** in BigQuery Studio to turn features off, or remove the API from `enabled_services` and apply.
- **At Accountable:** with real PII, don't do this. Put AI-assisted analysis in a **separate project that holds only approved data**, and get the compliance owner to review the caveat above first.

### 1.2 Enable the API

In your main checkout's `infra/terraform/sandbox/terraform.tfvars`, add `"cloudaicompanion.googleapis.com"` to `enabled_services`, then:

```sh
PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox plan
```

Expect exactly one addition, `google_project_service.required["cloudaicompanion.googleapis.com"]`, plus the known cosmetic dashboard normalization. Apply it. The first time you open data canvas, BigQuery Studio may ask you to confirm Gemini features. That's the console side of the same decision.

### 1.3 Create the practice data

```sh
bq query --project_id=fullstack-sandbox-tylervsd --location=us-west1 --use_legacy_sql=false \
  --maximum_bytes_billed=100000000 < analytics_practice/generate.sql
```

You can also paste [`generate.sql`](../../analytics_practice/generate.sql) into a console query tab and run it. It's safe to run again: it always rebuilds the same rows. To confirm you have the reference data, run check 1 of [`checks.sql`](../../analytics_practice/checks.sql). It should report **1767 rows, checksum `-6779663904789774770`**.

### 1.4 Set a byte cap in the console

In the query editor, open **More → Query settings → Advanced options → Maximum bytes billed** and set it to `100000000` (100 MB). Before running anything, glance at the editor's "This query will process…" estimate. That's the habit to build.

## 2. "Now" belongs in the definition

Every exercise starts with:

```sql
DECLARE as_of DATE DEFAULT DATE '2026-09-24';
```

and uses `as_of` wherever you'd be tempted to write `CURRENT_DATE()`. A metric pinned to "today" gives a different answer each time you run it, so nobody can reproduce last week's board number. Pinning the as-of date makes a result reproducible and makes "is this week complete?" an explicit question.

## 3. Part A: SQL exercises

Try each one yourself first. The reference SQL is in [`answers.sql`](../../analytics_practice/answers.sql) and the results in [`expected.md`](../../analytics_practice/expected.md).

### Exercise 1: Orientation

Open `analytics_practice.events`. Read the **Schema** tab, then **Preview** (free: it doesn't run a query). Write a query that returns the row count and the first and last `occurred_at`. Note the bytes-processed estimate before you run it.

### Exercise 2: Find the duplicates

Compare `COUNT(*)` with `COUNT(DISTINCT event_id)`. Then write a reusable deduplicating CTE (a named subquery you can build on in later queries):

```sql
WITH d AS (
  SELECT * FROM analytics_practice.events
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
)
SELECT COUNT(*) FROM d
```

`QUALIFY` filters on a window function, like `HAVING` does for aggregates. The `WHERE TRUE` is there because BigQuery requires a `WHERE`, `GROUP BY` or `HAVING` alongside `QUALIFY`.

### Exercise 3: Rebuild the activation funnel

Using the [Phase 26 definition](26-bigquery-analytics.md#3-metric-definitions), compute per signup ISO week: signed up, started within 7 days, completed within 7 days, and the completed rate. Replace `CURRENT_DATE()` with `as_of` in `cohort_complete`. Which cohorts are incomplete, and why would their low rates mislead a reader?

### Exercise 4: Week-over-week suggestion success

For each ISO week, compute `ready ÷ all suggestion_finished` on deduplicated data, and the change from the previous week with `LAG(...) OVER (ORDER BY week)`. Find the bad week. Then add a naive (non-deduplicated) rate next to it. How much do duplicates distort it here, and why so little?

### Exercise 5: Define a new metric, then write it

"Median suggestions requested per active user per week."

1. **Write the definition in words first.** Who counts as "active"? What counts as a "suggestion requested"? Is it by week or a rolling 7 days? Is the current week complete?
2. Then write the SQL. `APPROX_QUANTILES(x, 2)[OFFSET(1)]` is the median.

The reference definition is in `expected.md`. Alternatives that are just as reasonable give different numbers:

- counting requests instead of finished outcomes
- counting every user with a started workflow as active, including zero-suggestion weeks
- using a rolling 7-day window

That's the lesson: **the number is meaningless without its definition.**

### Exercise 6: Save and share

- **Save** one of your queries (**Save query**), and open **Query history** to see what ran and how many bytes each query processed.
- **Saved query vs view:** a saved query is a *text* you or your team can reopen and run. A view is a *table-like object* other queries and tools (like Hex) can build on, and access can be granted to it on its own. Metrics other people depend on belong in views, as in Phase 26.

## 4. Part B: A notebook

1. In BigQuery Studio, **Create notebook**. It runs on a Colab Enterprise runtime.
2. **Cell 1: load the weekly success rate.**

   ```python
   %%bigquery weekly --project fullstack-sandbox-tylervsd
   WITH d AS (
     SELECT * FROM analytics_practice.events
     WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
   )
   SELECT DATE_TRUNC(DATE(occurred_at), ISOWEEK) AS week,
     SAFE_DIVIDE(COUNTIF(outcome = 'ready'), COUNT(*)) AS success_rate
   FROM d WHERE event_name = 'suggestion_finished'
   GROUP BY week ORDER BY week
   ```

3. **Cell 2: chart it.**

   ```python
   weekly.plot(x="week", y="success_rate", marker="o", ylim=(0, 1))
   ```

4. **Cell 3: suggestions per user.**

   ```python
   %%bigquery per_user --project fullstack-sandbox-tylervsd
   WITH d AS (
     SELECT * FROM analytics_practice.events
     WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY loaded_at) = 1
   )
   SELECT user_key, COUNT(*) AS suggestions
   FROM d WHERE event_name = 'suggestion_finished'
   GROUP BY user_key
   ```

5. **Cell 4: the distribution**, which SQL shows badly and a chart shows at a glance.

   ```python
   per_user["suggestions"].plot.hist(bins=range(0, 10))
   ```

6. **Stop the runtime.** Use the runtime menu at the top right of the notebook (**Disconnect and delete runtime**, or the equivalent in the current UI), then confirm no runtime is listed as running. The runtime is billed while it runs, and it only shuts itself down after a long idle period.

**When a notebook beats SQL:** multi-step analysis, charts, distributions, and mixing data with explanation. **When it's overkill:** a single number, or a check you'll repeat, where a saved query or a view is simpler and cheaper.

## 5. Part C: Data canvas and AI-generated SQL

Create a **data canvas** in BigQuery Studio and ask these three questions, **word for word**:

1. "How many rows and how many unique event_id values are in analytics_practice.events?"
2. "For each signup week in analytics_practice.events, how many users signed up, and how many started and completed a workflow within 7 days of their own signup?"
3. "What was the weekly suggestion success rate in analytics_practice.events?"

For each one, open the SQL Gemini generated and fill in:

| Question | Deduplicated by `event_id`? | Counted events or users? | How was "now" / week completeness handled? | Matches `expected.md`? |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

Look especially for: missing deduplication, `COUNT(*)` where the definition needs distinct users, a calendar week instead of "7 days after *their own* signup", and `CURRENT_DATE()`. Plausible SQL that silently answers a different question is the main risk of AI-assisted analysis. The defense is written definitions and a habit of checking.

## 6. Part D: Real data and "which tool when"

Run **E5R** from `answers.sql`, your exercise 5 metric against the real `analytics.events_deduped`, in the console. Compare it with the practice numbers: real data is sparse and gives noisy medians. That's normal for a pre-launch product and a reason not to over-read early dashboards.

Then fill in the table below from your own experience in Parts A–C. There's no answer key; it's your note for Accountable.

| Tool | Ad hoc question | Deep analysis | Exploration | Shared reporting |
| --- | --- | --- | --- | --- |
| SQL console | | | | |
| Notebook | | | | |
| Data canvas | | | | |
| Hex (Phase 28b) | | | | |

## 7. Cost and cleanup

- **Queries:** the practice data is under 1 MB, so every query here processes kilobytes and costs effectively nothing. Keep the byte cap anyway.
- **Gemini in BigQuery:** its generally available features (SQL assistance, data canvas) carry no additional charge.
- **Notebook runtime:** billed while it runs. Stop it (Part B, step 6).
- **Cleanup when you're done:**

  ```sh
  bq query --project_id=fullstack-sandbox-tylervsd --location=us-west1 --use_legacy_sql=false \
    < analytics_practice/drop.sql
  ```

  This removes only `analytics_practice`. `generate.sql` can rebuild it identically any time.

## Acceptance record

| Check | Result |
| --- | --- |
| Gemini API enabled through a reviewed plan | Pending |
| Practice data generated; checksum matches | Pending |
| Exercises 1–6 matched `expected.md`, or differences explained | Pending |
| Notebook chart and histogram produced; runtime stopped | Pending |
| Three data canvas questions compared; discrepancies recorded | Pending |
| Exercise 5 metric run on real data | Pending |
| "Which tool when" table filled in | Pending |
| Practice dataset dropped (optional) | Pending |

### Deferred, not passed

- A separate practice project for Gemini (learner choice; recommended at Accountable).
- Scheduled queries and scheduled notebooks.
- BigQuery ML.
- Gemini Python code assist and data preparation.
- Hex (Phase 28b).

## Local verification

Observed on 2026-09-24 on `codex/phase-28a-bigquery-tools`:

- Both scripts passed dry-run validation.
- `generate.sql` ran twice with identical results (1767 rows, checksum `-6779663904789774770`), with learner approval for the sandbox write.
- `checks.sql` passed: no events after the cut-off; duplicate share 0.044; dip week 0.544 against at least 0.808 elsewhere; 400/250/139 users/starters/completers; 30 partial-week signups.
- `answers.sql` produced `expected.md`, and its consistency checks held.
- Markdown and link checks pass.

## Sources

- [Gemini in BigQuery overview](https://docs.cloud.google.com/bigquery/docs/gemini-overview) and [Gemini for Google Cloud pricing](https://cloud.google.com/products/gemini/pricing)
- [Set up Gemini in BigQuery](https://docs.cloud.google.com/bigquery/docs/gemini-set-up) and [security, privacy, and compliance](https://docs.cloud.google.com/bigquery/docs/gemini-security-privacy-compliance)
- [How Gemini for Google Cloud uses your data](https://docs.cloud.google.com/gemini/docs/discover/data-governance)
- [Data canvas](https://docs.cloud.google.com/bigquery/docs/data-canvas)
- [BigQuery notebooks](https://docs.cloud.google.com/bigquery/docs/notebooks-introduction) and [Colab Enterprise pricing](https://cloud.google.com/colab/pricing)
- [`QUALIFY`](https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#qualify_clause) and [`APPROX_QUANTILES`](https://cloud.google.com/bigquery/docs/reference/standard-sql/approximate_aggregate_functions#approx_quantiles)
