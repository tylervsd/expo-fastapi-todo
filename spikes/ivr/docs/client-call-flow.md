# IVR client: call handling and making flow changes

This guide explains the implementation through Lesson 4, at source commit
`41ffdc3` on `codex/ivr-04-value-or-error`. Source links open the existing lesson
worktree; line numbers describe that revision. Main may still contain the older
Lesson 3 client. Code labeled **current source** is extracted from the implementation;
code labeled **proposed change** is an example, not an installed feature.

The client is a fixed, prompt-driven state machine. It recognizes the current
prompt, sends a configured or speech-derived DTMF response, and waits for the
next prompt. It does not discover arbitrary menus or use an LLM.

**Start here for a flow change:** change the prompt grammar in `speech.py`, the
stage transitions in `client.py` if the sequence changes, and the answering
fixture in `fixture.py` if your local test service should speak the new protocol.
Most menu changes do not require touching webhooks, HTTP transport, or either CLI.

## Contents

- [Responsibilities and source map](#responsibilities-and-source-map)
- [One call from start to result](#one-call-from-start-to-result)
- [How a transcript becomes a keypress](#how-a-transcript-becomes-a-keypress)
- [Result finalization and cleanup](#result-finalization-and-cleanup)
- [Which files change for which request](#which-files-change-for-which-request)
- [Worked example: add a language prompt](#worked-example-add-a-language-prompt)
- [Testing and diagnosing changes](#testing-and-diagnosing-changes)

## Responsibilities and source map

There are two independent applications even when one process hosts both:
**the client places the call; the fixture answers it**. They have separate
application IDs, call legs, state, and webhook routes. The client never reads the
fixture's challenge, amount, or expected answer from memory.

| Component | Owns | Start reading |
| --- | --- | --- |
| Local CLI | Start webhook server, wait for readiness, start one call, print one JSON result, exit | [caller.py · run_call](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/caller.py:46) |
| Cloud control | Persistent server; explicit `start`, read-only `status`/`result`; one call per process lifetime | [cloud_runner.py · Control.handle](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/cloud_runner.py:23) |
| App lifespan | Load settings, create HTTP clients and controllers, run one-second watchdogs, close resources | [webhooks.py · lifespan](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/webhooks.py:46) |
| Webhook boundary | Signature/freshness, request size/envelope validation, route to the appropriate role | [webhooks.py · _receive_event](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/webhooks.py:173) |
| `Caller` | One run, call identity, async tasks, locking, early callbacks, tracing, final snapshot | [client.py · Caller](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:511) |
| `ClientFlow` | Current prompt stage, final transcript buffer, DTMF decisions, deadlines, result/error | [client.py · ClientFlow](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:230) |
| Speech grammar | Understand supported words/digits; distinguish pending, complete, and invalid prompts | [speech.py · recognize](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/speech.py:205) |
| Provider transport | Construct immutable command bodies and perform HTTP requests | [telnyx_commands.py · send_command](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/telnyx_commands.py:100) |
| Answering fixture | Speak prompts, gather digits, validate answers, speak amount, hang up | [fixture.py · Flow.handle](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/fixture.py:257) |

A useful reading order is `caller.py` → `webhooks.py` → `Caller` → `ClientFlow`
→ `speech.py`. `Caller` and `ClientFlow` are different classes in the same file:
the former owns asynchronous execution; the latter decides what the call means.

## One call from start to result

```mermaid
sequenceDiagram
    actor Operator
    participant Entry as Local CLI / cloud control
    participant Owner as Caller
    participant Telnyx
    participant Webhook as Verified client webhook
    participant Flow as ClientFlow + speech
    Operator->>Entry: Start one run
    Entry->>Owner: start() after server readiness
    Owner->>Telnyx: Dial configured number, transcription enabled
    Telnyx-->>Owner: HTTP dial response with call identity
    Note over Telnyx,Webhook: Callbacks can arrive before the dial HTTP response
    Telnyx->>Webhook: Answered / transcription / hangup event
    Webhook->>Owner: accept(data)
    Owner->>Owner: Validate and admit owned call/leg
    Owner->>Flow: handle(data, now)
    Flow->>Flow: Buffer finals; recognize current prompt
    Flow-->>Owner: Immutable DTMF command, or no command
    Owner->>Telnyx: Send command asynchronously
    Telnyx-->>Owner: HTTP command accepted (not next-stage proof)
    Note over Owner,Flow: Repeat as the remote IVR speaks each next prompt
    Telnyx->>Webhook: Hangup, possibly followed by late final speech
    Owner->>Flow: Events + watchdog ticks
    Flow-->>Owner: One terminal value/error
    Owner->>Owner: Settle tasks, clear sensitive buffers, set done
    Entry-->>Operator: JSON result and exit status
```

The diagram shows the ordinary path; HTTP responses and callbacks are separate
channels with no guaranteed delivery order. The watchdog also runs when no
callback arrives, so silence cannot leave an active flow waiting indefinitely.

### 1. Start only when the server is ready

`caller.py.run_call()` sets `app.state.caller_enabled`, starts Uvicorn on loopback,
and waits for readiness before `Caller.start()`. A startup/port failure must not
dial. `webhooks.lifespan()` constructs the controller with injected `dial` and
`send` functions. The same injection lets tests use fake functions instead of
making paid calls.

The cloud runner uses the same controller but keeps the server alive.
`cloud_runner.py start` initiates the call; `result` only retrieves a finished
snapshot. Merely importing modules, running a plain receipt-only client app,
or starting the cloud service does not initiate a call.

**Current source:**

[client.py · Caller.start](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:568)

```python
async def start(self):
    if self._started:
        raise RuntimeError("already_started")
    self._started = True
    self._started_at = self.clock()
    self._wall_started = datetime.now(UTC)
    self.request = make_dial(_dial_fields(self.settings))
    self._run_token = self.request.client_state
    self._log("dial_reserved")
    self._dial_task = asyncio.create_task(self._run_dial())
```

`_dial_fields()` reads only client settings, sets the destination and caller ID,
and enables Telnyx/inbound transcription at dial time. `_run_dial()` performs
the request. This is where telephony setup lives, not menu behavior.

### 2. Establish which call this process owns

The webhook verifies the original request bytes and rejects invalid signatures,
stale timestamps, oversized bodies, and malformed envelopes. HTTP 200 acknowledges
an accepted callback; it does not mean the call succeeded.

`Caller.accept()` checks event shape and application identity. Before identity is
bound, `_accept_preface()` can bind from a correlated outgoing `call.initiated`
using the run token, configured numbers, and timestamp. Other early callbacks
are buffered with limits. The dial response can also establish identity.
`_replay()` filters buffered events to that identity and handles buffered hangups
first; a call that already ended must not restart navigation.

Once bound, both `call_control_id` and `call_leg_id` must match. The fixture's
call identifiers cannot be substituted for the client's. State updates take
place under the controller's lock; outbound HTTP runs in separate tracked tasks.
See [client.py · Caller._accept_bound](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:860) and [client.py · Caller._run_command](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:892).

### 3. Follow the prompt stages

| Stage being listened for | Required recognition | DTMF sent | Next stage |
| --- | --- | --- | --- |
| `dialing` | Owned `call.answered` | None | `welcome` |
| `welcome` | Press 1 to continue | `1` | `challenge` |
| `challenge` | Complete four-digit code and pound-key instruction | Heard code + `#` | `menu` |
| `menu` | Personal/business menu with expected choices | `1` | `identifier` |
| `identifier` | Nine-digit personal-ID entry instruction | Configured synthetic ID + `#` | `confirmation` |
| `confirmation` | Exact readback matches configured ID; confirm instruction | `1` | `result` |
| `result` | Complete, supported, unambiguous dollar/cent amount | None | Finalize, then `ended` or bounded cleanup |

Example tones: `1`, `0742#`, `1`, `000123456#`, `1`. The leading zero stays intact
because codes and identifiers are strings. The result amount comes only from
transcription, not from fixture settings.

## How a transcript becomes a keypress

`ClientFlow.handle()` dispatches events. `_on_transcript()` ignores partials,
checks timestamps/order and buffer limits, appends final segments, and evaluates
the combined stage text. Different event IDs with identical text are not blanket
text-deduplicated: repeated zero words can be meaningful. Event-ID deduplication
is separate from understanding the transcript.

The parser contract is small:

| Return value | Meaning | Flow action |
| --- | --- | --- |
| `("pending", None)` | More final speech may be needed | Keep listening within the deadline |
| `("complete", "0742#")` | Current navigation prompt understood | Reserve DTMF and advance |
| `("complete", "1425.30")` at result | Complete amount candidate | Retain buffer; await finalization |
| `("invalid", "id_mismatch")` | Recognized failure/unsupported input | Record error; clean up |

**Current source:**

[client.py · ClientFlow._evaluate](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:349)

```python
def _evaluate(self, *, now, occurred):
    joined = " ".join(self._segments)
    status, value = recognize(self.stage, joined, self.settings.synthetic_id)
    self.parser_status = status
    self.parser_reason = value if status == "invalid" else None
    if status == "pending":
        return None
    if status == "invalid":
        return self._fail(value, now=now)
    if self.stage == "result":
        self.checkpoint_reached = True
        return None
    return self._reserve_dtmf(value, now=now, occurred=occurred)
```

`recognize()` first checks known rejection phrases and mixed-stage ambiguity.
Then it applies the grammar for the current stage. For a challenge it needs both
the code marker and the pound instruction before extracting exactly four digits.
For confirmation it checks the actual ID readback before sending confirmation.

**Current source:**

[client.py · ClientFlow._reserve_dtmf](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:330)

```python
def _reserve_dtmf(self, logical, *, now, occurred):
    wire = ("w" * self.settings.dtmf_pause_units).join(logical)
    command = make_command(
        self.identity.call_control_id,
        "send_dtmf",
        {
            "digits": wire,
            "duration_millis": self.settings.dtmf_duration_ms,
        },
    )
    self.pending = command
    self._segments = []
    self._chars = 0
    self._last_time = None
    self._consumed_at = occurred
    self.stage = _NEXT[self.stage]
    self.stage_started_at = now
    return command
```

The stage advances when the command is **reserved**, before its HTTP request
finishes. This permits the next prompt to arrive before the DTMF acknowledgment.
Do not move advancement into the HTTP-success callback. The next recognized
prompt is evidence of remote progression; `command_accepted` alone is not.

`make_command()` assigns a command ID and constructs the body once.
`send_command()` may retry the same object/body under its bounded policy;
reconstructing it inside a retry would create a different logical command.
`_run_command()` ignores failures for commands that are no longer current.
Do not add prompt-navigation sleeps to resolve callback ordering.

## Result finalization and cleanup

These milestones mean different things:

| Field/state | Meaning |
| --- | --- |
| `checkpoint_reached` | A complete result candidate has been recognized at least once; not a terminal success |
| `ClientFlow.result` | First terminal value/error has been decided |
| `stage == "hanging_up"` | Cleanup is in progress; a result/error may already exist |
| `stage == "ended"` | Flow no longer accepts navigation/transcript changes |
| `Caller.result` and `Caller.done` | Snapshot copied to owner; tasks settled and result ready for consumers |

Result-stage text is retained even after a candidate appears, so another final
can reveal a conflicting amount. The first result-stage hangup opens a
five-second window, capped by the overall deadline. Duplicate hangups do not
extend it. Events exactly at the boundary are too late. At the boundary,
`_on_deadline()` evaluates the whole remaining buffer. Missing/unsupported
speech produces `result_unrecognized`; matching repeated announcements are
allowed, conflicting amounts are rejected.

**Current source:**

[client.py · ClientFlow._expired](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:294)

```python
def _expired(self, now):
    if self._result_hangup_at is not None:
        boundary = min(
            self._result_hangup_at + 5,
            self.started_at + self.settings.call_timeout_seconds,
        )
        return "result_unrecognized" if now >= boundary else None
    if now - self.started_at >= self.settings.call_timeout_seconds:
        return "overall_timeout"
    if now - self.stage_started_at >= self.settings.stage_timeout_seconds:
        return "stage_timeout"
    return None
```

Without an observed hangup, a stage/overall deadline can finalize a complete
amount and attempt hangup. Without a complete amount, it records the timeout.
Failure to confirm teardown cannot overwrite an already decided value or the
original error. `_decide()` is the single-decision guard:

**Current source:**

[client.py · ClientFlow._decide](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/client.py:257)

```python
def _decide(self, reason, value=None):
    if self.result is not None:
        return
    self.outcome = reason
    if value is not None:
        self.result = {"status": "success", "value": value, "currency": "USD"}
        self.exit_code = 0
    else:
        self.failure_stage = self.stage
        self.result = error_result(reason, self.failure_stage)
        self.exit_code = 1
```

`Caller._finalize()` copies the snapshot before clearing transcript buffers,
identity, and command bodies. It cancels/joins outstanding tasks and sets `done`.
The local CLI emits JSON once in its outer finalization path. Cloud `result`
returns the retained snapshot only after `done`; earlier queries return
`result_not_ready`. Results disappear on process restart.

Timeout defaults: 30 seconds per stage, 180 overall, five for post-hangup speech,
and 15 for controller cleanup. Stage timeout resets on navigation, not on each
partial/event. The local CLI additionally bounds cleanup at 20 seconds and server
shutdown at 10. These are separate from speech recognition; do not promise that
wall-clock CLI exit happens exactly at the 180-second mark.

## Which files change for which request

| Requested change | Edit | Also verify |
| --- | --- | --- |
| Alternate wording for the same prompt | Stage-specific patterns/normalization in `speech.py` | `_STAGE_SIGNS`, negative/ambiguous/fragmented parser tests |
| Different menu key | Expected-choice patterns, rejection checks, returned DTMF in `recognize()` | Fixture spoken menu and expected input; exact-tone replay |
| Insert/remove/reorder a step | `client.py` `_NEXT` and corresponding `recognize()` stages | Fixture next-stage map, prompts/gather behavior, full replay, failure-stage output |
| Longer challenge/ID | Client numeric parser length and settings validation | Fixture generation/validation, gather lengths including `#`, readback tests |
| Different amount wording/range | `parse_amount()`, `_integer()`, `_recognize_result()` | Fixture formatter/range if relevant, Decimal behavior, zeros/conflicts/incomplete results |
| Tune DTMF timing/deadlines | Existing `IVR_CLIENT_*` settings | Validation bounds, no timeout resets from duplicates, real-call evidence |
| New public error code | `error_result()`, `_PUBLIC_ERRORS`/`_ERROR_ALIASES` | Original failure stage, JSON/exit parity in local and cloud paths |
| New provider action/event | `telnyx_commands.py` allowlist/transport or `Caller._KNOWN_EVENTS` and admission | Official provider contract, payload tests, ownership/security checks |

For a wording-only change, `_NEXT` usually stays untouched. For a new step,
changing only `_NEXT` is insufficient: `recognize()` rejects stages missing from
`_STAGE_SIGNS`. That table also detects cross-stage ambiguity.

There is another easy trap: `_NEXT` assumes a single linear route. If a future
menu needs truly different branches, first specify both routes and their terminal
behavior; then explicitly change the transition decision and its tests. Adding
a second option to a regex does not make the current linear graph branch.

## Worked example: add a language prompt

Assume the answering IVR will now say “Press 1 for English” **after welcome and
before the challenge**. This is a proposed change, not currently implemented.
The intended tones become `1`, `1`, `0742#`, `1`, `000123456#`, `1`.

### Step 1: Write down both sides of the protocol

New stage: `language`. Entry from: `welcome`. Prompt: “Press 1 for English.”
Accepted reply: `1`. Next stage: `challenge`. Wrong advertised choice is
`unexpected_menu`; an incomplete instruction stays pending until a deadline.
Use the existing stage timeout; this example needs no new configuration.

### Step 2: Add parser expectations first

**Proposed tests** in `tests/test_speech.py`:

```python
def test_language_prompt():
    assert recognize("language", "Press one for English.", "000123456") == (
        "complete",
        "1",
    )
    assert recognize("language", "Press 1 for English.", "000123456") == (
        "complete",
        "1",
    )
    assert recognize("language", "Press one for", "000123456") == ("pending", None)
    assert recognize("language", "Press 2 for English.", "000123456") == (
        "invalid",
        "unexpected_menu",
    )
    assert recognize(
        "language", "Press 1 for English. Press 2 for English.", "000123456"
    ) == ("invalid", "unexpected_menu")
```

Run them first and observe the unknown-stage failure. Add the new signature
alongside the existing `_STAGE_SIGNS` entries and add a dedicated choice pattern:

```python
# Proposed additions in speech.py, near the existing stage signs/patterns:
_STAGE_SIGNS["language"] = _compiled(("for", "english"))
_LANGUAGE_ANY = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"for"
    + _SEP
    + r"english(?![a-z0-9])"
)
```

Add this branch inside `recognize()`, after the shared rejection and ambiguity
checks and before the final result fallback:

```python
# Proposed branch inside recognize(); low is already normalized.
if stage == "language":
    choices = {match.group(1) for match in _LANGUAGE_ANY.finditer(low)}
    if choices - {"one", "1"}:
        return ("invalid", "unexpected_menu")
    return ("complete", "1") if choices else ("pending", None)
```

Do not append it below `return _recognize_result(low)`, where it would be
unreachable. Check mixed language/challenge prompts as invalid too. A production
wording change should use the actual documented menu, not this example's English
assumption.

### Step 3: Change the client transitions and replay

**Proposed replacement** for `_NEXT`:

```python
_NEXT = {
    "welcome": "language",
    "language": "challenge",
    "challenge": "menu",
    "menu": "identifier",
    "identifier": "confirmation",
    "confirmation": "result",
}
```

`error_result()` currently includes `_NEXT` keys in its stage allowlist, so the
new stage is accepted automatically. Still test that a timeout reports
`stage: language`, not `hanging_up` or `startup`.

In `tests/test_client.py`, insert the language prompt into `HAPPY_TEXTS`, update
the expected DTMF sequence, and review helpers/tests using positional slices such
as `HAPPY_TEXTS[:2]`. An insertion changes what those slices represent; blindly
updating one happy-path assertion can leave tests exercising the wrong stage.
Add a duplicate-event check: replaying the same language event ID sends no second
keypress. Verify partial/final fragmentation, timeout, and wrong-leg rejection.

### Step 4: Make the fixture speak the same protocol

If this repository's answering fixture is the target, update
[fixture.py · Flow._gather](/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr/fixture.py:204) with a `language` prompt, and change the local
`next_stage` map inside `Flow.handle()` to welcome → language → challenge.
Its current one-digit gather default and expected-answer default `1` already
cover this example; no new digit-length setting is needed.

For a different reply, inspect the `expected` mapping and the special business
menu rejection as well. For multi-digit input, update minimum/maximum lengths
and valid digits; the current fixture counts the final `#` as part of the input
rather than setting it as Telnyx's terminating digit.

Add fixture progression tests in `tests/test_fixture.py`. Keep the client
independent: it must hear the new prompt, not call fixture helpers to learn which
step is next. An external IVR change may need a compatible local fixture update,
but never grants access to the remote system's internal state.

### Step 5: Verify, document, then exercise one controlled call

Run parser tests, flow/controller replay, fixture tests, and the complete suite.
Update the stage table and walkthrough. Commit the implementation before a
separately authorized cloud deployment. Follow the existing deployment/rollback
procedure if testing on the VM; editing the local worktree does not update it.
Record live results separately, including failures, then seek learner acceptance
before merging under the lesson workflow.

## Testing and diagnosing changes

From this worktree's `spikes/ivr` directory:

```sh
uv run pytest tests/test_speech.py -q
uv run pytest tests/test_client.py tests/test_fixture.py -q
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The existing tests already offer useful entry points:

| Test location | What it proves |
| --- | --- |
| `tests/test_speech.py` | Grammar, exact digit strings, pending/invalid text, amount boundaries |
| `tests/test_client.py` `_flow`, `_Builder`, `_say`, `_drive_happy` | Synchronous event replay with injected time; exact tones and stage transitions |
| `tests/test_client.py` `_CallerHarness` | Async ownership, early callbacks, command races, cleanup, private logs |
| `tests/test_fixture.py` | Answering-side prompt/gather progression and validation |
| `tests/test_caller.py` | Readiness before dialing, one stdout record, failure/interrupt exit codes |
| `tests/test_cloud_runner.py` | Start/status/result behavior; retrieval never redials |
| `tests/test_webhooks.py` | Signed boundary, malformed events, correct role dispatch |

Start with a test at the layer being changed, then replay the full flow. Fake
clock tests should advance time rather than sleep for real call deadlines.
Offline tests do not establish that live transcription will produce the expected
wording. Keep that uncertainty visible in the acceptance record.

For a safe, runnable inspection of the **current** challenge recognizer:

```sh
uv run python - <<'PYCODE'
from speech import recognize
text = "Your verification code is zero seven"
assert recognize("challenge", text, "000123456") == ("pending", None)
text += " four two. Enter the code followed by pound."
assert recognize("challenge", text, "000123456") == ("complete", "0742#")
print("Complete challenge recognized; no call placed.")
PYCODE
```

| Symptom | Inspect first | Interpretation |
| --- | --- | --- |
| No dialing | CLI readiness/settings; cloud start acknowledgment | Startup and call initiation are separate |
| Webhook returns 401/400 | `verify_signature`, `_receive_event`, `Caller._validate` | Event never reached the flow; loosening grammar cannot fix it |
| Events arrive but no tones | Debug ownership/final flags; parser status | Wrong leg, partial speech, or incomplete grammar may be ignored/pending |
| Wrong tone/next stage | `recognize`, `_reserve_dtmf`, `_NEXT` | Speech decision and transition selection, not HTTP acknowledgment |
| Repeated tones | Event IDs, stage buffer reset, command-object reuse | Identify whether this is one retried command or a newly created command |
| Result marker heard but failure | `_recognize_result`, `_on_deadline` | A marker alone is insufficient; inspect completeness/conflicts and timing |
| Correct amount plus cleanup warning | `ClientFlow.result`, `cleanup_reason`, `Caller.done` | Value recognition and remote teardown are separate |

Default traces contain run ID, elapsed time, stage transitions, and hashed
`call_ref`/`leg_ref`. `IVR_CLIENT_DEBUG_TRANSCRIPTS=1` adds metadata, not transcript
text. Match observations to the correct run; do not log IDs, challenge values,
phone numbers, or raw provider bodies to debug grammar.

For operational commands and live evidence, use the [Lesson 4 walkthrough](../lessons/04-value-or-error.md)
and [deployment guide](../deploy/README.md). This guide documents source behavior;
it does not claim a new release has been deployed or live calls verified.

Lesson 5 adds fixture-only `IVR_SCENARIO` branches at the challenge, confirmation,
and result transitions. The client protocol and source excerpts above are unchanged.
See [reliability drills](../lessons/05-reliability-drills.md) for scenario selection
and offline prompt replay.
