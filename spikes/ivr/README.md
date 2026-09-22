# IVR spike

Lessons 1–5 are accepted. Lesson 4 adds strict amount extraction, one terminal
value-or-error JSON record, bounded finalization, and correlated safe diagnostics.
Implementation is verified offline; the learner reported Lesson 4 walkthrough
completion and signed off on 2026-09-22. Prior transcription reliability limitations remain.

Lesson 5 adds fixture-only failure scenarios and offline event-replay checks;
learner sign-off received 2026-09-22; detailed live-call evidence not supplied. See the
[Lesson 5 walkthrough](lessons/05-reliability-drills.md).

**Developer guide:** [Client call flow and how to change it](docs/client-call-flow.md) — source walkthrough, stage map, and a worked menu-step example.

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

One CLI invocation places exactly one call, then exits. Stdout contains one
JSON success (`value` as a two-place decimal string, `currency: USD`) or error
(`code`, original `stage`). Exit 0 means a complete unambiguous amount; errors
exit 1 and interruption may exit 130. Diagnostics go to stderr. Cleanup failure
does not replace an already decided result. `--app public` binds loopback 8010
and hosts both roles; `--app client` binds loopback 8011 and hosts only the caller.
See [Lesson 4](lessons/04-value-or-error.md) for grammar, finalization, output
capture, and cloud result retrieval. `IVR_CLIENT_DEBUG_TRANSCRIPTS=1` enables
metadata-only diagnostics without transcript text.

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
- [Lesson 3: automated caller](lessons/03-automated-caller.md) — accepted 2026-09-22.
- [Lesson 4: value or error](lessons/04-value-or-error.md) — accepted 2026-09-22; walkthrough completion reported by learner.

Accepted webhooks return empty **200**, after original-byte signature/freshness,
64 KiB body, and envelope checks. Fixture events additionally validate call
identity and current operation. No raw payloads, input, credentials, prompts,
or call-control tokens appear in default logs. Offline tests block real outbound
HTTP; they never place calls or open a tunnel.

Retries, operation correlation, replay guards, and a watchdog bound each call.
Final speech completion precedes normal hangup. Memory-only state cannot recover
calls after restart; end any active call on your handset before restarting.
See the walkthrough for limits, failure reasons, and learner-operated live checks.
