# IVR Google Cloud diagnostic deployment

Project `fullstack-sandbox-tylervsd`; VM `ivr-webhook`, zone `us-west1-a`.
Static address `ivr-webhook-ip`: `136.66.151.98`.
Hostname: `ivr.tylervallillee.info` (DNS stays with the existing provider).
Dedicated VPC/subnet `ivr-diagnostic`, range `10.42.0.0/24`.
Firewall `ivr-web-allow` permits TCP 80/443; `ivr-iap-ssh` permits TCP 22 only
from IAP's `35.235.240.0/20`. Both target the `ivr-webhook` tag. No Google runtime
service account. OS Login enabled; project SSH keys blocked.

## Operate over IAP

```sh
gcloud compute ssh ivr-webhook --project=fullstack-sandbox-tylervsd --zone=us-west1-a --tunnel-through-iap
sudo systemctl status ivr caddy --no-pager
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py status
sudo journalctl -u ivr -n 80 --no-pager
```

The server starts idle; boot/restart never dials. When ready to place one paid call:

```sh
sudo -u ivr /opt/ivr/current/.venv/bin/python /opt/ivr/current/cloud_runner.py start
```

Query status afterward. Losing the SSH acknowledgment does not cancel the call;
query status rather than starting again. A second start is rejected. After both
legs have ended and at least 60 seconds have elapsed, explicitly restart for a
new call: `sudo systemctl restart ivr`. If termination is unconfirmed, inspect
and end the remote call in Telnyx first. Restart loses all process-local state.

## Runtime and credentials

Caddy proxies only POSTs to the two webhook paths. Uvicorn listens on loopback
8010. The control socket is `/run/ivr/control.sock`, mode 0600, in a 0700
systemd-owned directory. Runtime user `ivr` cannot modify release files.

Root-owned `/etc/ivr/ivr.env` is mode 0600 and loaded by systemd. Populate through
encrypted SSH; never commit it, put it in instance metadata, or print it. Only
required TELNYX/IVR settings should be copied from the local configuration.
The permanent configuration uses Telnyx dial-time transcription with
`IVR_CLIENT_TRANSCRIPTION_TRACK=inbound` (also the local default). Only final
results drive navigation. See the acceptance record for live validation.

Deploy only committed files in `spikes/ivr`, without `.env`, `.venv`, caches or
unrelated repo files. Extract under `/opt/ivr/releases/<commit>`; install Python
3.14 using uv with `UV_PYTHON_INSTALL_DIR=/opt/ivr/python`, then run
`uv sync --locked` in that release. Point `/opt/ivr/current` at the selected
release. Install `ivr.service` in `/etc/systemd/system/` and `Caddyfile` in
`/etc/caddy/`. Validate using `systemd-analyze verify` and `caddy validate` before
`systemctl daemon-reload` and enabling services. Keep the previous release for rollback.

No container registry, load balancer, NAT gateway, SQL or Terraform state change
is required. Debian's packaged Caddy and the official uv installer are used;
record the resolved versions in the deployment evidence.

## Verification before callback cutover

```sh
curl -i -X POST https://ivr.tylervallillee.info/webhooks/client -H 'Content-Type: application/json' -d '{}'
curl -i -X POST https://ivr.tylervallillee.info/webhooks/test-ivr -H 'Content-Type: application/json' -d '{}'
curl -i https://ivr.tylervallillee.info/status
```

Expect 401, 401, 404 with valid TLS. Unsigned checks cannot place calls. Repeat
a small concurrent batch and record all results. Request logs show only path,
status and duration. Speech logs show final/ownership booleans and parser outcome;
raw transcripts, credentials and numeric input remain private.

After verification, record existing primary/failover URLs privately and update
the two Telnyx Voice API applications to:

- `https://ivr.tylervallillee.info/webhooks/client`
- `https://ivr.tylervallillee.info/webhooks/test-ivr`

Do not leave failover pointed to an inactive local process. Preserve number
assignments. Cutover and paid tests are separate from infrastructure deployment.
A working public 401 does not establish Telnyx delivery or Lesson 3 acceptance.

## Cost and cleanup

Target: under $20/month incremental cloud cost. Planning allowance for 730 hours:
about $6.12 compute, $3.65 attached public IPv4, and $0.80 for 20 GB standard disk,
roughly $10.60 before egress/tax and without free-tier credits. Regional SKUs and
actual usage govern billing; this is an estimate, not an enforced spending cap.
Existing sandbox services, domain renewal and Telnyx calls are separate.

Sources: [VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose),
[network/IP pricing](https://cloud.google.com/vpc/network-pricing),
[disk pricing](https://cloud.google.com/compute/disks-image-pricing).
Stop the VM between extended periods of inactivity if desired; disk and reserved
IP charges persist. An unassigned static IP is billable too.

Rollback: end calls, restore saved Telnyx URLs, verify the local Funnel and run
`caller.py` locally. To roll back code on the VM, stop ivr, point `current` at the
previous verified release and start ivr; it remains idle.

Explicit teardown, only after rollback/no active calls: delete VM `ivr-webhook`
and its auto-delete boot disk; release address `ivr-webhook-ip`; delete the two
named IVR firewall rules, IVR subnet and VPC; remove only the `ivr` DNS A record.
Do not delete the default network, other sandbox services, or shared IAM roles.

## Deployment evidence — 2026-09-21

Release `e4b5e29` deployed to the resources above. Debian 12, Python 3.14.7,
uv 0.12.17, Caddy 2.6.2. Local verification: 364 tests passed; Ruff checks and
formatting passed (two upstream deprecation warnings).

Both systemd services are active. Control reports `started: false`, `stage: idle`.
Credential file is root-owned 0600; runtime directory 0700; control socket 0600.
TLS certificate validation succeeds for the hostname. Ten concurrent-batch
unsigned webhook requests all returned 401; `/status` returned 404. These checks
used curl `--resolve` with the reserved IP because local DNS was still pending;
no certificate verification was bypassed. Google public DNS already resolved
the A record. Telnyx callback cutover and a real call remain unverified.

## Transcription diagnostics — 2026-09-21

Google/inbound with interim results produced only partial events. Disabling
interim results produced no transcription events, both at dial time and with
an accepted explicit transcription_start command after answer.

The same explicit-start probe using Telnyx/inbound returned final results and
passed welcome, challenge and menu in one call, then stalled at identifier.
A targeted probe confirmed the engine can transcribe "followed by pound" as
"followed by pounds". Release `328cbb9` narrowly normalizes that complete phrase;
it does not relax numeric validation or accept interim results. Regression test
failed before the fix; all 365 tests and Ruff passed afterward.

The full-flow retest with that fix stalled earlier at challenge (`pending`), so
end-to-end acceptance remains unverified. That challenge transcript was not
retained. Investigate its wording before broadening grammar. Temporary probe
service overrides were removed; normal service remains Google/final-only,
with the parser fix deployed. No permanent Telnyx-engine migration is claimed.

## Permanent Telnyx release and acceptance — 2026-09-22 UTC

Release `11f2e01` uses Telnyx/inbound transcription enabled at dial time,
without Google-only interim options. It normalizes only the observed
"followed by pounds" / "followed by a pound" instruction variants. It waits
at most five seconds for a final result transcript after a matching hangup;
missing results still fail, duplicate hangups cannot extend the wait, and
other-call transcripts remain rejected. No temporary engine probe is required.

Offline: 369 tests passed, Ruff and formatting passed (two existing warnings).
Normal live acceptance: 02:14:14–02:15:06 UTC, caller run
`50a1a401-2112-4678-b661-4bd6970af486`, all six parser stages complete,
fixture `result_spoken`, caller `completed` / exit 0.
Wrong-ID scenario: 02:07:38–02:08:27 UTC on release e493bb5, rejected at
identifier, caller `fixture_rejection` / exit 1, no confirmation tone sent.

Failed attempts remain material: before the final prompt normalization,
Google yielded no finals; explicit Telnyx start sometimes missed prompt text;
normal repeat reported unexpected_menu; menu transcription was absent in one
run; leading-zero challenge stalled on "a pound"; final result arrived after
hangup before the five-second grace was added. The first leading-zero run on
11f2e01 failed at welcome with unexpected_menu. A successful run is functional
acceptance evidence, not proof of transcription reliability.

Leading-zero final rerun: 02:17:05–02:17:58 UTC on `11f2e01`, caller
`6192c797-e7d0-45ff-8d32-b53f5e8cc29a`, fixture-only override `0742`, all six
parser stages complete, fixture `result_spoken`, caller `completed` / exit 0.
The fixture advanced only after the exact challenge plus pound matched.
At 02:18 UTC all test drop-ins and temporary settings were removed; systemd
reported no DropInPaths, normal cloud_runner.py serve, and idle/not-started.
Both original blockers (permanent engine and full live success) are closed.
