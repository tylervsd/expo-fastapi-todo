# Phase 23: Resilience and production operations

**Status:** Release A (expand, dual-write, backfill) and this walkthrough are implemented and locally verified. Live drills and learner acceptance are pending. Releases B, C1, and C2 follow as separate pull requests timed to the drill. [Spec](../superpowers/specs/2026-09-23-resilience-design.md) and [implementation plan](../superpowers/plans/2026-09-23-resilience.md). Companion: [readiness questionnaire](23-readiness-questionnaire.md).

## Why this phase

Most teams *assume* recovery works: backups are enabled, rollback "should" be fine, and nobody has written down who does what during an incident. This phase turns assumptions into rehearsals with timings and evidence, so you can tell the difference in someone else's system.

This is practice against the disposable sandbox. It is not Accountable's production runbook or compliance evidence. Use invented names and data throughout.

Run the parts in this order. The restore resets the database to the last nightly backup, which can move the schema backwards, so do it **before** release A is merged and deployed.

1. [Timed restore](#part-1-timed-restore)
2. [Expand/contract with a failed intermediate release](#part-2-expandcontract-with-a-failed-intermediate-release)
3. [Tabletop: customer PII in logs](#part-3-tabletop-customer-pii-in-logs)
4. [Readiness questionnaire](23-readiness-questionnaire.md)

Shared shell variables (same names as Phase 19):

```sh
export CLOUD_PROJECT='<project-id>'
export CLOUD_REGION='<region>'
export CLOUD_SERVICE='<api-service>'
export CLOUD_MIGRATION_JOB='<migration-job>'
export SQL_INSTANCE='<sql-instance>'
export API_URL='<stable API URL>'
```

## Part 1: Timed restore

| Objective | Target | Meaning |
| --- | --- | --- |
| Recovery time (RTO) | 30 minutes | From "start restore" to "API smoke passes" |
| Recovery point (RPO) | 24 hours | Up to a day of writes may be lost with daily backups |

Phase 16 restored a backup to a **separate** instance. This drill restores **in place**, over the instance the API is using, so you see the real user impact and the real data loss. Cloud SQL point-in-time recovery (PITR) always creates a new instance, so it is not used here. For production, "PITR to a new instance, verify, then cut the application over" usually gives a far smaller RPO than an in-place nightly restore. Knowing which runbook a team would use, and whether they have rehearsed it, is the point.

The sandbox data is disposable, so this drill takes no extra safety backup and does not pause delivery.

### 1. Find the backup you will restore

```sh
gcloud sql backups list --instance="$SQL_INSTANCE" --project="$CLOUD_PROJECT" \
  --limit=5 --format='table(id,type,status,endTime)'
export BACKUP_ID='<id of the newest SUCCESSFUL AUTOMATED backup>'
export BACKUP_END='<its endTime>'
```

Record `BACKUP_ID` and `BACKUP_END` in the acceptance record.

### 2. Write marker data after the backup

Use a synthetic account that existed **before** `BACKUP_END`, and note one of its todos from before that time as your survivor check. An account created now is itself post-backup data and disappears in the restore. If the sandbox has no suitable account, create one with `POST /auth/signup` and wait for the next nightly backup.

Replace `USERNAME` and `PASSWORD` with real values. Log in and check the status before extracting the token:

```sh
curl -sS -o login.json -w 'login HTTP %{http_code}\n' -X POST "$API_URL/auth/login" \
  -H 'Content-Type: application/json' -d '{"username":"USERNAME","password":"PASSWORD"}'
TOKEN=$(python3 -c 'import json;print(json.load(open("login.json"))["token"])') && rm login.json
```

Anything other than `login HTTP 200` stops here. A `401` means wrong credentials or a user missing from this database. A `422` means a malformed body, for example unreplaced placeholders. A `404` or HTML means `API_URL` is wrong.

```sh
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
curl -sS --fail-with-body -X POST "$API_URL/todos" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"title\":\"restore-marker-open-$STAMP\"}"
DONE_ID=$(curl -sS --fail-with-body -X POST "$API_URL/todos" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"title\":\"restore-marker-done-$STAMP\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
curl -sS --fail-with-body -X PATCH "$API_URL/todos/$DONE_ID" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"completed":true}'
```

### 3. Restore and time it

```sh
date -u   # START
gcloud sql backups restore "$BACKUP_ID" \
  --restore-instance="$SQL_INSTANCE" --project="$CLOUD_PROJECT"
gcloud sql operations list --instance="$SQL_INSTANCE" --project="$CLOUD_PROJECT" --limit=1
python3 scripts/release_smoke.py "$API_URL"
date -u   # STOP when the smoke passes
```

Confirm the prompt: the restore overwrites all current data in the instance.

While it runs, open the Phase 21 dashboard and note what users would have seen: request errors, latency, and Cloud Tasks retries. You are observing the impact, not preventing it.

The login `TOKEN` from step 2 was stored in the database after the backup, so it is gone too. Log in again before step 4.

### 4. Verify what survived

- Both `restore-marker-*` todos are **absent**. This is the RPO made visible.
- The pre-backup survivor todo is **present** with its original state.
- The schema version matches the code. Run this in Cloud SQL Studio:

```sql
SELECT version_num FROM alembic_version;
```

Compare it with the migration head of the code that is **currently deployed**: the newest file in `apps/api/alembic/versions/` on `main`, not on this phase's branch. Until release A merges, that is `2026091801`. If the database is behind, the running code expects columns the restored database doesn't have. Rerun migrations:

```sh
gcloud run jobs execute "$CLOUD_MIGRATION_JOB" --project="$CLOUD_PROJECT" \
  --region="$CLOUD_REGION" --wait
```

### 5. What we learned

Write three to five lines in the acceptance record. Prompts:

- Was the restore inside 30 minutes? What took the longest?
- For a fintech, what would losing up to 24 hours of writes mean: payments, KYC decisions, customer messages? Who would have to be told?
- Would PITR-to-new-instance with a cut-over have been the better runbook? What would need to be rehearsed for that?
- What would you now ask a team that says "backups are enabled"?

## Part 2: Expand/contract with a failed intermediate release

Change `todos.completed` (boolean) into `todos.completed_at` (timestamp) without downtime and without changing the API. Clients always see `completed: bool`.

| Release | Branch | Migration | Writes | Reads | Safe rollback target |
| --- | --- | --- | --- | --- | --- |
| A: expand | `codex/phase-23-resilience` | add nullable `completed_at` | both | `completed` | previous release, then rerun the backfill before B |
| B: read switch | `codex/phase-23-read-switch` | none | both | `completed_at IS NOT NULL` | A (B still writes `completed`) |
| C1: stop writing | `codex/phase-23-contract` | none | `completed_at` only | `completed_at` | B, with `completed` stale |
| C2: drop | `codex/phase-23-contract-drop` | drop `completed` | `completed_at` | `completed_at` | C1 |

Completing a todo sets `completed_at` once. Completing it again keeps the original time, and reopening clears it.

Use this query in Cloud SQL Studio to watch the two columns throughout:

```sql
SELECT completed, completed_at IS NOT NULL AS stamped, count(*)
FROM todos GROUP BY 1, 2 ORDER BY 1, 2;
```

### The drill

1. **Release A.** Merge PR A and approve the sandbox release. The migration job adds the column before traffic moves. Complete one todo in the app, then check that the query shows `true / true` for it. Older completed todos show `true / false`. They are waiting for the backfill.
2. **Release B, without the backfill.** Merge PR B and approve the release. CI and the smoke test pass. In the app, todos completed before release A now look **incomplete**. Nothing crashed; the data is quietly wrong. Record when B went live and when you noticed.
3. **Roll back to A.** Follow the [Phase 19 manual rollback](19-continuous-delivery.md#manual-rollback) with `PREVIOUS_REVISION` set to A's revision. The expanded schema stays; never downgrade the database. Verify that old completions display correctly again. Also verify that anything you completed or reopened while B was live is still correct. B kept writing both columns, which is why rolling back loses nothing.
4. **Backfill.** Run it twice:

   ```sh
   gcloud run jobs execute "$CLOUD_MIGRATION_JOB" --project="$CLOUD_PROJECT" \
     --region="$CLOUD_REGION" --wait --args="python -m app.backfill_completed_at"
   ```

   Read `backfill_completed_at: updated=<n> batches=<m>` in the execution's logs. The second run must report `updated=0`. The query should now show no `true / false` rows and no `false / true` rows. The backfill also clears stale stamps on reopened todos. Those appear only if code older than release A ran after A, for example after rolling A itself back, because older code writes only `completed`. The query, not the printed count, is the gate: rows locked by a user's click at that moment are skipped and caught by a rerun.

   Backfilled rows are stamped with the **time of the backfill**, because the real completion time was never recorded. In a fintech, an approximated timestamp is not audit evidence. Say so wherever the data is used.
5. **Return to B.** Route traffic back to B's revision, verify, and re-enable delivery as Phase 19 describes:

   ```sh
   gcloud run services update-traffic "$CLOUD_SERVICE" --project="$CLOUD_PROJECT" \
     --region="$CLOUD_REGION" --to-revisions="<B revision>=100"
   python3 scripts/release_smoke.py "$API_URL"
   ```

6. **Contract, later.** Once B is stable, release C1, then C2, checking the app and the query after each one.

### Why the contract is two releases

Delivery runs migrations **before** it shifts traffic. If one release both stopped writing `completed` and dropped it, the migration would drop the column while B was still serving, and every B write would fail until traffic moved. C1 first ships code that no longer knows the column exists. C2's migration can then drop it while C1 serves. Release C1 includes a test that proves both halves: B's writes fail on the dropped schema, and C1's code works on it.

## Part 3: Tabletop: customer PII in logs

This is a paper exercise, about 60 minutes. Claude plays the facilitator and reveals one inject at a time. Don't read ahead.

**Scenario:** Accountable-like, pre-launch fintech. On a Friday at 15:40, an engineer notices that a debug log line added 9 days ago writes each signed-in user's decrypted real name and email to Cloud Logging.

**Roles:** Assign them before you start. One person may hold several, which is realistic at a small company.

| Role | Owns |
| --- | --- |
| Incident commander | Decisions, priorities, and declaring the incident over |
| Operations lead | Containment and technical investigation |
| Communications / legal liaison | Internal updates, customer wording, and counsel contact |
| Scribe | Timeline and decision log |

### Injects

1. **Discovery (15:40).** What severity is this? Who is paged now, and who can wait until Monday? Do you freeze deploys, or ship the fix immediately? What is the first containment step?
2. **Scope (16:30).** The logs are also exported by a sink to BigQuery, and three contractors hold Logs Viewer on the project. Which people and systems could have read the data? What are the retention periods in Cloud Logging and in BigQuery? Can individual log entries be deleted, and if not, what are the options? How do you find out whether anyone actually read the data?
3. **Obligations (Monday 09:10).** A beta customer emails: "I saw my name in a screenshot of your logs someone posted." What do you reply, and who signs it off? When does counsel get involved, and what do you bring them?
4. **Close-out (Tuesday).** How do you prove the leak has stopped and the copies are handled? Which controls would have caught this before production?

### Questions to take to counsel

This guide gives no legal advice. These are the questions to bring:

- Does this count as a personal-data breach under the laws and contracts that apply to us?
- What notification duties and deadlines apply to regulators, partners, and customers?
- Do our beta terms or privacy notice change the answer?
- What records must we keep of the incident and our decisions?

### Incident record template

| Time (UTC) | Event / information | Decision | Owner |
| --- | --- | --- | --- |
| | | | |

### Blameless review template

- **What happened:** facts only, from the timeline.
- **Impact:** data, people, systems, duration.
- **What went well.**
- **What was hard:** tools, access, missing information, unclear ownership.
- **Follow-ups:** each with an owner and a date.

### Prevention controls to consider

- Serialized-output redaction tests like Phase 21's, extended to any new log call that handles user fields.
- Phase 22's rule that decrypted names never enter logs, traces, or analytics, enforced in review.
- Log exclusion filters and short retention for application logs.
- Restricted log buckets and log views, so contractors see only what they need.
- Treating log sinks such as BigQuery exports as copies of the data, with their own access and retention review.

## Acceptance record

Live results are learner-reported unless stated otherwise.

| Check | Result |
| --- | --- |
| Restore duration vs 30-minute RTO | Pending |
| Post-backup markers absent | Pending |
| Pre-backup survivor present | Pending |
| Schema version after restore (and migration rerun if needed) | Pending |
| Release A deployed; new completion dual-written | Pending |
| Release B defect detected (time to detect) | Pending |
| Rollback to A (duration, data intact) | Pending |
| Backfill counts (first run / second run = 0) | Pending |
| Traffic back on B, verified | Pending |
| Release C1 deployed | Pending |
| Release C2 deployed | Pending |
| Tabletop incident record and review completed | Pending |
| Readiness questionnaire reviewed | Pending |

### Deferred, not passed

- Cloud SQL regional high availability and its cost review.
- Security Command Center and Artifact Analysis finding triage.
- Secret rotation drill (Phase 15 rotated a credential; not repeated here).
- Dependency-maintenance cadence.
- Phase 18 steps 7–8: Terraform state recovery and guarded destruction.

## Local verification

Observed on 2026-09-23 on `codex/phase-23-resilience`: `pnpm test:api`, 718 passed, including dual-write, cross-owner, migration reversal, and backfill idempotency tests; `pnpm lint:api` clean. These do not prove any live result above.

## Sources

- [Cloud SQL: restore from a backup](https://cloud.google.com/sql/docs/postgres/backup-recovery/restoring)
- [Cloud SQL: point-in-time recovery](https://cloud.google.com/sql/docs/postgres/backup-recovery/pitr)
- [gcloud run jobs execute](https://cloud.google.com/sdk/gcloud/reference/run/jobs/execute)
- [Cloud Logging routing and storage](https://cloud.google.com/logging/docs/routing/overview)
