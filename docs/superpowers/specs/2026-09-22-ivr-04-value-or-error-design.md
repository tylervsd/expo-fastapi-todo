# IVR Lesson 4: a value-or-error contract

**Date:** 2026-09-22. **Status:** Implemented and verified offline: 422 tests passed; Ruff check and formatting passed, with two existing upstream deprecation warnings. Live verification and learner acceptance remain pending. Implementation and final author review used no subagents, as explicitly requested. No deployment or paid calls were performed.

**Walkthrough:** [Lesson 4](../../../spikes/ivr/lessons/04-value-or-error.md).

**Related:** [Curriculum](../../ivr-learning-plan.md), [implementation plan](../plans/2026-09-22-ivr-04-value-or-error.md), [Lesson 3 walkthrough](../../../spikes/ivr/lessons/03-automated-caller.md).

## Intent and checkpoint

Turn the existing automated caller into a program that returns exactly one structured value or error and terminates. The learner should distinguish understanding an amount from transport completion, and speech failures from provider failures. Changing the fixture amount must change the client's output; the client learns the amount only from final transcripts.

Success examples are `1425.30`, `0.00`, and a second configured amount. Unsupported or conflicting speech must never become a guessed amount. This lesson finishes with separate offline evidence, observed live stdout/stderr/exit status, and explicit learner acceptance. Lesson 5 retains the repeated-call reliability campaign.

## Baseline and workspace

Lessons 1–3 are accepted. Main `dc9ebc3` includes Lesson 3 via PR #35 and the cloud diagnostic extension. Historical planning documents contain superseded descriptions: the running client uses Telnyx/inbound dial-time transcription, and already waits five seconds for a result transcript after hangup.

Reuse `/Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity` on `codex/ivr-04-value-or-error`, created from merged main `dc9ebc3`. The old directory name is intentional. Preserve the Lesson 3 branch, ignored environment/settings, main checkout, and unrelated `.pi/`. No new worktree, reset, stash, push, merge, or cloud changes during planning.

Planning baseline: 369 tests passed; Ruff check and format passed; two existing upstream deprecation warnings. Used the worktree's existing environment without installing dependencies.

## Global constraints

- Python 3.14; reuse the independent uv environment and lockfile in `spikes/ivr/`.
- No new dependencies; use stdlib Decimal, re, json, hashlib, and existing pytest tooling.
- One call per run, one worker, in-memory state; preserve current local and cloud entry points.
- Client runtime code must not import fixture code or read fixture amounts, scenario settings, or expected results.
- Keep signed webhooks, timestamp checks, role/leg ownership, bounded buffers, command IDs, and local-only initiation intact.
- Preserve Telnyx/inbound transcription and configurable DTMF timing; no provider API or infrastructure changes.
- Default and debug logs exclude credentials, phone numbers, synthetic IDs, challenge values, raw transcripts, and call-control tokens.
- Automated checks are offline; paid calls, deployment, and learner acceptance are separate, explicitly recorded activities.

## Approach and alternatives

Extend `speech.py`, `ClientFlow`/`Caller`, and the two existing command entry points. Reuse their event admission and lifecycle machinery. A strict, small grammar covers the fixture's output; a shared result snapshot keeps local/cloud behavior aligned.

A general English-number library or LLM would accept more speech but adds dependencies and ambiguity outside this lesson. Requiring only decimal digits would be smaller but fails the fixture's documented spoken output. A separate result service or new runner would duplicate existing ownership and cleanup. None is needed.

## Amount grammar

`parse_amount(text: str) -> str` in `speech.py` accepts exactly one complete result announcement, anchored by “Your requested value is”. It returns a two-place decimal string, or raises `ValueError("result_unrecognized")`. Case, whitespace, terminal sentence punctuation, and hyphens between number words are normalized. A sentence boundary after “dollar(s)” before “and” may separate final transcript fragments; preserve the incomplete dollar fragment until cents arrive. Do not strip arbitrary words, signs, or decimal punctuation.

Supported body forms:

| Form | Example | Value |
| --- | --- | --- |
| Fixture words | one thousand four hundred twenty-five dollars and thirty cents | `1425.30` |
| Digit components | 1425 dollars and 30 cents | `1425.30` |
| Mixed components | one dollar and 5 cents | `1.05` |
| Decimal with currency | $1,425.30 or 1425.30 dollars | `1425.30` |
| Bare decimal in the anchored announcement | 1425.30 | `1425.30` |

Whole-dollar components range from 0 through 9999; cents from 0 through 99. Singular/plural dollar and cent tokens are accepted. Decimal forms require exactly two fractional digits; commas, if present, must be correctly grouped. No negative amounts, exponent notation, NaN, infinity, rounding, alternative currencies, digit-word fractions, “point”, “oh”, or “and” inside an integer. Whole dollars without the explicit cents clause are incomplete, not an implicit `.00`. `0.00` must be distinguishable from no value.

The integer grammar is zero through nineteen, tens optionally followed by one through nine, one through nine hundred optionally followed by a nonzero sub-hundred part, and one through nine thousand optionally followed by a nonzero sub-thousand part. Reject reordered/repeated scales and noncanonical zero tails. This mirrors the fixture without importing its formatter into runtime code. Use integer components and Decimal arithmetic, never float.

Keep `recognize(stage, text, synthetic_id)`'s existing tuple shape. At result stage it returns `("complete", amount)` only for a complete parse. An unfinished prefix/body returns pending while more final segments can arrive. Completed unsupported wording is invalid; unresolved/missing text becomes `result_unrecognized` at finalization. Existing fixture rejection phrases retain priority.

## Result assembly and terminal semantics

Final transcript segments remain subject to existing identity, event-ID, ordering, and size checks. Partial transcripts never contribute. Keep result-stage segments after recognizing a candidate; the current early-return/clear behavior would hide subsequent conflicts.

A complete anchored announcement establishes a candidate. Repeated complete announcements with the same normalized amount are allowed. Different amounts, trailing unexplained text/numbers, or unsupported complete announcements reject the whole result. Split announcements are assembled before parsing. A candidate is not yet a terminal success.

Use the existing result-stage hangup timestamp. The first matching hangup starts a fixed five-second finalization window for **all** result-stage calls, including those already holding a candidate. This lets late final segments reveal conflicts. Duplicate hangups do not extend it. Finalization closes at `min(first_hangup + 5, started_at + call_timeout_seconds)`; accept events only strictly before that boundary. Stage timeout no longer competes once this finalization window starts. The overall deadline is always enforced first.

At window close, publish the unique complete candidate or `result_unrecognized`. Hangup before result stage remains `early_hangup`. If result-stage timeout or overall timeout occurs without a hangup, publish a complete unambiguous candidate if present and attempt bounded hangup; otherwise publish the applicable timeout. Do not require a successful transport teardown to recognize already completed speech. Cleanup failure is a separate stderr diagnostic and cannot replace a decided result or its original error.

Add `result` (initially `None`) and failure-stage retention to the flow/controller. `Caller.result` becomes a stable plain dict snapshot before `_clear_sensitive`; it survives cleanup and repeated status reads. Exactly one terminal decision per run, and `ended` stays absorbing. `done` means bounded cleanup has settled. Existing 15-second cleanup bounds remain separate from the recognition deadline. No transcript collection or navigation resumes during cleanup.

## Public contract

Success (exit 0):

```json
{"status":"success","value":"1425.30","currency":"USD"}
```

Error (exit 1; interrupt may use 130):

```json
{"status":"error","code":"challenge_unrecognized","stage":"challenge"}
```

`stage` is where failure happened, captured before cleanup changes the state. Allowed values: `startup`, `dialing`, `welcome`, `challenge`, `menu`, `identifier`, `confirmation`, `result`. Do not expose `ended` or `hanging_up` as the error stage.

| Condition | Public code |
| --- | --- |
| Challenge parse failure | `challenge_unrecognized` |
| Unsupported navigation choice | `unexpected_menu` |
| Readback differs / cannot be read | `id_mismatch` / `confirmation_unrecognized` |
| Spoken fixture rejection | `fixture_rejection` |
| Missing, unsupported, conflicting result at finalization | `result_unrecognized` |
| Stage / overall deadline without complete result | `stage_timeout` / `overall_timeout` |
| Hangup before result | `early_hangup` |
| Rejected/uncertain dial or active command failure | `provider_failure` |
| Ordering, identity, buffer/event overflow, unknown stage or non-result ambiguity | `protocol_error` |
| Configuration/server startup failure or missing caller | `startup_failed` |
| Unexpected server stop or unexpected internal exception | `internal_error` |
| Cancellation / user interrupt before a terminal decision | `interrupted` |

Retain internal reason codes in sanitized diagnostics. Generic parser `unrecognized` maps by stage to challenge/confirmation/result errors, otherwise `protocol_error`. Unknown internal reasons map to `internal_error`; never serialize arbitrary exception messages.

`caller.py` prints one JSON line to stdout for every parsed call invocation, including startup failure and interruption, and uses stderr for diagnostics. `--help` and invalid command syntax retain argparse behavior and do not dial. One output owner emits after cleanup; no output in flow methods or webhook handlers. Early returns and finalizers must not cause duplicate JSON or swallow the original result. Uncatchable process termination cannot promise output.

Cloud compatibility: preserve `serve`, `start`, and `status`. Add `result` to the local socket protocol/CLI: it reads the retained snapshot, never starts or waits for a call, prints the same terminal JSON and returns its exit code. Before completion it prints `{"status":"error","code":"result_not_ready","stage":"startup"}` and exits 1; this retrieval error does not mutate the run. Status adds `result` (null until done) while retaining existing fields and its exit-0 query semantics. Start acknowledgment is not a call result. Preserve socket permissions, four-client limit, request deadlines, no-auto-dial and restart-required behavior.

## Trace and debug

Reuse `Caller.run_id`, monotonic clock, and logger. Default stderr trace records run ID, previous/new stage for transitions, elapsed seconds, terminal/internal reason, and call/leg references once bound. References are the first 12 hex characters of SHA-256 of each ID; never log raw call-control tokens. Call these `call_ref` and `leg_ref`, not provider IDs. Preserve correlation through final cleanup logging, then clear identities as today.

Add `IVR_CLIENT_DEBUG_TRANSCRIPTS=0|1` (default 0), validated without exposing its value on errors. Both local and cloud modes load it through existing settings. Debug adds sanitized transcription diagnostics: final/partial flag, character count, segment count, parser status/reason, and ownership match booleans. It never includes transcript text or token values. This deliberately gives parser evidence without a redaction heuristic that could leak a spoken ID. No raw-transcript flag in this lesson.

## Files and verification

Modify `speech.py`, `client.py`, `caller.py`, `cloud_runner.py`, `.env.example`, their four existing focused test modules, the IVR README, deployment usage documentation, and curriculum. Create `lessons/04-value-or-error.md` only during implementation. No fixture behavior changes; unsupported wording is tested through offline event replay. A fixture scenario switch belongs to Lesson 5.

Offline coverage includes fixture grammar boundaries, changed amounts and zero, numeric equivalents, malformed grammar, fragmented final text, conflicting amounts, partials, foreign legs, duplicate hangups, exact overall-deadline boundary, immutable results, cleanup failure, startup failure, cancellation, local/cloud output parity, and log privacy. Tests may use fixture formatting as an oracle; client runtime must remain independent.

Live acceptance: on the selected existing local or cloud path, capture one `1425.30` success, one changed-amount success, and one wrong-ID rejection, with stdout, stderr, exit code, timing, release, and every failed attempt. Restore fixture settings. The unsupported-phrase exercise uses offline replay until Lesson 5 provides that scenario. A cloud run requires deploying the implementation separately; planning does not alter the VM. Record observations independently from learner sign-off; no reliability claim from one successful call.

## Review record

Author self-review checked existing call sites (`recognize`, `ClientFlow`, `Caller`, local CLI, cloud Control), fixture amount bounds, cleanup retention, curriculum coverage, and prior lesson conventions. The five-second window and cloud runner are existing code to extend, not new infrastructure. No independent review or live validation claimed. Final author review added regressions for punctuated dollar/cents fragmentation, preserving the exit code on interruption after a decision, and distinguishing internal dial errors. All three failed before their fixes and passed afterward. Implementation remains on the lesson branch for the live learner checkpoint.
