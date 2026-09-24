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
    add_days_fraction(s.started_at, u(CONCAT('sugg-at-', s.n, '-', k)), 5) AS suggested_at
  FROM starts AS s,
    UNNEST(GENERATE_ARRAY(1, CAST(FLOOR(u(CONCAT('sugg-count-', s.n)) * 9) AS INT64))) AS k
),
suggestion_outcomes AS (
  SELECT
    n, user_key, k, suggested_at,
    CASE
      WHEN u(CONCAT('outcome-', n, '-', k))
        < IF(DATE_TRUNC(DATE(suggested_at), ISOWEEK) = DATE '2026-09-07', 0.45, 0.85) THEN 'ready'
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
    user_key, uuid_of(CONCAT('workflow-', n)), outcome, suggested_at
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
