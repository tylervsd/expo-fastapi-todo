-- Suggestion success (Phase 26 definition): ready / (ready + failed + expired)
-- per UTC day. Superseded requests emit no event, so they are excluded.
SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day,
       count(*) FILTER (WHERE outcome = 'ready') AS ready,
       count(*) FILTER (WHERE outcome = 'failed') AS failed,
       count(*) FILTER (WHERE outcome = 'expired') AS expired,
       round(count(*) FILTER (WHERE outcome = 'ready')::numeric / count(*), 4) AS success_rate
FROM analytics_events
WHERE event_name = 'suggestion_finished'
GROUP BY 1
ORDER BY 1
