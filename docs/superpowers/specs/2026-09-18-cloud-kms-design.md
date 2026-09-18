# Phase 22: Cloud KMS and encryption lifecycle

**Status:** Spec and implementation authorized by the learner on 2026-09-18. Local implementation and offline verification complete; cloud provisioning and learner acceptance are separate, unobserved steps.

**Context:** Based on `main` at `a0a9a5e`, following Phase 21. The learner will be CTO of Accountable, a fintech handling customer PII. This is an educational lab using invented data, not Accountable's production encryption design or compliance evidence.

**Related:** [Implementation plan](../plans/2026-09-18-cloud-kms.md), [walkthrough](../../guides/22-cloud-kms.md), [curriculum](../../curriculum-roadmap.md#22-cloud-kms-and-encryption-lifecycle).

## Outcome and choice

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

Do not grant any application runtime identity KMS permissions. Provisioning/lifecycle admin rights remain with the existing authorized operator; no project-wide KMS grants are added. Explain that the learner can impersonate both accounts, so this demonstrates separate workload permissions, not organizational dual control. Check inherited roles and impersonation paths during live acceptance.

Audit configuration is an explicit prerequisite: inventory existing Cloud KMS `DATA_READ` logging (encrypt and decrypt use it) and enable it through the existing IAM-policy owner if absent. Do not add an authoritative project audit-policy resource here that could replace exemptions or conflict with another owner. Admin Activity and Data Access evidence are separate acceptance rows.

## Fixture runner and format

Add `scripts/kms_lab.py` with two commands:

```sh
python3 scripts/kms_lab.py seal --key-version "$VERSION_RESOURCE" --identity "$READER" --bundle artifacts/kms-lab/before.json
python3 scripts/kms_lab.py check --identity "$READER" --bundle artifacts/kms-lab/before.json
```

`seal` encrypts only the built-in synthetic fixture, explicitly selecting the supplied version to make the experiment reproducible. The guide obtains the current primary immediately before each seal and shows it changing after rotation. `check` decrypts through the key (KMS selects the ciphertext's actual version) and compares exact fixture bytes without printing plaintext.

The JSON bundle contains only `schema: 1`, `key_version` (full resource name) and base64 `ciphertext`. Canonical JSON of schema and key-version metadata is supplied as additional authenticated data (AAD), binding metadata to ciphertext. AAD is not secret. Resource validation restricts keys to `phase22-lab/synthetic-pii` and identities to this lab's two accounts in the same project. Reject malformed/extra fields, invalid or oversized ciphertext, unsupported schema, and invalid resource paths before calling gcloud. Keep gcloud integrity verification enabled and use argument lists, never a shell.

Use private temporary files, clean them on success and failure, bounded subprocess timeouts, sanitized failures and no plaintext/token logs. New bundles must not overwrite existing files, including symlinks; store with mode 0600. A partial write must not leave a valid-looking bundle. `artifacts/kms-lab/` is ignored. No SDK, cryptographic primitive, API route, database migration, UI or paid CI call is introduced.

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
