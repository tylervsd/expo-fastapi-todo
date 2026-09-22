# Lesson 5 — Repeatable calls and failure drills

Implemented offline on `codex/ivr-05-reliability-drills` in the existing
`.worktrees/ivr-01-connectivity` worktree. Live exercises and learner acceptance
remain pending. No Lesson 5 deployment or paid calls were performed.

Read [Lesson 4](04-value-or-error.md) first. Keep its credentials, callback routes,
Telnyx/inbound transcription, synthetic IDs, and DTMF timing. The caller still
runs one call per process and returns exactly one value-or-error JSON record.

## 1. Understand which identity prevents which duplicate

A webhook event ID identifies one notification. Repeating it must not send
another tone. A command ID identifies one intended action. Retrying its HTTP
request must keep the same bytes and ID; a deliberately new gather attempt gets
its own ID. A stage's client-state token rejects obsolete fixture completions,
even when those notifications arrive with fresh event IDs.

Read [fixture.py](../fixture.py) (`Fixture.accept`, `Flow.handle`),
[client.py](../client.py) (`Caller.accept`, `ClientFlow.handle`), and
[telnyx_commands.py](../telnyx_commands.py) (`send_command`, `send_dial`). State
changes and command reservations happen under short-held controller locks;
provider I/O happens outside them. Neither HTTP acceptance nor a mock test proves
that the other end heard a DTMF tone.

Provider documentation checked 2026-09-22:

- [Answer](https://developers.telnyx.com/api-reference/call-commands/answer-call),
  [gather](https://developers.telnyx.com/api-reference/call-commands/gather-using-speak),
  [speak](https://developers.telnyx.com/api-reference/call-commands/speak-text),
  [hangup](https://developers.telnyx.com/api-reference/call-commands/hangup-call), and
  [DTMF](https://developers.telnyx.com/api-reference/call-commands/send-dtmf)
  document deduplication using command ID within the same call-control ID.
  These references do not specify a retention duration; do not assume permanence.
- The [retry guide](https://developers.telnyx.com/docs/voice/programmable-voice/command-retries)
  recommends identical-command retries for server errors or slow responses.
  This spike retains its conservative bounds: at most two action requests,
  five seconds per request, and a one-second delay. Cancellation can end a retry
  when its command no longer owns the stage. There is no automatic dial retry.
- DTMF has no command-completion webhook. Later recognized prompts drive the
  client onward; a delayed HTTP failure cannot rewind an already advanced stage.
- [Webhook fundamentals](https://developers.telnyx.com/docs/development/api-fundamentals/webhooks/receiving-webhooks)
  describe webhook delivery. The application must tolerate repeated delivery
  without depending on a particular retry count or schedule.

Deduplication is bounded and process-local. Reaching event capacity fails closed;
old IDs are not evicted to make room for replayable actions. Fixture tombstones
prevent completed calls from reopening until restart. They do not survive a crash.

## 2. Replay failures without calling anyone

From the existing worktree:

```sh
cd /Users/tylerv/projects/learning/expo-fastapi-todo/.worktrees/ivr-01-connectivity/spikes/ivr
uv run pytest tests/test_client.py -q -k scenario_prompt_replay
uv run pytest tests/test_fixture.py -q -k 'scenario or fresh_id_obsolete'
uv run pytest tests/test_telnyx_commands.py -q -k 'retry or lost_dtmf'
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The scenario replay test feeds actual fixture prompts to the client as synthetic
final transcripts and routes its DTMF back into fixture gather completions. Only
test code connects the two roles. Runtime client code never imports fixture code
or reads `IVR_SCENARIO`, `IVR_RESULT_AMOUNT`, or expected outcomes.

The tests duplicate prompts concurrently, replay obsolete completions with fresh
IDs, replay events after termination, and simulate lost command responses. The
existing checks also cover event capacity, uncertain dial cleanup, missing hangup
acknowledgement, local/cloud output, and concurrent start admission.

Exercise: inspect `test_scenario_prompt_replay` and
`test_result_window_capped_by_overall_deadline` in `tests/test_client.py`.
A final transcript can still complete an amount inside the five-second post-hangup
window. A repeated hangup cannot extend that window; at its boundary the terminal
result is immutable. Neither event can restart navigation after completion.

These checks do not model speech-recognition quality or real provider delivery.
Live observations below remain necessary.

## 3. Select a fixture scenario before a call

Edit only the nonsecret fixture settings in the ignored `.env` for local work,
or `/etc/ivr/ivr.env` through `sudoedit` on the VM after deploying Lesson 5.
Never replace the entire credential file with `.env.example` or print it.
Settings are loaded at process startup; editing a file does not change a running
fixture. Existing exported environment variables can override local env-file
values, so remove stale exported overrides before running the CLI.

| `IVR_SCENARIO` | Behavior | Expected terminal result |
| --- | --- | --- |
| `normal` | Random challenge; configured amount | Success with that amount |
| `leading_zero` | Challenge `0742` | Success with leading zero preserved |
| `rejected_id` | Reject correct ID before confirmation | `fixture_rejection` / `confirmation` |
| `silent_stage` | Silence after welcome, before challenge | `stage_timeout` / `challenge` |
| `unsupported_result` | Speak “Your requested value is unavailable.” | `result_unrecognized` / `result` |
| `early_hangup` | Hang up after welcome, before challenge | `early_hangup` / `challenge` |

Use `IVR_CLIENT_STAGE_TIMEOUT_SECONDS=30`, `IVR_CLIENT_CALL_TIMEOUT_SECONDS=180`,
and `IVR_CALL_TIMEOUT_SECONDS=300`. Silence waits for the caller's hangup or the
fixture's overall deadline; it does not send another prompt. A normal caller
therefore reaches its stage timeout first. A different deadline configuration
may produce a different first failure.

Keep client and fixture synthetic IDs equal for these drills. `rejected_id`
rejects otherwise valid input immediately; ordinary invalid-input retries are
unchanged. Clear `IVR_CHALLENGE_OVERRIDE` for normal calls so challenges vary.
For `leading_zero`, the override must be empty or `0742`; conflicting values
fail startup. Unknown/blank scenario values also fail startup.

Expected success (exit 0):

```json
{"status":"success","value":"17.42","currency":"USD"}
```

Expected deliberate failures (exit 1, one line per separate call):

```json
{"status":"error","code":"fixture_rejection","stage":"confirmation"}
{"status":"error","code":"stage_timeout","stage":"challenge"}
{"status":"error","code":"result_unrecognized","stage":"result"}
{"status":"error","code":"early_hangup","stage":"challenge"}
```

A different failure before reaching the drill is an unsuccessful attempt, not a
passing drill. Record it, diagnose, then repeat the affected exercise. Never
relax the grammar or accept interim transcripts merely to obtain a green row.

## 4. Run one live attempt at a time

These are learner-operated paid exercises. This implementation did not run them.
Use the path to which callbacks already route; do not start competing local and
cloud servers. For the cloud path, deploy the committed Lesson 5 release using
[the existing release procedure](../deploy/README.md) first. The previously
recorded Lesson 4 release does not include scenario selection.

### Local path

The combined CLI loads `.env`, hosts both roles on port 8010, and dials once:

```sh
uv run python caller.py --env-file .env --app public > /tmp/ivr-result.json 2> /tmp/ivr-trace.log
call_exit=$?
cat /tmp/ivr-result.json
printf 'exit=%s\n' "$call_exit"
```

Save the safe result/exit/elapsed evidence before overwriting those temporary
files on the next attempt. Inspect diagnostics locally; do not commit raw
transcripts, phone numbers, identifier/challenge digits, credentials, or tokens.

### Existing cloud path

```sh
gcloud compute ssh ivr-webhook --project=fullstack-sandbox-tylervsd --zone=us-west1-a --tunnel-through-iap
sudoedit /etc/ivr/ivr.env
```

After the prior call's two legs have ended and at least 60 seconds have elapsed,
restart to load the chosen scenario. Do not restart over an unconfirmed call.

```sh
sudo systemctl restart ivr
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py status
readlink -f /opt/ivr/current
```

Confirm `started=false`, `done=false`, and `result=null`. Restart must not dial.
Then explicitly start one call:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py start
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py status
```

Repeat `status` until `done=true`, then retrieve the result:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py result
call_exit=$?
printf 'exit=%s\n' "$call_exit"
sudo journalctl -u ivr -n 100 --no-pager
```

`result_not_ready` before completion is a query response, not the call's terminal
error. Repeated status/result reads never dial. A second start during a call
returns `busy`; after completion it returns `restart_required`. If SSH loses a
start acknowledgement, query status rather than starting again.

## 5. Acceptance record

Record each attempt's UTC time, deployed/local commit, scenario, safe run ID,
expected and actual JSON, exit code, elapsed time, failure stage, cleanup
confirmation, and diagnosis. Append failed attempts and reruns; do not overwrite
failures. Record that challenges varied/leading zero was preserved without
publishing their digits. A small successful sample is not a capacity estimate.

| Attempt | Scenario | Amount | Expected | Actual evidence |
| --- | --- | --- | --- | --- |
| 1 | normal | 1425.30 | Success | Not run |
| 2 | normal | 17.42 | Success | Not run |
| 3 | normal | 1425.30 | Success | Not run |
| 4 | normal | 17.42 | Success | Not run |
| 5 | normal | 1425.30 | Success | Not run |
| 6 | leading_zero | 1425.30 | Success; leading zero preserved | Not run |
| 7 | rejected_id | 1425.30 | fixture_rejection / confirmation | Not run |
| 8 | silent_stage | 1425.30 | stage_timeout / challenge | Not run |
| 9 | unsupported_result | 1425.30 | result_unrecognized / result | Not run |
| 10 | early_hangup | 1425.30 | early_hangup / challenge | Not run |

**Learner acceptance:** Pending. All five normal calls must return the correct
amount, leading zero must succeed, and every deliberate failure must reach its
intended stage and produce the expected error. Diagnose and rerun affected
exercises when this target is missed; retain all evidence.

## 6. Stop, recover, and restore

A graceful local interrupt or `sudo systemctl stop ivr` attempts bounded hangup.
A crash, hard kill, or network outage may leave provider call legs active. An
error result or `hangup_unconfirmed` does not prove those legs ended.

Before restarting, use authenticated Telnyx call controls to inspect both call
legs. If either remains active, terminate it there and verify termination. Use
the provider's authenticated support/control path if you cannot establish its
state; do not redial while termination is unknown. Never paste API keys or
call-control tokens into committed examples or command history. Existing
[deployment operations](../deploy/README.md#operate-over-iap) describe SSH access.

Restart loses the last result and all deduplication state; it does not recover
or reconcile old calls. Retrieve/save the result first. The caller is one-shot
per process; the fixture can accept subsequent calls after cleanup but has
bounded process-local tombstones. This is not a global 20-call admission system.

After the drills restore these fixture values in the active settings file:

```dotenv
IVR_SCENARIO=normal
IVR_RESULT_AMOUNT=1425.30
IVR_CHALLENGE_OVERRIDE=
```

Keep the normal client settings. After confirming both legs ended and waiting
the cleanup interval, restart the cloud service and check idle status again.
For local work, the next CLI invocation loads the restored file and places a
new call; do not invoke it just to check configuration.

## Implementation verification — 2026-09-22

452 tests passed; Ruff lint and formatting passed. Two existing upstream
FastAPI/Starlette deprecation warnings remain. New scenario tests failed before
implementation, then passed. Additional retry/replay checks verified existing
client behavior; client runtime and dependencies were unchanged. Review was
performed directly by the author; no subagents or independent-review claim.
Deployment, live results, and learner acceptance remain pending.
