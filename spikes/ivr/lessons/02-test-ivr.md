# Lesson 2 — A test IVR you can navigate by hand

**Status:** Implemented and verified offline on 2026-09-21. Live acceptance and
learner sign-off are pending. No live calls, tunnel exposure, purchases, or account
changes were performed by the implementation agent.

**Prerequisite:** Lesson 1 is accepted and merged through PR #33. Use its existing
Voice API applications, destination number, public verification key, and callback
routes. You also need a personal phone and a fixture API credential supplied
locally. The outbound calling client, its number/profile, and transcription are
still deferred to Lesson 3.

[Design](../../../docs/superpowers/specs/2026-09-21-ivr-02-test-ivr-design.md) ·
[Implementation plan](../../../docs/superpowers/plans/2026-09-21-ivr-02-test-ivr.md)

## Start in the existing IVR worktree

From your original checkout:

```sh
git worktree list
cd .worktrees/ivr-01-connectivity
git branch --show-current
cd spikes/ivr
```

Expected branch: `codex/ivr-02-test-ivr`. The directory retains its Lesson 1 name.
Do not reset branches or overwrite existing `.env`. All commands below assume
this spike directory. Pause at each checkpoint to run it and explain the result.

## What you are learning

An API response accepts a command; a later webhook reports its outcome. The
fixture answers, waits for `call.answered`, and then issues combined speech/gather
commands. Individual digit webhooks do not advance the menu. Only a matching
completed gather can do that. The last `speak` must complete before normal hangup.

| Stage | You hear | You send |
| --- | --- | --- |
| Welcome | Press 1 to continue | `1` |
| Challenge | Four digit words, including any zeros | Heard code plus `#` |
| Menu | 1 personal, 2 business | `1` |
| ID | Nine-digit personal ID | Synthetic `000123456#` by default |
| Confirmation | Digit-by-digit readback | `1` only when correct |
| Result | Configured dollars and cents | Nothing; listen until disconnect |

The fixture collects pound as an ordinary last character, with the provider's
terminator disabled. This enforces the whole code-plus-pound sequence instead
of accepting a code that happened to finish by timeout. Do not replace this with
integer conversion: `0742` and `742` are different input.

Every logical command has one immutable command ID. HTTP retries reuse it; a
new caller attempt gets a new ID. Each completion must also match the current
operation token. The token contains no ID, amount, or challenge. Input steps get
two attempts by default; provider no-input waits are 20 seconds after speech,
with a 5-second interdigit timeout. The local watchdog ends missing-callback
waits, and navigation has a 300-second overall bound plus bounded cleanup.

## Checkpoint A: offline foundation and settings

From the IVR worktree's `spikes/ivr` directory:

```sh
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git check-ignore .env
```

Expect all tests/checks pass and `.env` ignored. The implementation verification passed 168 tests; record your actual count. Explain
what MockTransport proves and why no paid call has happened. If `.env` exists,
edit it rather than overwriting it; otherwise copy `.env.example`. Learner supplies
public key, fixture API key, and IVR_CONNECTION_ID locally, without pasting them
into chat or acceptance artifacts. Synthetic ID default is `000123456`.

## Checkpoint B: local runtime and existing ingress

```sh
uv run uvicorn webhooks:test_ivr_app --host 127.0.0.1 --port 8012 --env-file .env --no-access-log
# A separate learner terminal:
curl -i http://127.0.0.1:8012/health
```

Expect 200 and fixture health JSON. Stop this process before the combined ingress:

```sh
uv run uvicorn webhooks:public_app --host 127.0.0.1 --port 8010 --env-file .env --no-access-log
```

Use one worker without reload. Do not run the client process for this exercise.
Learner inspects Tailscale status and reuses [Lesson 1’s exposure procedure](01-connectivity.md#4-expose-only-the-combined-webhooks) only
when ready; link its route-conflict and scoped cleanup instructions. Do not repeat
purchase/account-creation instructions. If existing routing or permissions need
changes, pause for the learner; do not perform those changes automatically.

Learner sets IVR_PUBLIC_URL locally to their actual origin, then runs:

```sh
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/test-ivr" -H 'Content-Type: application/json' --data '{}'
curl -i -X POST "$IVR_PUBLIC_URL/webhooks/client" -H 'Content-Type: application/json' --data '{}'
curl -i "$IVR_PUBLIC_URL/docs"
curl -i "$IVR_PUBLIC_URL/calls"
```

Expect 401, 401, 404, 404, no call actions. Authenticated provider deliveries now
receive 200. Explain the old 204 historical behavior without editing its evidence.

## Checkpoint C: call by hand and explain each transition

Call the existing destination from a personal phone. Press `1`; listen to the
four digit words and send those exact digits plus `#`; press `1` for personal;
enter `000123456#`; listen to the nine-digit readback and press `1` only if correct.
Hear the full `1425.30` amount and automatic disconnect after speech completion.

Inspect sanitized diagnostics for one answer, five successful gathers, one result
speech, and one hangup (transport retries share an ID). The learner must confirm
that challenge/ID pound keys were collected as intended, operation tokens matched,
and Telnyx delivery diagnostics accepted 200. Any discrepancy fails this checkpoint;
do not loosen input validation or correlation to force a pass.

## Checkpoint D: bounded failure and a troubleshooting exercise

On a fresh call enter a wrong challenge twice: one retry, then spoken failure and
hangup, no menu/result. On another call provide no input: provider's 20-second
post-prompt timeout plus one retry, then failure. This is not a promise that an
entire call lasts only 40 seconds; prompt playback and grace are separate.

Deliberately omit `#` on the challenge. Explain why a four-digit sequence alone
cannot pass; retry with the heard four digits plus pound. If input fails despite
correct digits, inspect sanitized status, stage, length, and token-match booleans
in a test-only diagnostic or learner's private provider view; do not enable raw
payload logging or commit sensitive artifacts. If HTTP commands fail, distinguish
API credential/permission, unsupported voice, command rejection, and webhook loss.
A local success response is not audible-result evidence.

Separate calls exercise business `2`, wrong ID twice, and confirmation `2` twice.
Each must reject without the amount. Hang up midway through another call and
confirm the next call is admitted. Offline replay tests cover duplicate commands;
do not replay live commands as a teaching shortcut.

## Checkpoint E: prove configuration and leading zeros

End calls before changing settings/restarting. Set `IVR_RESULT_AMOUNT=27.05`,
restart, and repeat the happy path: hear twenty-seven dollars and five cents.
Then set `IVR_CHALLENGE_OVERRIDE=0742`, restart, hear zero seven four two, and
enter `0742#`. Remove override afterward. Leave the chosen valid amount documented
locally. The later client must learn both values from speech, not fixture settings.

If two phones are available, call while a first call is active: the second must
end without entering the IVR, and the first must continue. Otherwise record
live busy-call exercise as not run; do not claim that mock evidence was live.

## Checkpoint F: stop and record acceptance

End any remaining call on the handset before stopping/restarting. Ctrl+C the
learner-operated ingress/tunnel and use [Lesson 1’s scoped cleanup checks](01-connectivity.md#7-stop-exposure-and-record-acceptance), preserving
unrelated mappings. An unconfirmed remote hangup requires manual handset termination;
process exit does not prove the remote call ended. No global Funnel reset.

## Settings and failure behavior

See [the environment example](../.env.example) for all local settings. Values
are read at startup; stop calls before restarting to apply changes. Amounts must
be `0.00` through `9999.99` with exactly two decimal places. IDs are exactly nine
ASCII digits. The optional override is exactly four ASCII digits. Basic voice
supports `female` or `male` in this fixture. Timeout and retry tuning is validated
at startup; invalid settings fail with a generic error without showing secrets.

A wrong entry gets one retry, then spoken rejection and hangup. Business `2`
rejects immediately. Rejected confirmation retries confirmation only. A remote
hangup ends local state. Missing speech completion or an exhausted API error
ends the flow without claiming success. A second call is hung up without answering
or speaking, so the first call remains undisturbed.

Logs show local run ID, stage, attempt, action, elapsed time, and reason codes;
webhook logs show event ID/type. Command IDs and operation-token values are kept
out of default logs along with input and prompts. Use your private provider view
for correlation evidence, and redact identifiers before recording anything here.
`command_accepted` is not speech completion. `result_spoken` follows completed
result speech; `hangup_unconfirmed` requires you to end the call on your handset.

State and replay guards are memory-only. A restart will ignore calls initiated
before that process started; it does not recover them. End the call yourself
before restarting. The fixture keeps at most 1000 call identities per process
and stops admitting unfamiliar calls at capacity; restart after ending calls.
An active call has a 4096-event safety ceiling. These are POC bounds, not a
production reliability or security guarantee.

## Acceptance record

Offline observation: 2026-09-21. `uv sync --locked`, pytest, Ruff check/format,
and `git diff --check`. The tests isolate inherited account settings, block real
outbound HTTP, use synthetic signatures, and use a fake transport/clock. Two
existing upstream Starlette/AnyIO deprecation warnings remain.

| Evidence | Offline result | Live observation / time | Learner acceptance |
| --- | --- | --- | --- |
| Settings, zeros, exact money wording | Passed | Not run | Pending |
| Signed routing and private paths | Passed | Not run | Pending |
| Answer and full five-gather flow | Passed | Not run | Pending |
| Pound collection, status and token echo | Contract checks passed | Not run | Pending |
| Wrong challenge twice, no result | Passed | Not run | Pending |
| No-input timeout and retry limit | Passed | Not run | Pending |
| Business, wrong ID, rejected confirmation | Passed | Not run | Pending |
| Changed amount `27.05` and code `0742` | Passed | Not run | Pending |
| Entire result before normal hangup | Passed | Not run | Pending |
| Duplicates, stale events, uncertain sends | Passed | Not run (offline replay exercise) | Pending |
| Early hangup, fresh call, busy rejection | Passed | Not run | Pending |
| Missing callbacks and shutdown cleanup | Passed | Not run | Pending |
| Scoped tunnel cleanup | Not applicable | Not run | Pending |
| Lesson completion | Local implementation verified | Not run | Pending |

For each attempt record date/time, scenario, expected versus heard speech,
attempt count, sanitized event/command correlation, actual disconnect, and any
failure/recovery. Record failed attempts as well as successful reruns. Do not
store credentials, phone numbers, full webhook payloads, or real personal IDs.
Learner sign-off remains **pending** until you complete the live checkpoints.
Stop after this lesson; Lesson 3 has not been implemented.
