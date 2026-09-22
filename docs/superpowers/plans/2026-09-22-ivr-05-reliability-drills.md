# IVR Lesson 5 Reliability Drills Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for direct execution, task by task. The user prohibited subagents, including reviewer agents. Steps use checkboxes. This plan is not authorization to deploy or place paid calls.

**Goal:** Make the existing single-call IVR demonstrably repeatable under duplicate delivery, late events, ambiguous command responses, and controlled fixture failures.

**Architecture:** Extend `fixture.Settings` and `fixture.Flow` with a fixed fixture-only scenario selection. Reuse the existing controller locks, command objects, mock transports, injected clocks, and terminal result contract. Add focused replay checks without a production simulation framework.

**Tech Stack:** Python 3.14, existing uv, FastAPI, httpx, pytest, Ruff, stdlib asyncio/json.

**Spec:** [Lesson 5 design](../specs/2026-09-22-ivr-05-reliability-drills-design.md).

**Status:** Implemented offline 2026-09-22: 452 tests, Ruff lint/format, and Markdown lint passed. Two existing upstream warnings remain. [Walkthrough](../../../spikes/ivr/lessons/05-reliability-drills.md). No subagents, deployment, or paid calls. Learner sign-off received 2026-09-22, with push/merge authorized; detailed live-call evidence not supplied. Baseline was 422 tests.

## Global constraints

- Python 3.14; reuse the existing uv environment, lockfile, pytest, and httpx. No new dependencies.
- One worker and one automated call per process; no queue, database, scheduler, batch dialer, distributed lock, or automatic redial.
- Preserve signature/freshness verification, ownership checks, bounded buffers, privacy, stdout JSON, and existing cloud commands.
- Client runtime must not import fixture code or read scenario settings or expected outcomes.
- Tests are offline. Deployment, paid calls, and learner sign-off are separate activities.
- Work only in `.worktrees/ivr-01-connectivity`, branch `codex/ivr-05-reliability-drills`, based on merged main `80dc76e`. Retain previous branches and ignored settings. No merge until learner sign-off.

## Review focus

- Silent fixture has no pending command: hangup, deadlines, shutdown, and stray events must remain safe (Task 1).
- Duplicate completion with a fresh event ID is not caught by ID deduplication: stage ownership must prevent a second action (Task 3).
- Lost HTTP response after an accepted action: retries preserve bytes/identity, and exhaustion never emits new DTMF (Task 2).
- Completion races with an obsolete command failure or final transcript at the exact deadline: preserve the first terminal decision and original deadline (Task 3).
- Repeated or concurrent cloud start and restart: one dial per process, explicit restart required, no claim of crash recovery (Tasks 3–4).

## File map and preparation

All task paths are relative to `spikes/ivr/` unless prefixed with repository `docs/`.

| Files | Purpose |
| --- | --- |
| `fixture.py`, `tests/test_fixture.py`, `.env.example` | Scenario selection and bounded fixture behavior |
| `tests/test_client.py` | Fixture-env isolation and controller replay checks; reuse its existing harness |
| `tests/test_telnyx_commands.py`, conditionally `telnyx_commands.py` | Identity-preserving retries and uncertainty |
| `tests/test_cloud_runner.py`, `tests/test_caller.py` | Admission and terminal-output regressions |
| Conditionally `client.py`, `cloud_runner.py` | Only fixes demonstrated by new regression checks |
| `lessons/05-reliability-drills.md`, `README.md`, `deploy/README.md`, `docs/client-call-flow.md` | Teaching guide, operations, source-guide updates if behavior changes |
| Repository `docs/ivr-learning-plan.md` and both planning documents | Progress and evidence links |

- [x] Inspect `git status --short --branch`; preserve unrelated changes. Read the spec and `fixture.Flow.handle/expire`, `Fixture.accept/_sync/close`, `Caller.accept/_run_command/_finalize/close`, `ClientFlow.handle`, `Control.handle`, and transport functions before edits.
- [x] Run baseline checks from `spikes/ivr/`:

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## Task 1 — Add fixture-only scenarios

**Files:** `fixture.py`, `tests/test_fixture.py`, `tests/test_client.py`, `.env.example`.

**Interfaces:** Add `Settings.scenario: str = "normal"`, loaded as `IVR_SCENARIO`. Preserve `Flow(settings, call_control_id, call_leg_id, *, now, challenge=None)` and all existing public controller signatures. No client setting is added.

- [x] Add settings tests using existing `settings(**changes)` and `load_settings`. Accept exactly `normal`, `leading_zero`, `rejected_id`, `silent_stage`, `unsupported_result`, `early_hangup`. Reject blank, unknown, uppercase, and non-string values with `RuntimeError("Invalid fixture configuration")`. Test conflicting leading-zero override and fixture-env isolation.

```python
@pytest.mark.parametrize("scenario", ["", "NORMAL", "unknown", None])
def test_invalid_scenario(scenario):
    with pytest.raises(RuntimeError, match="^Invalid fixture configuration$"):
        settings(scenario=scenario)


def test_leading_zero_scenario():
    flow = Flow(settings(scenario="leading_zero"), "call", "leg", now=0)
    assert flow.challenge == "0742"
```

- [x] Run `tests/test_fixture.py` and observe the new setting tests fail before implementation.
- [x] Add the dataclass field and exact allowlist validation; use existing `load_settings` mapping. Validate leading-zero override compatibility. Select `0742` only for the leading-zero scenario when no explicit test challenge is supplied; otherwise preserve existing challenge generation.
- [x] Add transition tests with existing `complete` and `flow_at` helpers. Verify default normal behavior remains unchanged. For rejected-ID, navigate with correct digits and assert failure speech at identifier completion, with no confirmation/result. For unsupported-result, assert the exact payload below.

```python
unsupported_prompt = "Your requested value is unavailable."
```

- [x] Add early-hangup and silent-stage tests after valid welcome input. The former returns one hangup and no challenge command; the latter returns no command, ignores stray gather/speak completions, accepts matching hangup, and attempts hangup at the fixture overall deadline. Exercise `Fixture.tick` and `Fixture.close`, not just `Flow`, for pending-none safety.
- [x] Implement small branches at the existing `next_stage` transition. Reuse `fail("input_rejected", ..., prompt="We could not verify your entry. Goodbye.")`, `hangup`, and `_reserve`. For silent stage set `stage="silent"`, `pending=None`, `deadline=call_deadline`. Move/check expiry before dereferencing pending in `handle`, then return on `pending is None`; leave matching `call.hangup` first. Make `expire` preserve silence until overall deadline. Do not call `_gather` for silence.
- [x] Extend the client environment-isolation test with `IVR_SCENARIO=unsupported_result`; assert client settings are unchanged. Add `.env.example` allowlist comments and default `IVR_SCENARIO=normal`.
- [x] Run focused tests and Ruff, then commit explicit changed files as `feat: add controlled IVR reliability scenarios`.

## Task 2 — Prove retry identity and ambiguous-response handling

**Files:** `tests/test_telnyx_commands.py`, `tests/test_client.py`; change `telnyx_commands.py` or `client.py` only for a demonstrated contract gap.

**Interfaces:** Preserve `send_command(client, command) -> None`, `send_dial(client, request) -> DialIdentity`, and `CommandError.reason`. No new retry service or provider lookup API.

- [x] Read the official sources linked in the spec and follow the Voice API command-retry documentation. Record the verification date and action-specific semantics in the walkthrough. Check answer, gather, speak, hangup, and DTMF; do not transfer action deduplication guarantees to outbound dial or assume permanent ID retention.
- [x] Extend `test_retry_keeps_identity_and_fixed_origin` to include `send_dtmf` with valid digits. Add a mock transport case where the first request is recorded as accepted by the fake remote then raises `httpx.ReadTimeout`, and the second succeeds. Use the existing no-sleep fixture.

```python
seen = []


def transport(request):
    seen.append(request.content)
    if len(seen) == 1:
        raise httpx.ReadTimeout("test response lost", request=request)
    return httpx.Response(200, json={"data": {"result": "ok"}})
```

- [x] Assert two requests at most and `seen[0] == seen[1] == command.body`. Retain tests for rejected/malformed responses, retry-after bounds, timeout exhaustion, and dial-once behavior. Add a fixture gather-retry assertion that an intentional new attempt gets a different ID.
- [x] Use the existing caller harness to force a current DTMF send to raise `CommandError("uncertain")`: assert provider error and bounded cleanup, with no replacement DTMF. Retain the test where the next prompt wins the race against an obsolete failure. Retain uncertain-dial/late-identity cleanup tests and assert one dial.
- [x] Run the focused transport/client tests. If all new checks pass initially, record existing behavior verified and leave runtime code unchanged. If a check fails, fix the shared owner/transport path minimally and rerun it; do not change expected results to accommodate unsafe behavior.
- [x] Commit explicit changed paths as `test: verify IVR command retry and uncertainty guarantees` (use `fix:` if runtime behavior changed).

## Task 3 — Replay duplicate, late, and concurrent events

**Files:** `tests/test_client.py`, `tests/test_fixture.py`, `tests/test_cloud_runner.py`, `tests/test_caller.py`; conditional fixes in their existing runtime owners.

**Interfaces:** Reuse `Caller.accept(data)`, `Caller.tick()`, `Fixture.accept(data)`, `Fixture.tick()`, and injected clocks. Keep helpers in their existing test module; do not import one test module from another or add a production replay endpoint.

- [x] Build an ordered replay check using the client module's existing harness and event constructors. A tiny local helper is sufficient if used repeatedly:

```python
async def replay(accept, events):
    for event in events:
        await accept(event)
```

- [x] Exercise each meaningful schedule in the table. Use fake clocks and `asyncio.Event` barriers for response races, never real timing sleeps. Record the emitted logical command bodies and terminal result to make failures legible.

| Schedule | Required assertion |
| --- | --- |
| Duplicate answered, prompt, and fixture completion with the same event ID | One logical action per transition |
| Old gather completion with a fresh ID and old client-state token | No repeated gather or stage rewind |
| Concurrent copies of the same prompt via `asyncio.gather` | Exactly one new DTMF reservation |
| New prompt before prior command response, then old failure | No corruption of newer stage/result |
| Hangup then final result inside grace, then duplicate hangup | Correct amount; deadline not extended |
| Final result at or after grace/overall boundary | No late success replacing the terminal error |
| Events after done; completed-call initiation replay on fixture | No new commands, reopening, or result mutation |
| Event capacity reached | Bounded fail-closed cleanup, no ID eviction replay |
| Cleanup command fails or hangup acknowledgement is absent | Original decision retained, tasks drained within bounds |

- [x] Reuse existing tests covering these schedules; add only missing combinations and explicit command-count assertions. Run the focused schedule check before each necessary runtime fix. Preserve guards and terminal semantics already proven in Lesson 4.
- [x] Extend scenario tests to assert expected client JSON from representative final transcripts/events: rejected-ID → `fixture_rejection/confirmation`; silence → `stage_timeout/challenge`; unsupported result → `result_unrecognized/result`; early hangup → `early_hangup/challenge`. Include normal amounts `1425.30`, `17.42`, and leading-zero challenge. Test scaffolding may know expectations; client code may not.
- [x] Retain the existing cloud concurrent-start check, repeated status/result read checks, and post-completion `restart_required`. Extend only if a path is missing. Verify local stdout is one JSON line and exit codes agree with cloud terminal results.
- [x] Run fixture/client/transport/cloud/CLI/webhook tests, then commit as `test: replay IVR duplicate and late-event failure drills`, or a precise `fix:` message if needed.

## Task 4 — Teach the drill and record acceptance separately

**Files:** Create `lessons/05-reliability-drills.md`; update `README.md`, `deploy/README.md`, repository `docs/ivr-learning-plan.md`, and these planning status records. Update `docs/client-call-flow.md` only where source behavior/locations changed.

**Interfaces:** Document existing local CLI and SSH control commands. No new call-start or scenario API, no batch runner.

- [x] Write prerequisites, event-vs-command identity explanation, commands for the focused offline replay tests, and fixture-only scenario selection. Use the existing Lesson 4 local/cloud invocation patterns; explain `.env` loading and restart requirements rather than suggesting environment changes affect a running process.
- [x] Provide a table for the ten planned live calls: normal amounts `1425.30`, `17.42`, `1425.30`, `17.42`, `1425.30`; then leading zero, rejected ID, silent stage, unsupported result, early hangup. Initialize every live result to `Not run` and learner acceptance to `Pending`.
- [x] Give exact expected JSON from the spec; explain that failure before reaching the selected drill is an unsuccessful attempt, not evidence that the intended scenario passed. Require all attempts and diagnosis/reruns in the record. Do not broaden speech grammar merely to reach a green row.
- [x] Document graceful stop, bounded cleanup, result retrieval before restart, and manual verification/termination of remaining provider call legs after a crash. State that restarting loses deduplication and results. Reference existing deployment authentication instructions; keep credentials/control tokens out of committed examples and shell history.
- [x] Document restoration to normal scenario/amount/empty challenge override and idle service verification. Keep deployment/calls pending until explicitly authorized; when later authorized, deploy committed files using existing release/rollback conventions before cloud drills.
- [x] Run final offline checks and Markdown lint. From repository root, reuse the already-installed main-checkout linter if this worktree lacks Node dependencies; do not install the whole frontend just to lint these documents.

```sh
cd spikes/ivr
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
cd ../..
/Users/tylerv/projects/learning/expo-fastapi-todo/node_modules/.bin/markdownlint-cli2 '**/*.md' '#node_modules' '#.superpowers' '#apps/**/node_modules' '#apps/**/.venv' '#apps/**/.expo'
git diff --check
git status --short --branch
```

- [x] Verify relative documentation links and source references. Record actual test totals and warnings, direct author review, and any remaining findings. Commit explicit paths as `docs: teach IVR reliability drills and recovery limits`.
- [x] Stop at the learner checkpoint. Keep the branch/worktree; do not merge, start Lesson 6, or build concurrency infrastructure. Live matrix execution and learner sign-off remain separate from offline implementation completion.

## Coverage and self-review

Scenario configuration, all six flows, and client isolation map to Task 1. Provider retry identity, deliberate new attempts, and uncertain dial/action outcomes map to Task 2. Serialization, lifetime deduplication, stale events, admission, deadline boundaries, cleanup, and unchanged output map to Task 3. Repeatable live exercises, recovery/restoration instructions, privacy, evidence separation, and learner acceptance map to Task 4.

The plan deliberately reuses existing passing tests and implementation. Every new failure scenario has a specified transition and expected outcome; silence explicitly accounts for `pending=None`. No new dependencies, infrastructure, external actions, or independent reviewer are implied.

## Implementation review record — 2026-09-22

- Task 1: 19 new scenario cases failed before implementation; fixture/client checks passed after the minimal fixture changes. Silent stage reuses existing overall expiry; no redundant expiry branch was needed.
- Task 2: Added DTMF lost-response/identity assertions and strengthened exhausted-uncertainty cleanup checks. Existing transport/client behavior already passed; runtime changes were unnecessary. Reviewed official action-specific command-ID semantics and retry guidance.
- Task 3: Test-only bridge replays actual fixture prompts through the client for every scenario, changed amounts, concurrent duplicate delivery, duplicate hangup deadlines, and post-terminal replay. Existing overflow, exact-boundary, admission, cleanup, signed-webhook, and stdout checks remain green.
- Ruling: Preserve the existing public code `fixture_rejection`; the draft spec's `fixture_rejected` was a naming error. Corrected both documents rather than changing the Lesson 4 API. Consumers using the draft spelling must use the established name.
- Ruling: Direct author review replaces reviewer dispatch because the user prohibited subagents. No independent-review claim.
- Task 4: Walkthrough includes the ten-call matrix, exact commands/results, restart limitations, and restoration steps. At implementation completion, live rows were `Not run` and acceptance was `Pending`. Learner sign-off was subsequently received on 2026-09-22; detailed live-call evidence was not supplied.
- Final author review checked all changed runtime branches, pending-none cleanup, command identity, source links, fixture/client separation, and scope. No deferred code findings. No new dependencies, client runtime changes, deployment, or paid calls.
