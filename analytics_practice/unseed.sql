-- Phase 28b: remove only synthetic seeded events from the outbox (prefix match).
DELETE FROM analytics_events
WHERE user_key::text LIKE '00000000-0000-4000-8000-%';
