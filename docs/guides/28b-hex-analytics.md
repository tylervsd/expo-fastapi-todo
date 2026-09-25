# Phase 28b: Hex analytics with BigQuery

**Status:** Implemented; synthetic data seeded and reconciled; learner Hex walkthrough pending. [Spec](../superpowers/specs/2026-09-24-hex-analytics-design.md), [implementation plan](../superpowers/plans/2026-09-24-hex-analytics.md), [reference results](../../analytics_practice/expected_hex.md).

## Why Hex

In 28a you answered questions yourself, with SQL, a notebook and data canvas. Hex's job is different: **turning reviewed analysis into something other people use** without seeing code, with inputs they can change and definitions next to every number. That's why Accountable pays for it. This phase connects a personal **14-day Hex trial** to your curated `analytics` views, builds a small metrics app, tries Hex's AI assistant, and then deletes everything properly.

## 1. The key exception (read first)

This curriculum hasn't used a downloaded service-account key since Phase 18. It makes one exception here, and a good team would document an exception like this the same way:

| | |
| --- | --- |
| **Why** | Hex's per-user BigQuery OAuth, where each person queries as themselves, is [available on the Enterprise plan](https://learn.hex.tech/docs/connect-to-data/data-connections/oauth-data-connections). A trial needs a service-account key. |
| **Scope** | `hex-reader` can read **only** the curated `analytics` dataset and run query jobs. No `analytics_raw`, no other data, no basic project role. |
| **Where the key lives** | Only inside Hex's connection settings. It exists on your disk for a moment and is then deleted. Never in Git, never in a notebook cell. |
| **Owner** | You. |
| **Expiry** | The end of the trial. Record the planned date in the acceptance record. |
| **Deletion** | `gcloud iam service-accounts keys delete` (section 9), then remove the Hex connection and the identity. |

**The question for Accountable:** *"Does Hex connect with per-user OAuth or a shared key? If a key: which identity, what can it read, who owns it, when was it last rotated?"* A shared key that can read raw PII tables is the finding to look for.

## 2. Setup

Run these from your **main checkout** after this phase's PR is merged and pulled.

1. **Terraform.** In `infra/terraform/sandbox/terraform.tfvars`, add `hex = {}`. Then:

   ```sh
   PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox plan
   ```

   Expect: `google_service_account.hex_reader`, `google_bigquery_dataset_access.hex_reader`, `google_project_iam_member.hex_job_user`, the `data_freshness` view and its authorized access, plus the known dashboard normalization. Nothing destroyed, no worker change. Apply.

2. **Create the key** in a temporary folder:

   ```sh
   KEY="$(mktemp -d)/hex-reader.json"
   HEX_SA="$(PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox output -raw hex_reader_email)"
   gcloud iam service-accounts keys create "$KEY" --iam-account="$HEX_SA"
   ```

3. **Connect Hex.** In your trial workspace, open **Settings → Data sources → Add → BigQuery** (the menu wording may differ slightly). Set the project to `fullstack-sandbox-tylervsd` and paste the contents of the key file. Save and test the connection.
4. **Delete the key file right away** and confirm it's gone:

   ```sh
   rm -P "$KEY" && test ! -e "$KEY" && echo "key file deleted"
   ```

5. **Record the key ID** for the acceptance record:

   ```sh
   gcloud iam service-accounts keys list --iam-account="$HEX_SA" --managed-by=user
   ```

6. **Check the scope from Hex's side.** In the connection's schema browser, `analytics` and its views should be visible, and `analytics_raw` should not be.

## 3. Synthetic data

*Already done on 2026-09-24 and reconciled; see [`expected_hex.md`](../../analytics_practice/expected_hex.md).* To repeat it:

1. Paste [`seed_outbox.sql`](../../analytics_practice/seed_outbox.sql) into Cloud SQL Studio and run it. It inserts 1,756 events for 400 invented users. Running it again inserts nothing.
2. Export: `gcloud scheduler jobs run analytics-export --location=us-west1 --project=fullstack-sandbox-tylervsd`, then confirm `pending` is 0.
3. Reconcile with the two Phase 26 PostgreSQL queries.

The synthetic events travelled through the real outbox and export, so every Phase 26 guarantee still holds. They're marked by the `user_key` prefix `00000000-0000-4000-8000-`. The business-state check against `todo_workflows` doesn't apply to them, because they have no workflow rows.

## 4. Build the app

Create a project named **"Product metrics (sandbox)"** using the BigQuery connection.

1. **Header.** A Markdown cell: *"Synthetic + real sandbox data. Not for decisions."* Then a SQL cell:

   ```sql
   SELECT last_loaded_at FROM analytics.data_freshness
   ```

   Show it with a single-value display as *"Data loaded up to …"*. A reader should always know how fresh a number is.

2. **Inputs:** `start_date` (date, default 2026-07-27), `end_date` (date, default today) and `include_incomplete` (checkbox, off).

3. **Activation funnel.** A SQL cell:

   ```sql
   SELECT * FROM analytics.activation_funnel
   WHERE cohort_week BETWEEN {{ start_date }} AND {{ end_date }}
   {% if not include_incomplete %} AND cohort_complete {% endif %}
   ORDER BY cohort_week
   ```

   Add a chart of `completed_rate` by `cohort_week`, and show the table under it.

4. **Weekly suggestion success.** A SQL cell:

   ```sql
   SELECT DATE_TRUNC(day, ISOWEEK) AS week,
          SUM(ready) AS ready,
          SUM(ready + failed + expired) AS finished,
          ROUND(SAFE_DIVIDE(SUM(ready), SUM(ready + failed + expired)), 4) AS success_rate
   FROM analytics.suggestion_success
   WHERE day BETWEEN {{ start_date }} AND {{ end_date }}
   GROUP BY week
   {% if not include_incomplete %} HAVING DATE_ADD(week, INTERVAL 7 DAY) <= CURRENT_DATE() {% endif %}
   ORDER BY week
   ```

   Add a line chart. The 2026-09-07 dip should be obvious.

   `{{ }}` and `{% if %}` are Hex's Jinja parameter syntax, and Hex passes input values as query parameters, not pasted text. Check the syntax in Hex's SQL editor if the UI has changed. A live dashboard can legitimately use `CURRENT_DATE()`; unlike 28a's reproducible reference answers, the inputs make the window explicit.

5. **Definitions.** A Markdown cell with the [Phase 26 definitions](26-bigquery-analytics.md#3-metric-definitions), word for word, linking to the view SQL in the repo. Every number on the page should have its definition next to it.

With the inputs at their defaults and `include_incomplete` on, your numbers should match `expected_hex.md`.

## 5. Checks (not in the published app)

Put these in a separate section and leave it out of the published app.

1. **Totals.** `SELECT COUNT(*) FROM analytics.events_deduped` should give **1773**, or more if you've used the app since.
2. **The duplicate drill.** Simulate a crash after a load:
   1. In Cloud SQL Studio:

      ```sql
      UPDATE analytics_events SET exported_at = NULL
      WHERE user_key::text LIKE '00000000-0000-4000-8000-%' AND event_name = 'suggestion_finished';
      ```

   2. Re-export, and confirm `pending` is back to 0.
   3. In the **BigQuery console** (as Owner), the raw table has inflated:

      ```sql
      SELECT COUNT(*) AS rows, COUNT(DISTINCT event_id) AS distinct_events FROM analytics_raw.events
      ```

   4. In **Hex**, rerun the project. Every number is unchanged, because the views deduplicate.
   5. In **Hex**, try `SELECT COUNT(*) FROM analytics_raw.events`. It should fail with an access-denied error. That's the governance working: Hex can't even reach the naive number.

## 6. The AI assistant

**What using it sends** (from [Hex's AI data privacy docs](https://learn.hex.tech/docs/hex-magic/magic-data-privacy)): project code, **cell outputs (query results)**, schema metadata, and prompts and responses go to Hex's LLM providers, **OpenAI and Anthropic**. The providers don't train on customer data and operate under zero data retention by default. Unlike Gemini in 28a, **result data is included**. At Accountable, the question is whether customer PII could appear in the outputs of projects where AI is enabled. The data here is invented, so it's fine. AI features can be turned off in the workspace settings (check the current menu).

In the same project, outside the published app, ask Hex's AI assistant, word for word:

1. "What was the weekly suggestion success rate?"
2. "Show the activation funnel by signup week."
3. "Do users whose first AI suggestion fails complete their workflow less often?"

| Prompt | Table(s) chosen | Definition fidelity (users vs events, order, 7-day window) | Used your inputs? | Matches `expected_hex.md`? | Uncertainty shown? |
| --- | --- | --- | --- | --- | --- |
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**Compared with Gemini (28a):** for prompt 3, did it handle the ordering trap (42 of 118 completers finished *before* their first suggestion in 28a's data)? Because Hex can only see the curated views, did its answers stay closer to the definitions than Gemini's did with the whole project? Write two or three sentences on it.

## 7. Publish and share

Publish the app, open the published version, and note:

- what a viewer sees (charts, inputs, definitions)
- what's hidden (SQL, the checks and AI sections, connection details)

Share it only inside your trial workspace. **No public links**, even for invented data; it's the habit that matters.

## 8. Cost

- **Where Hex's queries show up.** They run as `hex-reader`, billed to the sandbox project. In BigQuery, open **Job history → Project history** and filter by that account. At this data size, each query costs effectively nothing.
- **Optional cap:** a custom per-user daily query quota applies to service accounts too (IAM & Admin → Quotas; check the current console path).
- **No schedules:** keep Hex's scheduled runs off during the trial.
- **The trial** needs no card. Afterwards the workspace drops to the free plan unless you upgrade.

## 9. Deletion drill

Removing the synthetic data rehearses the deletion request described in Phase 26 §8, including downstream copies:

1. **Outbox:** run [`unseed.sql`](../../analytics_practice/unseed.sql) in Cloud SQL Studio.
2. **Raw table:**

   ```sql
   DELETE FROM analytics_raw.events WHERE STARTS_WITH(user_key, '00000000-0000-4000-8000-')
   ```

   Run it in the BigQuery console with the byte cap set. It deletes the duplicate-drill rows too.
3. **Check the views:** `analytics.events_deduped` should show only your real events again.
4. **Hex:** rerun the project. Its cached results now reflect the deletion; until the rerun, Hex still shows the old numbers. That's the downstream copy.
5. **Delete the key:**

   ```sh
   gcloud iam service-accounts keys delete KEY_ID --iam-account="$HEX_SA"
   ```

   Then delete the connection in Hex.
6. **Remove the identity:** set `hex = null` in tfvars, then plan and apply. Expect the identity and its two grants to be destroyed. The `data_freshness` view stays, because it belongs to Phase 26's curated set.
7. **Hex workspace:** let the trial lapse, or delete the workspace.
8. **What "deleted" still leaves:** BigQuery time travel keeps deleted rows recoverable for up to 7 days, then fail-safe for 7 more. Note that in the record.

## Acceptance record

| Check | Result |
| --- | --- |
| Synthetic data seeded, exported and reconciled | Passed, *verified* 2026-09-24: 1756 synthetic events in both PostgreSQL and BigQuery; funnel 9/9 and weekly success 9/9 identical |
| Terraform plan reviewed and applied (`hex`, `data_freshness`) | Pending |
| Key created; local file deletion verified; key ID recorded | Pending (key ID: —, created: —, planned deletion: —) |
| Hex connection sees `analytics` only | Pending |
| App built; inputs change the results | Pending |
| Hex numbers match `expected_hex.md` | Pending |
| Duplicate drill: raw inflated, Hex unchanged, raw access denied | Pending |
| AI assistant comparison recorded | Pending |
| Published and viewed as a viewer | Pending |
| Deletion drill completed; key deleted | Pending |

### Deferred, not passed

- Per-user OAuth (Enterprise only).
- A separate billing project for Hex queries.
- Scheduled runs and notifications.
- The semantic layer / dbt integration.
- A Hex exploration notebook (the corrected "first suggestion" investigation).

## Local verification

Observed on 2026-09-24 on `codex/phase-28b-hex`:

- `terraform test` (sandbox): 55 passed, including `data_freshness` (latest load time only, authorized on raw), the Hex identity's dataset-scoped read and jobUser grants, and the `hex`-requires-`analytics` validation.
- `pnpm test:api`: 751 passed, including four seed tests (deterministic reruns, the planned shape, the dip week, and `unseed.sql` leaving real events untouched).
- Markdown and link checks pass.

## Sources

- [Hex OAuth data connections](https://learn.hex.tech/docs/connect-to-data/data-connections/oauth-data-connections) and [data connections](https://learn.hex.tech/docs/category/data-connections)
- [Hex pricing](https://hex.tech/pricing/) and [compute limits](https://learn.hex.tech/docs/administration/workspace_settings/compute)
- [Hex AI data privacy](https://learn.hex.tech/docs/hex-magic/magic-data-privacy) and [data privacy FAQ](https://learn.hex.tech/docs/trust/data-privacy-and-usage-faq)
- [BigQuery time travel and fail-safe](https://cloud.google.com/bigquery/docs/time-travel)
