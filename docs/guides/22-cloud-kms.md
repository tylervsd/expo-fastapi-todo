# Phase 22: Cloud KMS and encryption lifecycle

**Status:** Local lab implementation; live provisioning and learner acceptance have not been performed. Use synthetic data only. [Spec](../superpowers/specs/2026-09-18-cloud-kms-design.md) and [implementation plan](../superpowers/plans/2026-09-18-cloud-kms.md).

## 1. What you should learn as a fintech CTO

The question is who can recover plaintext, under which authority, and what happens when that authority or key disappears. This lab separates the permissions needed to administer a key from those needed to use it. An operator who can impersonate both lab accounts still has access to both; this is not a demonstration of organizational dual control.

| Control | Who uses the key? | What to investigate |
| --- | --- | --- |
| Default encryption at rest | Google-managed storage systems | Application access still returns plaintext; storage encryption is not customer authorization |
| Customer-managed encryption keys (CMEK) | A managed service's service agent | Service-specific location, permissions, key-version adoption and backup recovery behavior |
| Application envelope encryption | Your application encrypts data with a data key and wraps that key with KMS | Ciphertext format, authenticated context, wrapped-key storage, plaintext lifetime, migration and recovery |
| Secret Manager | Authorized workloads retrieve a stored secret | Secret access and version rollout; this is where an API credential belongs |

The runnable lab uses **direct KMS encryption of a tiny fixture**. It does not implement envelope encryption or enable CMEK on Cloud SQL. See Google's [envelope encryption explanation](https://docs.cloud.google.com/kms/docs/envelope-encryption) for the separate data-key and wrapping-key roles. Larger application payloads need an appropriate encryption design, not a bigger version of this script.

For Accountable, separately inventory necessary PII, access paths, support/export tools, log exposure, retention, and backups. Classify the data and threat model before selecting field-level encryption or key boundaries. This lab is not a production architecture or compliance assessment.

## 2. Local checks and prerequisites

Run from the phase 22 worktree root. Use the project's pinned Terraform binary; [Terraform setup](../../infra/terraform/README.md#local-tooling) explains installation.

```sh
pnpm test:kms
terraform -chdir=infra/terraform/kms-lab init -backend=false -lockfile=readonly
terraform -chdir=infra/terraform/kms-lab fmt -check -recursive
terraform -chdir=infra/terraform/kms-lab validate
terraform -chdir=infra/terraform/kms-lab test -no-color
python3 scripts/kms_lab.py --help
```

These checks use mocked cloud boundaries. They establish neither encryption nor deployed permissions. Live steps below require gcloud login, Terraform ADC, an existing non-production project, the existing protected state bucket, and an operator authorized to provision resources and administer this lab key. Do not download service-account keys.

Before provisioning:

- Select the actual project and regional location; confirm residency and billing. Replace example values in ignored local configuration.
- IAM and IAM Credentials APIs are existing sandbox prerequisites. This root owns only `cloudkms.googleapis.com`; confirm another Terraform state does not already own that API resource or these lab names. Resolve ownership/imports before apply, not with two competing roots.
- Inventory Cloud KMS Data Access audit settings. Encrypt/decrypt use `DATA_READ`. Enable that category through the current IAM-policy owner if absent, preserving existing exemptions and other settings. Make this an explicit reviewed policy change. Ensure the learner can read private audit logs. [KMS audit reference](https://docs.cloud.google.com/kms/docs/audit-logging).
- Review current [KMS pricing](https://cloud.google.com/kms/pricing) and existing project budget. This drill normally leaves three software key versions. Repeating rotation creates additional versions; disabling does not necessarily end charges. Audit-log storage can also cost money. Budget alerts are not a spending cap.

## 3. Provision the separate lab

Copy the example files, then edit both copies with the actual project, region, learner email and state bucket. Use the separate `fullstack/phase22-kms` prefix; never the sandbox prefix.

```sh
cp infra/terraform/kms-lab/terraform.tfvars.example infra/terraform/kms-lab/terraform.tfvars
cp infra/terraform/kms-lab/backend.hcl.example infra/terraform/kms-lab/backend.hcl
```

Review the edited configuration before running:

```sh
terraform -chdir=infra/terraform/kms-lab init -backend-config=backend.hcl
terraform -chdir=infra/terraform/kms-lab plan -out=lab.tfplan
terraform -chdir=infra/terraform/kms-lab show lab.tfplan
```

The intended plan creates one API-enablement resource, one ring, one software symmetric key, two service accounts, two key IAM grants, and two account-scoped impersonation grants: **nine resources**. No database, Cloud Run, secret payload, public IAM grant, project-wide crypto permission, or existing key replacement belongs here. If names already exist, inspect/import their actual configuration or resolve the collision; do not rename blindly to accumulate keys.

After reviewing that concrete plan and its cost, apply it:

```sh
terraform -chdir=infra/terraform/kms-lab apply lab.tfplan
export KEY_ID="$(terraform -chdir=infra/terraform/kms-lab output -raw key_id)"
export READER="$(terraform -chdir=infra/terraform/kms-lab output -raw reader_email)"
export WRITER="$(terraform -chdir=infra/terraform/kms-lab output -raw writer_email)"
export LAB_PROJECT="$(printf '%s' "$KEY_ID" | cut -d/ -f2)"
export LAB_REGION="$(printf '%s' "$KEY_ID" | cut -d/ -f4)"
mkdir -p artifacts/kms-lab
chmod 700 artifacts/kms-lab
umask 077
```

Verify the full `KEY_ID` matches the selected project and regional location and ends in `/keyRings/phase22-lab/cryptoKeys/synthetic-pii`. The runner also validates those lab names and same-project lab identities. Use a shell with no ambient gcloud impersonation for lifecycle administration; encryption commands explicitly impersonate their stated service account.

The key has a 90-day rotation interval and a 30-day destruction delay. These are lab settings, not fintech regulatory requirements. `prevent_destroy` and provider `deletion_policy = "PREVENT"` protect Terraform operations; they do not prevent gcloud/API state changes.

## 4. First ciphertext and permissions

Read the primary version using the lifecycle operator. The crypto identity intentionally does not need key-metadata administration rights.

```sh
export BEFORE="$(gcloud kms keys describe synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='value(primary.name)')"
python3 scripts/kms_lab.py seal --key-version "$BEFORE" --identity "$READER" --bundle artifacts/kms-lab/before.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
shasum -a 256 artifacts/kms-lab/before.json > artifacts/kms-lab/before.sha256
```

The runner generates an invented customer record internally; there is no plaintext input option. The saved bundle carries schema, full key-version metadata, and base64 ciphertext. Metadata is authenticated as AAD. Temporary plaintext is removed after the command, not printed. Temporary-file deletion is not a secure erasure guarantee, another reason to use only the built-in fixture.

Now prove the writer can encrypt, and the reader can recover what it writes:

```sh
python3 scripts/kms_lab.py seal --key-version "$BEFORE" --identity "$WRITER" --bundle artifacts/kms-lab/writer.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/writer.json
python3 scripts/kms_lab.py check --identity "$WRITER" --bundle artifacts/kms-lab/writer.json
```

The final command must fail. Confirm a KMS denial of `cloudkms.cryptoKeyVersions.useToDecrypt` for **phase22-writer**, with successful writer encryption and reader decryption as controls. An impersonation failure, missing API, expired login, malformed bundle, or networking problem is not evidence of correct key IAM. Inspect inherited project/folder roles if writer decryption unexpectedly succeeds.

### Diagnose an expected rejection

The runner intentionally suppresses raw gcloud errors. For a negative test, use this synthetic-only diagnostic function in your shell to see gcloud's actual rejection. It reconstructs the bundle's ciphertext and AAD without printing plaintext. Its return status is gcloud's status; a successful decrypt here does not verify the fixture, so use the runner for positive checks.

```sh
kms_diagnose() (
  set -eu
  diagnostic_dir="$(mktemp -d)"
  trap 'rm -rf "$diagnostic_dir"' EXIT
  python3 - "$1" "$diagnostic_dir" <<'PY'
import base64, json, pathlib, sys
bundle = json.loads(pathlib.Path(sys.argv[1]).read_text())
directory = pathlib.Path(sys.argv[2])
(directory / "cipher").write_bytes(base64.b64decode(bundle["ciphertext"], validate=True))
metadata = {"schema": bundle["schema"], "key_version": bundle["key_version"]}
(directory / "aad").write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")))
PY
  gcloud kms decrypt --key=synthetic-pii --keyring=phase22-lab \
    --location="$LAB_REGION" --project="$LAB_PROJECT" \
    --impersonate-service-account="$2" \
    --ciphertext-file="$diagnostic_dir/cipher" --plaintext-file="$diagnostic_dir/plain" \
    --additional-authenticated-data-file="$diagnostic_dir/aad"
)
kms_diagnose artifacts/kms-lab/writer.json "$WRITER"
```

Keep diagnostic output private and record only the relevant error code/permission, method, identity and timestamp in acceptance evidence. Do not enable HTTP debug logging. Allow IAM propagation, then retry the same read/check; do not respond to a denial by broadening permissions automatically.

## 5. Rotate without rewriting old data

This is one manual rotation to observe immediately; verify the configured automatic schedule separately. Do not repeat version creation merely because a local command timed out: inspect the version list first.

```sh
gcloud kms keys versions create --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --primary
export AFTER="$(gcloud kms keys describe synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='value(primary.name)')"
test -n "$AFTER" && test "$BEFORE" != "$AFTER"
python3 scripts/kms_lab.py seal --key-version "$AFTER" --identity "$READER" --bundle artifacts/kms-lab/after.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/after.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
shasum -a 256 -c artifacts/kms-lab/before.sha256
```

Stop if the version comparison fails. The runner pins the observed version for reproducibility; normal KMS encryption without a version uses the key's primary. Observe the distinct bundle metadata and unchanged old file. [Rotation creates a new primary without rewriting old ciphertext](https://docs.cloud.google.com/kms/docs/key-rotation).

## 6. Disable and recover the old version

Perform this only on this lab's original non-primary version. Keep these recovery commands and version IDs available outside the shell before disabling anything. `writer.json` also uses the old version.

```sh
export OLD_NUMBER="${BEFORE##*/}"
export CURRENT_PRIMARY="$(gcloud kms keys describe synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='value(primary.name)')"
if test -n "$OLD_NUMBER" && test -n "$CURRENT_PRIMARY" && \
   test "$BEFORE" = "$KEY_ID/cryptoKeyVersions/$OLD_NUMBER" && test "$BEFORE" != "$CURRENT_PRIMARY"; then
  gcloud kms keys versions disable "$OLD_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT"
else
  printf '%s\n' 'STOP: old non-primary version checks failed.'
fi
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
kms_diagnose artifacts/kms-lab/before.json "$READER"
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/after.json
```

The original bundle must fail due to its disabled version; the new one must still pass. Verify the version state and actual error, allowing for propagation. Run negative commands individually; do not paste the entire guide into an unattended `set -e` script that exits before recovery.

**Recovery, including after interruption:**

```sh
gcloud kms keys versions enable "$OLD_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT"
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/writer.json
```

Re-encryption is a separate operation. For this fixed fixture, first recover and verify the old value, then seal the same known bytes under the new version and verify the replacement. Keep the original:

```sh
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json && \
python3 scripts/kms_lab.py seal --key-version "$AFTER" --identity "$READER" --bundle artifacts/kms-lab/replacement.json && \
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/replacement.json
```

This is a fixture-only illustration, not a migration tool for arbitrary customer data. For envelope encryption, determine whether to rewrap data keys or re-encrypt payloads from the threat model. Updating current records does not update old backups or exports. See [re-encryption responsibilities](https://docs.cloud.google.com/kms/docs/re-encrypt-data).

## 7. Schedule and cancel destruction on an unused version

Do not schedule `BEFORE` or `AFTER`, which have known ciphertext dependencies. Create one extra version **without** `--primary`; never encrypt a fixture with it:

```sh
export UNUSED="$(gcloud kms keys versions create --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='value(name)')"
export UNUSED_NUMBER="${UNUSED##*/}"
gcloud kms keys versions list --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='table(name,state,destroyTime)'
```

Before the next commands, review the exact resource and confirm:

- It is the newly created unused version in this non-production lab, not a current primary or a saved bundle's version. If creation's response was lost, list versions and identify it before creating another.
- No fixture, backup, export, wrapped data key, service CMEK setting, or retained Terraform/backend dependency uses this version. Labels or lack of recent audit traffic alone cannot prove that.
- You have authority to schedule destruction, a working restore identity, the 30-day window, and time to restore immediately. Record the version name somewhere durable outside shell history before proceeding.

The following guard runs before the destructive scheduling command. A separate unused version lets you learn the state transition without retiring data-bearing key material.

```sh
CURRENT_PRIMARY="$(gcloud kms keys describe synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='value(primary.name)')"
if test -n "$UNUSED_NUMBER" && test -n "$CURRENT_PRIMARY" && \
   test "$UNUSED" = "$KEY_ID/cryptoKeyVersions/$UNUSED_NUMBER" && \
   test "$UNUSED" != "$CURRENT_PRIMARY" && test "$UNUSED" != "$BEFORE" && test "$UNUSED" != "$AFTER"; then
  gcloud kms keys versions destroy "$UNUSED_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT"
else
  printf '%s\n' 'STOP: unused-version checks failed.'
fi
gcloud kms keys versions describe "$UNUSED_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='yaml(name,state,destroyTime)'
```

Observe `DESTROY_SCHEDULED` and its deadline. **Restore immediately; do not wait for destruction.** If the scheduling command failed or its response was lost, inspect state first. If interrupted, find the scheduled version with the list command above and restore it before doing any other exercise.

```sh
gcloud kms keys versions restore "$UNUSED_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT"
gcloud kms keys versions describe "$UNUSED_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='yaml(name,state)'
gcloud kms keys versions enable "$UNUSED_NUMBER" --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT"
```

Observe `DISABLED` after restore, then `ENABLED` after enable. [Restoration cancels scheduled destruction; it does not immediately enable the version](https://docs.cloud.google.com/kms/docs/destroy-restore). Once material is irreversibly destroyed, an application database backup or Terraform state cannot recreate it.

## 8. Tamper rejection and audit evidence

Keep the originals. Make a copy with changed key-version metadata; both versions must currently be enabled so the failure is about authentication, not lifecycle state:

```sh
python3 - <<'PY'
import json, os, pathlib
source = pathlib.Path("artifacts/kms-lab/before.json")
document = json.loads(source.read_text())
document["key_version"] = os.environ["AFTER"]
with pathlib.Path("artifacts/kms-lab/tampered.json").open("x") as output:
    json.dump(document, output)
PY
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/tampered.json
kms_diagnose artifacts/kms-lab/tampered.json "$READER"
```

Verify a KMS authentication/decryption failure with correct identity and enabled original version; check the untouched original still succeeds. Repeat for ciphertext tampering:

```sh
python3 - <<'PY'
import base64, json, pathlib
document = json.loads(pathlib.Path("artifacts/kms-lab/before.json").read_text())
ciphertext = bytearray(base64.b64decode(document["ciphertext"], validate=True))
ciphertext[-1] ^= 1
document["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
with pathlib.Path("artifacts/kms-lab/tampered-ciphertext.json").open("x") as output:
    json.dump(document, output)
PY
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/tampered-ciphertext.json
kms_diagnose artifacts/kms-lab/tampered-ciphertext.json "$READER"
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
```

Inspect recent audit metadata, not request/response payload dumps:

```sh
gcloud logging read 'protoPayload.serviceName="cloudkms.googleapis.com"' \
  --project="$LAB_PROJECT" --freshness=1h --limit=100 \
  --format='table(timestamp,logName,protoPayload.methodName,protoPayload.authenticationInfo.principalEmail,protoPayload.resourceName,protoPayload.status.code)'
```

Find encrypt/decrypt under the reader/writer identities and administration under the lifecycle operator. Distinguish Admin Activity from Data Access. Check impersonation delegation information privately if needed. If data-access events are missing, resolve logging configuration, viewer permission and ingestion delay; absence is not proof no data was accessed. Retain only redacted evidence links and resource IDs, not tokens or customer content.

## 9. Finish safely and record acceptance

```sh
gcloud kms keys versions list --key=synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='table(name,state,destroyTime)'
gcloud kms keys describe synthetic-pii --keyring=phase22-lab --location="$LAB_REGION" --project="$LAB_PROJECT" --format='yaml(primary.name,rotationPeriod,nextRotationTime,destroyScheduledDuration)'
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/after.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/writer.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/replacement.json
terraform -chdir=infra/terraform/kms-lab plan -detailed-exitcode
```

Confirm no `DESTROY_SCHEDULED` versions remain, dependency-bearing versions are enabled, primary and automatic schedule are correct, and the final plan exits 0. Exit 2 means changes to review; exit 1 means an error. Do not apply unexplained drift automatically.

Do not use `terraform destroy` for routine cleanup. Leave the protected key and versions available for the retained fixtures; review ongoing version/rotation cost. If retiring the lab, separately inventory dependencies, decide what ciphertext to delete/retain, stop automatic rotation through reviewed configuration, revoke unnecessary impersonation, and retire versions only under an explicit recovery/destruction decision. Do not remove deletion protections merely to make cleanup pass.

| Acceptance item | Evidence/status |
| --- | --- |
| Local runner tests and Terraform mock checks | See local verification record below |
| Correct project/region, isolated backend, reviewed plan/cost | Not performed |
| Reader round trip; writer encrypt succeeds/decrypt denied for the correct permission | Not performed |
| New primary, new ciphertext, unchanged old ciphertext still decrypts | Not performed |
| Old version disabled: old fails for state, new passes; original restored | Not performed |
| Verified replacement; backup/export dependencies explained | Not performed |
| Unused version scheduled with deadline, restored disabled, re-enabled | Not performed |
| Changed metadata and ciphertext rejected; original control passes | Not performed |
| Admin and Data Access audit identities/methods observed | Not performed |
| No scheduled destruction, all fixtures decrypt, no-change final plan | Not performed |
| Learner sign-off | Pending |

### Local verification record

Observed on 2026-09-18:

- Nine Python runner tests pass; only the gcloud subprocess is faked. Initial tests failed before implementation. Atomic publication and concurrent no-clobber behavior are covered.
- Four Terraform mock-plan runs pass; `fmt -check` and `validate` pass against Terraform 1.14.7 / Google 8.2.0. Tests first failed on absent lab resources. Provider socket access required running offline Terraform checks outside the filesystem sandbox.
- Ruff, changed-document Markdown lint, relative file-link checks, and walkthrough shell syntax checks pass. The gcloud encryption flags were checked against the installed CLI's help.
- The 21 repository contract checks pass.
- The pnpm wrapper initially attempted an unnecessary dependency install in the fresh worktree and hit restricted network access. The same `test:kms` command passed with `pnpm_config_verify_deps_before_run=false`; no dependency changes were made.

No real cloud API, IAM, billing, encryption, audit delivery or recovery results are implied by these checks. All live acceptance rows remain pending.
