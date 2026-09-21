# Lesson 1 — Local apps and verified webhooks

**Status:** Complete. Learner reported completion and signed off on 2026-09-21.

**Compatibility note, 2026-09-21:** This guide preserves Lesson 1's historical
commands and evidence. On the Lesson 2 branch, fixture/public startup additionally
requires the local API credential and fixture application ID; accepted callbacks
return 200. Use the [Lesson 2 settings and walkthrough](02-test-ivr.md) for current
commands. The client remains receipt-only. Lesson 1 acceptance below is unchanged.

An event tells you what happened. A command asks Telnyx to do something.
Returning HTTP 204 acknowledges an event; it does not answer a ringing call.
This lesson receives events only. Speech and menus belong to Lesson 2; outbound
calls, an API credential, and an outbound profile belong to Lesson 3.

## 1. Use the isolated worktree

The implementation is on `codex/ivr-01-connectivity`. From your original checkout:

```sh
git worktree list
git branch --list codex/ivr-01-connectivity
```

Use the existing listed IVR worktree; do not create a second one or reset its
branch. This execution used:

```sh
cd /Users/tylerv/.codex/worktrees/ivr-01-connectivity/fullstack/spikes/ivr
```

The curriculum, spec, and plan were copied into this worktree. Their original
uncommitted copies were preserved, along with unrelated `AGENTS.md` and `.pi/`.
All following commands assume this spike directory unless stated otherwise.

Prerequisites: uv, Python 3.14, Tailscale with Funnel permission, a verified Telnyx
account with Voice API access, and a personal phone. A voice-capable destination
number is needed at step 5; reuse a suitable owned number when possible.

## 2. Install and configure locally

```sh
uv sync --locked
cp .env.example .env
```

Skip the copy if you already configured `.env`. In the Telnyx portal, find the
account's public webhook verification key (base64 Ed25519, generally in account
/API-key settings). Paste it into `TELNYX_PUBLIC_KEY` in `.env` locally. Portal
labels may change. This is a public verification key, not an API credential.
Do not paste credentials into the lesson record or commit `.env`.

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git check-ignore .env
```

Expected: all tests and Ruff checks pass; `.env` is ignored. Missing, malformed,
or wrong-length keys stop app startup with a generic configuration error.
The locked test stack currently emits two upstream deprecation warnings about
Starlette's httpx support and its AnyIO portal alias; tests still pass.

## 3. Run each independent app

Terminal A:

```sh
uv run uvicorn webhooks:client_app --host 127.0.0.1 --port 8011 --env-file .env --no-access-log
```

Terminal B:

```sh
curl -i http://127.0.0.1:8011/health
```

Expect 200 and `{"status":"ok","role":"client"}`. Stop Terminal A with Ctrl+C.
Then run the fixture:

```sh
uv run uvicorn webhooks:test_ivr_app --host 127.0.0.1 --port 8012 --env-file .env --no-access-log
```

From Terminal B:

```sh
curl -i http://127.0.0.1:8012/health
```

Expect 200 and `{"status":"ok","role":"test-ivr"}`. Stop the fixture with Ctrl+C.
Each independent app owns only its role's webhook. Neither process is needed
for the live exercise: the combined ingress hosts both handlers in one process.
There is no forwarding between ports or cross-process shared state.

## 4. Expose only the combined webhooks

Terminal A, one worker and no reload:

```sh
uv run uvicorn webhooks:public_app --host 127.0.0.1 --port 8010 --env-file .env --no-access-log
```

Access logs are disabled so arbitrary request paths/query strings are not logged.
Accepted events still appear as JSON records in Uvicorn's stderr output.
Application event logs contain only role, event ID, and event type, never payloads.

Before changing any Tailscale routing, Terminal B:

```sh
tailscale version
tailscale funnel status
tailscale serve status
```

Record existing routes locally so cleanup can preserve them. If HTTPS 443 is
unused, start the foreground tunnel:

```sh
tailscale funnel --https=443 http://127.0.0.1:8010
```

Use the exact HTTPS origin printed by Tailscale. If 443 already has a Serve or
Funnel route, stop here and agree on an unused supported port/host before changing
anything. Do not overwrite unrelated mappings. Funnel supports 443, 8443, and
10000; an alternate port must also appear in both callback URLs. If permission
or enablement is required, resolve it with the tailnet owner. Do not bypass it.
See the [Funnel CLI reference](https://tailscale.com/docs/reference/tailscale-cli/funnel).

In Terminal C, replace the example with the reported origin, without a trailing slash:

```sh
export IVR_PUBLIC_URL='https://YOUR-REPORTED-HOST.ts.net'
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/test-ivr" \
  -H 'Content-Type: application/json' --data '{}'
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/client" \
  -H 'Content-Type: application/json' --data '{}'
for route in health docs redoc openapi.json calls arbitrary; do
  curl -i "$IVR_PUBLIC_URL/$route"
done
```

Expect 401 for both forged POSTs and 404 for every GET. No accepted event log
should appear for the forged requests. A 2xx is a failed security checkpoint;
stop exposure and diagnose before using a real call. A loopback bind does not
make a route private once tunneled.

## 5. Configure Telnyx and make one manual call

1. In the Telnyx portal, confirm the verification key is from this account and
   Voice API / Call Control is available.
2. Create a Voice API application named for the client. Set its webhook callback
   to the actual Funnel origin plus `/webhooks/client`, using POST where offered.
3. Create a separate Voice API application for the test IVR. Set its callback to
   the same origin plus `/webhooks/test-ivr`. Save both settings; avoid unrelated
   failover callbacks that would obscure this lesson's delivery evidence.
4. Inspect your owned numbers for a suitable voice-capable destination. If one
   must be purchased, review the portal's actual number and usage prices and
   explicitly approve the purchase yourself. This guide authorizes no purchase.
5. Associate the destination number only with the test-IVR Voice API application.
   Do not provision the client's outbound number or outbound profile yet.
6. Call the destination from your personal phone. Expect ringing and no speech.
   Look for `call.initiated` with role `test-ivr` in Terminal A.
7. Hang up from your phone. Look for `call.hangup` with role `test-ivr`.
   Record sanitized event IDs and observed time below, not phone numbers/payloads.

Illustrative accepted log (the ID will differ):

```json
{"role": "test-ivr", "event_id": "redacted-event-id", "event_type": "call.initiated"}
```

Unknown signed event types also return empty 204. Duplicate delivery may repeat
logs; this lesson performs no commands or other side effects. Fresh timestamps
limit replay age but do not deduplicate within the window. Command idempotency
must be added with the first call-control behavior, before its live use.

The [Telnyx signing reference](https://developers.telnyx.com/api-reference/callbacks/call-fork-started)
describes the timestamp and Ed25519 signature over `timestamp|raw_body`.
This implementation follows the spec's empty 204 response. That reference page
lists 200 as its callback response, so inspect actual delivery diagnostics for
acknowledgment/retries during acceptance; synthetic 204 checks cannot establish
provider acceptance. Do not declare the live checkpoint passed if delivery retries.
The client route has offline evidence only until outbound calling in Lesson 3.

## 6. Break the path, then recover

1. Temporarily change only the test-IVR callback to end in
   `/webhooks/test-ivr-wrong` and save it.
2. Make another manual call, then hang up. Inspect Telnyx delivery diagnostics
   for failure/404 at the wrong path; no accepted log should arrive there.
3. Restore `/webhooks/test-ivr`, save, and repeat a call and manual hangup.
4. Record successful initiated and hangup delivery after restoration. Repeat the
   two forged public POSTs from step 4: each must still return 401 without logging
   an accepted event.

If expected events do not arrive, inspect number-to-application assignment,
callback spelling, origin/port, Funnel availability, and provider diagnostics.
Do not expand the lesson to answering calls to hide a delivery problem.
For 401 on real events, check the account key, Mac clock synchronization, timestamp
age, and whether any intermediary rewrites body bytes. Never reserialize a body
before checking its signature or turn signature verification off to troubleshoot.
For connection refused, check the ingress process and port. A 413 means the
stream exceeded 65,536 bytes, regardless of Content-Length.

## 7. Stop exposure and record acceptance

Hang up any remaining call. Ctrl+C the foreground Funnel in Terminal B and the
ingress in Terminal A. Inspect routing again:

```sh
tailscale funnel status
tailscale serve status
```

Compare with the pre-lesson state. If this lesson's exact 443 mapping remains,
and it still points only to this lesson's ingress, remove only that mapping:

```sh
tailscale funnel --https=443 http://127.0.0.1:8010 off
tailscale funnel status
tailscale serve status
```

If an alternate port was agreed, use its original flags instead. Never reset all
Funnel routes. Confirm unrelated mappings are unchanged and this lesson's public
URL no longer reaches the app. No session state exists to clear.

## Acceptance record

Offline observation: 2026-09-20 (America/Los_Angeles), Python 3.14.7.
Commands: `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .`,
`uv run ruff format --check .`; loopback Uvicorn smoke checks with a generated
in-memory key. No real account key, tunnel, number purchase, or paid call was used.

| Evidence | Required outcome | Observed status |
| --- | --- | --- |
| Startup settings | Missing or invalid key fails closed | Passed offline |
| Independent apps | Both health endpoints identify the right role | Passed offline and loopback |
| Signed HTTP checks | Both routes accept authentic synthetic envelopes | Passed offline |
| Rejection checks | Tampering, wrong key, missing headers, stale/future timestamps rejected | Passed offline |
| Envelope and size | Signed malformed input returns 400; oversized stream returns 413 | Passed offline |
| Public surface | No health, docs, or control endpoints exposed | Passed locally; live completion reported by learner |
| Privacy | Accepted logs contain no payload or secrets | Passed offline |
| Live incoming call | Initiated and hangup events observed on fixture route | Completion reported by learner |
| Routing recovery | Wrong callback fails; restored callback succeeds | Completion reported by learner |
| Cleanup | Lesson tunnel removed; unrelated mappings preserved | Completion reported by learner |
| Learner acceptance | Learner confirms walkthrough completion | Signed off 2026-09-21 |

Learner sign-off recorded 2026-09-21 (America/Los_Angeles): “I completed lesson 1
and signed off.” Live completion is learner-reported, not independently observed
by the implementation agent. Per-checkpoint timestamps, Tailscale version/origin,
probe output, sanitized event IDs, delivery diagnostics, and cleanup output were
not supplied in this conversation and are not fabricated here.

Lesson 1 is accepted. Continue with Lesson 2 on a new branch from updated `main`.
