# IVR cloud VM diagnostic deployment

**Status:** Proposed; planning only, 2026-09-21. No cloud resources created.
**Plan:** [Implementation](../plans/2026-09-21-ivr-cloud-vm.md).

## Purpose and evidence

Move the Lesson 3 webhook process off the learner's Mac and Tailscale Funnel to
a stable Google Cloud HTTPS endpoint. This changes the delivery path; it does
not guarantee delivery or solve speech finalization. Keep Lesson 3 acceptance
pending until speech-driven navigation works on a real call.

Observed during troubleshooting, separately from automated tests:

- Explicit Google/outbound transcription startup returned HTTP 200/result ok,
  but no transcription callbacks arrived.
- Changing only that diagnostic runner's track to inbound produced callbacks;
  navigation still timed out. The supplied examples were interim transcripts.
- Telnyx recorded failed transcription deliveries with No Response, including
  three attempts lasting approximately 17–37 ms. Missing final events remain
  possible; neither all-final suppression nor its cause has been established.
- Unsigned connectivity checks returned expected 401: localhost 15/15, private
  tailnet 15/15, and both public Funnel IPv4 addresses combined 14/14. The public
  checks took 230–365 ms. This short sample did not reproduce Telnyx's failures.
- Explicit-start/inbound changes exist only in temporary diagnostic runners,
  not in the committed application's default behavior.

Use the existing worktree `.worktrees/ivr-01-connectivity` and branch
`codex/ivr-03-automated-caller`; planning starts at `aa8f587`. Preserve local
credentials, the local runner, previous lesson history, and unrelated files.
This is a Lesson 3 diagnostic extension, not completion of Lesson 4 or 5.

## Decision and alternatives

Choose one Compute Engine VM with Caddy terminating HTTPS and one Uvicorn process
on loopback. Run both role controllers in that process, retaining independent
state and the existing byte-exact webhook signature boundary.

Cloud Run would provide a managed URL but introduces instance lifecycle and
in-memory ownership concerns for the present controller. It is possible with
additional design; it is not necessary for this diagnostic. A replacement tunnel
would be smaller but keeps the Mac and tunnel in the path the learner wants to
remove. No load balancer, autoscaling, database or durable queue in this extension.

Reference: [Compute Engine instances](https://cloud.google.com/compute/docs/instances/create-start-instance),
[Cloud Run autoscaling](https://cloud.google.com/run/docs/about-instance-autoscaling).
Documentation reviewed 2026-09-21; deployment commands must be verified against
the installed tooling during implementation.

## Deployment inputs and resource boundary

Before provisioning resolve these explicit inputs with the learner:

- Project: `fullstack-sandbox-tylervsd`, matching the active gcloud configuration
  and the learner's existing fullstack sandbox selection. Verify billing/IAM before provisioning.
- Region/zone; propose us-west1/us-west1-a, subject to permissions and availability.
- A learner-controlled DNS hostname and permission to point its A record at the VM.
- Budget ceiling: $20/month, supplied by the learner. Treat this as incremental
  IVR cloud spend; existing sandbox services and Telnyx usage are not included
  in that assumption. Confirm scope before provisioning if a total-project cap
  is intended. Determine whether the VM will stop between sessions.
- Existing VPC/subnet to use or permission to create a dedicated IVR network.

Proposed sizing: one non-Spot e2-micro VM, Debian 12, 20 GB standard persistent
boot disk, one regional static IPv4 address. Confirm current compute, disk,
IPv4 and egress costs before approval; do not claim free-tier coverage or treat
a billing alert as a spending cap. Stopped VMs can still retain billable resources.
No changes to existing todo Cloud Run, Cloud SQL, IAM or Terraform state.
The 1 GiB VM must pass an install/startup and call-memory check before cutover;
do not silently upgrade beyond the ceiling. Check [VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose)
and [IPv4 pricing](https://cloud.google.com/vpc/network-pricing), without assuming free-tier credits.

Use explicit gcloud commands recorded in a deployment guide for this single
diagnostic VM, not a new reusable Terraform module. Reuse the repo's cloud CLI
workflow, but create only named IVR resources and record their identifiers for
teardown. Check name collisions before mutations; never adopt an unrelated VM.

## HTTPS, access and secrets

Reserve an address and set DNS before certificate issuance. Caddy handles a
publicly trusted certificate for the supplied hostname. Permit public TCP 80/443
only for the tagged IVR VM; 80 serves certificate validation/HTTPS redirection.
Proxy only POST `/webhooks/client` and `/webhooks/test-ivr`; reject other paths
and methods. The Python listener remains `127.0.0.1:8010`; never expose 8010,
control sockets, docs or health routes publicly.

Admin access uses IAP SSH and OS Login, with the narrowly scoped SSH firewall
source and IAM permissions required by Google. No public all-source SSH rule.
The VM needs no Google API credentials at runtime: do not attach a broadly
privileged default service account. Outbound HTTPS must reach Telnyx and package
and certificate services. Preserve clock synchronization for webhook freshness.

Install a locked Python 3.14 environment via uv. Transfer only the selected
committed spike source, never the whole local directory with .env/.venv.
Use a dedicated unprivileged `ivr` system user and root-owned release files.
Provision `/etc/ivr/ivr.env` through an encrypted admin channel, mode 0600 owned
by root, loaded by systemd EnvironmentFile. Never place credentials in instance
metadata, startup scripts, shell arguments, git, screenshots or logs. The service
inherits only its required environment; backups and source archives exclude it.

References: [IAP SSH](https://cloud.google.com/compute/docs/connect/ssh-using-iap),
[static addresses](https://cloud.google.com/compute/docs/ip-addresses/reserve-static-external-ip-address),
[Caddy HTTPS](https://caddyserver.com/docs/automatic-https).

## Persistent process, local initiation

Add `cloud_runner.py` with `serve`, `start`, and `status` subcommands. `serve`
enables the existing caller controller and combined public app, starts Uvicorn,
and creates a local Unix socket only after server readiness. Boot, restart and
import never dial. Existing `caller.py` remains the local one-call experience.

The socket is `/run/ivr/control.sock`, owned by the service user, mode 0600,
inside systemd's RuntimeDirectory with mode 0700. Operate it via SSH and
`sudo -u ivr ... cloud_runner.py start` or `status`. No new HTTP controls.
Only literal `start\n` and `status\n` commands are supported, capped at 64 bytes
with a two-second read timeout. Limit control handlers to four; reject excess
connections. Commands accept no phone number, settings, path or arbitrary JSON.

`start` reserves one call through the existing Caller.start(), acknowledges it
immediately, and exits. `status` reports a sanitized stage, done flag, outcome
and exit code, never call IDs or transcripts. Serialize start acceptance so two
requests cannot dial twice. If an acknowledgment is lost, query status instead
of retrying blindly. Disconnecting SSH never cancels the call.

Keep the server and its controllers alive after caller.done. Signed late events
still receive the usual acknowledgment; completed client state remains absorbing.
One outbound call per process is deliberate: additional starts return busy while
active or restart_required after completion. Preserve the fixture's normal manual
call capability. Restart explicitly only after both legs are known ended and at
least 60 seconds have passed after completion; this observation interval is not a
promise that every provider retry arrived. Unknown cleanup requires provider call
status inspection/manual termination before restart. Reboot never resumes a call.

Systemd runs the service with Restart=on-failure, bounded restart rate, and a
60-second shutdown allowance for both existing controller cleanup paths. Caddy
is a separate service. On shutdown close the socket, stop admission, then let
the app lifespan clean up controllers and HTTP clients. Preserve local outcomes
in sanitized journal logs, since in-memory status is lost after restart.

## Speech configuration and diagnostic evidence

Promote track selection to `IVR_CLIENT_TRANSCRIPTION_TRACK`, allowed values
inbound/outbound, with existing outbound default to preserve local behavior.
Set inbound explicitly in the VM environment based on the observed test. Use
the existing dial-time transcription method for the initial deployment; record
that explicit-start/inbound has been observed but dial-time/inbound has not.
Do not silently implement a second transcription startup path or use both tracks.

Add sanitized request diagnostics: path, HTTP status and duration, without headers,
query strings or body. For verified transcription events log booleans for final,
matching call/leg/application, plus parser pending/complete/invalid and current
stage. Do not log the spoken challenge, ID or amount. Preserve final-only gating,
all authentication checks, original response codes, and bounded in-memory state.

Public and local request outcomes distinguish transport loss from rejection.
Counters of final/interim events distinguish speech finalization from parser
failure. If final events are still absent, investigate separately; do not accept
partials as a shortcut or mark cloud deployment as lesson acceptance.

## Cutover, rollback and acceptance

Before changing Telnyx, validate the VM's certificate and unsigned POST 401s from
outside the VM, with a small sequential/concurrent sample. Unknown public routes
must return 404; GET webhooks must not trigger commands. Verify startup/restart
produces zero dial requests and local control is unreachable over HTTPS.

Record both existing callback URLs privately, then change only the two Voice API
application callback URLs to the new hostname with the existing paths. Inspect
failover settings to prevent stale routing to an inactive Mac; record any change.
Do not modify number assignment, caller ID, engine or fixture scenario at cutover.

Use one learner-authorized live test, capture delivered/failed counts, sanitized
final/interim counters, progression and both hangups. Keep the server up to observe
late events. Repeat calls only within the learner's authorized test scope. Cloud
ingress acceptance and full Lesson 3 acceptance are separate records.

Rollback: end active calls, restore the recorded Telnyx URLs, verify local Funnel
connectivity, and run the original local command. Stop the VM after rollback if
not needed; release disk/IP/network resources only during explicit teardown.
Document exact named resources and DNS removal, without deleting shared resources.

Planning delivers this spec and its plan. Implementation, cost approval,
provisioning, DNS/callback cutover and live acceptance remain separate uncompleted
steps; no account-specific values or successful outcomes are invented.
