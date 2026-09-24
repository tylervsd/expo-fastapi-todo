# Phase 28a expected results

Recorded on 2026-09-24 from a live run of [`answers.sql`](answers.sql) against data built by [`generate.sql`](generate.sql). Try each exercise first; compare afterwards.

**Generator fingerprint:** 1,767 rows, checksum `-6779663904789774770` (check 1 in [`checks.sql`](checks.sql)). If your checksum differs, the data differs, and so will these answers.

All exercises use the as-of date `2026-09-24`.

## E1: Orientation

| n_rows | first_event (UTC) | last_event (UTC) |
| ---: | --- | --- |
| 1767 | 2026-07-27 01:15:04 | 2026-09-24 23:45:19 |

## E2: Duplicates

| n_rows | distinct_events | duplicate_rows |
| ---: | ---: | ---: |
| 1767 | 1692 | 75 |

About 4.4% of events were loaded twice. Every later answer reads deduplicated data unless it says "naive".

## E3: Activation funnel

| cohort_week | signed_up | started_7d | completed_7d | completed_rate | cohort_complete |
| --- | ---: | ---: | ---: | ---: | --- |
| 2026-07-27 | 40 | 21 | 11 | 0.275 | true |
| 2026-08-03 | 32 | 12 | 5 | 0.1563 | true |
| 2026-08-10 | 45 | 24 | 12 | 0.2667 | true |
| 2026-08-17 | 46 | 22 | 9 | 0.1957 | true |
| 2026-08-24 | 61 | 30 | 17 | 0.2787 | true |
| 2026-08-31 | 40 | 26 | 10 | 0.25 | true |
| 2026-09-07 | 50 | 25 | 8 | 0.16 | true |
| 2026-09-14 | 56 | 22 | 5 | 0.0893 | false |
| 2026-09-21 | 30 | 4 | 0 | 0.0 | false |

Signups total 400. The last two cohorts are incomplete: their members haven't all had 7 days yet, so their low rates aren't a decline.

## E4: Week-over-week suggestion success

| week | success_rate | change_vs_prior_week | naive_success_rate | week_complete |
| --- | ---: | ---: | ---: | --- |
| 2026-07-27 | 0.9375 | — | 0.9412 | true |
| 2026-08-03 | 0.8519 | -0.0856 | 0.8571 | true |
| 2026-08-10 | 0.9 | 0.0481 | 0.9036 | true |
| 2026-08-17 | 0.8321 | -0.0679 | 0.8333 | true |
| 2026-08-24 | 0.9412 | 0.1091 | 0.9435 | true |
| 2026-08-31 | 0.8079 | -0.1332 | 0.8089 | true |
| 2026-09-07 | 0.5442 | -0.2637 | 0.5541 | true |
| 2026-09-14 | 0.8807 | 0.3365 | 0.886 | true |
| 2026-09-21 | 0.8854 | 0.0047 | 0.87 | false |

The dip is the week of 2026-09-07. Naive and deduplicated rates differ by at most about 0.015 here, because duplicates are spread evenly across outcomes (the Phase 26 lesson): uniform duplicates barely move a ratio, but they do inflate counts.

## E5: Median suggestions per active user per week

Reference definition: in each ISO week, an **active user** has at least one `suggestion_finished` event that week; report the median of their counts.

| week | active_users | median_suggestions | week_complete |
| --- | ---: | ---: | --- |
| 2026-07-27 | 7 | 2 | true |
| 2026-08-03 | 19 | 3 | true |
| 2026-08-10 | 26 | 2 | true |
| 2026-08-17 | 45 | 3 | true |
| 2026-08-24 | 40 | 3 | true |
| 2026-08-31 | 50 | 3 | true |
| 2026-09-07 | 47 | 2 | true |
| 2026-09-14 | 35 | 2 | true |
| 2026-09-21 | 32 | 2 | false |

`APPROX_QUANTILES` is approximate in general but exact at this size. A different, equally reasonable definition gives a different number. For example, counting every user with a started workflow as active (including zero-suggestion weeks) can only lower the median or leave it unchanged. Neither is wrong; the written definition is what makes a number comparable.

## E5R: Your metric on real data

This varies with your real sandbox data; compare it with your own run. On 2026-09-24 the real `analytics.events_deduped` gave one week (2026-09-21) with 2 active users and a median of 4.
