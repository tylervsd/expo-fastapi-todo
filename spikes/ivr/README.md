# IVR spike

Lesson 2 implements an inbound test IVR: answer, spoken menus, a random
four-digit challenge, synthetic-ID validation, confirmation, and a configurable
spoken amount. Local implementation is verified; Lesson 2 was signed off by the learner on
2026-09-21. Intermittent webhook delivery failures remain under investigation. The client still receives events only; outbound calling waits for Lesson 3.

Python 3.14 and uv are required. From this worktree's `spikes/ivr` directory:

```sh
uv sync --locked
# Only if .env does not already exist:
cp .env.example .env
# Edit .env locally; do not paste or commit credentials.
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run uvicorn webhooks:public_app --host 127.0.0.1 --port 8010 --env-file .env --no-access-log
```

The combined ingress and independent fixture require `TELNYX_PUBLIC_KEY`,
`TELNYX_API_KEY`, and `IVR_CONNECTION_ID`. The independent client requires only
`TELNYX_PUBLIC_KEY`. All fixture defaults and optional tuning are documented in
[.env.example](.env.example). The public key verifies callbacks; the API key
sends commands. Use only synthetic identifiers.

| Entry point | Port | Routes |
| --- | --- | --- |
| `webhooks:client_app` | 8011 | `/health`, `/webhooks/client` |
| `webhooks:test_ivr_app` | 8012 | `/health`, `/webhooks/test-ivr` |
| `webhooks:public_app` | 8010 | Both webhook routes only |

Use one process/worker, no reload, and only the combined ingress for the live
exercise. Separate entry points do not share in-memory state. No public control,
scenario, health, documentation, or call-start endpoints are exposed.

- [Lesson 1: connectivity](lessons/01-connectivity.md) — accepted 2026-09-21.
- [Lesson 2: navigate the IVR by hand](lessons/02-test-ivr.md) — walkthrough and acceptance record.

Accepted webhooks return empty **200**, after original-byte signature/freshness,
64 KiB body, and envelope checks. Fixture events additionally validate call
identity and current operation. No raw payloads, input, credentials, prompts,
or call-control tokens appear in default logs. Offline tests block real outbound
HTTP; they never place calls or open a tunnel.

Retries, operation correlation, replay guards, and a watchdog bound each call.
Final speech completion precedes normal hangup. Memory-only state cannot recover
calls after restart; end any active call on your handset before restarting.
See the walkthrough for limits, failure reasons, and learner-operated live checks.
