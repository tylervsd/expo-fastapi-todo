# IVR automation spike: lesson plan

## Status and outcome

Curriculum started September 20, 2026. Lessons 1 and 2 are accepted. Lesson 2 was signed off by the learner on
2026-09-21 after successful live calls. This is a separate learning track from
the numbered fullstack curriculum. Each lesson will get a concrete implementation
plan and walkthrough when we work through it.

Build two independently runnable Python applications in `spikes/ivr/`:

1. **Flow client:** call a real number, listen to prompts, replay a spoken
   numeric challenge using DTMF, navigate menus, and print a value or an error.
2. **Test IVR:** answer a real call, present those prompts, validate the caller's
   input, and speak a configurable result. A person can also call it manually.

Both run on the Mac. Telnyx supplies telephony, speech synthesis, and initial
speech recognition. Public HTTPS webhooks reach the local applications through
Tailscale Funnel. Self-contained means we control both applications; live testing
still requires Telnyx service, real phone numbers, network access, and usage charges.

## Scope and boundaries

- Plan for two voice-capable Telnyx numbers: a destination assigned to the test
  IVR and an outbound caller ID for the client. Confirm account permissions,
  outbound routing, and number configuration during setup; reuse suitable owned
  numbers where available. The destination is needed in Lesson 1; the outbound
  number and profile wait until Lesson 3.
- Use separate Telnyx Voice API applications and webhook routes for the two roles.
- Keep one independent Python environment and lockfile for the spike. Start with
  the repo's Python version if supported by the selected dependencies; verify
  compatibility before pinning versions.
- Use FastAPI, Uvicorn, and a small Telnyx integration. Reuse familiar tooling,
  without importing the todo application's business logic or database.
- One automated call at a time, one worker per local application, in-memory state.
  Restarting a process loses its active session; recovery is outside the POC.
- No UI, database, cloud deployment, queues, caller-ID pool, LLM-based navigation,
  or custom audio streaming in the initial lessons.
- The client may know the menu protocol and a synthetic personal ID. It must
  learn the challenge and returned value only through call transcription.
  It cannot import the test IVR's state, scenario settings, or expected result.
- Use synthetic identifiers. Keep secrets out of Git and omit identifiers,
  credentials, and full transcripts from default logs.
- Expose webhook routes only through the public tunnel. Keep call-start and
  scenario controls local. Verify webhook signatures and timestamp freshness
  before accepting public events.

## Running example

| Step | Test IVR says | Caller sends |
| --- | --- | --- |
| Welcome | “Press 1 to continue.” | `1` |
| Challenge | “Your verification code is zero seven four two. Enter the code followed by pound.” | `0742#` |
| Menu | “Press 1 for personal. Press 2 for business.” | `1` |
| Identifier | “Enter your nine-digit personal ID followed by pound.” | Synthetic nine-digit ID plus `#` |
| Confirmation | “You entered … Press 1 if correct.” | `1` after checking the readback |
| Result | “Your requested value is one thousand four hundred twenty-five dollars and thirty cents.” | Nothing; extract `1425.30` |

The code changes per call and remains a string to preserve leading zeros.
The fixture accepts only its configured synthetic ID. Unsupported business-menu
selection, invalid input, or exhausted attempts produces a spoken failure and
hangup. The final result is configurable so the client cannot pass by hardcoding it.

Proposed terminal outputs:

```json
{"status":"success","value":"1425.30","currency":"USD"}
```

```json
{"status":"error","code":"challenge_unrecognized","stage":"challenge"}
```

Money is parsed with decimal arithmetic and serialized as a decimal string.
Diagnostics go to stderr; stdout contains one terminal JSON result. Success exits
with code 0; errors exit nonzero. Missing or ambiguous speech never becomes a
guessed value or a success with zero.

## How each lesson works

Each walkthrough contains prerequisites, the concept being taught, small build
steps, exact run commands, expected output, a troubleshooting exercise, and a
checkpoint. Use a focused offline regression check for each meaningful behavior,
then perform the relevant live exercise. Offline checks never place paid calls.

Record automated checks, observed live results, and learner acceptance separately.
Stop at lesson checkpoints so the learner can run and understand the result before
continuing. Add lesson guides under `spikes/ivr/lessons/` as they are implemented;
do not create empty guides in advance.

## Lesson 1 — Local applications and real webhook connectivity

**Planning:** [Spec](superpowers/specs/2026-09-20-ivr-01-connectivity-design.md) and
[implementation plan](superpowers/plans/2026-09-20-ivr-01-connectivity.md).
Local implementation is verified; the learner reported completion and signed off
on 2026-09-21. Detailed live artifacts were not supplied; see the acceptance record.

**Walkthrough:** [Lesson 1 connectivity](../spikes/ivr/lessons/01-connectivity.md).

**Learn:** distinguish the calling client from the answering IVR, and distinguish
an API command from the later webhook describing its outcome.

**Build:** the spike environment, two minimal FastAPI entry points, health checks,
ignored local settings, and a documented public route to each webhook. Use one
webhook-only ingress with two role routers to share one Funnel hostname, while
retaining independent application entry points. Follow the walkthrough to inspect
existing routing before enabling the tunnel.

- [x] Configure the two Telnyx applications, one destination number, public
  verification key, and callback URLs. Add the fixture API credential in Lesson 2 and the outbound caller ID/profile
  in Lesson 3; Lesson 1 only receives events.
- [x] Validate incoming signatures against the original request body and reject
  invalid or stale requests. Confirm that local controls are not public.
- [x] Call the destination manually and observe a verified incoming-call event.
- [x] End the test call and confirm both event handling and cleanup.

**Checkpoint:** both apps run locally; a real Telnyx event reaches the intended
handler; a forged request is rejected. No full IVR flow is required yet.

**Exercise:** use a wrong webhook path, diagnose the missing event, and restore it.

## Lesson 2 — A test IVR you can navigate by hand

**Planning:** [Spec](superpowers/specs/2026-09-21-ivr-02-test-ivr-design.md) and
[implementation plan](superpowers/plans/2026-09-21-ivr-02-test-ivr.md).
**Walkthrough:** [Lesson 2 test IVR](../spikes/ivr/lessons/02-test-ivr.md).
Local implementation is verified; the learner signed off on 2026-09-21.
Intermittent webhook delivery failures remain an open observation for subsequent
lessons; see the walkthrough acceptance record.
The fixture API credential is required now for answer/speech/hangup. Minimum
command idempotency, replay guards, and cleanup deadlines are included before
live control; Lesson 5 still owns the broader reliability campaign.

**Learn:** answering, speaking, gathering DTMF, explicit state transitions, and
distinguishing individual digit events from a completed gather.

**Build:** the full running example in the test IVR, using speech plus digit
collection. Generate a four-digit challenge per call, validate each answer, and
speak the configured amount. Advance once per completed gather, rather than once
for every digit event. Wait for final speech completion before normal hangup.

- [x] Add a focused offline check for valid progression, wrong challenge, and
  leading-zero preservation.
- [x] Implement the welcome, challenge, personal menu, ID, confirmation, and result.
- [x] Bound input waits and retries: initially 20 seconds per gather and at most
  two attempts per input step; make these fixture settings easy to tune.
- [x] Provide explicit spoken rejection and cleanup on failure.
- [ ] Complete the flow from a personal phone, then try an incorrect challenge.

**Checkpoint:** a person can obtain the configured spoken result through a real
call; an incorrect code cannot reach the result.

**Exercise:** change the amount and verify that the new amount is actually spoken.

## Lesson 3 — An automated caller that hears and responds

**Planning:** [Spec](superpowers/specs/2026-09-21-ivr-03-automated-caller-design.md) and
[implementation plan](superpowers/plans/2026-09-21-ivr-03-automated-caller.md).
**Walkthrough:** [Lesson 3 automated caller](../spikes/ivr/lessons/03-automated-caller.md).
Local implementation is verified (358 tests, Ruff check and format clean,
2026-09-21); live verification and learner acceptance remain pending.
Reuse the existing IVR worktree on `codex/ivr-03-automated-caller`.

**Learn:** outbound dialing, call-leg identification, transcription lifecycle,
partial versus final transcripts, and synchronizing input to recognizable prompts.

**Build:** a local client command that calls only the configured test number,
starts transcription of the remote side, and navigates through confirmation.
Track client and fixture legs separately; never treat their webhook IDs as
interchangeable.

- [x] Check numeric parsing offline with digit words, formatted digits, leading
  zeros, and incomplete or ambiguous challenges.
- [x] Buffer relevant final transcription segments by stage; do not assume an
  entire prompt arrives in one event or act on unstable partial text.
- [x] Send the exact challenge plus `#` only once the complete challenge and
  entry prompt are recognized. Navigate by prompts, not fixed sleeps.
- [x] Enter the configured synthetic ID and verify its spoken readback before
  confirming. Reject mismatches.
- [x] Add a stage deadline and an overall call deadline, initially 30 seconds
  and 180 seconds. Keep tone duration and timing configurable for real-call tuning.
- [ ] Run against the fixture and inspect its received digits as test evidence.

**Checkpoint:** the client reaches the result stage on a real call using a code
it learned only from speech. Repeat with a different challenge.

**Exercise:** force a leading-zero challenge in the fixture and verify exact replay.

## Lesson 4 — A value-or-error contract

**Learn:** separate recognizing a result from successfully completing transport;
distinguish failure to understand speech from a provider or call failure.

**Build:** deterministic extraction for the fixture's documented dollar-and-cent
phrasing and numeric transcript equivalents, plus the terminal output contract.
No general English-number framework or LLM is required for this narrow grammar.

- [ ] Check `1425.30`, zero, and a changed amount offline; reject missing amounts,
  unsupported wording, and conflicting amounts in the result prompt.
- [ ] Print a success only after a complete, unambiguous result is recognized.
- [ ] Return explicit errors for unrecognized challenge, unexpected menu,
  ID mismatch, fixture rejection, unrecognized result, timeout, early hangup,
  and provider failure.
- [ ] Account for a final transcript arriving after the hangup event: allow a
  bounded finalization window, initially five seconds, within the overall deadline.
  Preserve an already completed result when late terminal events arrive.
- [ ] Emit a concise trace with local run ID, call IDs, state transitions, and
  elapsed times. Make sanitized transcription diagnostics an explicit debug option.
- [ ] Verify stdout, stderr, and exit status for one live success and one failure.

**Checkpoint:** running the client produces exactly one structured value or error
and terminates. Changing the fixture's amount changes the client's output.

**Exercise:** use an unsupported result phrase and verify an error rather than a guess.

## Lesson 5 — Repeatable end-to-end tests and failure drills

**Learn:** webhook retries, duplicate commands, late events, and the limits of a
local process with in-memory state.

**Build:** a small offline event-replay check and fixture scenarios selected locally
before a call: normal, leading-zero code, rejected ID, silent stage, unsupported
result, and early hangup. The client has no access to scenario expectations.

- [ ] Serialize state changes per call and deduplicate webhook event IDs for the
  call's lifetime. Use stable command IDs for the same logical action; a deliberate
  new attempt gets its own ID.
- [ ] Replay duplicate and late events offline: no repeated DTMF, invalid state
  advancement, second terminal output, or reopening of a completed call.
- [ ] Handle an uncertain command response without blindly issuing a new command.
  Verify the provider's current retry and command-ID semantics during implementation.
- [ ] Enforce the one-active-call limit locally; reject a second start rather than
  queueing it. Ensure deadlines attempt hangup and release local state.
- [ ] Run five normal live calls with changing challenges and at least two amounts,
  plus the leading-zero case and each failure scenario. Record every attempt,
  including failures; separate offline event-order tests from live-call evidence.
- [ ] Document stop/restart cleanup and manual termination of a call if the local
  process or network fails. In-memory deduplication does not survive a restart.

**Checkpoint:** all five normal calls return the correct amount, the leading-zero
case succeeds, deliberate failures return the expected error, and offline replay
does not produce duplicate actions. If the live target is missed, diagnose and
repeat the affected exercise; do not label the spike reliable from offline tests alone.

**Exercise:** delay a final transcript and replay a completed event. Explain why
one may still contribute to finalization while the other cannot restart navigation.

## Completion record

Fill this in while doing the lessons. A small live sample demonstrates the POC;
it is not a production reliability estimate.

| Lesson | Offline checks | Live evidence | Learner acceptance |
| --- | --- | --- | --- |
| 1. Connectivity | 41 tests, Ruff, loopback smoke checks passed | Completion reported by learner | Signed off 2026-09-21 |
| 2. Test IVR | 168 tests and Ruff passed | Successful calls reported; intermittent delivery failures observed | Signed off 2026-09-21 |
| 3. Automated caller | 358 tests and Ruff passed | Not run | Pending |
| 4. Value or error | Not run | Not run | Pending |
| 5. Reliability drills | Not run | Not run | Pending |

The two final deliverables are the independently runnable flow client and test
IVR, with reproducible setup, lesson guides, offline checks, and recorded live
acceptance. A later lesson may deploy them to Google Cloud after this local
checkpoint; durable state and multi-instance behavior need their own design then.

## References

- [Existing isolated spike](../spikes/assistant-ui-ag-ui/README.md): repository precedent.
- [Telnyx gather using speak](https://developers.telnyx.com/api-reference/call-commands/gather-using-speak): speech and DTMF collection for the fixture.
- [Telnyx transcription start](https://developers.telnyx.com/api-reference/call-commands/transcription-start): client speech recognition.
- [Telnyx send DTMF](https://developers.telnyx.com/api-reference/call-commands/send-dtmf): client touchtones and command identifiers.
- [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel): public HTTPS access to local webhook handlers.

Provider documentation checked September 20, 2026. Confirm exact event payloads,
SDK support, account capabilities, and selected speech engine when implementing
each lesson; the curriculum does not promise an untested SDK or account setup.
