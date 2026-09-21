# IVR Lesson 1 Connectivity Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan sequentially.
> The learner explicitly prohibited subagents. Do not delegate implementation or review.

**Goal:** Establish two local application entry points and verify actual inbound
Telnyx events through a webhook-only public ingress.

**Architecture:** One module owns two role routers, shared authentication, and
three FastAPI app entry points. A single Funnel exposes the combined webhook app.
Lesson 1 acknowledges events only and issues no telephony commands.

**Tech Stack:** Python 3.14, uv, FastAPI, Uvicorn, cryptography, pytest, httpx.

**Spec:** [Lesson 1 design](../specs/2026-09-20-ivr-01-connectivity-design.md).

**Status:** Local implementation and inline review complete. Learner reported
Lesson 1 completion and signed off on 2026-09-21. See the [walkthrough](../../../spikes/ivr/lessons/01-connectivity.md)
for observed results. No subagents were used. These snippets describe the contracts.

## Global constraints

- No subagents during planning or execution unless the learner changes this instruction.
- Python 3.14, independent uv environment and lockfile under `spikes/ivr/`.
- No changes to existing application dependencies or deployment configuration.
- No outbound HTTP calls, answer command, speech, transcription, DTMF, database,
  call state, background tasks, cloud resources, or application UI in Lesson 1.
- Public routes are only `/webhooks/client` and `/webhooks/test-ivr`.
- Preserve unrelated working-tree files and existing Tailscale mappings.
- Keep automated verification offline; live exercises are learner-operated checkpoints.

## File map

| Path | Responsibility |
| --- | --- |
| `spikes/ivr/pyproject.toml` | Independent dependencies, Python requirement, pytest/ruff settings |
| `spikes/ivr/uv.lock` | Resolved dependency versions |
| `spikes/ivr/.env.example` | Public-key setting, no credentials |
| `spikes/ivr/webhooks.py` | Verification, bounded request handling, role routers, app entry points |
| `spikes/ivr/tests/test_webhooks.py` | Offline signed requests and route/privacy checks |
| `spikes/ivr/README.md` | Run commands and lesson links |
| `spikes/ivr/lessons/01-connectivity.md` | Interactive walkthrough and observed acceptance |
| `docs/ivr-learning-plan.md` | Link Lesson 1; clarify first-number timing |

## Task 1 — Isolate the work and create the runnable foundation

- [x] Inspect `git status --short`, `git worktree list`, and branch existence. Use
  the using-git-worktrees guidance to create the agreed worktree and
  `codex/ivr-01-connectivity` branch from current main. Do not duplicate an existing
  worktree or force a branch reset. Copy the curriculum, spec, and plan if they are
  uncommitted; compare their contents before removing any original copy. Do not
  stage unrelated `.pi/` or `AGENTS.md` files.
- [x] Create the project manifest, using the repo's existing FastAPI version:

```toml
[project]
name = "ivr-spike"
version = "0.1.0"
requires-python = "==3.14.*"
dependencies = ["fastapi==0.141.1", "uvicorn[standard]", "cryptography"]

[dependency-groups]
dev = ["pytest", "httpx", "ruff"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
target-version = "py314"
line-length = 88
```

- [x] Run `uv sync --project spikes/ivr`. Confirm Python 3.14 resolves successfully;
  if a dependency cannot support it, report the concrete incompatibility before
  changing the specified runtime. Commit the resulting lockfile with the code.
- [x] Add `.env.example` containing `TELNYX_PUBLIC_KEY=` and comments describing
  the account's base64 public verification key. Confirm ignore behavior with
  `git check-ignore spikes/ivr/.env` and that `.env.example` is not ignored.

**Interface for subsequent tasks:** `webhooks.py` exports `client_app`,
`test_ivr_app`, `public_app`, and
`verify_signature(body: bytes, timestamp: str, signature: str, key: Ed25519PublicKey, *, now: float) -> None`.
Invalid authentication raises `ValueError`; startup configuration errors raise
`RuntimeError` with a generic message. `now` is explicit to make boundary checks
repeatable without sleeps.

## Task 2 — Prove the authentication boundary before wiring routes

- [x] Write a failing test in `tests/test_webhooks.py` using a generated key:

```python
import base64
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from webhooks import verify_signature


def test_exact_bytes_and_freshness():
    private = Ed25519PrivateKey.generate()
    body = b'{"data": {"id": "event-1"}}'
    stamp = "1000"
    signature = base64.b64encode(private.sign(b"1000|" + body)).decode()
    key = private.public_key()
    verify_signature(body, stamp, signature, key, now=1000)
    for bad_body, now in [(body + b" ", 1000), (body, 1301), (body, 699)]:
        with pytest.raises(ValueError):
            verify_signature(bad_body, stamp, signature, key, now=now)
```

- [x] Run from `spikes/ivr`: `uv run pytest tests/test_webhooks.py -q`.
  Confirm failure is the missing implementation, not a broken test environment.
- [x] Implement strict base64 decoding, integer timestamp validation, a ±300-second
  freshness check, and verification of original bytes. Normalize expected parsing
  and `InvalidSignature` failures to `ValueError`. The essential operation is:

```python
key.verify(base64.b64decode(signature, validate=True), timestamp.encode("ascii") + b"|" + body)
```

- [x] Extend the same check with invalid base64, wrong signing key, nonnumeric
  timestamp, and exact accepted boundaries at 700 and 1300. No network or sleeps.
- [x] Add a lifespan that reads the public key, strictly decodes it, and constructs
  `Ed25519PublicKey.from_public_bytes(...)`; set `app.state.telnyx_key`. Reject
  missing/malformed settings on startup, suppressing raw values in errors.
- [x] Run the focused check green. Do not add a development bypass or fake-key
  fallback to application code; test-only keys are injected through the environment.

## Task 3 — Build the three app entry points and test their HTTP behavior

**Consumes:** verification function and startup key from Task 2.
**Produces:** the route and status contract in the spec, with no external effects.

- [x] Add an HTTP test that generates a key, sets `TELNYX_PUBLIC_KEY`, and signs
  actual request bytes. Use `TestClient` as a context manager to execute lifespan:

```python
import json
import time
from fastapi.testclient import TestClient
from webhooks import public_app


def test_both_public_routes(monkeypatch):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setenv("TELNYX_PUBLIC_KEY", base64.b64encode(
        private.public_key().public_bytes_raw()).decode())
    body = json.dumps({"data": {
        "id": "evt-1", "event_type": "call.initiated", "payload": {}
    }}).encode()
    stamp = str(int(time.time()))
    headers = {
        "telnyx-timestamp": stamp,
        "telnyx-signature-ed25519": base64.b64encode(
            private.sign(stamp.encode() + b"|" + body)).decode(),
    }
    with TestClient(public_app) as client:
        for path in ("/webhooks/client", "/webhooks/test-ivr"):
            assert client.post(path, content=body, headers=headers).status_code == 204
            assert client.post(path, content=body).status_code == 401
        for path in ("/health", "/docs", "/openapi.json", "/calls"):
            assert client.get(path).status_code == 404
```

- [x] Run the test and confirm it fails before implementing the apps.
- [x] Implement one common handler taking the role and request; stream into a
  bytearray, returning 413 above 65,536 bytes. Authenticate before JSON parsing.
  Validate the envelope bounds from the spec and return generic 400 on bad input.
  Use one router per role with fixed role values; never take role from payload.
- [x] Define the three app objects with lifespan and disabled docs. Include only
  their intended routers. Add health handlers only to the independent local apps.
  A common handler is enough; no configurable app factory is needed.
- [x] Log `json.dumps({"role": role, "event_id": event_id, "event_type": event_type})`
  through the `ivr.webhooks` logger. Return `Response(status_code=204)`.
- [x] Add parameterized HTTP checks for the following cases, signing altered
  payloads anew where the test concerns envelope validation rather than tampering:

| Input or operation | Assertion |
| --- | --- |
| Signed invalid JSON, missing data, nonobject payload, overlong ID/type | 400 |
| Unsigned or wrong-key body, stale/future timestamp | 401 |
| 65,537 streamed bytes with no Content-Length | 413 |
| Unknown signed event type | 204 |
| Same signed event sent twice | Two 204 responses; no external action |
| Local apps' `/health` | Exact role-specific JSON |
| Other role's route on independent app | 404 |
| Startup without key or with wrong-length key | RuntimeError, no key echoed |
| Payload with synthetic phone and secret sentinel | Neither appears in captured logs |

- [x] For the size case, pass `content=iter([b"x" * 32768, b"x" * 32769])` to
  TestClient; verify no Content-Length is supplied. Capture logs with `caplog` at
  INFO for `ivr.webhooks`. Check the accepted entry includes the expected role.
- [x] Run `uv run pytest -q`, `uv run ruff check .`, and
  `uv run ruff format --check .` from the spike. Fix failures and inspect the diff.

## Task 4 — Write the interactive lesson and perform local verification

- [x] Write README setup commands and a link to `lessons/01-connectivity.md`.
  All commands below assume the shell is in `spikes/ivr`:

```sh
uv sync --locked
cp .env.example .env
# Edit .env locally to set the public verification key.
uv run uvicorn webhooks:client_app --host 127.0.0.1 --port 8011 --env-file .env
# In another terminal:
curl -i http://127.0.0.1:8011/health
```

- [x] Give the corresponding independent test-IVR command on port 8012. Explain
  that neither independent process is needed while the combined ingress is used.
  Use one worker, no reload for the live exercise.

```sh
uv run uvicorn webhooks:public_app --host 127.0.0.1 --port 8010 --env-file .env
# In another terminal, first inspect current routing:
tailscale version
tailscale funnel status
tailscale serve status
# Only when HTTPS 443 is available for this lesson:
tailscale funnel --https=443 http://127.0.0.1:8010
```

- [x] Include numbered portal steps: obtain the public verification key; create
  two Voice API applications; set callbacks; review/purchase one voice-capable
  destination; assign it only to the test-IVR application. Do not request an API
  key, outbound number, or outbound profile for this receiver-only lesson.
- [x] Show the learner how to use the actual Funnel origin for both callbacks and
  public negative probes. `IVR_PUBLIC_URL` below is set locally to that origin:

```sh
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/test-ivr" \
  -H 'Content-Type: application/json' --data '{}'
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/client" \
  -H 'Content-Type: application/json' --data '{}'
curl -i "$IVR_PUBLIC_URL/docs"
```

Expected statuses are 401, 401, and 404. A 2xx here is a failed security checkpoint.

- [x] Explain the manual incoming call: expect ringing, a logged initiated event,
  then a hangup event after the caller ends the call. No answer/menu is implemented.
  If the account does not deliver the expected events, inspect delivery diagnostics
  and fix configuration; do not silently expand this lesson to answering calls.
- [x] Include the wrong-path drill and recovery, Tailscale permission/port conflict
  troubleshooting, signature failure causes (key, clock, raw bytes), and stop steps.
  Never prescribe `tailscale funnel reset`; remove only this lesson's route.
- [x] Copy the spec's acceptance table into the guide with all live rows initially
  Not run. Include observed date, commands, sanitized event IDs, and learner sign-off.
- [x] Update the curriculum's Lesson 1 link and number timing: destination number
  now, outbound number/profile in Lesson 3. Do not mark Lesson 1 complete yet.
- [x] Run the offline suite and formatting once after final changes. Manually
  launch both independent entry points with a synthetic local verification key
  and check health, then stop them. Do not enable Funnel or buy numbers as part
  of offline verification.

## Task 5 — Review, checkpoint, and learner handoff

- [x] Review the whole diff inline against the spec: role separation, fail-closed
  startup, byte-exact authentication, bounded bodies, safe logs, and public routes.
  No subagents. No existing application or cloud changes should be present.
- [x] Run `git diff --check`; inspect `git status --short` and staged filenames to
  ensure only lesson files and its documents are included, with no `.env`.
- [x] Commit the completed local foundation on `codex/ivr-01-connectivity` with
  a message such as `feat: add IVR lesson 1 verified webhook foundation`.
- [x] Present the walkthrough and local verification results. Work through its
  live checkpoints with the learner and record observations as they occur.
- [ ] After the learner's live acceptance, review/merge the lesson PR through the
  agreed repository workflow. Lesson 2 starts on a new branch from updated main
  in the same IVR worktree. Never claim Lesson 1 passed before live evidence exists.

## Validation of this plan

The scope deliberately stops at authenticated event receipt. The tests exercise
both applications and the combined public surface; live evidence covers only the
fixture because the client does not dial yet. Deferred lessons are not implemented
as scaffolding. Worktree creation and offline implementation are complete. The learner reported live completion and signed off on 2026-09-21; detailed live
artifacts were not supplied. See the walkthrough acceptance record.
