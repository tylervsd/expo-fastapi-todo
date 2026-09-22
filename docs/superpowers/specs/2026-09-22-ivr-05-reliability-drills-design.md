# IVR Lesson 5: repeatable calls and failure drills

**Date:** 2026-09-22. **Status:** Implemented and verified offline: 452 tests and Ruff lint/format passed; Markdown lint passed. Two existing upstream warnings remain. [Walkthrough](../../../spikes/ivr/lessons/05-reliability-drills.md). Learner sign-off received 2026-09-22, with push/merge authorized; detailed live-call evidence not supplied. No subagents, deployment, or paid calls.

**Plan:** [Implementation plan](../plans/2026-09-22-ivr-05-reliability-drills.md).

## Intent and checkpoint

Complete the existing Lesson 5 curriculum after accepted Lesson 4: demonstrate that duplicate delivery, delayed events, ambiguous provider responses, and deliberate fixture failures do not cause duplicate actions, incorrect results, or unbounded calls. Preserve the speech-only client boundary and Lesson 4 value-or-error contract.

The learner's eventual target of 20 concurrent calls and 5,000 calls/day informs the importance of these checks, but this lesson remains one active automated call per process. Passing a small live sample is functional evidence, not a production reliability or capacity estimate.

## Approach and alternatives

Extend existing state machines and pytest checks, adding one fixture-only scenario setting and a small test-only event replay helper. Locks, bounded event-ID sets, command reservations, terminal snapshots, and cloud start admission already exist; retain them and fix only demonstrated gaps.

Documentation-only drills would leave failures difficult to reproduce. A general simulation framework or durable job system would expand the lesson beyond its teaching purpose. Neither is needed here.

## Workspace and baseline

Reuse `/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity` on `codex/ivr-05-reliability-drills`, based on merged main `80dc76e`. Preserve previous lesson branches, ignored environment files, and the main checkout's unrelated `.pi/` directory. Keep planning commits on this branch until the learner checkpoint.

Baseline on 2026-09-22: 422 tests passed, Ruff lint and formatting passed; two existing upstream deprecation warnings. Cloud release `bde9fdf` is the previously recorded Lesson 4 deployment; this plan does not change it.

## Constraints

- Python 3.14; reuse the existing uv environment, lockfile, pytest, and httpx. No new dependencies.
- One worker and one automated call per process; no queue, database, scheduler, batch dialer, distributed lock, or automatic redial.
- Keep existing signed webhook verification, timestamp checks, event/leg ownership, bounded buffers, and safe logging.
- Client runtime must not import fixture code or consume fixture scenario names, expected amounts, or expected outcomes.
- Keep stdout to exactly one terminal JSON object, diagnostics on stderr, success exit 0, and errors nonzero. Preserve cloud `status`, `result`, `busy`, and `restart_required` semantics.
- Offline tests never contact Telnyx, start a real call, or change cloud configuration.
- Implementation, deployment, live attempts, and learner acceptance are separate records. Future cloud deployment and paid drills need explicit authorization for that work; prior Lesson 4 authorization does not initiate Lesson 5 calls.

## Fixture scenarios

Add `Settings.scenario: str = "normal"`, loaded through the existing `IVR_` mapping as `IVR_SCENARIO`. Validate the exact allowlist below at startup using the existing generic configuration error. The setting is fixed for the fixture process lifetime, selected locally before a call, and never exposed as an HTTP control. The client environment loader continues to ignore fixture settings.

| Scenario | Fixture behavior | Expected caller result after reaching the drill |
| --- | --- | --- |
| `normal` | Existing flow, random four-digit challenge, configured amount | Success with the spoken configured amount |
| `leading_zero` | Existing flow with challenge `0742` | Success; sent challenge preserves its leading zero |
| `rejected_id` | After otherwise valid identifier entry, speak the existing rejection phrase and hang up, without confirmation/result | `fixture_rejection`, stage `confirmation` |
| `silent_stage` | After valid welcome input, send no challenge prompt and wait for remote hangup or the existing fixture overall deadline | `stage_timeout`, stage `challenge` |
| `unsupported_result` | At result, speak “Your requested value is unavailable.” and finish normally | `result_unrecognized`, stage `result` |
| `early_hangup` | After valid welcome input, hang up before speaking the challenge | `early_hangup`, stage `challenge` |

`normal` retains `IVR_CHALLENGE_OVERRIDE` for prior lesson exercises. For `leading_zero`, allow an empty override or `0742`; reject any conflicting nonempty override rather than silently ignoring it. Other scenarios retain the normal challenge selection. Offline explicit challenge injection remains available to tests; dedicated leading-zero tests exercise scenario selection without injection.

Implement scenarios with small branches in `Flow`, not subclasses or a scenario engine. Reject an ID immediately once the correct identifier gather completes; do not require changing the client ID or waiting for fixture input retries. Preserve `max_attempts` behavior for genuinely invalid input.

The silent stage is explicit: `stage="silent"`, `pending=None`, and its deadline equals `call_deadline`. `handle` must still process matching hangup and expiry before ignoring other events with no pending command. `expire` attempts hangup at the existing overall deadline. `command_failed` and close must tolerate no pending command. No speech, gather, or retry is emitted while silent. Live instructions use client stage timeout 30 seconds and fixture call timeout 300 seconds, so the intended client timeout comes first.

## Delivery and command invariants

1. State changes and command reservations remain serialized under existing short-held controller locks. Never hold these locks across provider I/O.
2. Duplicate IDs during an active call cannot reserve another action. Late events with a fresh ID are separately tested: obsolete stage tokens and terminal events cannot move the flow backward or reopen it.
3. Preserve bounded storage: at event capacity fail closed rather than evicting IDs and replaying old actions. Fixture tombstones protect completed calls during the process lifetime; restarting loses them. Do not claim protection across processes or restarts.
4. Transport retries reuse the exact immutable `Command` body, ID, and client state. A deliberate new gather attempt has a new command ID. Exhausted ambiguous responses fail with bounded cleanup; they never create a replacement DTMF command.
5. Outbound dial remains one request. An uncertain dial can still correlate a late initiation event for cleanup, but must not redial or resume navigation as if success were certain.
6. A next-stage event may arrive before an earlier HTTP response. Its obsolete failure must not overwrite newer state. Cancellation and cleanup cannot change a decided terminal result.
7. Final transcription after hangup may contribute only within Lesson 4's five-second window capped by the overall deadline. Replaying a completion cannot extend that window or publish a second result.
8. Concurrent cloud starts yield one dial and one `busy`; after completion, start returns `restart_required`. Status/result queries never dial. This is per-process admission, not a machine-wide concurrency limit.

## Provider contract evidence

Checked on 2026-09-22: the [Telnyx Send DTMF reference](https://developers.telnyx.com/api-reference/call-commands/send-dtmf) documents command deduplication for the same command ID and call-control ID, and lists no completion webhook for this command. Do not invent a DTMF acknowledgement event or interpret HTTP acceptance as proof of remote IVR consumption.

The existing transport makes at most two action requests using identical bytes, with five-second request bounds and a one-second retry delay; dial is not retried. Preserve those bounds unless the implementation's review of official action-specific documentation demonstrates a mismatch. Review [webhook fundamentals](https://developers.telnyx.com/docs/development/api-fundamentals/webhooks/receiving-webhooks) and the Voice API command-retry documentation before implementation, recording exact supported semantics and any undocumented retention limit. Do not depend on a particular number of webhook retries or infer permanent exactly-once delivery.

## Offline evidence

Use existing fixture/client harnesses and injected clocks. Add a small ordered sequence helper inside tests only if it removes repetition. Replay selected meaningful orderings rather than all permutations. Record commands and result snapshots; assert observable behavior rather than implementation shape.

Cover normal/changed amount/leading zero, each failure scenario, duplicate IDs, fresh-ID stale events, late final transcript inside/outside the window, concurrent delivery, ambiguous action response, uncertain dial with late identity, obsolete command failure, event capacity, and cleanup without hangup acknowledgement. Existing tests that already prove an invariant count; do not duplicate them solely to increase the test total.

Retain signed-webhook tests and local/cloud output tests. Replay does not simulate speech-recognition quality, telephony delivery, or real provider deduplication; those remain separate live observations.

## Walkthrough and live acceptance

Create `spikes/ivr/lessons/05-reliability-drills.md` during implementation, with commands for offline replay, local scenario selection, the existing SSH-only cloud path, and a per-attempt table. Do not create a live batch dialer.

After separately authorized deployment/calls, run five normal calls with changing challenges and at least two amounts (`1425.30` and `17.42`), one leading-zero call, and one of each four failure scenarios: ten planned calls. Record every unsuccessful attempt as well as any rerun. An earlier transcription failure does not count as reaching the intended drill. Diagnose and repeat that exercise without hiding the failed attempt or weakening grammar.

For every attempt record UTC time, release, scenario, safe run ID, expected/actual terminal JSON, exit status, elapsed time, observed failure stage, cleanup confirmation, and diagnosis. Preserve privacy rules; do not commit raw transcripts, control tokens, phone numbers, or identifier/challenge digits. A leading-zero check can record “leading zero preserved” without publishing the challenge trace. Mark rows `Not run` until evidence exists, and learner acceptance `Pending` until sign-off.

Explain graceful stop versus abrupt termination: the process attempts bounded hangup during graceful cleanup; a crash/network outage cannot guarantee it. Before restart, inspect and terminate any remaining call legs using authenticated provider controls, then confirm they ended. Restart does not recover the old result or deduplication set. Cloud result should be retrieved before restart. Restore `IVR_SCENARIO=normal`, amount `1425.30`, and clear challenge overrides after drills; verify the restarted service is idle and does not dial.

## Acceptance and review

Implementation is ready for learner review when offline checks pass, scenario selection is fixture-only, the walkthrough is reproducible, and recovery limits are explicit. Lesson completion additionally requires the recorded live matrix and learner sign-off; do not merge or begin scaling work merely because offline checks pass.

Direct author self-review mapped scenario branches, no-pending-command handling, retry identity, temporal boundaries, and checkpoint evidence to the implementation tasks. No independent review is claimed; the user's no-subagent instruction remains in force.
