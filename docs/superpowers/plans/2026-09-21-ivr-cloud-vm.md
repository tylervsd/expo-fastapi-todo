# IVR Cloud VM Implementation Plan

> Use superpowers:executing-plans to implement sequentially. No subagents are
> needed for this small extension. Planning does not provision resources or dial.

**Goal:** Run the IVR behind stable Google Cloud HTTPS and observe transcription
delivery without the Mac/Funnel path.
**Architecture:** One Compute Engine VM, Caddy, one persistent combined FastAPI
process, and a Unix socket for SSH-operated initiation. One call per process.
**Stack:** Existing Python 3.14/uv/httpx/FastAPI/pytest; stdlib asyncio Unix sockets;
Debian 12, systemd, Caddy and gcloud.
**Spec:** [Cloud VM design](../specs/2026-09-21-ivr-cloud-vm-design.md).
**Status:** Proposed 2026-09-21; all implementation and deployment tasks pending.

## Global constraints

- Use the existing Lesson 3 branch/worktree; preserve local runner and credentials.
- One worker, in-memory state, one automated call per process; restart never dials.
- Keep signature verification, final-only parsing, deadlines and fixture isolation.
- No public controls, new Python dependencies, database, queue or autoscaling.
- Do not mutate the existing todo infrastructure or its Terraform state.
- Project is `fullstack-sandbox-tylervsd`; ceiling is $20/month for the proposed
  incremental IVR cloud resources. Hostname is `ivr.tylervallillee.info`, using
  the learner's existing DNS provider. Network remains an input; propose
  us-west1/us-west1-a and e2-micro. Confirm regional pricing and memory fit.
- Obtain a concrete resource/cost approval before provisioning; no guessed targets.
- Cloud delivery, speech recognition, and learner acceptance are separate outcomes.

## Review focus

- A dropped start acknowledgment must not lead to a duplicate paid call (Task 1).
- Early readiness failure or a service restart must never dial (Task 1).
- Malformed unsigned requests must remain rejected without logging secrets (Task 2).
- Loopback control must not become publicly reachable through Caddy (Tasks 3–4).
- Service shutdown must preserve bounded cleanup and never claim remote termination
  from local process exit alone (Tasks 1 and 4).

## Baseline and file map

Work in `/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity`,
branch `codex/ivr-03-automated-caller`; planning baseline commit `aa8f587`.
Before code edits read the spec, full `caller.py`, `webhooks.py`, and Caller
lifecycle in `client.py`, then run:

```sh
git status --short --branch
cd spikes/ivr
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Do not reuse historical test counts as new evidence. All paths below are relative
to `spikes/ivr/` unless explicitly prefixed with `docs/`.

| File | Change |
| --- | --- |
| `cloud_runner.py` | New persistent runner and local socket client/server |
| `tests/test_cloud_runner.py` | Lifecycle, control parsing, concurrency, cleanup |
| `client.py`, `tests/test_client.py` | Validated track setting and sanitized speech decisions |
| `webhooks.py`, `tests/test_webhooks.py` | Request outcome diagnostics |
| `.env.example` | Optional track setting with existing default |
| `deploy/ivr.service`, `deploy/Caddyfile` | Runtime and HTTPS templates |
| `deploy/README.md` | Exact provisioning, installation, cost, cutover and teardown guide |
| `README.md`, `lessons/03-automated-caller.md` | Cloud diagnostic extension links and evidence |

## Task 1 — Persistent server and private one-shot control

- [ ] Add failing tests using an injected fake caller and server. Define
  `async handle_control(reader, writer, caller, lock)` and
  `async serve()` in `cloud_runner.py`, with `main(argv=None)` selecting
  serve/start/status. Tests must verify zero dial on serve startup, one dial for
  two concurrent starts, status after lost acknowledgment, and service survival
  after caller.done. Example core assertions using the test's fake caller:

```python
assert fake_caller.start_count == 0  # after server readiness
await asyncio.gather(send_start(), send_start())
assert fake_caller.start_count == 1
fake_caller.done.set()
assert not server_task.done()
assert (await get_status())["done"] is True
```

- [ ] Implement fake helpers locally in the test with StreamReader and a writer
  capturing bytes; no real cloud or paid call. Run
  `uv run pytest tests/test_cloud_runner.py -q` and confirm failure first.
- [ ] Implement control with `asyncio.start_unix_server`, 64-byte request bound,
  two-second read deadline, mode 0600 socket in the protected directory, four
  concurrent handlers maximum and one start lock. Accept only `start\n` and
  `status\n`. Use Caller._started only where required by the existing API; avoid
  adding a new controller framework. Reply with bounded JSON literals such as
  `{"status":"started"}`, `{"status":"busy"}` or
  `{"status":"restart_required"}`. Status exposes only safe fields from the spec.
- [ ] Enable `public_app.state.caller_enabled`, start Uvicorn on loopback 8010,
  use the existing readiness pattern, and create the control socket only after
  lifespan has initialized `app.state.caller`. Never call start from serve.
  Reuse lifespan watchdogs and cleanup; keep serving after caller.done.
- [ ] Add tests for oversized/unterminated commands, stalled peers, excess
  connections, disconnect before acknowledgment, duplicate starts after finish,
  socket permissions, startup failure and cancellation. On shutdown close the
  Unix listener/handlers before Uvicorn; drain under the service's 60-second
  allowance. Never unlink an arbitrary path or another running server's socket.
- [ ] Run focused tests plus the existing CLI/webhook tests and Ruff; commit
  only the runner and its tests as `feat: add persistent IVR diagnostic runner`.

## Task 2 — Track selection and private diagnostics

- [ ] Add `transcription_track: str = "outbound"` to ClientSettings, mapped to
  `IVR_CLIENT_TRANSCRIPTION_TRACK`. Tests pin accepted inbound/outbound, rejected
  both/empty/arbitrary values, and unchanged default dial payload. Test core:

```python
assert _dial_fields(settings_inbound)["transcription_config"]["transcription_tracks"] == "inbound"
assert _dial_fields(settings_default)["transcription_config"]["transcription_tracks"] == "outbound"
```

- [ ] Verify new tests fail, replace the hardcoded track in `_dial_fields`, and
  document the variable in `.env.example`. The VM guide explicitly sets inbound.
  Keep dial-time startup; do not copy the temporary monkeypatch runner into product code.
- [ ] Add request-outcome logging around the verified routes, including rejected
  requests. Log only path, status and duration. Test unsigned POST yields 401,
  malformed signed event yields 400, accepted event yields 200, and sentinel
  values in body/headers/query never appear in logs. Keep existing status semantics.
- [ ] Add sanitized client transcription diagnostic fields: final boolean,
  ownership-match booleans, stage and parser decision. Observe the real parser
  result rather than parsing a second time for logging. Test partial events
  produce no DTMF, final complete welcome does, wrong-leg finals do not, and logs
  omit transcript/identifiers/call tokens. Use synthetic test-only values.
- [ ] Run the complete offline suite, Ruff and format check; record real results
  and commit as `feat: expose safe IVR transcription diagnostics`.

## Task 3 — Deployable service, proxy and operating guide

- [ ] Create systemd template using a fixed release installation path:

```ini
[Unit]
Description=IVR diagnostic webhook server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
User=ivr
Group=ivr
WorkingDirectory=/opt/ivr/current
EnvironmentFile=/etc/ivr/ivr.env
ExecStart=/opt/ivr/current/.venv/bin/python cloud_runner.py serve
RuntimeDirectory=ivr
RuntimeDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/ivr
Environment=PYTHONDONTWRITEBYTECODE=1

[Install]
WantedBy=multi-user.target
```

- [ ] Create a Caddy template with the actual hostname supplied through its
  service environment. Validate installed Caddy syntax before enabling:

```caddyfile
{$IVR_HOSTNAME} {
    @webhooks {
        method POST
        path /webhooks/client /webhooks/test-ivr
    }
    handle @webhooks {
        reverse_proxy 127.0.0.1:8010
    }
    handle {
        respond 404
    }
}
```

- [ ] Write `deploy/README.md` with concrete parameterized gcloud commands for
  the approved project/zone/network, static IP, tagged firewall rules, Debian VM,
  IAP SSH and OS Login. Do not use default service-account privileges. Inspect
  existing network policies rather than assuming a VPC exists or is safe.
- [ ] Include a resource/cost table populated from current Google pricing for
  the chosen inputs before provisioning. Include VM running hours, disk, IPv4,
  egress, domain if needed, and persistent charges after stop. Ask for remaining
  inputs together; don't request secrets in chat.
- [ ] Document verified official installation steps for uv/Python 3.14 and Caddy;
  resolve a tested release commit, transfer only tracked spike source, run
  `uv sync --locked`, and set release ownership so the runtime cannot modify code.
  Install root-owned 0600 environment file through SSH, not metadata or CLI args.
- [ ] Include `systemd-analyze verify`, `caddy validate`, service status/journal
  inspection, local/public unsigned curl checks, and local socket commands.
  Test Linux-specific permissions and service hardening on the VM before cutover.
- [ ] Add rollback and named-resource teardown instructions. Preserve the local
  command and existing URLs privately. Commit reviewed templates/guide.

## Task 4 — Provision, validate and cut over after inputs/approval

- [ ] Present the concrete target project, resource names, region/zone, network,
  hostname and estimated monthly cost for approval after Tasks 1–3 are reviewable.
  No provisioning command runs with unresolved values.
- [ ] Provision only approved named IVR resources; record IDs and resolved image/
  package versions. Install the release and secret environment without printing
  its contents. Start systemd/Caddy, verify DNS and certificate trust externally.
- [ ] Verify startup and service restart dial zero times. Check protected socket
  ownership and that port 8010 is inaccessible externally. Unsigned POSTs must
  consistently return 401; unknown routes return 404. Run a small concurrent
  sample and record failure/status/latency counts, not a reliability guarantee.
- [ ] After confirming no active call, save old Telnyx primary/failover URLs
  privately and change only approved callback settings to the cloud hostname.
  Leave number assignments and existing local files intact.
- [ ] Run one authorized call through the SSH/socket command. Capture safe
  interim/final and ownership/parser diagnostics plus delivery counts. Confirm
  both call legs ended; keep serving at least 60 seconds afterward. If remote
  termination is uncertain, inspect/terminate via provider before service restart.
- [ ] Record cloud-ingress acceptance separately from final transcript and
  Lesson 3 acceptance. If the call still fails, preserve evidence; do not disable
  final-only parsing, bypass signatures or widen scope to Lesson 4.
- [ ] Verify rollback instructions and service stop behavior. Summarize actual
  resources/cost exposure, deployment URL, source commit, tests, live result and
  outstanding issues. Do not merge the lesson without learner acceptance.

## Planning self-review

Tasks cover process ownership/control (1), track and privacy (2), deployment
artifacts/security/cost (3), and cutover/evidence/rollback (4). No new persistent
state is implied; one-call-per-process is explicit. Credentials and deployment
inputs are distinct. No cloud or live success is claimed during planning.
