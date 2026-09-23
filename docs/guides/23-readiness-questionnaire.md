# Production-readiness questionnaire

A first-week conversation guide for a new engineering leader. It helps you tell whether a team has **rehearsed** its recovery or only **assumes** it works. Companion to the [Phase 23 walkthrough](23-resilience.md).

## How to use it

- Ask the questions in conversation, not as a form. Listen for specifics: dates, durations, names, links to notes.
- Score each answer **Rehearsed** (done, with evidence), **Assumed** (configured or believed, never exercised), or **Unknown**.
- An "Assumed" answer is not a failure. Before launch it is common. It tells you where to spend the first quarter.
- The **Phase** column points to where this curriculum practised the topic, so you can refresh before asking.

This is not a compliance checklist and does not replace legal, security, or regulatory review.

## 1. Backups and restore

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| When did you last restore a backup, and how long did it take? | "Last month; 18 minutes to a new instance; here's the note." | "Backups are enabled." | | 16, 23 |
| What are our RPO and RTO, and who agreed them? | Numbers, and the business owner who accepted them. | "As small as possible." | | 23 |
| Would we restore in place, or to a new instance and cut over? | A reasoned choice, with the runbook. | "Whatever the console does." | | 23 |
| After a restore, how do we check the schema matches the running code? | A specific check on the migration version. | Never considered. | | 23 |
| Which data lives outside the main database (files, logs, warehouse), and how is it backed up? | An inventory with owners. | "Everything's in Postgres." | | 23, 26 |

## 2. Schema changes

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| How do you change a column while old and new code both run? | Expand, migrate, contract, as separate releases. | "We deploy at night." | | 23 |
| Can every release be rolled back without touching the database? | "Yes; migrations are additive until a later contract release." | "Rollback means restoring a backup." | | 19, 23 |
| How are backfills run, and can they be safely re-run? | Idempotent, batched, observable, separate from deploys. | A one-off script someone ran by hand. | | 23 |
| Who reviews migrations, and what do they check? | Lock impact, reversibility, compatibility with the running code. | Nobody in particular. | | 16, 23 |

## 3. Deploy and rollback

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| How does code reach production, and who approves it? | One pipeline, a protected environment, named approvers. | Deploys from a laptop. | | 19 |
| When did you last roll back production, and how long did it take? | A recent rehearsal or incident, with timing. | "We've never needed to." | | 19, 23 |
| How would we notice a release that corrupts data but returns 200s? | Data-level checks, dashboards, and customer-facing verification. | "CI would catch it." | | 21, 23 |
| Can we pause delivery quickly, and who can? | A known switch, with named people. | Unclear. | | 19 |

## 4. Incidents and on-call

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| Who is paged when production breaks at 2am? | A rota, or an honest "the founders, and we know it's fragile." | "Whoever sees Slack." | | 21 |
| What alerts exist, and when did one last fire usefully? | A short list with recent examples. | Many alerts nobody reads, or none. | | 21 |
| Walk me through your last incident. | Timeline, decisions, and follow-ups that were actually done. | No written record. | | 23 |
| Who decides whether to tell customers, and how quickly? | A named role and a draft process, with counsel involved. | "We'd figure it out." | | 23 |

## 5. Secrets and PII

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| Where do secrets live, and how would we rotate one today? | A secret manager, with a rehearsed rotation. | Env files, or secrets in CI variables nobody owns. | | 15 |
| Which personal data do we store, and where is it encrypted beyond the default? | An inventory, with a reason for each field. | "The database is encrypted." | | 22 |
| How do we stop PII from reaching logs, traces, and analytics? | Tests, review rules, and redaction. | "Engineers are careful." | | 21, 22, 23 |
| Who has access to production data and logs, and when was that last reviewed? | A least-privilege list and a recent review. | Everyone has Owner. | | 13, 15 |
| Are there copies of production data elsewhere (exports, sinks, laptops)? | Known, with retention. | Unknown. | | 23, 26 |

## 6. Dependencies and vulnerabilities

| Question | Good answer sounds like | Red flag | Score | Phase |
| --- | --- | --- | --- | --- |
| How are dependency updates handled? | Automated PRs on a cadence, merged with tests. | Updated "when something breaks." | | 19 |
| Who triages vulnerability findings, and how fast? | A severity policy with response times. | Scanner output nobody reads. | | 19 |
| What are our known open findings right now? | A short, honest list with owners. | "None", with no scanning in place. | | 19 |

## Afterwards

Pick the two or three **Assumed** answers with the largest blast radius. Schedule rehearsals for them before launch, not after the first incident.
