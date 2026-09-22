# Lesson 4 — A value-or-error contract

Lesson 4 extends the accepted Lesson 3 caller. Work in
`.worktrees/ivr-01-connectivity`, branch `codex/ivr-04-value-or-error`.
Implementation is verified offline. The learner reported walkthrough completion
and signed off on 2026-09-22; detailed live artifacts were not supplied. No deployment or paid calls were performed during implementation.

## Prerequisites

Read [Lesson 3](03-automated-caller.md) for number/app setup, verified callbacks,
remote-side transcription, and synthetic-ID navigation. Keep the two role
configurations separate. Use the existing Python 3.14 environment and uv lockfile.
Never replace an existing `.env` with the example or print its contents.

From the repository's existing worktree:

```sh
cd /Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python caller.py --help
uv run python cloud_runner.py --help
```

Offline tests mock telephony; they do not dial, change routing, or deploy.

## 1. Recognizing a marker is not recognizing an amount

Previously, “Your requested value is available” could satisfy the Lesson 3
checkpoint. Lesson 4 requires a complete amount:

```text
Your requested value is one thousand four hundred twenty-five dollars and thirty cents.
Your requested value is $1,425.30.
Your requested value is 1425.30 dollars.
```

Each normalizes to `1425.30`. Try the parser without starting any server:

```sh
uv run python - <<'PY'
from speech import parse_amount
for body in ("zero dollars and zero cents", "17.42", "one dollar and five cents"):
    print(parse_amount("Your requested value is " + body + "."))
try:
    parse_amount("Your requested value is about a thousand dollars.")
except ValueError as error:
    print(error)
PY
```

Expected: `0.00`, `17.42`, `1.05`, then `result_unrecognized`. Zero is a real
value. It is never a fallback for missing speech.

The parser handles 0–9999 dollars and 0–99 cents, using integer components and
Decimal arithmetic. Whole-dollar wording still needs “and zero cents”. Decimal
forms require two fractional digits. Negative values, other currencies, “point”,
internal “and” in number words, malformed comma grouping, and conflicting
amounts are rejected. Runtime client code never imports the fixture formatter
or reads `IVR_RESULT_AMOUNT`.

## 2. Buffer final speech, then decide once

Read `speech.py` result recognition and `ClientFlow._on_deadline` in `client.py`.
Only final transcripts from the admitted client call/leg enter the bounded
buffer. A complete candidate remains provisional; a later final can finish a
fragment or expose a conflicting amount. Repeated complete announcements of the
same amount are allowed. Partial transcripts never complete an amount.

The first matching result-stage hangup opens a five-second finalization window,
even if an amount was already heard. Duplicate hangups cannot restart it. The
window ends at the earlier of hangup + five seconds and the overall call
deadline. Text arriving exactly at the boundary is too late.

At finalization, a complete unambiguous amount wins; missing/unsupported text
returns `result_unrecognized`. Hangup before the result stage is `early_hangup`.
Without hangup, a stage/overall deadline returns the corresponding timeout unless
complete speech already established an amount; in that case it preserves the
amount and attempts cleanup. Teardown has its existing separate, bounded budget.
`hangup_unconfirmed` is a diagnostic: it cannot replace an already decided value
or the original failure. If remote termination is unconfirmed, inspect and end
the call in Telnyx before another run.

Exercise the event ordering offline:

```sh
uv run pytest tests/test_client.py -q -k 'result_window or finalization or conflict or cleanup_failure'
```

## 3. Read stdout, stderr, and exit status separately

A local invocation prints exactly one JSON line:

```json
{"status":"success","value":"1425.30","currency":"USD"}
```

Success exits 0. Failures exit 1; an interrupted local invocation may exit 130:

```json
{"status":"error","code":"fixture_rejection","stage":"identifier"}
```

The error stage records where the failure occurred, before hangup cleanup.
Challenge recognition, unsupported menus, ID mismatch, fixture rejection,
result recognition, stage/overall timeout, early hangup, provider failure,
protocol errors, startup failure, internal failure, and interruption have
explicit codes. `--help` and invalid argument syntax retain argparse behavior.

Default stderr contains run ID, elapsed time, stage transitions, internal reason,
and hashed call/leg references. References correlate logs without exposing
provider call-control tokens. Set `IVR_CLIENT_DEBUG_TRANSCRIPTS=1` in the ignored
settings file before starting the process to add final/partial flags, character
and segment counts, parser status, and ownership booleans. This option never
prints transcript text, challenge digits, IDs, credentials, or phone numbers.
Reset it to `0` after diagnosis.

### Local call (learner-operated)

Use this only when callbacks already route to this local process. The combined
CLI replaces the old Uvicorn process on port 8010 and hosts both roles. Do not
start a duplicate server or change the active cloud callback path accidentally.

```sh
uv run python caller.py --env-file .env --app public > /tmp/ivr-result.json 2> /tmp/ivr-trace.log
call_exit=$?
cat /tmp/ivr-result.json
printf 'exit=%s\n' "$call_exit"
```

Inspect `/tmp/ivr-trace.log` locally for stage transitions and cleanup warnings.
Retain only sanitized evidence. A bind/startup failure prints a structured error
and dials zero times.

### Existing cloud runner

Lesson 4 release `bde9fdf` was deployed separately on 2026-09-22 and verified
idle. See [deployment evidence](../deploy/README.md#lesson-4-deployment--2026-09-22).
Learner acceptance is recorded below. SSH through the existing IAP path, then:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py start
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py status
```

`started` acknowledges the command; it does not mean the call succeeded. Query
status until `done=true`, then retrieve the terminal record:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py result
call_exit=$?
printf 'exit=%s\n' "$call_exit"
sudo journalctl -u ivr -n 80 --no-pager
```

`result` is read-only and never dials. It prints the same value/error JSON and
exits 0/1 accordingly. Before completion it returns `result_not_ready`, exit 1;
query later without sending another `start`. Status retains query exit 0 and
includes `result: null` until completion. Repeated result reads are stable.
The server remains running after a call; its stderr trace is in the journal.
Restart only after both legs are ended and the prior lesson's cleanup interval
has elapsed. Restart loses the previous in-memory result.

## 4. Troubleshooting and acceptance

Change only fixture `IVR_RESULT_AMOUNT` from `1425.30` to `17.42` in its ignored
local settings before the next invocation. Do not change client code/settings.
For cloud, use the existing protected service settings and restart procedure
after separately deploying; never put secrets in shell arguments. Repeat the
call and verify the output changes to `17.42`. Restore `1425.30` afterward.

For a failure, set the client's synthetic ID to a different nine-digit synthetic
value than the fixture, call once, and expect `fixture_rejection` at identifier.
Restore the matching synthetic value before the next normal run. Never use a
real identifier. Keep every unsuccessful live attempt in the record.

Unsupported wording exercise: the parser command above is deliberately offline.
Lesson 5 owns live scenario overrides; don't edit production fixture speech to
simulate them here. If a live result is unrecognized, inspect safe diagnostics
first. Do not relax the grammar or accept partial transcripts to force success.

| Evidence | Result |
| --- | --- |
| Offline suite and Ruff | See implementation verification record below |
| Live normal `1425.30`: release, stdout, stderr, exit, timing | Walkthrough completion reported by learner; detailed artifacts not supplied |
| Live changed `17.42`: same evidence | Walkthrough completion reported by learner; detailed artifacts not supplied |
| Live wrong-ID rejection: same evidence | Walkthrough completion reported by learner; detailed artifacts not supplied |
| Additional failed attempts and diagnosis | None performed during implementation |
| Learner acceptance | Signed off 2026-09-22 |

Checkpoint: the client prints exactly one structured result and terminates;
changing only the fixture amount changes the returned value. Offline passing
checks do not establish live transcription reliability. Sign off only after
reviewing the observed live results. Lesson 5's repeated-call reliability drills
remain separate.

## Implementation verification — 2026-09-22

422 tests passed; Ruff check and format passed. Both CLI help commands passed;
Markdown links and `git diff --check` passed. Two existing upstream deprecation
warnings remain. No dependencies added. Tests used the existing worktree Python
environment. Final review was performed by the author; no subagents were used.
The three final-review regressions cover segmented dollar/cents punctuation,
interruption after a terminal decision, and internal-vs-provider dial failure.
This implementation verification record does not claim deployment or live-call evidence.

## Deployment verification — 2026-09-22

Release `bde9fdf` is running on `ivr-webhook` in `us-west1-a`, project
`fullstack-sandbox-tylervsd`. All 422 tests and Ruff passed on the VM. Both services
are active; caller is idle; result retrieval returns `result_not_ready`/exit 1;
public unsigned webhooks return 401 and `/status` returns 404. No paid calls were
placed during deployment verification. Previous release
`11f2e01` is retained for rollback.

## Learner acceptance — 2026-09-22

The learner reported: “i have completed the lesson 4 walkthrough and signed off.”
They authorized committing and merging to main and updating the local checkout.
This records learner-reported completion, separately from the automated checks
and deployment verification above. Per-call output, timestamps, and run IDs were
not supplied with sign-off; no additional live calls were observed by the author.
