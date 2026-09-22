# Lesson 3 — An automated caller that hears and responds

**Status:** Implemented and verified offline (358 tests, Ruff check and format
clean, 2026-09-21); live verification and learner acceptance remain pending.
No live calls, tunnel exposure, purchases, or account changes were performed
by the implementation agent.

**Prerequisite:** Lesson 2 is accepted and merged through PR #34. You need its
Voice API applications, destination number, public verification key, callback
routes, and fixture API credential. You additionally need a learner-owned
outbound caller ID (number and outbound voice profile) and a Telnyx Voice API
application for the client role, plus Telnyx transcription support on the
account. Amount extraction and the value-or-error JSON contract are Lesson 4;
do not expect a spoken amount or any stdout JSON from this lesson.

[Design](../../../docs/superpowers/specs/2026-09-21-ivr-03-automated-caller-design.md) ·
[Implementation plan](../../../docs/superpowers/plans/2026-09-21-ivr-03-automated-caller.md)

## Start in the existing IVR worktree

From your original checkout:

```sh
git worktree list
cd .worktrees/ivr-01-connectivity
git branch --show-current
cd spikes/ivr
```

Expected branch: `codex/ivr-03-automated-caller`. The directory retains its Lesson 1 name.
Do not reset branches or overwrite existing `.env`. All commands below assume
this spike directory. Pause at each checkpoint to run it and explain the result.

## What you are learning

A Telnyx API response accepts a command; a later webhook reports its outcome.
The client dials with `POST /v2/calls`, and the provider answers that request
with call identity — not with proof that anything was heard. Proof arrives
later, as `call.transcription` webhooks carrying someone speaking. Only a
recognized spoken prompt authorizes the next DTMF; fixed sleeps never do.

Each call has two legs that must never be confused: the client's outgoing leg
(which the client owns and commands) and the fixture's incoming leg (which the
fixture owns). Webhook IDs from one leg are meaningless on the other.

| Leg | Owner | Webhook route | Commands sent to it |
| --- | --- | --- | --- |
| Client outgoing | `Caller` in `client.py` | `/webhooks/client` | `dial` (once), `send_dtmf`, `hangup` |
| Fixture incoming | `Fixture` in `fixture.py` | `/webhooks/test-ivr` | `answer`, `gather_using_speak`, `speak`, `hangup` |

The client learns the challenge and the result announcement only through its
own remote speech. It never reads fixture state, the challenge override, the
result amount, or fixture settings. Fixture webhook digits are acceptance
evidence for you, the learner — never inputs to client navigation.

| Stage | Client hears (final transcripts) | Client sends |
| --- | --- | --- |
| Welcome | Press 1 to continue | `1` |
| Challenge | Four digit words, including any zeros | Heard code plus `#` |
| Menu | 1 personal, 2 business | `1` |
| Identifier | Nine-digit personal ID prompt | Synthetic `000123456#` by default |
| Confirmation | Digit-by-digit readback | `1` only when the readback matches |
| Result | “Your requested value is …” | Nothing; waits for fixture hangup |

The code stays a string to preserve leading zeros: `0742` and `742` are
different input. The client recognizes ASCII digit runs and zero–nine words
with space/comma/hyphen separators only. Unicode digits, decimals, signs,
number words like “seventy”, and substitutions like “oh” are never guessed.

### Partial versus final transcripts

`call.transcription` events carry `transcription_data.transcript` and a real
boolean `is_final`. Interim (`is_final: false`) segments are unstable provider
guesses — the client ignores their text entirely and they never extend a
deadline. Only final segments feed the per-stage buffer (at most 4096
characters / 64 segments), and a prompt split across several finals is joined
with spaces, so a digit run broken across segments still parses. A decreasing
event timestamp fails the run as `transcript_order`; duplicates are dropped.

## Checkpoint A: offline foundation and settings

From the IVR worktree's `spikes/ivr` directory:

```sh
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
git check-ignore .env
```

Expect 358 tests passing (two existing upstream Starlette/AnyIO deprecation
warnings remain), both Ruff checks clean, `--help` showing only `--env-file`
and `--app public|client`, and `.env` ignored. MockTransport proves no test
touches the real network; no paid call has happened. If `.env` exists, edit it
rather than overwriting it; otherwise copy `.env.example`. You supply the
public key, both API credentials, both connection IDs, both numbers, and the
client synthetic ID locally, without pasting them into chat or acceptance
artifacts.

Client settings use only these names (see [.env.example](../.env.example)):

```sh
IVR_CLIENT_CONNECTION_ID=      # required; must differ from IVR_CONNECTION_ID
IVR_CLIENT_FROM_NUMBER=        # required E.164; your outbound caller ID
IVR_CLIENT_TO_NUMBER=          # required E.164; the sole test destination
IVR_CLIENT_SYNTHETIC_ID=000123456
IVR_CLIENT_STAGE_TIMEOUT_SECONDS=30
IVR_CLIENT_CALL_TIMEOUT_SECONDS=180
IVR_CLIENT_DTMF_DURATION_MS=250
IVR_CLIENT_DTMF_PAUSE_UNITS=0
```

Settings the client ignores (fixture-only): `IVR_CONNECTION_ID`,
`IVR_SYNTHETIC_ID`, `IVR_RESULT_AMOUNT`, `IVR_CHALLENGE_OVERRIDE`, and all
fixture gather/voice tuning. Invalid client settings fail with a generic
configuration error that omits the submitted value.

## Checkpoint B: routing, numbers, and transcription readiness (learner operations)

Before any call, verify as learner operations — none of this is automated:

1. Both Telnyx Voice API applications exist with distinct IDs; the fixture
   number routes to the fixture app and the client's callback URL routes to
   the client webhook.
2. The outbound caller ID is assigned to your profile, the destination is
   permitted, and the account has balance.
3. The dial enables the Telnyx transcription engine on the `inbound` track.
   This track was verified to hear fixture speech on the client leg.
   Only final transcripts drive navigation; Google-only interim options are omitted.

Stop the old Lesson 2 ingress before the CLI owns its port: the CLI's
`--app public` mode binds `127.0.0.1:8010` itself and replaces that process —
do not run both on 8010. `--app client` binds `127.0.0.1:8011` and hosts only
the caller, for a separately run fixture with separately configured callback
routing. Independent app processes cannot share in-memory state: each process
keeps its own controllers, so the client and fixture rendezvous only through
the provider, never through shared memory.

On the first live call, verify the selected track actually hears fixture
speech on the client's callback. If it does not, re-check the account and
application configuration — never merge both transcription tracks to conceal
a mismatch.

## Checkpoint C: one automated call (learner-operated)

After checking settings and existing routing:

```sh
uv run python caller.py --env-file .env --app public
echo $?
```

One invocation places exactly one call, then exits. Exit 0 only when the
result announcement **and** a matching fixture hangup were both observed.
Stdout stays empty; one final diagnostic line goes to stderr:

```sh
ivr caller public: completed (exit 0)
```

Anything else exits nonzero with a sanitized reason (`challenge_unrecognized`,
`id_mismatch`, `stage_timeout`, `early_hangup`, `hangup_unconfirmed`, …).
The amount is **not** extracted or printed — reaching the result announcement
is the checkpoint; Lesson 4 owns the value. Watch the stage progression on
stderr, then confirm the five DTMF inputs in your private provider
diagnostics (redact the synthetic ID before recording anything). Default
application logs stay private: they omit transcripts, digits, numbers,
credentials, and call-control tokens.

If the local process fails or you see `hangup_unconfirmed`, end the call
manually in the provider portal: process exit never proves the remote call
ended, and provider time/overall limits are only fallbacks.

## Checkpoint D: repeat with a different code, zeros, and a wrong ID

Run the Checkpoint C command once per exercise and record every attempt:

1. **Normal call.** Verify stage progression plus provider-side received-digit
   evidence, as in Checkpoint C.
2. **Different challenge.** The fixture generates a fresh random code per call;
   confirm the client replays the new code, not a previous one.
3. **Leading zero.** Set fixture-only `IVR_CHALLENGE_OVERRIDE=0742`, restart
   through the CLI, and verify exact `0742#` received; clear the override
   afterward. Client settings and code must never read it.
4. **Mismatched ID.** Configure a different `IVR_CLIENT_SYNTHETIC_ID` and
   observe bounded rejection with no confirmation tones; restore the setting.
   The offline suite separately forces a wrong confirmation readback.

End any active call before changing settings or restarting. If delivery drops
recur, record timing, event types, and provider delivery status, and rerun the
affected exercise. Do not label the path reliable from offline checks.

## Checkpoint E: DTMF tuning and limits

Tone duration (`IVR_CLIENT_DTMF_DURATION_MS`, 100–500 ms) and inter-digit
`w` pauses (`IVR_CLIENT_DTMF_PAUSE_UNITS`, 0–2, each a 500 ms pause) tune
audio only — they never extend navigation deadlines. If digits are missed,
tune these and rerun; do not add sleeps to the navigation.

| Bound | Default | Meaning |
| --- | --- | --- |
| Stage deadline | 30 s (10–60) | Each new stage gets a fresh window; partials and duplicates never extend it |
| Overall deadline | 180 s (60–600, ≥ stage) | Starts at dial reservation; navigation stops when it expires |
| Cleanup budget | 15 s | One best-effort hangup of the owned leg after errors/timeout/Ctrl-C |
| Server readiness | 10 s | CLI dials only after its Uvicorn server reports ready; a bind/startup failure dials zero times |
| Dial submission | 5 s, once | No retry even on 429/5xx; uncertainty waits for a correlated callback, never redials |

## Checkpoint F: troubleshooting exercise

Kill the CLI mid-call (Ctrl-C) and confirm bounded cleanup runs and a fresh
invocation starts cleanly — memory-only state cannot resume the old call.
Then force a failure: stop the fixture process and run the CLI, observing a
stage timeout rather than a hang. Distinguish API credential/permission,
unsupported voice, command rejection, transcription-track mismatch, and
webhook loss using sanitized status plus your private provider view; do not
enable raw payload logging or commit sensitive artifacts. A dial HTTP 200 is
not audible-result evidence, and an API acknowledgment of DTMF does not prove
digits were received — only the next expected spoken prompt does.

## Checkpoint G: stop and record acceptance

End any remaining call in the provider portal before stopping processes.
Ctrl+C the learner-operated CLI/tunnel and use
[Lesson 1’s scoped cleanup checks](01-connectivity.md#7-stop-exposure-and-record-acceptance),
preserving unrelated mappings. No global Funnel reset.

## Settings and failure behavior

See [the environment example](../.env.example) for all local settings. Values
are read at startup; stop calls before restarting to apply changes. The client
synthetic ID is exactly nine ASCII digits. Timeouts and DTMF tuning are
validated at startup; invalid settings fail with a generic error without
showing secrets.

A wrong readback ends navigation with `id_mismatch` and no confirmation tones.
Fixture rejection phrases end navigation without resend. An early hangup is a
nonzero exit even if a late final arrives afterward. After the result
announcement the client waits for the fixture's ordinary hangup within the
remaining deadlines; a missing hangup acknowledgment is `hangup_unconfirmed`.
A second `start()` is rejected; completed controllers cannot start another
call. Unknown, duplicate, wrong-role, and wrong-leg events are ignored with
empty 200s and no action.

Logs show run ID, stage, elapsed time, and sanitized reason only. Use your
private provider view for correlation evidence, and redact identifiers before
recording anything here. State and replay guards are memory-only: a restart
ignores calls started before it. The client keeps at most 32 pre-identity
events / 64 KiB, 4096 event IDs, and a 64-segment stage buffer; overflow fails
the run. These are POC bounds, not a production reliability or security
guarantee.

## Acceptance record

Offline observation: 2026-09-21. `uv sync --locked`, pytest (358 passed, two
existing upstream Starlette/AnyIO deprecation warnings), Ruff check, Ruff
format check (`16 files already formatted`), `caller.py --help`, and
`git diff --check`. Tests isolate inherited account settings, block real
outbound HTTP, use synthetic signatures, and use fake transports/clocks. No
live calls were placed by the implementation agent.

| Evidence | Offline result | Live observation / time | Learner acceptance |
| --- | --- | --- | --- |
| Settings bounds, fixture-independence | Passed (358 tests) | Not run | Pending |
| Digit grammar, leading zeros, no guessing | Passed (358 tests) | Not run | Pending |
| Single-submission dial, DTMF transport | Passed (358 tests) | Not run | Pending |
| Five-action prompt navigation replay | Passed (358 tests) | Not run | Pending |
| Call/leg ownership, early callbacks, cleanup | Passed (358 tests) | Not run | Pending |
| CLI lifecycle, role isolation, stdout privacy | Passed (358 tests) | Not run | Pending |
| Normal live call to result announcement | Passed (offline replay) | Not run | Pending |
| Different-challenge live repeat | Passed (offline replay) | Not run | Pending |
| `0742` override live replay | Passed (offline replay) | Not run | Pending |
| Mismatched-ID live rejection | Passed (offline replay) | Not run | Pending |
| Transcription track hears fixture speech | Not applicable offline | Not run | Pending |
| Scoped tunnel cleanup | Not applicable | Not run | Pending |
| Lesson completion | Local implementation verified | Not run | Pending |

For each attempt record date/time, scenario, expected versus heard speech,
stage progression, provider-side received DTMF (synthetic ID redacted),
actual disconnect, and any failure/recovery. Record failed attempts as well
as successful reruns. Do not store credentials, phone numbers, full webhook
payloads, full transcripts, or real personal IDs. Learner sign-off: **Pending**.

Open observation (carried from Lesson 2, still unresolved): intermittent
webhook delivery failures — missing gather-completion callbacks with provider
error code `75000` on some calls, later calls succeeding. Do not treat
successful Lesson 3 reruns as a reliability fix. On recurrence, retain call
time, last prompt, provider delivery status, and ingress errors. No
credentials or raw call payloads belong in this record.
Stop after this lesson; Lesson 4 has not been implemented.
