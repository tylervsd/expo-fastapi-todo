-- Phase 30a: remove synthetic client events from every table the seed writes.
-- RudderStack can't delete from a warehouse; the warehouse owner does.
DELETE FROM rudderstack_raw.tracks
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.auth_screen_viewed
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.signup_submitted
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.signin_submitted
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.suggestion_requested
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.identifies
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.users
WHERE id LIKE '00000000-0000-4000-8000-%';
