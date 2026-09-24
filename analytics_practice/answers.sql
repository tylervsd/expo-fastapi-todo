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
