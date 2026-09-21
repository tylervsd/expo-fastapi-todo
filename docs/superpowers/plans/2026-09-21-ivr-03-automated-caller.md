# IVR Lesson 3 Automated Caller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (fresh worker per task plus per-task review) or superpowers:executing-plans
> for inline execution. Steps use checkbox syntax for tracking.
> Planning used no subagents. The learner authorized implementation with
> subagents on 2026-09-21; this document is not permission to place live calls.

**Goal:** Call the configured fixture, navigate using final speech transcripts,
verify the synthetic-ID readback, and reach the result announcement safely.

**Architecture:** A one-call CLI owns Uvicorn and the client controller in one
event loop, reusing verified webhook routes. The combined mode also hosts the
independent fixture controller. A narrow parser recognizes the documented
prompts; immutable commands and monotonic deadlines bound call control.

**Tech Stack:** Python 3.14, uv, FastAPI, Uvicorn, cryptography, httpx, pytest,
Ruff; stdlib argparse, asyncio, dataclasses, re, time, datetime, uuid and base64.

**Spec:** [Lesson 3 design](../specs/2026-09-21-ivr-03-automated-caller-design.md).

**Status:** Implemented and verified offline 2026-09-21 (358 tests, Ruff check
and format clean); live verification and learner acceptance remain pending.
[Lesson guide](../../../spikes/ivr/lessons/03-automated-caller.md) created.
Planning used no subagents; implementation used authorized subagents (bounded
scout, workers per task, per-task reviewers, final whole-branch review).
Author self-review plus per-task and final reviews; no live calls placed.

## Global Constraints

- Python 3.14; one independent uv environment and lockfile under `spikes/ivr/`.
- Reuse FastAPI, Uvicorn, cryptography, pytest, and httpx; no new library or SDK.
- One automated call per CLI invocation, one worker, no reload, in-memory state only.
- Keep all three existing entry points and both webhook paths; no HTTP call-start or scenario controls.
- Dial only the configured test number; no destination argument or webhook-driven dialing.
- Client code must not read fixture state, challenge override, result amount, or fixture settings.
- No database, queue, cloud deployment, UI, LLM, recording, or custom audio streaming.
- No subagents during planning; implementation used learner-authorized subagents.
- Automated verification is offline; live acceptance is learner-operated and separately recorded.
- Do not purchase numbers, change account settings, or expose a tunnel during this work.
- Preserve unrelated local changes and existing Tailscale mappings.

## Review Focus

- Answered/transcription/hangup can precede the dial HTTP response; no foreign leg may acquire control (Task 4).
- Repeated zero words and fragmented digit runs must survive buffering; decimal or ambiguous text must not become valid digits (Tasks 1 and 3).
- A next-stage prompt may beat DTMF HTTP acknowledgment; obsolete errors cannot undo progress or resend tones (Task 4).
- A port collision or lifespan failure must prevent a paid dial, and CLI shutdown must clean up its owned call (Task 5).
- Call-control tokens and identifiers must not leak through exceptions, settings repr, stdout, or provider bodies (Tasks 2, 4 and 5).

## Workspace and baseline

Reuse `/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity`
on `codex/ivr-03-automated-caller`, created from merged main `ea6ee2d` (PR #34).
The historical directory name remains intentional. Keep the prior lesson branch
and main checkout's unrelated `.pi/`. No reset, stash, clean, new worktree, or
copying of credentials. Do not push or merge before the learner's checkpoint.

Before implementation inspect the working tree, read both planning documents,
then verify the baseline from the worktree:

```sh
git status --short --branch
git worktree list
git log -3 --oneline
cd spikes/ivr
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Planning verified 168 tests and both Ruff checks with the existing `.venv/bin/`
executables; two upstream deprecation warnings remain. Do not mistake the
existing Lesson 2 spec's stale acceptance status for a new blocker: the
curriculum and Lesson 2 guide record learner acceptance on 2026-09-21.

## File map and interfaces

Paths in tasks are relative to `spikes/ivr/`, unless prefixed with `docs/`.

| Action | Path | Responsibility |
| --- | --- | --- |
| Create | `speech.py` | Bounded digit and stage-prompt parsing, no fixture imports |
| Create | `client.py` | Validated settings, navigation, event ownership, watchdog and cleanup |
| Create | `caller.py` | Local one-call CLI and Uvicorn lifecycle |
| Modify | `telnyx_commands.py` | Allow DTMF; separate single-submission dial request/response |
| Modify | `webhooks.py` | Optional caller lifespan and verified client dispatch |
| Modify | `.env.example` | Explicit client-only settings and account prerequisites |
| Create | `tests/test_speech.py` | Narrow grammar and segmentation cases |
| Create | `tests/test_client.py` | Settings, flow, runtime, ordering and deadlines |
| Create | `tests/test_caller.py` | CLI startup/termination and privacy |
| Modify | `tests/test_telnyx_commands.py` | Dial/DTMF fixed-origin contracts and failures |
| Modify | `tests/test_webhooks.py` | Caller dispatch, security and app isolation |
| Modify | `README.md` | Entry-point behavior and implemented command |
| Create during implementation | `lessons/03-automated-caller.md` | Hands-on lesson and acceptance record |
| Modify | `docs/ivr-learning-plan.md` | Planning/walkthrough links and truthful status |

Keep existing fixture logic, dependency manifests and lockfile unchanged unless
a verified incompatibility requires a documented plan adjustment. The autouse
test fixture already clears `IVR_`/`TELNYX_` variables and blocks real HTTP.

The interfaces below are implementation targets, not existing APIs. Small
internal helpers may change during execution; keep consumers and tests consistent.

## Task 1 — Client settings and narrow speech grammar

**Files:** Create `speech.py`, `client.py`, `tests/test_speech.py` and the settings
portion of `tests/test_client.py`; modify `.env.example`.

**Interfaces produced:**

```python
# speech.py
def parse_digits(text: str, length: int) -> str:  # raises ValueError
    ...

# Returns ("pending", None), ("complete", logical_digits_or_None),
# or ("invalid", sanitized_reason). Only result completes with no digits.
def recognize(stage: str, text: str, synthetic_id: str) -> tuple[str, str | None]:
    ...

# client.py: frozen, repr=False; all values validated on construction
@dataclass(frozen=True, repr=False)
class ClientSettings:
    api_key: str
    connection_id: str
    from_number: str
    to_number: str
    synthetic_id: str = "000123456"
    stage_timeout_seconds: int = 30
    call_timeout_seconds: int = 180
    dtmf_duration_ms: int = 250
    dtmf_pause_units: int = 0

def load_client_settings() -> ClientSettings:
    ...
```

- [ ] Add failing parser examples, including these assertions:

```python
@pytest.mark.parametrize("text", ["zero seven four two", "0742", "0 7-4,2"])
def test_leading_zero(text):
    assert parse_digits(text, 4) == "0742"

@pytest.mark.parametrize("text", [
    "742", "07421", "0.742", "+0742", "０７４２", "oh seven four two",
    "zero seven four two or one two three four", "seventy four two",
])
def test_no_guessing(text):
    with pytest.raises(ValueError):
        parse_digits(text, 4)

def test_complete_challenge_requires_both_markers():
    assert recognize("challenge", "Your verification code is zero seven", "000123456") == ("pending", None)
    assert recognize("challenge", "Your verification code is zero seven four two. Enter the code followed by pound.", "000123456") == ("complete", "0742#")
    assert recognize("confirmation", "You entered zero zero zero one two three four five seven. Press 1 if correct.", "000123456") == ("invalid", "id_mismatch")
```

- [ ] Add parameterized settings checks for every bound in the spec, including
  absent key/app/numbers, equal numbers, booleans, whitespace, Unicode digits,
  inverted deadlines and malformed synthetic ID. Assert generic configuration
  errors omit the submitted value. Set invalid fixture-only amount/override
  variables and prove `load_client_settings()` ignores them.
- [ ] Run `uv run pytest tests/test_speech.py tests/test_client.py -q`; confirm
  failure due to missing interfaces before implementation.
- [ ] Implement `parse_digits` with tokenization and a local zero–nine map;
  validate allowed separators before stripping anything. Reject periods/signs
  inside the numeric span. Concatenate digit strings and require exact length.
  `recognize` locates complete anchored protocol phrases, then calls this parser
  only on the delimited digit span. Keep pending distinct from invalid. Match
  choice words one/two/nine only at their documented prompt positions.

```python
WORDS = dict(zip("zero one two three four five six seven eight nine".split(), "0123456789"))
# Core token conversion after separator validation:
digits = "".join(WORDS[token] if token in WORDS else token for token in tokens)
if not re.fullmatch(r"[0-9]{%d}" % length, digits):
    raise ValueError("unrecognized_digits")
```

- [ ] Cover all six prompt recognitions, case/punctuation variants, split marker
  prefixes, completed wrong digit counts, multiple/conflicting prompts, fixture
  rejection prefixes and complete unsupported menus. Unknown/incomplete text is
  pending until the controller deadline; completed invalid text is never guessed.
- [ ] Load settings through an explicit field-to-environment mapping from the
  spec; do not reuse fixture's `IVR_` prefix loader. Add blank required client
  values plus documented defaults to `.env.example`, without editing `.env`.
- [ ] Run the focused tests and Ruff, then commit:

```sh
uv run pytest tests/test_speech.py tests/test_client.py -q
uv run ruff check .
git add speech.py client.py tests/test_speech.py tests/test_client.py .env.example
git commit -m "feat: add IVR caller settings and speech grammar"
```

## Task 2 — Dial once and send bounded DTMF commands

**Files:** Modify `telnyx_commands.py`, `tests/test_telnyx_commands.py`.

**Consumes:** Existing `Command`, `make_command`, `send_command`, `CommandError`.
**Produces:** Add `send_dtmf` to `ACTIONS`; retain existing signatures and retry
semantics. Add these separate dial interfaces in the same file:

```python
@dataclass(frozen=True, repr=False)
class DialRequest:
    command_id: str
    client_state: str
    body: bytes

@dataclass(frozen=True, repr=False)
class DialIdentity:
    call_control_id: str
    call_leg_id: str

def make_dial(fields: dict) -> DialRequest:
    ...

async def send_dial(client: httpx.AsyncClient, request: DialRequest) -> DialIdentity:
    ...
```

- [ ] Add a MockTransport test capturing URL/body; return 200 with
  `{"data":{"call_control_id":"client-call","call_leg_id":"client-leg"}}`.
  Assert exact identity, fixed `/v2/calls`, no redirects, one HTTP submission,
  random IDs allocated before send and no secret repr. Dial is not an action.
- [ ] Add timeout, 429, 5xx, redirect, 4xx, malformed JSON, missing/oversized/nonstring
  identities and wrong success-shape cases. Each submits at most once, fails
  with sanitized `CommandError`, and never treats `data.result=ok` as a leg.
  Distinguish definitive rejection from uncertainty/invalid successful response.
- [ ] Run `uv run pytest tests/test_telnyx_commands.py -q`; observe new failures.
- [ ] Implement the dial path with one five-second `asyncio.timeout` surrounding
  `client.post`, plus httpx timeout and no redirects. Validate the complete
  response before returning identity. Do not refactor the proven action loop.
  The client controller constructs this dial payload from validated settings:

```python
fields = {
    "connection_id": settings.connection_id,
    "from": settings.from_number,
    "to": settings.to_number,
    "timeout_secs": 30,
    "time_limit_secs": settings.call_timeout_seconds,
    "transcription": True,
    "transcription_config": {
        "transcription_engine": "Google",
        "transcription_engine_config": {
            "transcription_engine": "Google", "language": "en", "interim_results": True,
        },
        "transcription_tracks": "outbound",
    },
}
```

- [ ] Extend existing action retry tests to `send_dtmf`; assert retries reuse
  body/command ID. Keep `make_command(..., "dial", ...)` forbidden. Prove the
  DTMF digits and tokens do not occur in errors or logs.
- [ ] Run focused tests and all existing fixture/transport tests, then commit:

```sh
uv run pytest tests/test_telnyx_commands.py tests/test_fixture.py -q
uv run ruff check .
git add telnyx_commands.py tests/test_telnyx_commands.py
git commit -m "feat: add single-submission IVR dial and DTMF transport"
```

## Task 3 — Prompt-driven navigation with stage buffers

**Files:** Modify `client.py`, `tests/test_client.py`.

**Consumes:** Task 1 parser/settings and Task 2 command values.
**Produces:** A synchronous flow with no I/O; controller serialization comes next.

```python
class ClientFlow:
    def __init__(self, settings: ClientSettings, identity: DialIdentity, *, started_at: float, now: float):
        ...
    def handle(self, data: dict, *, now: float) -> Command | None:
        ...
    def expire(self, *, now: float) -> Command | None:
        ...
    def command_failed(self, command_id: str, *, now: float) -> Command | None:
        ...
    def stop(self, reason: str, *, now: float) -> Command | None:
        ...
# Observed fields: stage, pending, checkpoint_reached, outcome, exit_code.
# exit_code is None until ended, then 0 or 1. stop/hangup are idempotent.
```

`started_at` is the monotonic dial-reservation time passed by `Caller`, not the
identity-binding time; constructing a flow must not reset the overall deadline.
Use `now` for its current stage's start time.

- [ ] Add a pure offline navigation replay. Define a local event builder with
  increasing timestamps and unique event IDs; emit `call.answered`, then split
  final transcript events. The logical tones must be exactly:

```python
expected = ["1", "0742#", "1", "000123456#", "1"]
texts = [
    "Welcome to the test IVR. Press one to continue.",
    "Your verification code is zero seven",
    "four two. Enter the code followed by pound.",
    "Press one for personal. Press two for business.",
    "Enter your nine digit personal ID followed by pound.",
    "You entered zero zero zero one two three four five six. Press one if correct.",
    "Your requested value is one thousand four hundred twenty-five dollars and thirty cents.",
]
# Collect returned send_dtmf commands, decode their JSON body and compare to expected.
# No success before result marker plus matching call.hangup; stdout is not involved here.
```

- [ ] Add checks that partial challenge/readback generates no command; repeated
  zero segments remain distinct; duplicate event IDs cannot append or send;
  stale prior-stage text cannot enter the current buffer; decreasing timestamps
  fail; equal timestamps preserve arrival order; buffers over either limit fail.
- [ ] Pin wrong readback to `id_mismatch` with no confirmation command, rejection
  to no resend, early hangup to nonzero, result marker without amount parsing to
  checkpoint state, and hangup-before-result to nonzero even if a late final follows.
- [ ] Run `uv run pytest tests/test_client.py -q`; verify the new flow tests fail.
- [ ] Implement the stage table in the spec with `recognize`, stage-local final
  buffers, deadline checks before each transition and one reserved immutable
  DTMF command per stage. Clear consumed text; retain no amount. Format audio
  pauses only at command construction:

```python
wire_digits = ("w" * settings.dtmf_pause_units).join(logical_digits)
command = make_command(identity.call_control_id, "send_dtmf", {
    "digits": wire_digits, "duration_millis": settings.dtmf_duration_ms,
})
```

- [ ] Add fake-clock tests at exactly the stage/overall deadline, timeout with
  only partials, late duplicate events, and cleanup after 15 seconds. Ensure
  duplicates and partials never refresh deadlines. Waiting after result marker
  allows the fixture to finish; timeout triggers hangup but cannot manufacture
  a matching hangup observation or exit 0.
- [ ] Run focused tests and Ruff; commit only the flow changes:

```sh
uv run pytest tests/test_client.py tests/test_speech.py -q
uv run ruff check .
git add client.py tests/test_client.py
git commit -m "feat: navigate IVR prompts from final speech segments"
```

## Task 4 — Runtime ownership, early callbacks and bounded cleanup

**Files:** Modify `client.py`, `tests/test_client.py`.

**Consumes:** `ClientFlow`, `make_dial`, injected async `send_dial`/`send_command`.
**Produces:** One controller with the following lifecycle:

```python
class Caller:
    def __init__(self, settings, dial, send, *, clock=time.monotonic):
        ...
    async def start(self) -> None:  # reserves/schedules one dial; rejects repeats
        ...
    async def accept(self, data: dict) -> None:  # validation then short lock, no network wait
        ...
    async def tick(self) -> None:
        ...
    async def close(self) -> None:  # bounded best-effort hangup/drain
        ...
# Caller.done is an asyncio.Event. Caller.exit_code and Caller.outcome are
# available after done. State includes request, identity, flow and tracked tasks.
```

- [ ] Build tests with `asyncio.run`, an injected mutable clock, and async fake
  send functions controlled by `asyncio.Event`. Hold the dial response while
  delivering outgoing initiated, answered, final speech and hangup in different
  orders. Assert identity agreement, answer-gated DTMF and no reopening after
  a buffered hangup. Foreign call/leg/connection and incoming fixture events
  must never trigger client commands, even with a shared session ID.
- [ ] Test a dial timeout before identity: exactly one request, no DTMF, then a
  correlated initiated event permits cleanup only. If identity/progress was
  established before the late HTTP error, retain it; never redial. A conflicting
  response fails closed without controlling the foreign identity.
- [ ] Test an accepted next prompt while the previous DTMF HTTP request is held;
  release it with a failure and assert no rewind, duplicate tones or termination.
  Test a failure for the still-current action does stop and hang up.
- [ ] Test 32-event/64-KiB pending limits, 4096 event IDs, malformed nested speech,
  timestamp validation, second start rejection, close during dial, unknown leg
  cleanup and controller isolation. Sanitized logs must omit all sentinels.
- [ ] Run `uv run pytest tests/test_client.py -q`; confirm failures before code.
- [ ] Implement admission exactly as the spec: reserve run token/dial body and
  wall-clock cutoff before I/O, bind from response or correlated initiated,
  bounded pre-identity buffering, then call/leg/app checks. Do not use the
  fixture's admission rule or require a current stage token for transcripts.
  Check deadlines before accepting events, including while no flow exists.
- [ ] Schedule network sends after reservations under one short-held lock. Use
  task ownership checks before sends/retries, ignore obsolete completions, and
  contain raw exceptions. Reuse fixture's tracked-task pattern, not its state
  object. Add the deliberate limit comment:

```python
# ponytail: one call per process and a short-held lock; durable per-call workers if scale is needed.
```

- [ ] Set `done` only after observed termination or bounded cleanup; close must
  keep handling identifying callbacks during uncertain dial cleanup until its
  budget expires. Cancel/drain remaining tasks, clear transcript and ID buffers,
  and preserve only the sanitized outcome. An unknown remote leg yields an
  explicit unconfirmed termination diagnostic.
- [ ] Run the complete offline suite and Ruff, then commit:

```sh
uv run pytest -q
uv run ruff check .
git add client.py tests/test_client.py
git commit -m "feat: bound automated IVR call ownership and cleanup"
```

## Task 5 — CLI-owned server and authenticated client dispatch

**Files:** Create `caller.py`, `tests/test_caller.py`; modify `webhooks.py` and
`tests/test_webhooks.py`.

**Consumes:** `Caller`, `load_client_settings`, `send_dial`, `send_command`.
**Produces:** `async run_call(app_name: str, env_file: str) -> int` and `main()`
in `caller.py`; optional `app.state.caller` lifecycle in `webhooks.py`.

- [ ] Add tests with fake Uvicorn server/lifespan and mock dial proving server
  readiness precedes dial, bind/startup failures dial zero times, one invocation
  dials once, SIGINT/cancellation runs cleanup, and stdout stays empty. No real
  sockets, HTTP, Funnel, or paid call is needed for these tests.
- [ ] Extend signed-webhook tests: CLI-enabled client route dispatches only to
  `app.state.caller`, fixture route only to `app.state.ivr`; 401/400/413 paths
  do not mutate either. A blocked network send must not delay the 200 callback.
  A plain Uvicorn client remains receipt-only and needs only its public key.
  Repeated app startup must not retain the prior controller or CLI flag.
- [ ] Run `uv run pytest tests/test_caller.py tests/test_webhooks.py -q` and
  inspect the new failures.
- [ ] Extend lifespan without making the fixture branch an early return that
  skips an enabled caller. Load only enabled roles' settings; combined mode
  validates different application IDs. Share an HTTP client if credentials
  match, but keep controllers/settings independent. Start watchdogs and close
  both controllers before the HTTP client is closed. Keep security code intact.
- [ ] Implement the CLI using existing Uvicorn env-file handling. Parser choices
  are `--env-file` (default `.env`) and `--app public|client` (default public).
  There is no destination, host, port, worker or reload argument. The core
  orchestration is:

```python
app = webhooks.public_app if app_name == "public" else webhooks.client_app
app.state.caller_enabled = True
config = uvicorn.Config(
    app, host="127.0.0.1", port=8010 if app_name == "public" else 8011,
    env_file=env_file, access_log=False, workers=1,
)
server = uvicorn.Server(config)
# Start server.serve() as a tracked task. For at most 10 seconds, await readiness
# while also checking task completion/errors. This polling is server startup,
# never prompt navigation. Only then await app.state.caller.start().
# Wait for caller.done OR server task termination; on either path run bounded
# controller cleanup, set server.should_exit, await server, and clear CLI state.
```

- [ ] Handle early Uvicorn `SystemExit`/startup task failure without leaving
  pending tasks or dialing. Keep diagnostics on stderr and suppress raw HTTP
  exception URLs. Print one concise checkpoint/error line; use exit 0 only for
  the spec's result-announcement-plus-hangup outcome. `if __name__ == "__main__"`
  invokes `main`; imports and ordinary Uvicorn startup do not start a call.
- [ ] Run all tests, Ruff check and formatting, then commit:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git add caller.py webhooks.py tests/test_caller.py tests/test_webhooks.py
git commit -m "feat: run automated IVR caller with its webhook server"
```

## Task 6 — Walkthrough, final verification and learner checkpoint

**Files:** Create `lessons/03-automated-caller.md`; modify `README.md`,
`docs/ivr-learning-plan.md`, and these spec/plan status records after verification.

- [ ] Write the lesson with prerequisites, role/leg diagram or table,
  command-versus-event explanation, partial/final examples, small build steps,
  and exact commands from the same worktree. Explain why the CLI replaces the
  previous process and why independent app processes cannot share state.
- [ ] Document outbound app/profile/number checks as learner operations; do not
  automate purchase or configuration. Explain Google engine/remote-track live
  validation, ignored settings, DTMF tuning, stage/overall/cleanup limits,
  one-call invocation, and manual provider termination after a local failure.
- [ ] Include these run/verification commands, with no real number or secret:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
# Learner-operated only, after checking settings and existing routing:
uv run python caller.py --env-file .env --app public
echo $?
```

- [ ] Show expected stderr checkpoint/error diagnostic and empty stdout. State
  explicitly that the amount is not extracted. Include normal, different-code,
  `0742` override and mismatched-ID exercises, clearing/restoring settings after
  each. Explain where the learner inspects actual received DTMF in provider
  diagnostics and redacts synthetic IDs; do not enable raw default logs.
- [ ] Add an acceptance table with separate offline result, every live attempt,
  delivery observations and learner sign-off. Live rows start “Not run” and
  sign-off “Pending”. Preserve Lesson 1/2 history, including the delivery issue.
  Do not check Lesson 3 live boxes merely because offline replay passes.
- [ ] Perform author self-review against all spec sections: settings, no fixture
  imports/data leaks, six prompt stages, identity races, bounded tasks/buffers,
  provider payloads, local-only initiation and Lesson 4/5 boundaries. Per-task
  and final reviewers check each task; Task 6 keeps an author self-review of
  the full spec. Fix concrete findings and rerun affected checks.
- [ ] Run final verification from the IVR directory and worktree root:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
git diff --check
git status --short --branch
```

- [ ] Record actual results and commit the lesson/docs using explicit paths.
  Link the walkthrough for learner-operated calls and stop at the checkpoint.
  Do not merge, claim live success, or begin amount parsing without instruction.

## Spec coverage and planning review

| Spec requirement | Implementation task |
| --- | --- |
| Settings and fixture independence | 1, 5 |
| Numeric grammar, leading zero, ambiguity and prompt completeness | 1, 3 |
| Fixed-origin dial/transcription configuration/DTMF | 2 |
| Stage progression, final buffers, exact ID readback and deadlines | 3 |
| Identity admission, early events, idempotency and cleanup | 4 |
| CLI/server lifecycle, signatures, role isolation and privacy | 4, 5 |
| Teaching guide, live track/digit evidence and separate acceptance | 6 |

Author review checked coverage and interface consistency. Existing fixture
transport can be reused for actions, but not for the different dial response.
Transcription is admitted by leg identity, not the fixture's per-operation token.
The missing post-hangup finalization window is intentional Lesson 4 scope, not
an undocumented success fallback. Live track selection and initial prompt capture
remain explicit acceptance checks. No independent review was performed during
planning; implementation used per-task and final independent reviews.

Implementation used the learner-authorized subagent flow (bounded scout, workers
per task in dependency order, reviewer gate per task, final whole-branch review).
Stop at the Lesson 3 live acceptance checkpoint; do not begin Lesson 4 without
a new request.
