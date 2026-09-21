# IVR Lesson 2: a test IVR you can navigate by hand

**Date:** 2026-09-21. **Status:** Proposed design, ready for learner review.
This is documentation only; implementation, live verification, and Lesson 2
acceptance have not occurred. No subagents.

**Related:** [Curriculum](../../ivr-learning-plan.md),
[implementation plan](../plans/2026-09-21-ivr-02-test-ivr.md),
[Lesson 1 spec](2026-09-20-ivr-01-connectivity-design.md),
[Lesson 1 plan](../plans/2026-09-20-ivr-01-connectivity.md), and
[Lesson 1 acceptance](../../../spikes/ivr/lessons/01-connectivity.md#acceptance-record).

## Intent and inherited baseline

A learner calls the existing destination from a personal phone, hears a changing
four-digit challenge, navigates the personal menu, supplies the configured
synthetic ID, confirms its readback, and hears a configurable dollar amount.
They can explain each command, completion webhook, retry, and terminal transition.
Wrong answers must not reach the result. Outbound automation remains Lesson 3.

Lesson 1 is signed off, learner-reported on 2026-09-21, and merged through PR #33
at `896e742` on main. Its acceptance record does not contain independently
observed live artifacts; this design does not manufacture them. Reviewed the
complete `webhooks.py`, tests, manifest, README, environment example, guide, spec,
and plan. The baseline is 41 passing tests and passing Ruff checks, rerun in the
existing environment on 2026-09-21 (two previously documented deprecation warnings).

Use branch `codex/ivr-02-test-ivr` from merged main. Reuse the existing, clean IVR
worktree at `.worktrees/ivr-01-connectivity`, as the Lesson 1 plan directs; its
historical directory name is not the current lesson number. Do not create a
second IVR worktree or rename/delete the previous branch. The main checkout's
untracked `.pi/` remains untouched.

## Constraints

- Python 3.14; one independent uv environment and lockfile under `spikes/ivr/`.
- Reuse FastAPI, Uvicorn, cryptography, pytest, and httpx; no new library or SDK.
- One active fixture call, one worker, no reload, in-memory state only.
- Keep all three entry points and the two webhook paths; no public controls.
- No outbound dialing, transcription, client navigation, recording, or media streaming.
- No database, durable queue, cloud deployment, UI, or unrelated application changes.
- No subagents during planning, implementation, or review.
- Automated verification is offline; live acceptance is learner-operated and separately recorded.
- Do not purchase numbers, change account settings, or expose a tunnel during this work.
- Preserve unrelated local changes and existing Tailscale mappings.

The user supplied the scope and learning goal. Proposed defaults below (synthetic
ID, amount range, deadlines, voice, and retry behavior) are design choices for
review, not previously accepted requirements. Both documents are drafted together
for review as requested; neither constitutes approval to execute the plan.

## Approaches and decision

1. **Recommended: retain Call Control and use `gather_using_speak`.** Add a small
   fixture controller and a thin httpx command sender. The app owns logical
   attempts, and provider completion events drive progress. This teaches the
   requested events directly and retains Lesson 1's security boundary.
2. Separate `speak` and `gather` at every input step. This permits finer playback
   behavior but adds synchronization and more commands. Reserve separate `speak`
   for terminal messages, where waiting for completion matters.
3. Move the fixture to TeXML or a workflow engine. This could express a menu,
   but changes the lesson's command/webhook model and adds another architecture.

## Verified Telnyx contracts

Checked against official docs and their linked
[Call Control OpenAPI source](https://developers.telnyx.com/openapi/source/external/call-control/call-control.json)
on 2026-09-21. These are documentation checks, not account capability tests.

| Operation | HTTP contract | Completion used here |
| --- | --- | --- |
| [Answer](https://developers.telnyx.com/api-reference/call-commands/answer-call) | `POST https://api.telnyx.com/v2/calls/{call_control_id}/actions/answer` | `call.answered` |
| [Gather using speak](https://developers.telnyx.com/api-reference/call-commands/gather-using-speak) | Same prefix, `/gather_using_speak`; required `payload`, `voice` | `call.gather.ended`; individual `call.dtmf.received` events do not advance |
| [Speak](https://developers.telnyx.com/api-reference/call-commands/speak-text) | Same prefix, `/speak`; required `payload`, `voice` | `call.speak.ended` |
| [Hangup](https://developers.telnyx.com/api-reference/call-commands/hangup-call) | Same prefix, `/hangup` | `call.hangup` |

Commands use Bearer authorization and JSON. HTTP 200 with `data.result == "ok"`
acknowledges a command; it is not evidence the call answered or speech finished.
`command_id` deduplicates commands on the same `call_control_id`. Base64
`client_state` carries application correlation data. No webhook echo of
`command_id` is assumed. See the [command retry guidance](https://developers.telnyx.com/docs/voice/programmable-voice/command-retries).

Gather supports digit bounds, `maximum_tries`, `timeout_millis`,
`inter_digit_timeout_millis`, `valid_digits`, and `terminating_digit`.
The response wait starts after speech ends; interdigit timeout is separate.
An empty terminating digit allows `#` to be collected as data. Speech can be
interrupted by input. The application settings below deliberately override
provider defaults. [Gather contract](https://developers.telnyx.com/api-reference/call-commands/gather-using-speak).

Webhook envelopes contain `data.id`, `data.event_type`, `data.occurred_at`, and
`data.payload`. Relevant payload fields are `call_control_id`, `call_leg_id`,
`connection_id`, and `client_state`; initiated also has `direction` and `state`.
Admission requires `direction == "incoming"`. Session IDs group legs and are
not command targets. [Webhook fields](https://developers.telnyx.com/docs/voice/programmable-voice/voice-api-webhooks).

The OpenAPI `CallGatherEnded` schema defines string `digits` and statuses
`valid`, `invalid`, `timeout`, `call_hangup`, `cancelled`, `cancelled_amd`.
`CallSpeakEnded` defines `completed`, `call_hangup`, `cancelled_amd`.
`CallDtmfReceived` has singular `digit`, not `digits`.
[Gather callback](https://developers.telnyx.com/api-reference/callbacks/call-gather-ended),
[speech callback](https://developers.telnyx.com/api-reference/callbacks/call-speak-ended),
[DTMF callback](https://developers.telnyx.com/api-reference/callbacks/call-dtmf-received).

Change accepted webhook responses on both routes from empty **204 to empty 200**.
The [receiving guide](https://developers.telnyx.com/docs/voice/programmable-voice/receiving-webhooks)
and callback references specifically request 200, whereas the general webhook
page permits 2xx. Returning 200 satisfies both. Keep 400/401/413 validation
responses. Delivery can duplicate, overlap, or arrive out of order. Acknowledge
without waiting for outbound network requests. Verify actual delivery diagnostics
at live acceptance; do not reinterpret Lesson 1's historical record.

## Runtime and trust boundaries

Keep `webhooks:client_app` (8011), `webhooks:test_ivr_app` (8012), and
`webhooks:public_app` (8010). Combined ingress owns its own fixture runtime;
independent test-IVR owns a separate one when used instead. Never run both for
the same callback. The client route remains receipt-only and requires only the
public verification key. Public and test-IVR startup additionally require fixture
settings and a Telnyx API key. The API credential moves to Lesson 2 because
answer/speech/hangup are authenticated commands; outbound number/profile stays
in Lesson 3. Correct the prospective curriculum/README guidance accordingly.

`webhooks.py` retains byte-exact signature verification, ±300-second freshness,
64 KiB streaming bound, envelope validation, routes, and lifespan ownership.
Only after authentication may the fixture controller inspect relevant payloads.
Use `app.state.ivr`; no global cross-app session singleton. Add:

- `fixture.py`: settings, prompt formatting, small state machine, admission,
  deduplication, command reservations, tracked tasks, and watchdog.
- `telnyx_commands.py`: fixed-origin HTTP command submission with bounded retries.

Promote the already locked `httpx` from dev-only to runtime dependencies. Do not
add the Telnyx SDK or import todo-app code. Use a single `asyncio.Lock` for short
state mutations, never held across network awaits. Reserve state and a command
before scheduling its tracked async send task. Lifespan starts one watchdog,
cancels/drains tasks, and closes the httpx client on shutdown. No durable queue.

Only admit an initiated event with bounded nonempty call/leg IDs, configured
`connection_id`, incoming direction, and parseable UTC `occurred_at` at or after
process startup (also no more than 300 seconds in the future). This intentionally
ignores calls begun before a restart. All subsequent events must match the
stored call/leg/application IDs. Treat call-control IDs as opaque path segments:
URL-encode them, never accept an arbitrary command host or webhook-supplied URL.

Actionable call IDs are nonempty strings capped at 1024 characters; leg IDs,
connection IDs, and operation tokens are capped at 256. For a valid-status gather,
require a string digits field (at most 128 characters); absent digits on timeout
or invalid status mean empty input. Non-string digits are malformed.
Malformed actionable payloads get generic 400 before state mutation. Well-formed
unknown events, wrong-app/wrong-leg events, duplicates, and stale correlations
get 200 with no action. Unknown gather/speech statuses on the current operation
are protocol failures, never successful input. A missing/invalid operation token
cannot advance; the watchdog bounds the wait. `call.hangup` for an owned leg is
terminal regardless of token. An unknown hangup for the configured app creates
a tombstone so a reordered initiated event cannot reopen the call.

## Fixture settings and prompts

Environment is loaded at startup, never through a public scenario endpoint.
Snapshot settings per admitted call. Local `.env` remains ignored; validate
without printing raw values or secrets.

| Setting | Default / validation |
| --- | --- |
| `TELNYX_PUBLIC_KEY` | Existing required base64 Ed25519 key |
| `TELNYX_API_KEY` | Required nonempty secret for fixture runtimes only |
| `IVR_CONNECTION_ID` | Required nonempty fixture application ID, at most 256 chars |
| `IVR_SYNTHETIC_ID` | `000123456`; exactly nine ASCII digits; never a real identifier |
| `IVR_RESULT_AMOUNT` | `1425.30`; canonical ASCII `0` or nonzero-leading integer, exactly two decimals; `0.00`–`9999.99` |
| `IVR_GATHER_TIMEOUT_MS` | `20000`; integer 1000–60000 |
| `IVR_INTER_DIGIT_TIMEOUT_MS` | `5000`; integer 1000–gather timeout |
| `IVR_MAX_ATTEMPTS` | `2`; integer 1–3; counts initial attempt |
| `IVR_SPEECH_GRACE_SECONDS` | `30`; integer 10–60 |
| `IVR_CALL_TIMEOUT_SECONDS` | `300`; integer 60–600 |
| `IVR_VOICE` | `female`; allow `female` or `male` with basic service |
| `IVR_CHALLENGE_OVERRIDE` | Empty normally; optional exactly four ASCII digits for learner leading-zero exercise |

Use `payload_type="text"`, `service_level="basic"`, `language="en-US"` for
both gather and speech. Voice/account support and audible pronunciation remain
live acceptance checks. Generate the challenge once per call with
`f"{secrets.randbelow(10000):04d}"`; keep it as a string through comparison and
readback. Retries repeat the same challenge. Random draws can legitimately repeat
across calls; tests must not require uniqueness. The override is fixture-local
and never exposed to the later client.

Spell each challenge and ID digit through a ten-word lookup. Format the bounded
amount with `Decimal` and a small English integer formatter for 0–9999, with
correct singular dollar/cent. Reject negative, nonfinite, exponent, comma,
whitespace, overprecision, and out-of-range amounts; never round silently.
Default result is exactly: “Your requested value is one thousand four hundred
twenty-five dollars and thirty cents.” No general language/money library.

## State and input contract

Stages: `answering → welcome → challenge → menu → identifier → confirmation →
result → hanging_up → ended`. Rejections enter `failure → hanging_up → ended`.
`ended` is absorbing. A matching `call.answered` alone leaves `answering`; an
answer command's HTTP response does not. An early hangup can end any stage.

| Input stage | Spoken prompt | Accepted input | Next |
| --- | --- | --- | --- |
| welcome | “Welcome to the test IVR. Press 1 to continue.” | `1` | challenge |
| challenge | “Your verification code is {digit words}. Enter the code followed by pound.” | Exact challenge plus `#` | menu |
| menu | “Press 1 for personal. Press 2 for business.” | `1`; `2` is immediate unsupported-business failure | identifier |
| identifier | “Enter your nine-digit personal ID followed by pound.” | Exact synthetic ID plus `#` | confirmation |
| confirmation | “You entered {ID digit words}. Press 1 if correct.” | `1` only | result |

Gather construction is a fixture choice:

- Single-key stages: min=max=1, `valid_digits="0123456789*#"`.
- Challenge: min=max=5, `valid_digits="0123456789#"`.
- Identifier: min=max=10, `valid_digits="0123456789#"`.
- All use `terminating_digit=""`, `maximum_tries=1`, and configured timeouts.

Collect pound as data so four/nine digits alone cannot accidentally pass when a
provider gather finishes by timeout or digit limit. Compare the complete string
including its final `#`; do not strip all pound signs or coerce to integers.
This is a deliberate use of Telnyx's disabled-terminator mode, not an assumption
that a normal terminator appears in `digits`. Pin the behavior offline and verify
it on the first learner-operated call. No digit buffering from individual events.

Only a current-token `call.gather.ended` with `status="valid"` and exact matching
string advances. `invalid`, `timeout`, empty, short, long, misplaced pound,
non-ASCII, or incorrect strings consume an attempt. One retry by default:
prefix the same prompt with “That entry was not accepted. Please try again.”
On exhaustion say “We could not verify your entry. Goodbye.” Business selection
says “Business requests are not supported by this test IVR. Goodbye.” A rejected
confirmation retries confirmation, not the ID or challenge; it never yields a
result. Attempts reset to one on entering a new input stage.

`call_hangup` completes local cleanup without further speech. `cancelled` or
`cancelled_amd` on the current gather is a provider failure: attempt one failure
speech, then hangup. A terminal `call.speak.ended` with current token and
`status="completed"` triggers normal hangup. Other speech statuses never count
as successful result delivery; `call_hangup` cleans up, others trigger hangup.
Do not hang up on `call.speak.started`, a stale completion, or HTTP 200 alone.

## Idempotency and ordering, before live call control

Use `data.id` deduplication for every actionable event during an active call.
Also gate by stage and operation token: a repeated completion with a new event ID
must not spend another attempt. Each logical answer, gather attempt, terminal
speech, and hangup gets one UUID4 `command_id`, allocated and retained before I/O.
Transport retries reuse the same ID and serialized body; a new caller attempt
gets a new UUID. Store the pending operation's token, stage, attempt, and expected
completion type before sending. Encode only a random operation UUID as base64
`client_state`; keep challenge/ID/amount out of it.

For advancement require exact `client_state` equality with the locally reserved
operation, expected type, and matching call/leg/app. Do not trust decoded state
as instructions. This uses documented state pass-through; its behavior on actual
gather and terminal speech callbacks is a live contract checkpoint. Never fall
back to “any completion belongs to the current stage” if the token is missing.

A completion may arrive before the HTTP command response. Its transition wins;
a late transport success/failure may mutate state only if its operation is still
current. A pending send checks current ownership before each attempt. Hangup or
termination cancels obsolete sends; a request already on the wire cannot be
recalled, but its late reply cannot reopen state. Concurrent duplicate initiated
events reserve at most one answer. Unknown events do not acquire control.

Cap active-call seen event IDs at 4096; exhaustion terminates via the failure
path rather than evicting deduplication evidence. Keep terminal tombstones for
the process lifetime, stripping challenge, ID,
amount, and event sets on release. Cap distinct tracked call identities at 1000
per process; at capacity stop admitting/controlling unfamiliar calls and log
`capacity_reached`, requiring learner shutdown/restart after ending calls.
Do not evict old identities and silently reopen them. Add a `ponytail:` comment
for this POC ceiling and for the single lock. Restart loses state; it is not
durable idempotency, and the startup admission cutoff is not recovery.

A second incoming call while one is active gets one idempotent hangup without
answer or speech, leaves the first untouched, and becomes a tombstone. This is
the explicit busy exception to spoken rejection: do not answer a second paid leg
just to announce busy. No queue or second menu session.

## Bounded network behavior and cleanup

The sender allows only answer, gather_using_speak, speak, and hangup to the fixed
Telnyx origin, with redirects disabled. Per HTTP attempt use a five-second total
`asyncio.timeout`, in addition to httpx timeouts. At most two submissions, one
second apart, on transport timeout/error, HTTP 429, or 5xx. Honor a nonnegative numeric
Retry-After only if it fits within the same one-second retry budget; otherwise
stop retrying and report failure. Do not retry other 4xx, redirects, or malformed
success bodies. This conservative local policy differs from Telnyx's suggested
500 ms latency retry and makes no extra delivery guarantee.

On rejected/uncertain answer, gather, or result command, stop navigation and
attempt “The test service is unavailable. Goodbye.” only if answer was observed.
The failure-speech command has the same bounded transport policy; if it fails,
go directly to one logical hangup. Never recursively speak an error about an
error. If hangup fails or its callback is missing, release local ownership after
the cleanup deadline with `hangup_unconfirmed`; tell the learner to end the call
on their handset. Local cleanup does not prove remote termination.

Use monotonic deadlines, checked by a lifespan-owned watchdog every ≤1 second:

| Wait | Deadline from operation reservation |
| --- | --- |
| Answer completion | 20 seconds |
| Gather completion | gather timeout + speech grace (50 seconds by default) |
| Result or failure speech completion | speech grace (30 seconds by default) |
| Hangup confirmation | 15 seconds |
| Entire navigation, including retries | call timeout (300 seconds from admission) |

Provider timeouts enforce ordinary no-input retries. A missing gather webhook
at the local deadline is a transport/protocol failure: terminate, do not launch
a new overlapping gather. The overall deadline goes directly to hangup, including
if terminal speech is still pending. Thus cleanup can extend at most 15 seconds
plus one watchdog tick beyond the navigation bound. Ordinary input rejection
gets spoken failure; network failure, deadline enforcement, and remote hangup
cannot promise audible speech.

On graceful shutdown stop admission, best-effort hang up the active call within
the 15-second cleanup budget, cancel/drain pending tasks and watchdog, clear
sensitive state, close HTTP transport. An abrupt crash cannot perform this;
the walkthrough requires handset termination before restart.

Logs retain Lesson 1's safe envelope fields and add local run ID, stage, attempt,
action, elapsed time, and bounded reason codes. Do not log call-control tokens,
headers, URLs containing tokens, prompts, gathered digits, ID, challenge, amount,
raw provider errors, or request/response bodies. Disable httpx/httpcore request
logging and continue `--no-access-log`. Record sanitized evidence manually.

## Verification and learner acceptance

Offline tests use synthetic signatures, fixed clock/UUID/random inputs, and
`httpx.MockTransport`; never a real API key, socket, tunnel, or call. Cover valid
progression, `0742`, `0000`, all validation/retry paths, exact command contracts,
duplicate/out-of-order callbacks, uncertain sends, token mismatches, busy calls,
watchdog deadlines, shutdown, route isolation, and privacy. Preserve Lesson 1's
security tests, updating only intentional startup/status/payload changes.

The implementation will create `lessons/02-test-ivr.md`, not an empty guide now.
Walkthrough checkpoints, in order:

1. Explain command acceptance versus completion and individual digits versus
   finished gathers; inspect the state table and run offline checks.
2. Configure the fixture API credential locally and review existing destination,
   application ID, callbacks, and public key. Reuse Lesson 1 resources. Stop for
   learner action if configuration needs changes; no purchases or agent changes.
3. Learner starts the combined ingress and re-establishes only the previously
   agreed tunnel after inspecting routes with Lesson 1's instructions. No tunnel
   is opened by writing or testing this plan. Probe authentication and private paths.
4. Manual happy-path call: `1`, heard challenge plus `#`, `1`, synthetic ID plus
   `#`, check spoken readback, `1`. Hear entire amount before disconnect.
5. New call, two incorrect challenge entries: hear one retry then failure;
   no menu/result. Separate no-input call proves timeout retry and disconnect.
6. Change amount to `27.05`, restart only after ending calls, repeat successfully.
   Set override `0742`, repeat leading-zero entry/readback, then remove override.
7. Try business selection, wrong ID, and rejected confirmation on separate calls;
   each must be bounded and must not speak a result. Hang up mid-flow and confirm
   a subsequent call is admitted. Run a two-phone busy drill if available;
   otherwise retain its offline result and explicitly record live busy as not run.
8. End calls, stop ingress/exposure using Lesson 1's scoped cleanup, and record
   evidence separately from learner sign-off. Pause here; do not start Lesson 3.

| Evidence category | Required evidence | Status now |
| --- | --- | --- |
| Existing baseline | 41 Lesson 1 tests and Ruff | Passed 2026-09-21 |
| Lesson 2 offline | Tests and checks named in implementation plan | Not run |
| Live protocol | Commands accepted; expected gather status/digits shape and token echo; HTTP 200 deliveries | Not run |
| Live success | Full amount heard, final speech completes before hangup | Not run |
| Live rejection | Wrong challenge twice, no input, business, wrong ID, confirmation rejection | Not run |
| Live variation | `27.05` heard; `0742` preserved | Not run |
| Live cleanup | Early hangup/new call, scoped tunnel cleanup | Not run |
| Learner acceptance | Explicit dated sign-off after checkpoints | Pending |

Record observed time, scenario, expected/actual speech, sanitized event/command
correlations, attempt counts, hangup outcome, diagnostics, and corrective reruns.
Never infer live success from mocks. Five-call reliability campaigns, automated
caller value/error output, persistence, and scenario automation stay in later lessons.
