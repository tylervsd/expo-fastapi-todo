# Phase 22: Cloud KMS and encryption lifecycle

**Status:** Spec and implementation authorized by the learner on 2026-09-18. Expanded with learner approval to encrypted registration names; full-stack implementation complete and locally verified. The learner reported successful live completion and signed off on 2026-09-20; individual live artifacts were not independently captured.

**Context:** Based on `main` at `a0a9a5e`, following Phase 21. The learner will be CTO of Accountable, a fintech handling customer PII. This is an educational application feature and isolated lifecycle lab, not Accountable's production encryption design or compliance evidence. Use invented names during acceptance.

**Related:** [Implementation plan](../plans/2026-09-18-cloud-kms.md), [walkthrough](../../guides/22-cloud-kms.md), [curriculum](../../curriculum-roadmap.md#22-cloud-kms-and-encryption-lifecycle).

## Primary full-stack use case (approved extension)

Registration on web/iOS adds an optional real-name field. The API accepts omitted/null names for existing clients, but supplied names must trim to 1–100 Unicode code points with no control/surrogate characters. No requirement for a western first/last-name structure. Store only `users.real_name_ciphertext` (nullable PostgreSQL BYTEA), never a plaintext column. Names are not searchable and are not copied into tokens, workflow records, analytics, logs, traces or persisted client storage.

Use direct Cloud KMS encryption via the supported Python SDK with CRC32C integrity verification and a 3-second timeout, no automatic RPC retries. Associated data is `fullstack:users:real_name:v1:<public UUID>`; copying ciphertext to another user's row must fail authentication. KMS embeds the version in its ciphertext; only the configured logical key resource is needed for reads. The application supports version rotation within that key, not changing to a new logical key without an explicit data migration.

One concrete `NameCipher` handles encrypt/decrypt; tests inject its KMS client. Configure `REAL_NAME_KMS_KEY` at startup. If absent, old nameless signup still works, while signup supplying a name fails 503 (never store plaintext or silently discard it). If present but malformed, fail startup. The production entry point has no fake encryption mode. Initialize/close the SDK client with the application lifespan.

Generate the public UUID and encrypt before opening the signup write transaction; a KMS failure must create no account. Signup's response does not return a name. After successful credential verification and session commit, login may return the decrypted name; `/auth/me` does the same only after resolving the authenticated user. No decrypt on bad credentials, anonymous requests or normal todo operations. Missing/unavailable/tampered ciphertext produces no name in the response and a safe operational failure event; authentication remains usable. Successful signup/login/profile responses use `Cache-Control: no-store`; auth validation errors must not echo raw inputs/context. Never emit raw KMS exception messages.

`UserPublic.real_name` is optional and omitted when unavailable, preserving the existing nameless response shape. New clients accept both shapes, reject unknown response fields and malformed names, and show `Welcome, <real name or username>`. Keep the name in session memory only; clear it on sign-out/account replacement and clear the registration draft on success/mode change. UI names are optional for compatibility, visibly labeled, bounded and accessible. Browser/iOS share the existing native form and header.

Provision an opt-in `real_name_encryption` setting in the existing sandbox Terraform root, default false. It owns a separate `fullstack-profile` ring / `real-name` software symmetric key with the same 90-day rotation and 30-day destruction window and deletion protections. Grant only `var.api.identity` key-scoped encrypt/decrypt. Set `REAL_NAME_KMS_KEY` only on API Cloud Run; no worker, invoker, migration, browser or lab identity receives access. The KMS API remains owned by the existing phase22 lab root; enable that root first. Do not disable/delete application keys for drills. No KMS secrets in Terraform state.

Deploy the migration before the API, provision the application key/configuration, and deploy compatible web/iOS clients before using named accounts; old clients can reject named responses, so coordinate their retirement. During staged rollout, name-bearing signup requires the new API and working KMS permissions. Keep the additive column and key on rollback. Existing users remain NULL; there is no backfill or profile editor. Missing name is a username fallback, not a reason to guess a legal name.

Verify SDK CRC/AAD/timeout contracts, database ciphertext and no-account-on-failure, owner isolation and invalid-login no-decrypt, safe degradation and privacy, Unicode names, legacy responses and session restoration, frontend form/header behavior, and a credential-free browser journey. Mock KMS is test-only and never proves real encryption/IAM. Live acceptance additionally inspects the stored column, rotates the application key safely, verifies old/new names, and records web/iOS checks and privacy evidence. No destructive drills on this key.

## Isolated lifecycle lab and choice

Encrypt one synthetic customer fixture, recover it with an authorized identity, reject an encrypt-only identity's decrypt, rotate the key, and prove that the old ciphertext still depends on the old version. Disable/re-enable that version and rehearse cancelling scheduled destruction on a separate unused version. Record audit evidence and the dependency checks needed before any real key retirement.

Three approaches were considered:

1. **Direct KMS lab — selected:** native KMS operations and a small stdlib Python fixture runner. Teaches key permissions and lifecycle without changing the application or implementing cryptography.
2. **Application envelope encryption:** useful for a later concrete field-level threat model, but adds a cryptography dependency, data-key handling, and a persistent format beyond this lesson.
3. **CMEK on existing Cloud SQL/storage:** teaches service integration, but couples this exercise to live application availability and backups. Explain the integration boundary without migrating existing resources.

## Scope and threat model

The synthetic fixture contains an invented customer ID, name, and `example.test` email, marked synthetic. The runner has no arbitrary plaintext input option. The exercise assumes an observer can obtain the saved ciphertext bundle but lacks KMS decrypt permission. It does not protect plaintext from an authorized decrypting process, a compromised operator who can impersonate that process, or an owner who can grant themselves access.

Explain four distinct controls: provider-default encryption at rest; CMEK used by a managed service's identity; application envelope encryption with a local data-encryption key wrapped by KMS; and Secret Manager for application secrets. Distinguish data minimization, authorization and retention from encryption. No claims that KMS alone satisfies fintech regulation.

## Infrastructure and ownership

Add a standalone `infra/terraform/kms-lab` root, reusing Terraform **1.14.7**, Google provider **8.2.0**, and the existing lockfile hashes. Use a separate partial GCS backend prefix `fullstack/phase22-kms`; never share the sandbox state prefix. Project and regional location are explicit deployment inputs. Use the application's region if appropriate after checking residency needs; do not guess Accountable's requirements.

Create one key ring `phase22-lab`, one `synthetic-pii` key with `ENCRYPT_DECRYPT`, software protection and `GOOGLE_SYMMETRIC_ENCRYPTION`. Automatic rotation is **7776000 seconds (90 days)**, a teaching default, not a regulatory rule. Destruction scheduling is **2592000 seconds (30 days)**. Keep `prevent_destroy = true` and provider `deletion_policy = "PREVENT"` on the key. The root manages key configuration, not individual versions: manual rotation and recovery use gcloud, so Terraform cannot attempt to reconcile version states.

Enable only the Cloud KMS API with `disable_on_destroy = false`. IAM and IAM Credentials APIs are existing sandbox prerequisites and remain owned there. If Cloud KMS is already managed by another root, resolve its single owner before applying; do not manage the same API resource in two states. Two new service accounts get additive, key-scoped grants:

| Identity | Grant | Purpose |
| --- | --- | --- |
| `phase22-reader` | `roles/cloudkms.cryptoKeyEncrypterDecrypter` | Seal and verify fixtures |
| `phase22-writer` | `roles/cloudkms.cryptoKeyEncrypter` | Encrypt successfully, fail to decrypt |
| Explicit learner user | `roles/iam.serviceAccountTokenCreator` on those two accounts only | Temporary impersonation; no downloaded keys |

Do not grant any application runtime identity permissions on the lab key; the application has its own key-scoped grant described above. Provisioning/lifecycle admin rights remain with the existing authorized operator; no project-wide KMS grants are added. Explain that the learner can impersonate both accounts, so this demonstrates separate workload permissions, not organizational dual control. Check inherited roles and impersonation paths during live acceptance.

Audit configuration is an explicit prerequisite: inventory existing Cloud KMS `DATA_READ` logging (encrypt and decrypt use it) and enable it through the existing IAM-policy owner if absent. Do not add an authoritative project audit-policy resource here that could replace exemptions or conflict with another owner. Admin Activity and Data Access evidence are separate acceptance rows.

## Fixture runner and format

Add `scripts/kms_lab.py` with two commands:

```sh
python3 scripts/kms_lab.py seal --key-version "$VERSION_RESOURCE" --identity "$READER" --bundle artifacts/kms-lab/before.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
```

`seal` encrypts only the built-in synthetic fixture, explicitly selecting the supplied version to make the experiment reproducible. The guide obtains the current primary immediately before each seal and shows it changing after rotation. `check` decrypts through the key (KMS selects the ciphertext's actual version) and compares exact fixture bytes without printing plaintext.

The JSON bundle contains only `schema: 1`, `key_version` (full resource name) and base64 `ciphertext`. Canonical JSON of schema and key-version metadata is supplied as additional authenticated data (AAD), binding metadata to ciphertext. AAD is not secret. Resource validation restricts keys to `phase22-lab/synthetic-pii` and identities to this lab's two accounts in the same project. Reject malformed/extra fields, invalid or oversized ciphertext, unsupported schema, and invalid resource paths before calling gcloud. Keep gcloud integrity verification enabled and use argument lists, never a shell.

Use private temporary files, clean them on success and failure, bounded subprocess timeouts, sanitized failures and no plaintext/token logs. New bundles must not overwrite existing files, including symlinks; store with mode 0600. A partial write must not leave a valid-looking bundle. `artifacts/kms-lab/` is ignored. This fixture runner introduces no SDK or application dependencies of its own; the full-stack feature above uses the KMS SDK. Neither path makes paid CI calls or invents cryptographic primitives.

## Lifecycle and recovery

- Capture the primary version, seal/check a bundle, and record its hash.
- Create a new primary version. Seal/check a second bundle with the observed new version. Verify the first bundle's hash is unchanged and it still decrypts.
- Disable the old, non-primary version. Verify old ciphertext fails because of that version's state, while new ciphertext still works. IAM/API failures must not be counted as state evidence. Allow for propagation; stop and investigate unexpected results.
- Re-enable the old version and verify the original bundle decrypts again.
- For re-encryption, decrypt and verify the old fixture, then seal a replacement under the new primary. Keep the original until replacement verification succeeds. Rewriting current data does not remove old key dependencies from backups, exports, caches or retained state.
- Create a separate **unused, non-primary** version for the destroy/restore exercise. Check dependencies, schedule destruction, capture the deadline, restore immediately, observe `DISABLED`, then enable. Never schedule a version referenced by either saved fixture, shorten the 30-day window, or wait for irreversible destruction for this lesson.
- Before ending, verify every dependency-bearing version is enabled, no version is `DESTROY_SCHEDULED`, both bundles decrypt, and Terraform has no unexplained drift. If interrupted after scheduling, restore the unused version first; if interrupted after disable, enable the original version first.

The runner has no lifecycle mutation commands. These remain explicit walkthrough steps with exact version checks and a destruction checklist. `prevent_destroy` does not protect against gcloud/API commands or removing protections; Terraform state is not a backup of key material.

## Cost and acceptance

Provisioning creates billable resources; review current [Cloud KMS pricing](https://cloud.google.com/kms/pricing) with the existing project budget before apply. Bound the normal exercise to one initial version, one rotation, and one unused recovery version. Re-running version creation increases persistent costs. Rotation keeps creating versions; disabled versions may remain billable. Decommissioning needs dependency inventory and a separate retirement decision, not `terraform destroy` as an automatic cleanup step.

Local acceptance requires stdlib runner tests with gcloud replaced at the subprocess boundary, Terraform mock-plan checks, formatting/validation, and Markdown/link checks. These cannot establish real IAM propagation, encryption, audit delivery or key recovery. Live acceptance requires observed results for all lifecycle steps above, correct KMS denial evidence, tampered metadata/ciphertext rejection, audit identities/methods, and learner sign-off. Do not label the phase complete based only on mocks.

## Sources checked on 2026-09-18

- [KMS rotation](https://docs.cloud.google.com/kms/docs/key-rotation) and [re-encryption](https://docs.cloud.google.com/kms/docs/re-encrypt-data).
- [Destroy and restore](https://docs.cloud.google.com/kms/docs/destroy-restore) and [version states](https://docs.cloud.google.com/kms/docs/key-states).
- [Envelope encryption](https://docs.cloud.google.com/kms/docs/envelope-encryption) and [audit logging](https://docs.cloud.google.com/kms/docs/audit-logging).
- [gcloud encrypt](https://docs.cloud.google.com/sdk/gcloud/reference/kms/encrypt) and [provider 8.2.0 key resource](https://github.com/hashicorp/terraform-provider-google/blob/v8.2.0/website/docs/r/kms_crypto_key.html.markdown).
