# Phase 28b expected results

Recorded on 2026-09-24 after the learner ran [`seed_outbox.sql`](seed_outbox.sql) in the sandbox and the export loaded it. They come from the curated `analytics` views in BigQuery and were reconciled against PostgreSQL. Use them in the Hex checks section.

They **include the real sandbox events** (17 at recording time). If you've used the app since, expect small differences in the latest cohort and week. Synthetic rows are the ones whose `user_key` starts with `00000000-0000-4000-8000-`.

## Seed and totals

| Measure | Value |
| --- | ---: |
| Synthetic events in the outbox (PostgreSQL) | 1756 |
| Synthetic events in BigQuery (`events_deduped` minus real) | 1756 |
| Synthetic users | 400 |
| Real events | 17 |
| Distinct events in `analytics.events_deduped` | 1773 |

The seed is deterministic: the same script on the local test database also inserts 1756 rows.

## Activation funnel (`analytics.activation_funnel`)

| cohort_week | signed_up | started_7d | completed_7d | started_rate | completed_rate | cohort_complete |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-07-27 | 41 | 20 | 10 | 0.4878 | 0.2439 | true |
| 2026-08-03 | 48 | 23 | 11 | 0.4792 | 0.2292 | true |
| 2026-08-10 | 50 | 25 | 8 | 0.5 | 0.16 | true |
| 2026-08-17 | 45 | 23 | 10 | 0.5111 | 0.2222 | true |
| 2026-08-24 | 43 | 24 | 11 | 0.5581 | 0.2558 | true |
| 2026-08-31 | 37 | 19 | 8 | 0.5135 | 0.2162 | true |
| 2026-09-07 | 56 | 26 | 12 | 0.4643 | 0.2143 | true |
| 2026-09-14 | 59 | 22 | 11 | 0.3729 | 0.1864 | false |
| 2026-09-21 | 23 | 5 | 1 | 0.2174 | 0.0435 | false |

`cohort_complete` uses `CURRENT_DATE('UTC')`, so it changes as time passes: this table was recorded on 2026-09-24. The 2026-09-21 cohort includes your 2 real signups.

## Weekly suggestion success (from `analytics.suggestion_success`)

| week | ready | finished | success_rate |
| --- | ---: | ---: | ---: |
| 2026-07-27 | 11 | 12 | 0.9167 |
| 2026-08-03 | 86 | 100 | 0.86 |
| 2026-08-10 | 106 | 127 | 0.8346 |
| 2026-08-17 | 104 | 121 | 0.8595 |
| 2026-08-24 | 77 | 95 | 0.8105 |
| 2026-08-31 | 144 | 174 | 0.8276 |
| 2026-09-07 | 37 | 101 | 0.3663 |
| 2026-09-14 | 117 | 134 | 0.8731 |
| 2026-09-21 | 77 | 94 | 0.8191 |

The dip is the week of 2026-09-07. The 2026-09-21 week includes your 8 real suggestion outcomes (3 ready, 5 failed).

## Reconciliation

On 2026-09-24 the learner ran both Phase 26 PostgreSQL reconciliation queries ([funnel](../apps/api/analytics_sql/postgres_activation_funnel.sql), [suggestion success](../apps/api/analytics_sql/postgres_suggestion_success.sql)) in Cloud SQL Studio:
- The funnel matched all 9 cohorts exactly.
- The daily success rows, rolled up to ISO weeks, matched all 9 weeks exactly (ready and finished).
