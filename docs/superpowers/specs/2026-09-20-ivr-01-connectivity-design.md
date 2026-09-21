# IVR Lesson 1: local applications and verified webhooks

**Status:** Local foundation implemented and verified on `codex/ivr-01-connectivity`.
Live acceptance remains pending; see the [walkthrough](../../../spikes/ivr/lessons/01-connectivity.md).
No subagents were used. The table below preserves the pre-execution baseline.

**Related:** [Curriculum](../../ivr-learning-plan.md),
[implementation plan](../plans/2026-09-20-ivr-01-connectivity.md).

## Goal

Run the client and test-IVR application foundations locally and demonstrate that
an actual inbound Telnyx call delivers authenticated events to the test-IVR route.
Reject forged requests. Teach the difference between receiving an event and
issuing a command to answer or control a call.

The learner reports Tailscale installed and a verified Telnyx account. Number
ownership, Voice API permissions, Funnel availability, and webhook delivery remain
unverified. One voice-capable destination number is needed for this lesson. The
outbound number and dialing profile belong to Lesson 3.

## Scope

- Python 3.14, independent uv environment and lockfile under `spikes/ivr/`.
- FastAPI and Uvicorn; cryptography for Ed25519 verification; pytest and httpx for
  local HTTP checks. No Telnyx SDK or API credential is needed to receive events.
- Two independently runnable local FastAPI apps: client and test IVR.
- One combined public ingress containing only the two webhook routes.
- No outbound HTTP calls, answer command, speech, transcription, DTMF, database,
  call state, background tasks, cloud resources, or application UI in Lesson 1.
- No changes to existing application dependencies or deployment configuration.
- No subagents during planning or execution unless the learner changes this instruction.

## Architecture and route contract

Use one small `webhooks.py` module with a shared verification function, one router
per role, and three FastAPI app objects. Sharing transport code is intentional;
future client and fixture state must remain separate. Do not introduce a service
framework, proxy process, or provider abstraction.

| Entry point | Local port | Routes |
| --- | --- | --- |
| `webhooks:client_app` | 8011 | `GET /health`, `POST /webhooks/client` |
| `webhooks:test_ivr_app` | 8012 | `GET /health`, `POST /webhooks/test-ivr` |
| `webhooks:public_app` | 8010 | Both webhook POST routes only |

All bind to `127.0.0.1`. Disable OpenAPI, Swagger, and ReDoc on all apps.
Health returns `{"status":"ok","role":"client"}` or role `test-ivr`.
The public app includes only webhook routers, not the full local apps; `/health`,
`/docs`, `/openapi.json`, `/calls`, and arbitrary paths return 404 there.

During live testing run the combined ingress only. It hosts both role handlers in
one process; the independent entry points demonstrate separate runnability and
are checked locally. There is no forwarding between the three ports and no claim
that separate processes share state. Revisit runtime composition when adding state.

Telnyx configuration uses two Voice API applications with callbacks ending in
`/webhooks/client` and `/webhooks/test-ivr` on the same Funnel hostname. Associate
one purchased voice number with the test-IVR application. The client application
has no live originating call in this lesson, so its evidence is offline only.

## Authentication and validation

Read `TELNYX_PUBLIC_KEY` from the environment at application startup. It is the
account's base64 Ed25519 public verification key, not an API key. Missing, invalid
base64, or wrong-length key must fail startup without echoing the configured value.
Use a FastAPI lifespan for each runnable app, with the decoded key on app state.

For each webhook:

1. Collect the original body bytes with a 64 KiB streaming limit; stop and return
   413 when exceeded, even if Content-Length is missing or misleading.
2. Require `telnyx-timestamp` and `telnyx-signature-ed25519`. Reject malformed
   headers, invalid signature encoding, and timestamps more than 300 seconds in
   either direction from local wall time with generic 401 responses.
3. Verify Ed25519 over the exact bytes `timestamp + "|" + raw_body`; do not parse
   and reserialize JSON before verification. Use the cryptography library's
   primitive, not handwritten cryptographic code.
4. Parse and validate the signed envelope. Require an object `data` with nonempty
   bounded strings `id` (maximum 256 characters) and `event_type` (maximum 128),
   and an object `payload`. Allow additional provider fields. Return generic 400
   for invalid JSON or envelope; do not echo validation inputs.
5. Emit one structured log entry containing only role, event ID, and event type,
   JSON-escaped to prevent multiline log injection. Return empty 204.

Do not log request bodies, headers, phone numbers, credentials, or payload fields.
Unknown signed event types are accepted and logged without taking action. Duplicate
signed events may produce duplicate logs; they have no side effects. Timestamp
freshness limits replay age but does not deduplicate events within that window.
Command idempotency belongs with the first call-control behavior, before live use.

## Local configuration and exposure

Commit `.env.example` with an empty `TELNYX_PUBLIC_KEY` and an explanation of where
it comes from. Local `.env` is already ignored by the repo. Use Uvicorn's env-file
support; pin all resolved dependencies with the spike's own `uv.lock`.

Before changing Tailscale, inspect `tailscale version`, `tailscale funnel status`,
and `tailscale serve status`. Preserve existing routes. If HTTPS 443 is unused,
run the foreground command `tailscale funnel --https=443 http://127.0.0.1:8010`.
Use the actual reported HTTPS hostname. If an existing route conflicts, stop the
setup step and resolve which unused supported port/host to use with the learner;
do not run a global reset or replace unrelated routes. Funnel requires the
appropriate tailnet permission and may prompt for enablement.

A local terminal starts the ingress; a second starts Funnel. Stopping the foreground
Funnel and ingress ends this exposure. Inspect status afterward and remove only
this lesson's mapping if it remains. Public probes must show webhook authentication
and absent administrative routes; a loopback bind alone does not make tunneled
routes private.

## Lesson walkthrough and acceptance

The implementation adds `spikes/ivr/lessons/01-connectivity.md`. It contains exact
commands, expected responses, portal concepts, and the following checkpoints:

1. Create/use the isolated IVR worktree on `codex/ivr-01-connectivity`. Transfer
   these documents and curriculum without losing the original uncommitted files.
2. Install the independent environment, configure the public key locally, and
   run offline tests. Start each independent app and inspect its health response.
3. Start the combined ingress and Funnel; inspect public route behavior.
4. Create the two Voice API applications, configure callbacks, and associate one
   voice-capable number with the test IVR. Review actual number and usage prices
   in the portal before purchase. This document authorizes no purchase itself.
5. Call that number from a personal phone. Observe a verified `call.initiated`
   event tagged `test-ivr`, then manually hang up and observe `call.hangup`.
   The app does not answer: ringing and no spoken response are expected.
6. Send a forged webhook to each public route and observe 401 without an accepted
   event log. Temporarily misconfigure the callback path, observe delivery failure,
   restore it, and repeat a call. Provider dashboard details may vary.
7. Stop exposure and record results. No session state exists to clean up; the
   learner ends the ringing call from the handset.

| Evidence | Required outcome | Initial status |
| --- | --- | --- |
| Startup settings | Missing or invalid key fails closed | Not run |
| Independent apps | Both health endpoints identify the right role | Not run |
| Signed HTTP checks | Both routes accept authentic synthetic envelopes | Not run |
| Rejection checks | Tampering, wrong key, missing headers, stale/future timestamps rejected | Not run |
| Envelope and size | Signed malformed input returns 400; oversized stream returns 413 | Not run |
| Public surface | No health, docs, or control endpoints exposed | Not run |
| Privacy | Accepted logs contain no payload or secrets | Not run |
| Live incoming call | Initiated and hangup events observed on fixture route | Not run |
| Routing recovery | Wrong callback fails; restored callback succeeds | Not run |
| Cleanup | Lesson tunnel removed; unrelated mappings preserved | Not run |
| Learner acceptance | Learner confirms walkthrough completion | Pending |

Offline synthetic signatures prove local behavior, not Telnyx delivery. Do not
claim live success from unit tests. Live client-originated webhooks are deferred
until Lesson 3, and full menu behavior until Lesson 2.

## Alternatives considered

Separate public tunnels for each process add configuration without helping this
stateless lesson. Mounting whole local apps publicly risks exposing future controls.
An explicit webhook-only combined app keeps a single tunnel and a narrow surface.

## References

Checked while drafting; verify installed CLI behavior during the walkthrough.

- [Telnyx webhook headers and signing format](https://developers.telnyx.com/api-reference/callbacks/call-fork-started)
- [Telnyx webhook guide](https://github.com/team-telnyx/ai/blob/main/guides/webhooks.md)
- [Tailscale Funnel command](https://tailscale.com/docs/reference/tailscale-cli/funnel)
- [Tailscale Funnel requirements](https://tailscale.com/docs/features/tailscale-funnel)
