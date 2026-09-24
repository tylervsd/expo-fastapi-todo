-- Activation funnel (Phase 26 definition). Cohort: ISO week (UTC) of
-- user_signed_up. Started/completed: distinct cohort users with the event
-- within 7 days after their own signup. Complete once 14 days past week start.
WITH signups AS (
    SELECT user_key, occurred_at AS signed_up_at,
           date_trunc('week', occurred_at AT TIME ZONE 'UTC')::date AS cohort_week
    FROM analytics_events
    WHERE event_name = 'user_signed_up'
),
reached AS (
    SELECT s.user_key, s.cohort_week,
           bool_or(e.event_name = 'workflow_started') AS started,
           bool_or(e.event_name = 'workflow_completed') AS completed
    FROM signups s
    LEFT JOIN analytics_events e
      ON e.user_key = s.user_key
     AND e.event_name IN ('workflow_started', 'workflow_completed')
     AND e.occurred_at >= s.signed_up_at
     AND e.occurred_at < s.signed_up_at + interval '7 days'
    GROUP BY s.user_key, s.cohort_week
)
SELECT cohort_week,
       count(*) AS signed_up,
       count(*) FILTER (WHERE started) AS started_7d,
       count(*) FILTER (WHERE completed) AS completed_7d,
       round(count(*) FILTER (WHERE started)::numeric / count(*), 4) AS started_rate,
       round(count(*) FILTER (WHERE completed)::numeric / count(*), 4) AS completed_rate,
       cohort_week + 14 <= (now() AT TIME ZONE 'UTC')::date AS cohort_complete
FROM reached
GROUP BY cohort_week
ORDER BY cohort_week
