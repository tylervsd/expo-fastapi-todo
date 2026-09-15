# Phase 18: Terraform and reproducible Google infrastructure

## Status and outcome

Planning prepared on 2026-09-14 from `main` at `d845c58`, after the learner
signed off Phase 17. Terraform code, credential-free checks, and the manual
guide are implemented. Core cloud adoption is learner-completed: 25 resources
imported with a follow-up no-change plan and exit code 0. The learner agreed
to defer recovery/destruction steps 7–8 (A10/A11 and drill portions of A3);
these are not passed checks. Final label-drift verification remains unconfirmed.
See the [guide progress record](../../guides/18-terraform.md#learner-progress-and-agreed-deferrals).
Work lives on `codex/phase-18-terraform` in `.worktrees/phase-18-terraform`.

Adopt the working Google sandbox into one Terraform root, preserve the hosted
app and data, and reach a reviewed plan showing no changes. The learner then
practices drift, state recovery, and destruction of a separate disposable
resource. Repository preparation is agent work; cloud inventory confirmation,
bootstrap, imports, applies, and hosted verification are a manual walkthrough.

## Approach and alternatives

Choose import-first adoption. Recreating the sandbox would risk Cloud SQL data,
change service addresses, duplicate costs, and obscure what adoption teaches.
A second full sandbox would isolate experimentation but duplicate resources
and cost. Instead, isolate recovery/destruction exercises in a tiny drill root
with a separate state prefix and one disposable bucket.

Use plain Terraform resources without custom modules, wrappers, Terragrunt,
or environment workspaces. The default workspace and one explicit sandbox
root are sufficient. Cloudflare stays manually managed. Phase 19 will add
GitHub authentication and automated delivery; this phase's CI has no cloud
credentials and never plans against the live environment.

## Known context and discovery boundary

The following are conversation records, not a fresh cloud inventory:

| Field | Recorded value |
| --- | --- |
| Project | `fullstack-sandbox-tylervsd` |
| Region | `us-west1` |
| Cloud Run API | `fullstack-api` |
| Runtime identity | `fullstack-run@fullstack-sandbox-tylervsd.iam.gserviceaccount.com` |
| Production web origin | `https://expo-fastapi-todo.pages.dev` |
| Former preview alias | `https://codex-phase-17-cloudflare-pa.expo-fastapi-todo.pages.dev` |
| API secret names | `openrouter-api-key`, `fullstack-database-url` |
| Working AI model | `openrouter/free` |

Discover current values before generating adoption inputs. Phase 17's final
image digest, API revision, migration job name, SQL configuration, budgets,
and monitoring IDs were not recorded. Never replace these with Phase 14
examples. The current service template can differ from the revision serving
traffic; compare both. Resolve any mismatch before adopting desired settings.

Inventory the registry, API and job identities, IAM members, enabled APIs,
secret metadata and numeric version references, Cloud SQL instance/database,
backups/PITR, authorized networks and connector settings, Cloud Run image,
command/args, environment, scaling, CPU, probes, timeouts, volumes, traffic,
public invocation mechanism, billing budget scope/thresholds, and monitoring.
Use read-only describe/list calls and retain sensitive raw exports outside Git.
Do not access secret payloads or database passwords during discovery.

## Ownership contract

| Resource | Terraform ownership and import policy |
| --- | --- |
| Existing project and billing link | Read-only `google_project` data source; never manage the project lifecycle or billing association. |
| State bucket | Manually bootstrapped and protected; intentionally outside application state. Its exact creation and recovery recipe is versioned. |
| Required project APIs | `google_project_service`, one address per required API; import existing services and set `disable_on_destroy = false`. Do not manage every enabled API indiscriminately. |
| Artifact Registry | Existing `google_artifact_registry_repository`; preserve location, format, encryption and cleanup policy. Images are released separately. |
| Service identities | Import dedicated runtime and migration service accounts; preserve existing identity separation. Default/service-agent accounts stay Google-managed. |
| IAM | Additive `*_iam_member` resources for specific owned grants. No authoritative project policy/binding replacement. Preserve unrelated members and conditions. |
| Secret containers | `google_secret_manager_secret` metadata and secret-scoped accessor members only; import replication configuration unchanged. |
| Secret versions and SQL credentials | External. No secret-version resource/data source, SQL user password, random password, or plaintext credential variable. Terraform records numeric secret references only. |
| Cloud SQL | Import existing `google_sql_database_instance` and application `google_sql_database`; preserve edition, version, tier, region, networking, storage, backups and PITR. SQL users and schema/Alembic revisions remain external. |
| API and migration job | `google_cloud_run_v2_service` and `google_cloud_run_v2_job`; import existing objects with exact image digests and current settings. Terraform never executes migrations. |
| Budget | Import the existing project-filtered `google_billing_budget` by billing-account/budget ID. If absent, use nullable budget input to omit it during adoption, then create it in the approved follow-up. Preserve thresholds and notifications; budgets do not cap spending. |
| Basic monitoring | Import existing HTTPS health uptime check and associated alert policy if present. Otherwise propose one health check and one alert policy as a separate, explicit additive plan after adoption. Use an existing verified notification channel; channel creation/verification remains manual. |
| Cloudflare Pages | External throughout Phase 18: project, builds, domains, variables and preview controls. |

Required APIs follow actual dependencies (Run, SQL Admin, Artifact Registry,
Secret Manager, Service Usage, IAM, Monitoring, Logging, and billing budgets
where needed). Import IDs and optional fields must be verified against the
pinned provider schema. Missing billing visibility or a notification channel
is a named prerequisite, not a silently skipped acceptance criterion. If a
budget is absent, its amount requires learner input before creation.

## Terraform layout and interfaces

Use `infra/terraform/sandbox/` for application state, `infra/terraform/drill/`
for exercises, and `infra/terraform/README.md` for ownership and command entry
points. No module extraction. Split the sandbox root into `versions.tf`,
`backend.tf`, `variables.tf`, `services.tf`, `iam.tf`, `secrets.tf`, `database.tf`,
`run.tf`, `operations.tf`, and `outputs.tf`. Store examples in
`backend.hcl.example` and `terraform.tfvars.example`.

Terraform CLI baseline is **1.14.7**; pin that exact version in
`infra/terraform/.terraform-version` and CI. Pin **hashicorp/google 8.2.0** in
both roots and commit their `.terraform.lock.hcl` files with Darwin ARM64 and
Linux AMD64 checksums. Use the stable provider only. Resolve a schema
incompatibility explicitly in the spec before broadening providers or changing
versions; these pins are a reproducibility baseline, not a claim of latest.

Inputs are typed, non-secret descriptions of observed resources: project,
region, image digests, service/job names, identities and member-role grants,
secret resource/version maps, non-secret env maps, SQL settings, registry
settings, API set, budget configuration, and uptime/alert configuration.
Declare complete nested object shapes during implementation from the pinned
schema. Cloud Run env maps must not overlap; reject secret-like keys such as
`OPENROUTER_API_KEY` and `DATABASE_URL` in the plain map. Require nonempty
`OPENROUTER_MODEL`, numeric secret versions, image references ending in a
SHA256 digest, and exact HTTPS CORS origins. Generate the API's JSON CORS list
with `jsonencode`; never accept Markdown links, wildcards or trailing slashes.
Final sandbox CORS contains the production origin only, following Phase 17
cleanup. Preserve all other observed non-secret variables.

Outputs: API URI, SQL connection name, registry path, runtime/migration
identity emails, and managed resource IDs. No outputs of full environment
maps, raw resource objects, secret payloads, or credentials.

## State, access, and bootstrap

Use a GCS bucket in the chosen region, with uniform bucket-level access,
public access prevention, object versioning, and Google-managed encryption.
No locked retention policy: it could prevent lock-object deletion. Keep the
bucket out of routine cleanup, with no lifecycle deletion rule in this phase.
Document small storage costs and the independent bucket ownership boundary.

Bootstrap manually with explicit project/account checks and a unique bucket
name supplied by the learner. An existing same-name bucket must be inspected,
not assumed owned or changed. Authenticate Terraform using local Application
Default Credentials, distinct from the gcloud CLI login; no downloaded
service-account JSON keys. Limit state-object access to the named operator(s),
separate from cloud resource-management permissions. Do not grant broad new
project Owner/Editor roles as a convenience. Cloud Run adoption may require
`iam.serviceAccounts.actAs`; budget operations need billing-scope permissions.
The guide lists needed permissions for each operation and checks access before
writing state. Application runtime identities get no state access.

The sandbox backend prefix is `phase18/sandbox`; drill uses `phase18/drill`.
Partial backend files contain only bucket/prefix. The GCS backend supplies
locking; never use `-lock=false`. Serialize imports/applies and stop concurrent
manual deployment changes during adoption. Explain stale locks and owner
verification; no routine force-unlock or forced state push.

Ignore `.terraform/`, state/backup files, local `.tfvars`, backend `.hcl`, saved
plans/JSON plans, crash logs, generated import/config files and local inventory.
Explicitly retain `.terraform.lock.hcl` and sanitized example files. State and
plans remain sensitive even when Terraform marks a field `sensitive`.

## Adoption and operating sequence

1. Record the working production app baseline, SQL recovery configuration,
   resource ownership and current traffic/image. Complete inventory and inputs.
2. Install pinned tooling, establish ADC, bootstrap the state bucket, verify
   access/versioning, and initialize the sandbox backend.
3. Write a local `imports.tf` from verified IDs for resources that already
   exist. Each remote object has exactly one Terraform address. Keep sanitized
   import-address/ID-format documentation in Git; actual local imports are
   ignored. Do not import the project, service agents, secret payloads or users.
4. Plan the full declared root with reviewed import blocks. No broad `-target`,
   no apply of an incomplete root that would create duplicate resources. A
   saved adoption plan must contain imports only: zero additions, changes,
   replacements or destruction. Correct configuration to observed reality
   until this is true; import can otherwise carry real update actions.
5. Apply exactly that inspected local saved plan, then require exit code 0 from
   `terraform plan -detailed-exitcode`. Code 2 means differences; 1 means error.
   No-change alone is insufficient: confirm explicit resource settings could
   reproduce the intended sandbox rather than hiding fields behind defaults.
6. Add missing monitoring/budget or improve deletion guards only in a separate
   reviewed plan with explicit expected additions/changes. No SQL replacement,
   networking redesign, credential rotation, image release or migration occurs
   as part of adoption. Re-test hosted auth, todos and AI after intentional
   Cloud Run changes. Finish with a no-change plan.

Use lifecycle `prevent_destroy` from the first configuration for durable
resources. Model provider/API deletion-protection flags as observed inputs for
the import-only pass, even when false. Require a separate step 6 follow-up to
enable supported provider protections on Run/SQL and SQL API-level protection
before sign-off; do not force an update during adoption. A lifecycle `prevent_destroy` guard is not a
substitute for backups and can be bypassed by removing the resource block.

Terraform owns Cloud Run image, env, scaling and traffic after handoff. Do not
ignore entire templates, images, CORS, IAM, or SQL settings to manufacture an
empty plan. Explicitly preserve the observed public invocation mechanism; do
not enable a second mechanism. Adoption preserves observed traffic by revision
where necessary. A later deployment changes image/revision/traffic through one
reviewed owner; Phase 19 must establish that workflow before automation.

## Exercises and acceptance

Use a harmless service-level user label for the live drift exercise. Record
its prior value, change it in the console, inspect a normal refresh-enabled
plan, reconcile the approved label in code, and return to exit code 0. Avoid
image, IAM, networking, credentials, CORS, or DB schema as drift experiments.

State recovery and destruction use only the drill root's empty bucket. Produce
two state generations, simulate losing only the drill object's state entry,
restore a known version under an exclusive maintenance window, compare
lineage/serial and actual resources, then plan to confirm reconciliation.
Restoring state does not roll back cloud resources or databases. The guide
must verify supported GCS generation-copy steps and never use a live sandbox
state rollback as the learning experiment. Test protection on the drill bucket,
then explicitly remove its guard and destroy only the drill root after checking
its single resource and backend prefix. Never run sandbox `terraform destroy`.

| ID | Required evidence |
| --- | --- |
| A1 | Pinned CLI/provider, platform lock checksums, fmt and validate pass. |
| A2 | Reviewed redacted inventory and ownership/import map; each mandatory resource accounted for. |
| A3 | Versioned private state bucket, scoped operator access, sandbox/drill prefixes, locking and recovery recipe verified. |
| A4 | No secret payloads/SQL credentials in configuration, inputs, outputs or newly introduced state; no state/plan files tracked. |
| A5 | Import-only adoption plan reviewed and applied with zero unintended remote changes; imported resource addresses recorded. |
| A6 | Explicit preserved API/job, IAM, SQL, registry, secrets, budget and monitoring configuration; all intentional follow-up changes reviewed. |
| A7 | Full sandbox plan returns exit code 0 after adoption/follow-up. No ignored meaningful drift. |
| A8 | Production signup/login, todo CRUD/persistence/isolation, guided workflow and live AI remain functional. |
| A9 | Harmless console drift detected, reconciled in code, and no-change plan restored. |
| A10 | Drill state recovered from a versioned object; lock handling and recovery limitations documented. |
| A11 | Deletion guards checked; only the disposable drill resource destroyed; sandbox and state bucket remain intact. |
| A12 | Credential-free CI validation, mocked safety checks and misconfiguration scan pass; exception justifications, cost settings and ownership handoff recorded. |

No cloud acceptance is inferred from local tests. Mocked tests verify desired
configuration contracts, not provider behavior or live permissions. Keep local
`imports.tf` outside the root (renamed to an ignored `.local` file) while running
tests; run tests before preparing imports and archive imports after successful
adoption. Use a mocked `google_project` data source to avoid live project reads.
The guide teaches resource dependency edges using `terraform graph`, including
project-number lookup for budgets and explicit service/IAM prerequisites. Final
sign-off requires the learner's results and records any missing identifiers
without inventing them.

## References

- [Curriculum Phase 18](../../curriculum-roadmap.md#18-terraform-and-reproducible-google-infrastructure)
- [Phase 17 acceptance](../../guides/17-cloudflare-pages.md#acceptance-record)
- [Terraform 1.14.7 release](https://releases.hashicorp.com/terraform/1.14.7/)
- [GCS backend and locking](https://developer.hashicorp.com/terraform/language/backend/gcs)
- [Import blocks](https://developer.hashicorp.com/terraform/language/block/import)
- [Provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking)
- [Sensitive state and plans](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
- [Google Cloud Run v2 resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service)
