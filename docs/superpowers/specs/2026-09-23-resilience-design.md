# Phase 23: Resilience and production operations

**Status:** Design approved by the learner in conversation on 2026-09-23. Written spec awaiting learner review.

**Context:** Based on `main` at `f0e0006`, following Phase 22. The learner will be CTO of Accountable, a pre-launch fintech handling customer PII, and wants to judge whether an inherited team has *rehearsed* recovery or merely *assumes* it works. This phase is educational practice against the disposable sandbox, not Accountable's production runbook or compliance evidence. Use invented names and data throughout.

**Related:** [Implementation plan](../plans/2026-09-23-resilience.md), [walkthrough](../../guides/23-resilience.md), [readiness questionnaire](../../guides/23-readiness-questionnaire.md), [curriculum](../../curriculum-roadmap.md#23-resilience-and-production-operations).

## Scope

Four parts, run in this order because the restore resets the schema to the last nightly backup:

1. Timed in-place backup restore (guide only, no new code).
2. Expand/contract schema change with a deliberately failed intermediate release (releases A, B, C1, C2).
3. Tabletop incident: customer PII in logs (guide only).
4. Production-readiness questionnaire (standalone document).

Manual Cloud Run rollback and candidate-failure handling were already rehearsed in Phase 19. This phase rehearses rollback **during** a migration, when two schemas and two code versions coexist.

**Deferred from the roadmap entry (not passed):** Cloud SQL regional high availability, Security Command Center and Artifact Analysis triage, secret rotation, dependency-maintenance cadence, and the Phase 18 state-recovery/destruction drills. The sandbox database is disposable, so the drills take no undo backup and do not pause delivery.

## 1. Timed restore drill

**Objectives:** RTO 30 minutes, RPO 24 hours (realistic pre-launch targets with daily automated backups). The restore is **in place** over the sandbox instance from the most recent automated backup. Cloud SQL point-in-time recovery always creates a new instance, so it is not used here; the guide explains when PITR-to-clone plus cut-over is the better production runbook.

Procedure:

1. Record the latest successful automated backup's ID and end time (`gcloud sql backups list`).
2. Through the API, create two marker todos after that time with invented, timestamped titles; complete one.
3. Start the clock. Run `gcloud sql backups restore <BACKUP_ID> --restore-instance=<INSTANCE>`.
4. Wait for the operation to finish, run the existing API smoke check, stop the clock.

Evidence recorded in the guide's acceptance record:

- Restore duration versus RTO.
- The post-backup markers are absent (RPO made visible); a pre-backup todo remains.
- `alembic_version` after restore versus `main`'s head. If it is behind, execute the migration job before continuing; the lesson is that restoring can move the schema backwards while the running code does not.
- Observed Cloud Run and Cloud Tasks behavior during the window, read from the Phase 21 dashboard (user impact is observed, not prevented).
- A short "what we learned" note: what losing up to 24 hours of data would mean for a fintech, and the questions it raises for a team.

## 2. Expand/contract: `todos.completed` → `todos.completed_at`

Replace the boolean `completed` with a nullable `completed_at timestamptz`. The public API contract never changes: clients always receive `completed: bool`. Only `app/todo_repository.py` and the todo read in `app/workflow_service.py` touch the column. Workflow snapshot JSON keeps its own `completed` key and is out of scope.

| Release | Branch | Migration | Writes | Reads | Safe rollback target |
| --- | --- | --- | --- | --- | --- |
| A: expand | `codex/phase-23-resilience` | add nullable `completed_at` | both | `completed` | previous release |
| B: read switch | `codex/phase-23-read-switch` | none | both | `completed_at IS NOT NULL` | A (B still writes `completed`) |
| C1: stop writing | `codex/phase-23-contract` | none | `completed_at` only; `completed` is left to its server default on insert and no longer updated | `completed_at` | B, with `completed` stale — acceptable only because C2 follows |
| C2: drop | `codex/phase-23-contract-drop` | drop `completed` | `completed_at` | `completed_at` | C1 |

Write semantics from A onward: completing sets `completed_at = coalesce(completed_at, now())` (re-completing keeps the original time); reopening sets it to `NULL`. New todos have `completed_at = NULL`.

**Why the contract is two releases:** delivery runs migrations before shifting traffic. A single "stop writing and drop" release would drop the column while B still serves, and B's writes would fail. A local test runs B's repository code against the C2 schema and asserts it fails; this is the cheap version of the premature-contract lesson.

C1 removes `completed` from the ORM mapping entirely, so C1's code already runs on the C2 schema; C2's migration runs while C1 still serves. A test asserts C1's repository code works against the C2 schema.

C2's downgrade re-adds `completed` as `NOT NULL DEFAULT false` and sets it from `completed_at IS NOT NULL`.

### Backfill

`python -m app.backfill_completed_at` updates rows `WHERE completed AND completed_at IS NULL` in batches of 500, committing each batch, and prints rows updated. A second run updates 0 rows. It never touches reopened rows. It stamps rows with the backfill time: historical completion times are **unknown**, and the guide says so plainly — a backfilled timestamp is an approximation, not audit evidence.

It is run as an operator step on the existing migration job with overridden args (the job's command is `sh -c`):

```sh
gcloud run jobs execute "$MIGRATION_JOB" --region "$REGION" --wait \
  --args="python -m app.backfill_completed_at"
```

The backfill ships in release A so it exists before B is deployed, but is **not** an Alembic migration, so the drill can deploy B before running it.

### Drill

1. Merge and release A. Complete a marker todo; verify both columns in the database.
2. Merge and release B **without running the backfill**. CI and the deploy pass; older completed todos appear incomplete. Record time-to-detect.
3. Roll back traffic to A's revision using the Phase 19 manual rollback. Verify correct completion state and that writes made during B were not lost (dual-write).
4. Run the backfill; record counts; run it again and confirm 0.
5. Route traffic back to B's revision; verify.
6. Later, release C1, then C2, verifying each.

## 3. Tabletop incident: customer PII in logs

Paper exercise, about 60 minutes, run live with Claude delivering injects; the guide contains the scenario, injects, and templates.

**Scenario:** a pre-launch fintech app. A debug log line has written each user's decrypted real name and email to Cloud Logging for 9 days. An engineer notices on a Friday afternoon.

**Roles:** incident commander, operations lead, communications/legal liaison, scribe. One person may hold several roles; the learner assigns them.

**Injects**, each with decision prompts:

1. Discovery — severity, who is paged, whether deploys freeze.
2. Scope — logs are also exported to a BigQuery sink and 3 contractors hold Logs Viewer. What was exposed, what are retention and deletion options?
3. Obligations — a beta customer emails about "weird logs in a screenshot". What is communicated, when, and when counsel is involved. The guide lists questions for counsel; it gives no legal advice.
4. Close-out — how to prove the fix and which prevention controls would catch recurrence.

**Output:** a completed incident record (timeline, decisions, owners, follow-ups) and a blameless post-incident review. Prevention controls reference earlier phases: log redaction tests (Phase 21), names never logged (Phase 22), log exclusions, retention, and restricted log buckets.

## 4. Readiness questionnaire

`docs/guides/23-readiness-questionnaire.md`: about 25 questions in six areas — backups and restore; schema changes; deploy and rollback; incidents and on-call; secrets and PII; dependencies and vulnerabilities. Each question has *what a good answer sounds like*, a *red-flag answer*, a *rehearsed vs. assumed* column for scoring, and the curriculum phase that taught the topic. Written for a first-week conversation with a team, not as a compliance checklist.

## Testing and acceptance

Local, test-first, on the existing pytest + PostgreSQL setup:

- A: dual-write semantics for complete, re-complete, and reopen; reads still from `completed`.
- A: backfill is batched, idempotent (second run updates 0), and skips reopened rows.
- Migration applies and reverses cleanly for A and C2.
- Mixed versions: A's reads are correct on data written by B's code, and vice versa.
- B: reads from `completed_at`; a completed-but-unbackfilled row reads as incomplete (the drill's bug, pinned).
- C: B's repository code fails against the C2 schema; C1's code passes against both the C1 and C2 schemas.
- API response shapes unchanged; existing quality, security, and e2e CI stay green.

Live acceptance is learner-run and recorded in the guide like prior phases: restore timing and marker/schema evidence; B detected, rollback time, backfill counts, recovery; C1/C2 releases; completed tabletop record; questionnaire reviewed. Anything not performed is recorded as deferred, not passed.

## Sources to check during implementation

- [Cloud SQL restore from backup](https://cloud.google.com/sql/docs/postgres/backup-recovery/restoring) and [PITR](https://cloud.google.com/sql/docs/postgres/backup-recovery/pitr).
- [gcloud run jobs execute](https://cloud.google.com/sdk/gcloud/reference/run/jobs/execute) argument overrides.
- [Cloud Logging retention and exclusions](https://cloud.google.com/logging/docs/routing/overview).
