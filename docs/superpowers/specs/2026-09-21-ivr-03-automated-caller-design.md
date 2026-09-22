# IVR Lesson 3: an automated caller that hears and responds

**Date:** 2026-09-21. **Status:** Implemented and verified offline; live
verification and learner acceptance remain pending. Spec and plan drafted
together at the learner's request. Planning used no subagents. The learner
authorized implementation with subagents on 2026-09-21; implementation used a
bounded scout pass, fresh workers per task, and per-task reviewers plus a
final whole-branch review.

**Related:** [Curriculum](../../ivr-learning-plan.md),
[implementation plan](../plans/2026-09-21-ivr-03-automated-caller.md),
[Lesson 2 spec](2026-09-21-ivr-02-test-ivr-design.md), and
[Lesson 2 walkthrough](../../../spikes/ivr/lessons/02-test-ivr.md).

## Intent and baseline

Turn the receipt-only client into a local, one-call command. It calls the
configured test number, hears the fixture, replays the spoken challenge exactly,
selects personal, enters a synthetic ID, checks its readback, and recognizes the
result-stage announcement. The learner should understand which call leg owns
each event, when transcription is usable, and why prompts rather than sleeps
authorize DTMF. Repeat with a different code, including one beginning with zero.

“IVA plan” is interpreted as the repository's IVR learning plan. Its Lesson 3
is the scope. Amount extraction and the final value-or-error JSON contract remain
Lesson 4; the multi-scenario reliability campaign remains Lesson 5.

Lesson 2 is accepted and merged through PR #34 at `ea6ee2d` on main. The
curriculum and acceptance record supersede stale pending-acceptance wording in
the Lesson 2 planning artifacts. Intermittent webhook delivery failures remain
an observation, not a solved issue or permission to bypass signature checks.
Planning baseline: 168 tests and both Ruff checks pass, with two existing
upstream deprecation warnings. No dependencies installed for this check.

Reuse `.worktrees/ivr-01-connectivity`; its old name is intentional. Work on
`codex/ivr-03-automated-caller`, created from merged main `ea6ee2d`. Preserve the
Lesson 2 branch, ignored `.env`/environment, main checkout, and unrelated `.pi/`.
Do not create another worktree, reset branches, push, or merge during planning.

## Constraints

- Python 3.14; one independent uv environment and lockfile under `spikes/ivr/`.
- Reuse FastAPI, Uvicorn, cryptography, pytest, and httpx; no new library or SDK.
- One automated call per CLI invocation, one worker, no reload, in-memory state only.
- Keep all three existing entry points and both webhook paths; no HTTP call-start or scenario controls.
- Dial only the configured test number; no destination argument or webhook-driven dialing.
- Client code must not read fixture state, challenge override, result amount, or fixture settings.
- No database, queue, cloud deployment, UI, LLM, recording, or custom audio streaming.
- No subagents during planning. Implementation used authorized subagents (see
  status record above); automated verification stayed offline and live
  acceptance remains learner-operated and separately recorded.
- Do not purchase numbers, change account settings, or expose a tunnel during this work.
- Preserve unrelated local changes and existing Tailscale mappings.

## Approaches and decision

1. **Choose a one-call CLI that owns its webhook server.** Reuse the existing
   routes and signature boundary, attach a client controller to that app's state,
   and dial only after the server is ready. The combined mode also runs the
   fixture controller. This needs no IPC or public controls.
2. A persistent server with a separate CLI and local control socket would allow
   repeated runs without restarting, but introduces a control protocol we do
   not need for one call at a time.
3. A separate CLI with its own in-memory controller beside the existing ingress
   would not receive that ingress's events. Reject this disconnected design.

Use dial-time transcription rather than issuing a start command after receipt of
`call.answered`: the fixture starts its welcome immediately, so a second network
round trip can lose its beginning. This reduces that race; it does not guarantee
the provider captures every initial word. Missing prompts time out safely.

## Provider contract and live assumptions

Official documentation checked 2026-09-21; account capability is not verified.

- [Dial](https://developers.telnyx.com/api-reference/call-commands/dial):
  `POST https://api.telnyx.com/v2/calls` with `connection_id`, `from`, `to`,
  a random `command_id`, and base64 random run token as `client_state`. A 200
  response contains call identity, not the action sender's `data.result` shape.
  Enable `transcription: true`; set `timeout_secs: 30` and `time_limit_secs`
  to the configured overall limit. These provider limits supplement local cleanup.
- [Transcription options](https://developers.telnyx.com/api-reference/call-commands/transcription-start):
  put `transcription_engine: "Google"`, engine config
  `{"transcription_engine":"Google","language":"en","interim_results":true}`,
  and `transcription_tracks: "outbound"` in `transcription_config`.
  The documentation describes outbound as the other leg relative to the
  requesting leg. This is a proposed remote-side selection, not a proven
  mapping for this account. Confirm fixture speech on the client's callback
  during the first live exercise; never merge both tracks to conceal a mismatch.
- [Transcription callback](https://developers.telnyx.com/api-reference/callbacks/transcription):
  handle `call.transcription`, with nested `transcription_data.transcript` and
  boolean `is_final`. The documented example carries call, leg, session and
  connection IDs; it does not promise a stage token, segment sequence number,
  or track field. Do not require invented fields or a `transcription.started`
  event. Partials are not navigation evidence.
- [Send DTMF](https://developers.telnyx.com/api-reference/call-commands/send-dtmf):
  reuse the action sender for `send_dtmf`, with `digits`, `duration_millis`,
  stable `command_id` and opaque `client_state`. Tone duration is 100–500 ms;
  `w` encodes a 500 ms pause. API acknowledgment does not prove digits were
  received. The next expected spoken prompt supplies progression evidence.

Use the application-configured callback URL; do not accept a callback URL from
the CLI or an event. Keep bearer authorization, fixed API origin, URL-encoded
call-control tokens, no redirects, and sanitized errors. Before implementation,
recheck these contracts if documentation or real payloads disagree; record an
explicit adjustment, not a silent fallback to fixture internals.

## Runtime and settings

Add `client.py` for client settings/controller, `speech.py` for the small prompt
grammar, and `caller.py` for the local CLI. Extend `telnyx_commands.py` for dial
and DTMF. Reuse `webhooks.py` for app lifespan, verified routing and shutdown.
Do not extract a general call-control framework from the fixture.

The implemented command will be:

```sh
cd .worktrees/ivr-01-connectivity/spikes/ivr
uv run python caller.py --env-file .env --app public
```

`--app public` binds `127.0.0.1:8010`, runs both role controllers, and exposes
only the two existing webhook routes through the existing Funnel mapping.
It replaces the Lesson 2 Uvicorn process for the call; do not run both on 8010.
`--app client` binds `127.0.0.1:8011` and hosts only the caller, for an independently
run fixture with separately configured callback routing. Do not add a port/host
override in this lesson. The standalone Uvicorn entry points retain their
existing behavior when the CLI has not enabled a client controller.

Use Uvicorn's existing env-file support, start its server in the CLI event loop,
wait for `server.started` while also watching the server task for failure, then
start exactly one call through `app.state.caller`. Bound server readiness at
10 seconds. Importing modules or starting plain Uvicorn must never dial.
CLI-enabled state belongs to the selected app instance and is cleared on exit.
Lifespan owns HTTP clients, controllers, watchdogs and task cleanup. The client
controller never receives a fixture controller reference, even in combined mode.

Client settings use only the explicit names below and `TELNYX_PUBLIC_KEY`.
Shared API credentials are allowed; shared runtime/business settings are not.

| Setting | Default and validation |
| --- | --- |
| `TELNYX_API_KEY` | Required; same printable-ASCII nonempty validation as fixture, no secret repr |
| `IVR_CLIENT_CONNECTION_ID` | Required, nonempty, at most 256 characters; distinct from fixture app in combined mode |
| `IVR_CLIENT_FROM_NUMBER` | Required E.164 `+[1-9][0-9]{7,14}`; learner-owned outbound caller ID |
| `IVR_CLIENT_TO_NUMBER` | Required E.164, distinct from from-number; the sole allowed test destination |
| `IVR_CLIENT_SYNTHETIC_ID` | `000123456`; exactly nine ASCII digits, independently configured |
| `IVR_CLIENT_STAGE_TIMEOUT_SECONDS` | `30`; integer 10–60 |
| `IVR_CLIENT_CALL_TIMEOUT_SECONDS` | `180`; integer 60–600, at least stage timeout |
| `IVR_CLIENT_DTMF_DURATION_MS` | `250`; integer 100–500 |
| `IVR_CLIENT_DTMF_PAUSE_UNITS` | `0`; integer 0–2, inserts that many `w` between logical digits |

Do not coerce booleans to integers, strip invalid numbers into valid ones, or
print rejected settings. No engine selector or general language parser yet.
The learner checks outbound profile, number assignment, destination permissions,
balance and Google transcription support before placing a call. No account
configuration changes are part of automated implementation.

## Call admission and transport ownership

Reserve one run and its dial body before I/O. A second `start()` is rejected;
completed controllers cannot start another call. Dial is submitted once with a
five-second total timeout and no automatic retry, even on 429/5xx. Retain its
command ID. If a verified callback already established this run's identity,
that evidence wins over a late HTTP error and normal navigation can continue.
Otherwise, on uncertainty, stop navigation, allow the dialing-stage deadline
for a correlated initiated callback to reveal the leg, and attempt hangup if
identified. Never issue a new dial to resolve uncertainty. Report an unresolved
remote call to the learner; provider limits and manual termination are fallbacks.

Bind the client call/leg pair from a validated dial response or a verified
outgoing `call.initiated` carrying this run's exact token, configured connection,
from/to and fresh `occurred_at`. If both arrive, they must agree. A conflict
fails closed and cleans up only the identity already established for this run.
Never admit an arbitrary webhook merely because its connection ID matches.

Before identity is known, retain at most 32 verified candidate events/64 KiB for
the configured client connection, begun after the local dial reservation. Replay
only those matching the established call/leg; discard the rest. Overflow fails
the run. This handles answered/transcription/hangup before the HTTP response.
Prioritize a matching buffered hangup before navigation so a dead call cannot
be reopened. Require observed answer before sending DTMF; a dial response alone
cannot authorize tones. Preserve early final transcripts until answer arrives.

Every actionable event must have bounded nonempty call (1024), leg (256), and
connection (256) strings and an aware parseable event timestamp. Preserve the
existing signature/freshness/body/envelope limits. Malformed actionable payloads
get generic 400 without mutation; wrong-role, wrong-leg, unknown and duplicate
events get empty 200 with no action. Public callbacks do not await provider HTTP.
Session IDs are diagnostic grouping only, never command targets.

After binding, use call/leg/connection ownership, not current `client_state`, for
transcripts: each DTMF command changes that state and callbacks can overlap.
Reserve one command per logical input stage before scheduling I/O. Reuse the
existing immutable command body and bounded action retry policy; no new command
ID for a retry. A next-stage prompt can beat its HTTP acknowledgment; a late
failure for an obsolete action cannot rewind or terminate the advanced stage.

## Transcript grammar and stage progression

Stages: `dialing → welcome → challenge → menu → identifier → confirmation →
result → hanging_up → ended`. `ended` is absorbing. The result stage starts
after reserving confirmation DTMF; reaching it alone is not checkpoint success.

Maintain a bounded stage buffer of final segments only (maximum 4096 characters
and 64 segments). Ignore partials including their text; require `is_final` to be
a real boolean and transcript to be a string of at most 4096 characters. Dedup
event IDs for the invocation (cap 4096; overflow fails). Join final fragments
with a space, permitting a digit run split across segments. Do not use text
deduplication that would delete repeated zero digits.

Normalize case and limited punctuation, not meaning. Recognize ASCII digit runs
and digit words zero–nine, with spaces, commas and hyphens as separators. Keep
identifiers as strings. Reject Unicode digits, decimal points within digit
spans, plus/minus signs, number words like seventy, and substitutions like
oh/to/for. No integer conversion, padding, truncation, homophone inference, or
substring selection from a longer number. Conflicting or multiple candidate
spans fail; incomplete fragments wait only until their deadline.

| Waiting for | Complete final evidence required | Logical digits reserved once |
| --- | --- | --- |
| welcome | “press 1 to continue” (one/1 equivalent) | `1` |
| challenge | “your verification code is” + exactly four digits + “enter the code followed by pound” | parsed code + `#` |
| menu | Both “press 1 for personal” and “press 2 for business” | `1` |
| identifier | “enter your nine digit personal id followed by pound” (nine/9 equivalent) | configured synthetic ID + `#` |
| confirmation | “you entered” + exactly nine digits + “press 1 if correct”; readback equals configured ID | `1` |
| result | “your requested value is” after confirmation | none; record checkpoint reached |

Prompt phrases are the documented fixture protocol, not imports from
`fixture.py`. Sentence punctuation around delimiters is allowed; punctuation
inside numeric spans follows the stricter rule above. Parse only between the
numeric prompt's start/end markers so menu-choice digits cannot contaminate it.
In the parser distinguish pending, complete, and invalid; never send on pending.
An end marker with the wrong digit count is invalid immediately.

Clear the buffer on a reserved transition. Keep the last consumed event time;
older fragments may not feed a later stage. Within a stage, a decreasing event
timestamp fails safely as `transcript_order`; equal timestamps preserve arrival
order. Do not pretend `occurred_at` is an audio offset. Recognizable prior-stage
replays do not produce tones, and clear their text before it can pollute the
current prompt. A single transcript containing incompatible stage prompts fails
as ambiguous. General out-of-order speech reconstruction is outside this lesson.

Known rejection/retry phrases (“that entry was not accepted”, “we could not
verify your entry”, “business requests are not supported”, “test service is
unavailable”) end navigation, including when split across final segments.
Do not automatically resend on a fixture retry. A completed wrong menu is
`unexpected_menu`; an incomplete/unknown prompt eventually times out. ID mismatch
terminates without sending confirmation. Input/output evidence must come only
from the client's remote speech; fixture webhook digits are acceptance evidence
for the learner, never inputs to client navigation.

## Deadlines, outcome and cleanup

Use monotonic time. Each new stage gets 30 seconds by default; partials, duplicate
events and unrelated text never extend it. The overall 180-second deadline starts
at dial reservation. Check both before processing each event and in a watchdog
at least once per second. Configurable DTMF pauses tune audio, not navigation.
Do not use fixed sleeps to decide when to send a menu answer.

Once the result announcement is recognized, retain `checkpoint_reached` and wait
for the fixture's ordinary hangup, bounded by the current stage and overall
deadlines. Do not parse, log or report its amount. This allows normal fixture
speech to finish. On errors, timeout, Ctrl-C or server shutdown, cancel obsolete
commands and attempt one logical hangup of the owned client leg. Cleanup has a
separate maximum 15-second budget; no navigation beyond the overall deadline.
Hung-up events stop commands immediately. Missing hangup acknowledgment is
`hangup_unconfirmed`, never proof that the provider call ended.

Exit 0 only when the result announcement and a matching hangup were both
observed. Otherwise exit nonzero with a concise reason: invalid configuration,
dial rejected/uncertain, provider failure, malformed/ambiguous speech,
challenge unrecognized, transcript order, unexpected menu, ID mismatch,
fixture rejection, stage/overall timeout, early hangup or unconfirmed cleanup.
This lesson writes a short checkpoint/error diagnostic to stderr and leaves
stdout empty. The structured JSON value contract is not implemented yet.
Do not grant a post-hangup transcript window here; Lesson 4 owns finalization.

Logs include run ID, stage, elapsed time and sanitized reason only; omit full
transcripts, numeric input, numbers, credentials and call-control tokens. Keep
raw provider bodies and exception URLs out of logs. Debug transcript storage and
the richer Lesson 4 trace are deferred. Redact any manually recorded live evidence.

## Verification and acceptance

Offline checks use existing pytest and MockTransport, with real network blocked.
Cover parsing variants/leading zeros; segmented finals/partials; all five DTMF
actions; ID mismatch; duplicate and late events; foreign fixture legs; early
callbacks; dial ambiguity; next prompt before HTTP response; startup failure;
deadlines, shutdown, bounded buffers, stdout privacy and entry-point isolation.
Preserve all Lesson 1/2 security and fixture checks. No paid calls in tests.

During implementation add `spikes/ivr/lessons/03-automated-caller.md`, with concepts,
small build steps, settings, exact commands, expected stderr/exit status,
troubleshooting, manual termination and a separate acceptance table. Do not
create an empty guide during planning. At the learner-operated checkpoint:

1. Verify routing, distinct application IDs, outbound caller ID/profile and
   allowed destination; stop the old ingress before the CLI owns its port.
2. Run a normal call; verify the selected transcription track hears fixture
   speech. Record stage progression and actual fixture received-digit evidence
   using learner-inspected provider diagnostics, with synthetic ID redacted.
   Default application logs remain private.
3. Repeat with a different random challenge; record every attempt, not only
   successes. Random repetition is possible and is not a randomness defect.
4. Set fixture-only `IVR_CHALLENGE_OVERRIDE=0742`, restart through the CLI, and
   verify exact `0742#` received; clear the override afterward. Client settings
   and code must never read it.
5. Configure a mismatched client synthetic ID and observe bounded rejection;
   the offline test separately forces a wrong confirmation readback and proves
   no confirmation tones. Restore the settings.
6. If delivery drops recur, record timing/event types/provider delivery status
   and rerun the affected exercise. Do not label it reliable from offline checks.

Planning delivered only this spec, its implementation plan, and curriculum links.
Offline implementation is complete (358 tests, Ruff clean); live evidence and
learner acceptance remain pending. Stop after
the Lesson 3 checkpoint; do not continue into Lesson 4 without a new request.
