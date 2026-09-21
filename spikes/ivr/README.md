# IVR spike

Lesson 3 implements the automated caller: a one-call CLI that dials only the
configured test number, transcribes the remote side, replays the spoken
challenge, selects personal, enters the synthetic ID, checks its readback,
and waits for the result announcement plus fixture hangup. Local
implementation is verified (358 tests, Ruff clean); live verification and
learner acceptance remain pending. Intermittent webhook delivery failures
remain under investigation. Amount extraction and the value-or-error JSON
contract wait for Lesson 4.

Python 3.14 and uv are required. From this worktree's `spikes/ivr` directory:

```sh
uv sync --locked
# Only if .env does not already exist:
cp .env.example .env
# Edit .env locally; do not paste or commit credentials.
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
# Learner-operated only, after checking settings and existing routing:
uv run python caller.py --env-file .env --app public
```

One CLI invocation places exactly one call, then exits. Exit 0 requires the
result announcement plus a matching fixture hangup; stdout stays empty and one
final diagnostic line goes to stderr. `--app public` binds `127.0.0.1:8010` and runs
both role controllers (replacing the Lesson 2 Uvicorn process on that port);
`--app client` binds `127.0.0.1:8011` and hosts only the caller. The amount is
not extracted in this lesson.

The combined ingress and independent fixture require `TELNYX_PUBLIC_KEY`,
`TELNYX_API_KEY`, and `IVR_CONNECTION_ID`. The automated caller requires
`TELNYX_PUBLIC_KEY`, `TELNYX_API_KEY`, and the `IVR_CLIENT_*` settings
(own connection ID, outbound caller ID, test destination, synthetic ID).
The independent client requires only
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
- [Lesson 3: automated caller](lessons/03-automated-caller.md) — implemented offline; live verification pending.

Accepted webhooks return empty **200**, after original-byte signature/freshness,
64 KiB body, and envelope checks. Fixture events additionally validate call
identity and current operation. No raw payloads, input, credentials, prompts,
or call-control tokens appear in default logs. Offline tests block real outbound
HTTP; they never place calls or open a tunnel.

Retries, operation correlation, replay guards, and a watchdog bound each call.
Final speech completion precedes normal hangup. Memory-only state cannot recover
calls after restart; end any active call on your handset before restarting.
See the walkthrough for limits, failure reasons, and learner-operated live checks.
