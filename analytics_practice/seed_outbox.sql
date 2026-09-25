-- Phase 28b: seed deterministic synthetic events into the analytics outbox.
-- Invented users only (user_key prefix 00000000-0000-4000-8000-). The normal
-- export then loads them into BigQuery. Safe to rerun: existing events are skipped.
-- Remove with unseed.sql (plus the BigQuery DELETE in the Phase 28b guide).
CREATE OR REPLACE FUNCTION pg_temp.u(seed text) RETURNS double precision
LANGUAGE sql IMMUTABLE
AS $$ SELECT ('x' || substr(md5(seed), 1, 7))::bit(28)::int / 268435456.0 $$;

WITH
users AS (
  SELECT n,
    ('00000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid AS user_key,
    timestamptz '2026-07-27 00:00:00+00'
      + floor(pg_temp.u('signup-' || n) * 60 * 86400) * interval '1 second' AS signed_up_at
  FROM generate_series(1, 400) AS n
),
starts AS (
  SELECT n, user_key,
    signed_up_at + floor(pg_temp.u('start-delay-' || n) * 10 * 86400) * interval '1 second' AS started_at
  FROM users WHERE pg_temp.u('starts-' || n) < 0.7
),
completions AS (
  SELECT n, user_key,
    started_at + floor(pg_temp.u('complete-delay-' || n) * 3 * 86400) * interval '1 second' AS completed_at
  FROM starts WHERE pg_temp.u('completes-' || n) < 0.6
),
suggestions AS (
  SELECT s.n, s.user_key, k,
    s.started_at + floor(pg_temp.u('sugg-at-' || s.n || '-' || k) * 5 * 86400) * interval '1 second' AS suggested_at
  FROM starts AS s
  CROSS JOIN LATERAL generate_series(1, floor(pg_temp.u('sugg-count-' || s.n) * 9)::int) AS k
),
suggestion_outcomes AS (
  SELECT n, user_key, k, suggested_at,
    CASE
      WHEN pg_temp.u('outcome-' || n || '-' || k)
        < CASE WHEN date_trunc('week', suggested_at AT TIME ZONE 'UTC')::date = date '2026-09-07'
               THEN 0.45 ELSE 0.85 END THEN 'ready'
      WHEN pg_temp.u('failure-kind-' || n || '-' || k) < 0.8 THEN 'failed'
      ELSE 'expired'
    END AS outcome
  FROM suggestions
),
events AS (
  SELECT md5('hex-seed-user_signed_up-' || n)::uuid AS event_id, 'user_signed_up' AS event_name,
    user_key, NULL::uuid AS workflow_key, NULL::text AS outcome, signed_up_at AS occurred_at
  FROM users
  UNION ALL
  SELECT md5('hex-seed-workflow_started-' || n)::uuid, 'workflow_started', user_key,
    md5('hex-seed-workflow-' || n)::uuid, NULL, started_at
  FROM starts
  UNION ALL
  SELECT md5('hex-seed-workflow_completed-' || n)::uuid, 'workflow_completed', user_key,
    md5('hex-seed-workflow-' || n)::uuid, NULL, completed_at
  FROM completions
  UNION ALL
  SELECT md5('hex-seed-suggestion_finished-' || n || '-' || k)::uuid, 'suggestion_finished',
    user_key, md5('hex-seed-workflow-' || n)::uuid, outcome, suggested_at
  FROM suggestion_outcomes
)
INSERT INTO analytics_events (event_id, event_name, user_key, workflow_key, outcome, occurred_at)
SELECT event_id, event_name, user_key, workflow_key, outcome, occurred_at
FROM events
WHERE occurred_at < timestamptz '2026-09-25 00:00:00+00'
ON CONFLICT (event_id) DO NOTHING;
