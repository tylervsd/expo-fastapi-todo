# IVR Lesson 4 Value-or-Error Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Execution method has not been selected; planning used no subagents. This document does not authorize deployment or paid calls.

**Goal:** Return exactly one speech-derived USD amount or explicit error from the existing IVR caller.

**Architecture:** Extend the narrow speech grammar and existing call state machine, retain one terminal result through cleanup, and serialize that same snapshot through the local CLI and cloud control socket. Keep all existing webhook security and ownership checks.

**Tech Stack:** Python 3.14, existing uv/FastAPI/Uvicorn/httpx/pytest/Ruff; stdlib Decimal, re, json, hashlib, asyncio.

**Spec:** [Lesson 4 design](../specs/2026-09-22-ivr-04-value-or-error-design.md).

**Status:** Planning complete; implementation and live acceptance pending. Baseline: 369 tests passed, Ruff check and format passed, two existing upstream warnings.

## Global Constraints

- Python 3.14; reuse the independent uv environment and lockfile in `spikes/ivr/`.
- No new dependencies; use stdlib Decimal, re, json, hashlib, and existing pytest tooling.
- One call per run, one worker, in-memory state; preserve current local and cloud entry points.
- Client runtime code must not import fixture code or read fixture amounts, scenario settings, or expected results.
- Keep signed webhooks, timestamp checks, role/leg ownership, bounded buffers, command IDs, and local-only initiation intact.
- Preserve Telnyx/inbound transcription and configurable DTMF timing; no provider API or infrastructure changes.
- Default and debug logs exclude credentials, phone numbers, synthetic IDs, challenge values, raw transcripts, and call-control tokens.
- Automated checks are offline; paid calls, deployment, and learner acceptance are separate, explicitly recorded activities.

## Review Focus

- A complete-looking amount can be followed by conflicting final text; delay publication and reject the conflict (Tasks 1–2).
- Zero is a valid amount, while dollars without cents and marker-only text are not (Tasks 1–2).
- Hangup at the overall deadline must not buy another five seconds; exact-boundary events cannot alter the snapshot (Task 2).
- Cleanup exceptions, startup failures, and cancellation must still produce one JSON record with the original failure stage (Tasks 2–3).
- Cloud polling and debug output must neither redial nor leak transcripts or call-control tokens (Tasks 3–4).

## Workspace, baseline, and file map

Work only in `/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity`, branch `codex/ivr-04-value-or-error`, based on merged main `dc9ebc3`. The branch already exists. Preserve prior branches and ignored settings/environment. No new worktree, reset, stash, push, or merge.

Before editing, inspect status and read both planning documents. All task paths below are relative to `spikes/ivr/` unless explicitly rooted at the repository.

```sh
git status --short --branch
git log -3 --oneline
cd spikes/ivr
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

| File | Responsibility |
| --- | --- |
| `speech.py`, `tests/test_speech.py` | Strict amount grammar and result recognition |
| `client.py`, `tests/test_client.py` | Result assembly, finalization, public snapshot, trace settings |
| `caller.py`, `tests/test_caller.py` | Exactly one local output and exit status |
| `cloud_runner.py`, `tests/test_cloud_runner.py` | Read-only result retrieval and status compatibility |
| `.env.example`, `README.md`, `deploy/README.md` | Debug setting and local/cloud command contract |
| `lessons/04-value-or-error.md` | Teaching guide and separate acceptance record |
| Repository `docs/ivr-learning-plan.md` and these planning documents | Links and truthful progress records |

Do not split the existing controller or add a result framework. Read `_evaluate`, `_on_transcript`, `_expired`, `handle`, `expire`, `command_failed`, `stop`, `_replay`, `_accept_bound`, `_finish`, `_finalize`, `_clear_sensitive`, and `close` before modifying terminal behavior. They all participate in the same lifecycle.

## Task 1 — Parse only documented, complete amounts

**Files:** Modify `speech.py`, `tests/test_speech.py`.

**Interfaces:** Produce `parse_amount(text: str) -> str`, raising `ValueError("result_unrecognized")`; preserve `recognize(stage: str, text: str, synthetic_id: str) -> tuple[str, str | None]`. Result completion now carries an amount string.

- [ ] Add a focused parameterized check with exact values, using the existing pytest module:

```python
@pytest.mark.parametrize(("body", "expected"), [
    ("one thousand four hundred twenty-five dollars and thirty cents", "1425.30"),
    ("zero dollars and zero cents", "0.00"),
    ("one dollar and one cent", "1.01"),
    ("two thousand dollars and five cents", "2000.05"),
    ("9999 dollars and 99 cents", "9999.99"),
    ("$1,425.30", "1425.30"),
    ("1425.30 dollars", "1425.30"),
    ("17.42", "17.42"),
])
def test_amount(body, expected):
    assert parse_amount(f"Your requested value is {body}.") == expected

@pytest.mark.parametrize("body", [
    "", "available", "one dollar", "1.2", "1.234", "-1.00",
    "1e3", "NaN", "infinity", "10000.00", "1,42.30",
    "one dollars and one hundred cents", "one hundred hundred dollars and zero cents",
    "zero thousand dollars and zero cents", "one thousand zero dollars and zero cents",
    "one hundred and five dollars and zero cents", "1.00 euros",
    "1.00 or 2.00", "1.00 then 2", "one point five dollars",
])
def test_unsupported_amount(body):
    with pytest.raises(ValueError, match="result_unrecognized"):
        parse_amount(f"Your requested value is {body}.")
```

- [ ] Run `.venv/bin/python -m pytest tests/test_speech.py -q`; confirm the new missing-parser failures.
- [ ] Implement anchored full-body parsing with separate decimal and dollars/cents matches. Normalize only case, whitespace, inter-word hyphens, and terminal punctuation. Keep decimal points and signs intact for validation. Use explicit zero–nineteen/tens tables and bounded hundreds/thousands decomposition; reject extra scale tokens, zero tails, and residual words. Implement the arithmetic as:

```python
value = Decimal(dollars) + Decimal(cents) / Decimal(100)
return format(value, ".2f")
```

  For decimal input, validate the full numeric regex and comma grouping before removing commas, enforce 0–9999.99, and format Decimal directly. Never call float or import `fixture`.
- [ ] Update result recognition: split complete anchored announcements, parse each full body, require one distinct normalized value; return pending for an unfinished suffix and invalid for a completed unsupported body. Retain the full bounded stage buffer so a later segment can finish it. One complete announcement followed by another incomplete announcement is pending, not success.
- [ ] Add recognizer assertions for prefix-only, split cents, same-value repeated announcements, different-value announcements, trailing unexplained numeric text, case/hyphen normalization, and fixture rejection priority. Representative checks:

```python
assert recognize("result", "Your requested value is", "000123456") == ("pending", None)
assert recognize("result", "Your requested value is zero dollars and zero cents.", "000123456") == ("complete", "0.00")
assert recognize("result", "Your requested value is 1.00. Your requested value is 2.00.", "000123456") == ("invalid", "result_unrecognized")
```

- [ ] In tests only, compare fixture-generated prompts at dollar boundaries `0, 1, 19, 20, 21, 99, 100, 101, 999, 1000, 1001, 9999`, crossed with cents `0, 1, 9, 10, 19, 20, 21, 99`. This checks the shared documented grammar without coupling client runtime to the fixture.
- [ ] Run focused tests and Ruff; commit `feat: parse documented IVR result amounts` using explicit paths.

## Task 2 — Finalize one immutable value or error

**Files:** Modify `client.py`, `tests/test_client.py`.

**Interfaces:** Consume `recognize` from Task 1. Add `ClientFlow.result` and `Caller.result`, each `dict[str, str] | None`; add `failure_stage: str | None` to the flow. Provide `error_result(reason: str, stage: str) -> dict[str, str]` in `client.py` for shared mapping. Keep `Caller.done`, `outcome`, and `exit_code` for compatibility.

- [ ] Update `HAPPY_TEXTS[-1]` to the full fixture phrase ending “dollars and thirty cents.” Replace assertions that accept “available” or dollars-only as success. Keep the original prompt-marker tests as negative cases.
- [ ] Add a fake-clock check with the existing `_flow`, `_Builder`, `_drive_happy`, and `_say` helpers:

```python
flow, events = _flow(), _Builder()
_, now, offset = _drive_happy(flow, events)
assert flow.result is None
flow.handle(events.event("call.hangup", offset=offset), now=now)
flow.expire(now=now + 4.999)
assert flow.result is None
flow.expire(now=now + 5)
assert flow.result == {"status": "success", "value": "1425.30", "currency": "USD"}
saved = flow.result.copy()
flow.handle(events.event("call.hangup", offset=offset + 1), now=now + 6)
assert flow.result == saved
```

- [ ] Add sibling replay checks: complete amount after hangup; zero; conflicting second amount within the window; cents split across final events; partial text cannot finish an amount; marker-only ends `result_unrecognized`; hangup before result ends `early_hangup`; foreign leg cannot finish; duplicate hangup cannot extend. Reuse `_CallerHarness` for identity tests, not only direct flow tests.
- [ ] Add exact overall-boundary checks with started-at 1000 and timeout 180: result hangup at 1178 has finalization deadline 1180, not 1183; final text at 1179.999 can contribute, at 1180 cannot. A candidate at deadline survives; missing text becomes `result_unrecognized` if hangup was already observed. Without hangup, missing text yields `overall_timeout`.
- [ ] Run `.venv/bin/python -m pytest tests/test_client.py -q`; inspect the new failures.
- [ ] Retain result buffers/candidate until finalization. Remove the result-checkpoint shortcut in `_on_transcript`; prefix recognition alone must never set success. At the event gate and watchdog, calculate the boundary from monotonic times:

```python
finalize_at = min(
    self._result_hangup_at + 5,
    self.started_at + self.settings.call_timeout_seconds,
)
```

  Only calculate this once hangup exists. At/after the boundary, finalize before consuming another event. Before hangup use existing stage and overall deadlines. Once hangup exists, ignore stage deadline and cap by overall deadline. Re-evaluate the retained complete buffer at finalization; pending/invalid becomes `result_unrecognized`. Without hangup at a recognition deadline, preserve a complete candidate and initiate bounded cleanup, or preserve the timeout failure when incomplete.
- [ ] Capture `failure_stage` before `_hangup` changes stage. Implement the spec's public error mapping in `error_result`, with a fixed allowlist for stages and an `internal_error` fallback. Map each existing outcome explicitly; keep internal reasons separate. Validate representative mappings:

```python
assert error_result("dial_rejected", "dialing") == {
    "status": "error", "code": "provider_failure", "stage": "dialing",
}
assert error_result("transcript_order", "result") == {
    "status": "error", "code": "protocol_error", "stage": "result",
}
```

- [ ] Set the terminal snapshot once, before cleanup; copy it from flow to controller in `_finalize`. `_finish` creates mapped errors for pre-bind failures. `_clear_sensitive` retains only sanitized result/diagnostic fields. Derive exit 0 only from a success snapshot, never `checkpoint_reached`. Keep `outcome="completed"` for success compatibility.
- [ ] Audit `_fail`, `command_failed`, `stop`, `expire`, `_finish`, `_finalize`, and `close`: teardown failure cannot overwrite a decided result or original error. Failure to hang up still logs a cleanup reason. Bounded cleanup settles `done`; ended calls cannot reopen. Keep active command failures before a decision as `provider_failure`.
- [ ] Extend harness checks to cover successful speech plus failed hangup, failure plus cleanup timeout, duplicate `_finalize`/`close`, dial rejection before identity, out-of-order finals, and final result survival after identity/transcript clearing. Assert no extra DTMF and unchanged snapshot.
- [ ] Run all IVR tests and Ruff; commit `feat: finalize one IVR value or error within call deadlines`.

## Task 3 — Deliver the contract through local and cloud commands

**Files:** Modify `caller.py`, `cloud_runner.py`, `tests/test_caller.py`, `tests/test_cloud_runner.py`.

**Interfaces:** Consume `Caller.result`, `Caller.exit_code`, `Caller.done`, and `error_result`. Preserve `run_call(app_name: str, env_file: str) -> int`. Extend cloud socket/CLI command choices with `result`.

- [ ] Extend `FakeCaller` to expose a terminal result. Replace stdout-empty assertions with exactly-one-line JSON assertions:

```python
out, err = capsys.readouterr()
assert len(out.splitlines()) == 1
assert json.loads(out) == {"status": "success", "value": "1425.30", "currency": "USD"}
assert err.strip()
```

  For the existing stage-timeout case use `{"status":"error","code":"stage_timeout","stage":"challenge"}` and assert exit 1. Constructor/lifespan failure expects `startup_failed`/`startup`, one line, and zero dials. Add start exception, unexpected server stop, cleanup exception, and cancellation cases. Interruption emits `interrupted`, cleans up, then propagates cancellation; the CLI maps user interrupt to exit 130 without a traceback or second record.
- [ ] Run `.venv/bin/python -m pytest tests/test_caller.py -q` to observe failures.
- [ ] Give `run_call` one terminal payload variable, initialized to `error_result("server_startup_failed", "startup")`. Update it on each existing failure path or from the completed caller. Keep one `print(json.dumps(payload))` at the outer finalization boundary after bounded cleanup. Nest cleanup in `try/finally` so shutdown exceptions cannot suppress output or override the payload. Return the corresponding code; avoid stale `exit_code` in early-return diagnostics. Keep cancellation cleanup shielded and bounded.
- [ ] Test the cloud protocol with existing `Writer`/`Control` fake helpers: `result` before start and during a call returns `result_not_ready` without starting anything; after done returns the exact snapshot repeatedly; status includes `result`; start after completion remains restart-required. Existing invalid/oversized input, permissions, and no-auto-dial tests remain.
- [ ] Extend only the existing command allowlist and status branch. The result branch uses:

```python
response = (
    dict(self.caller.result)
    if self.caller.done.is_set() and self.caller.result is not None
    else {"status": "error", "code": "result_not_ready", "stage": "startup"}
)
```

  Add `result` to argparse choices. `request("result")` exits 0 only for a success payload and 1 otherwise; status retains its query exit-0 semantics. Keep the existing five-second socket request bound; result retrieval does not block on call completion.
- [ ] Add fake-socket request tests that assert one JSON line, matching exit status for success/error/not-ready, unchanged start/status behavior, and no socket request on `--help`. Update `SimpleNamespace` test callers with `result=None` so mocks preserve the new interface.
- [ ] Run `.venv/bin/python -m pytest tests/test_caller.py tests/test_cloud_runner.py -q`, then all tests and Ruff. Commit `feat: expose IVR terminal JSON locally and over cloud control`.

## Task 4 — Add safe correlated traces and the lesson checkpoint

**Files:** Modify `client.py`, `tests/test_client.py`, `.env.example`, `README.md`, `deploy/README.md`, repository `docs/ivr-learning-plan.md`, and these planning status records. Create `lessons/04-value-or-error.md`.

**Interfaces:** Add `ClientSettings.debug_transcripts: bool = False`, env `IVR_CLIENT_DEBUG_TRANSCRIPTS`; only `0` and `1` are accepted. Existing loader must convert it separately from `_INT_FIELDS` and reject any other value with the generic settings error.

- [ ] Add settings cases for unset/0/1 and rejection of `true`, blank, and `2`. Add `caplog` checks for default trace fields and debug-only metadata. Seed raw call/control IDs, phone numbers, challenge digits, synthetic ID digits/words, API key, and transcript sentinel text; assert none appear in either mode.
- [ ] Run focused settings/log tests to see failures. Extend `_log` with correlation references and stage transitions, using existing logger/run ID/clock. Hash identities while bound:

```python
call_ref = hashlib.sha256(identity.call_control_id.encode()).hexdigest()[:12]
leg_ref = hashlib.sha256(identity.call_leg_id.encode()).hexdigest()[:12]
```

  Cache only hashes through final log emission. Wrap existing flow event/watchdog/replay transitions with before/after-stage observations; do not create a new event bus or logging framework. Move unconditional per-transcript metadata behind the debug setting, with run ID and elapsed time. Emit only character/segment counts, ownership booleans, final flag, and parser status/reason. Never log tokenized or raw text. Preserve concise lifecycle/terminal default logs.
- [ ] Add `.env.example` documentation:

```dotenv
# Safe transcription metadata only; never prints transcript text.
IVR_CLIENT_DEBUG_TRANSCRIPTS=0
```

- [ ] Write the guide with prerequisites, small build steps, complete amount vs marker-only examples, result-versus-cleanup explanation, parser exercises, stdout/stderr/exit contract, and local/cloud alternatives. Explain why the five-second window was already present but now applies to every result and is capped by overall time. Include the exact offline commands and learner-operated local command:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
# Learner-operated, only with callback routing already aimed at this process:
uv run python caller.py --env-file .env --app public > /tmp/ivr-result.json 2> /tmp/ivr-trace.log
call_exit=$?
cat /tmp/ivr-result.json
printf 'exit=%s\n' "$call_exit"
```

- [ ] Document cloud retrieval separately from start acknowledgment, using the existing SSH-only runner after a separately authorized deployment:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py start
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py status
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py result
call_exit=$?
printf 'exit=%s\n' "$call_exit"
```

  Wait for status `done=true` before retrieving the terminal result. Explain `result_not_ready` and that querying never redials. Service logs contain the stderr trace; the result command prints the value/error and its exit status. Preserve existing restart/manual termination guidance.
- [ ] Provide acceptance rows for normal `1425.30`, changed `17.42`, wrong-ID rejection, and every unsuccessful live attempt. Initialize live evidence “Not run” and learner acceptance “Pending”. Zero and unsupported wording are offline exercises. Show how to change only `IVR_RESULT_AMOUNT` for the fixture between calls, leaving client configuration untouched, and restore it afterward. Do not introduce a scenario switch solely for this lesson.
- [ ] Update README/curriculum planning links and explain that local stdout-empty/checkpoint semantics are superseded once implementation passes. Preserve historical Lesson 3 evidence and observed STT limitations. Add a deployment-doc `result` command example without claiming it has been deployed.
- [ ] Final verification from `spikes/ivr/`, then repository root:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
uv run python cloud_runner.py --help
cd ../..
git diff --check
git status --short --branch
```

- [ ] Record actual offline results and commit the explicit changed paths as `docs: teach IVR value-or-error contract and acceptance`. Stop for learner review/live checkpoint; do not merge or begin Lesson 5.

## Spec coverage and self-review

| Requirement | Tasks |
| --- | --- |
| Strict amounts, zero, changed values, no fixture runtime imports | 1 |
| Fragmentation, duplicates, conflicts and post-hangup ordering | 1–2 |
| Deadline cap, immutable decision, cleanup separation, error stage | 2 |
| Exactly one local output, startup/cancellation, exit codes | 3 |
| Cloud result retrieval and backward-compatible status/start | 3 |
| Correlation, metadata-only debug, privacy | 4 |
| Walkthrough, truthful offline/live/learner records | 4 |

Author self-review checked task interfaces, existing caller sites, grammar bounds, all curriculum Lesson 4 checkboxes, and boundary/failure checks. No provider schema changes are proposed; reverify official provider documentation only if implementation discovers a need to alter provider commands. No implementation, deployment, paid call, or independent review occurred during planning.
