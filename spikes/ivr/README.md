# IVR spike

Lesson 1 receives authenticated Telnyx events. It does not answer or place calls.
Python 3.14 and uv are required; dependencies and the lockfile are independent
of the main application.

From this worktree's `spikes/ivr` directory:

```sh
uv sync --locked
cp .env.example .env
# Edit .env locally: TELNYX_PUBLIC_KEY is the account's base64 verification key.
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run uvicorn webhooks:client_app --host 127.0.0.1 --port 8011 --env-file .env --no-access-log
```

In another terminal: `curl -i http://127.0.0.1:8011/health`.
Expected: HTTP 200 and `{"status":"ok","role":"client"}`.

| Entry point | Port | Routes |
| --- | --- | --- |
| `webhooks:client_app` | 8011 | `/health`, `/webhooks/client` |
| `webhooks:test_ivr_app` | 8012 | `/health`, `/webhooks/test-ivr` |
| `webhooks:public_app` | 8010 | Both webhook routes only |

Use [Lesson 1: connectivity](lessons/01-connectivity.md) for the test-IVR command,
public ingress, Telnyx setup, security probes, and cleanup. Live acceptance is
pending. Offline signatures do not prove delivery from Telnyx.

The receiver limits bodies to 64 KiB, verifies exact bytes and a ±300-second
window, validates the envelope, and logs only role, event ID, and event type.
Repeated events are acknowledged again without call-control effects. There is
no replay deduplication or session state in this lesson.
