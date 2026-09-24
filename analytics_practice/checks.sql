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
