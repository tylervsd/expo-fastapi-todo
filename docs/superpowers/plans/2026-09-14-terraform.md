# Phase 18 Terraform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare import-first Terraform configuration, credential-free checks,
and a manual walkthrough that adopts the existing Google sandbox safely.

**Architecture:** One sandbox root owns the documented Google resources. A
manually bootstrapped GCS bucket stores versioned, locked state; a separate
drill root/prefix isolates recovery and destruction exercises. Cloudflare,
secret values, SQL users/schema and application delivery remain external.

**Tech Stack:** Terraform 1.14.7, hashicorp/google 8.2.0, GCS backend, native
Terraform tests with mocked providers, existing Trivy action, gcloud CLI.

**Spec:** [Phase 18 design](../specs/2026-09-14-terraform-design.md).

## Global constraints

- Repository implementation is authorized and complete. Manual cloud execution
  remains a separate learner stage; no cloud mutation occurs during preparation.
- Use `codex/phase-18-terraform` in `.worktrees/phase-18-terraform`, based on
  `d845c58`. Keep the existing app working and preserve Phase 17 sign-off.
- Pin CLI 1.14.7 and stable google provider 8.2.0; no beta provider or new modules.
- Use one sandbox root, one drill root, default workspace, and prefixes
  `phase18/sandbox` and `phase18/drill`. Never disable state locking.
- No Terraform secret versions/data reads, password resources, SQL users,
  downloaded account keys, cloud credentials in CI, or committed state/plans.
- Import-only adoption means zero create/update/delete/replace actions.
  Follow-up improvements get their own reviewed plan. No broad `ignore_changes`.
- Terraform owns Cloud Run settings after adoption. Do not introduce a second
  deployment owner before Phase 19 defines its delivery workflow.
- All cloud acceptance remains pending until learner execution. Unexpected
  resource identities or destructive plans stop the dependent action.

## Execution sequence and file map

Tasks 1–4 produce repository artifacts; task 5 produces the manual guide and
handoff. The guide's inventory checkpoint must be completed before the learner
runs live plans. Real values absent from Git are deliberately required inputs,
not guessed infrastructure. If discovery exposes unsupported topology, return
the discrepancy to the controller/spec rather than redesigning infrastructure.

| Task | Deliverable |
| --- | --- |
| 1 | Complete: Terraform entry points, pins, ignored local artifacts, input contract and tool instructions. |
| 2 | Complete: importable APIs, registry, IAM, secret containers, SQL instance/database configuration. |
| 3 | Complete: importable API/job, budget, monitoring, outputs and safety tests. |
| 4 | Complete: isolated drill root and credential-free CI checks. |
| 5 | Complete repository guide/links; all manual cloud acceptance remains pending. |

Use Luna for mechanical implementation, Terra for provider/import integration,
and Sol medium for task/whole-branch review per project instructions. Do not
parallelize edits within the same Terraform root. No agent executes cloud apply.

## Repository execution record

- [x] Task 1: pinned sandbox root, ignored local artifacts, and typed input boundary.
- [x] Task 2: imported foundation, IAM, secret metadata, and Cloud SQL resources.
- [x] Task 3: Cloud Run/operations resources, outputs, and credential-free mocked safety tests.
- [x] Task 4: isolated drill root and Terraform CI/configuration scan.
- [x] Task 5: manual adoption guide and repository links.
- [ ] Final whole-branch gate and learner A1–A12 acceptance remain pending.

Rulings retained from the execution ledger: all implementation was repository
only; live inventory, backend initialization, imports, plans, applies, and
manual acceptance remain learner work. Provider schema inspection used the
ignored backend-free workspace, and provider processes may need local scoped
execution permission; neither grants cloud access.

### Task 1: Establish the root and input boundary

**Files:** Create `infra/terraform/README.md`, `.terraform-version`,
`sandbox/versions.tf`, `sandbox/backend.tf`, `sandbox/variables.tf`,
`sandbox/backend.hcl.example`, `sandbox/terraform.tfvars.example`, and
`sandbox/.terraform.lock.hcl` under `infra/terraform/`; modify `.gitignore`.

**Interfaces:** Subsequent resources consume explicit typed input objects,
validated against the provider schema. All example IDs use a clearly fictitious
project, with no defaults that accidentally target the real sandbox.

- [ ] Read the spec, Phase 17 guide, Dockerfile, API CORS/config readers and
  existing quality/security workflows. Record the service-vs-serving-revision
  caveat and secret-map separation in the Terraform README.
- [ ] Install the pinned CLI from HashiCorp's official release, verifying its
  checksum. Document macOS ARM64 setup, PATH/version check and ADC setup in the
  README. Do not change Phase 0's global doctor to require Terraform for all users.
- [ ] Define both the version baseline and partial backend:

```hcl
terraform {
  required_version = "= 1.14.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.2.0"
    }
  }
  backend "gcs" {}
}
```

Keep the backend block in `backend.tf`, the remaining block in `versions.tf`;
Terraform merges them. Set the provider's project and region from inputs.
The example backend uses `bucket = "example-phase18-state"` and
`prefix = "phase18/sandbox"` and contains no credentials.

- [ ] Initialize with `terraform -chdir=infra/terraform/sandbox init -backend=false`.
  Read `terraform providers schema -json` locally to define only the observed
  provider-supported nested settings; don't copy obsolete v1 Run annotations
  directly into v2 resources. Commit the provider lock with:

```sh
terraform -chdir=infra/terraform/sandbox providers lock \
  -platform=darwin_arm64 -platform=linux_amd64
```

- [ ] Define `project_id` and `region` strings; required objects `registry`,
  `database`, `api`, `migration_job`; map `service_accounts`; set
  `enabled_services`; maps `project_iam_members`, `secret_iam_members` and
  `secrets`; nullable `budget` and `monitoring` objects. Each resource map uses stable logical
  keys as Terraform addresses. Require observed SQL/Run settings rather than
  supplying lower-cost defaults that could replace or resize imported resources.
- [ ] Define `api` with explicit name, identity, image digest, non-secret env,
  secret references, production CORS origins, SQL connection, runtime settings
  and traffic. Define the job separately with its observed command/args,
  retries/timeout/tasks, identity, image and env. Images must match
  `@sha256:[0-9a-f]{64}$`; secret versions must match `^[1-9][0-9]*$`.
  Validate nonempty `api.plain_env.OPENROUTER_MODEL`, reject `DATABASE_URL` and
  `OPENROUTER_API_KEY` in plain env, disallow overlapping plain/secret keys.
  Reserve `CORS_ALLOWED_ORIGINS` for generation from the origin input.
- [ ] Exclude `.terraform/`, `*.tfstate*`, `*.tfplan`, `*.plan.json`,
  `crash*.log`, actual `*.tfvars`/`*.tfvars.json`, local `backend.hcl`,
  `imports.tf`, generated config, and `infra/terraform/.local/` from Git.
  Keep `.terraform.lock.hcl`, examples and tests tracked. Confirm with
  `git check-ignore` using representative paths before creating real local files.
- [ ] Supply sanitized, valid example values sufficient for mocked plan tests;
  mark their role as examples in prose. No actual secret bytes are accepted.
  Run `fmt -check -recursive` and `validate`, then commit
  `chore: establish Phase 18 Terraform configuration boundary`.

### Task 2: Model the existing foundation and database

**Files:** Create `sandbox/services.tf`, `iam.tf`, `secrets.tf`, `database.tf`;
expand `variables.tf` and `terraform.tfvars.example`; update Terraform README.

**Interfaces:** Export resource references within the root for task 3. Use
`google_project_service.required`, `google_artifact_registry_repository.api`,
`google_service_account.dedicated`, `google_project_iam_member.owned`,
`google_secret_manager_secret.containers`,
`google_secret_manager_secret_iam_member.access`,
`google_sql_database_instance.primary`, and `google_sql_database.app`.

- [ ] Read provider 8.2.0 resource docs/schema for these exact types and record
  accepted import-ID formats in the README ownership table. Verify compound
  IAM IDs including role/member/condition handling. Do not guess conditional
  member imports or manage the same grant in multiple resources.
- [ ] Add a read-only `data "google_project" "current"` lookup using
  `var.project_id`; its project number supplies the budget project filter.
  Override/mock this data source in tests; it grants no project ownership.
- [ ] Build API resources with `for_each = var.enabled_services` and
  `disable_on_destroy = false`. Preserve registry cleanup/replication/encryption
  settings and import existing dedicated identities rather than creating names.
- [ ] Add only inventoried additive IAM grants. Runtime/migration identities
  retain Cloud SQL Client and the secret-specific accessor grants actually
  needed. Existing public invocation is modeled in task 3; don't convert every
  project role into Terraform ownership or remove other grants.
- [ ] Model secret metadata/replication without versions or payload access.
  Preserve replication exactly: changing immutable configuration stops adoption.
- [ ] Model SQL version/edition, availability, disk, maintenance, flags,
  networking, backup schedule/retention/PITR and application database settings.
  Include lifecycle `prevent_destroy` for the instance immediately. Model both
  provider-level and API-level deletion protection from explicit observed
  inputs during adoption; require a separate follow-up to enable any disabled
  protection. Do the same for supported Run provider protection flags. Do not rotate passwords, create SQL
  users, run migrations, upgrade PostgreSQL or add private networking.
- [ ] Put `prevent_destroy` on durable owned resources; preserve current API
  behavior and apply additional protections only in the deliberate follow-up
  plan if they change remote settings. Explain why removing a resource block
  bypasses lifecycle protection and why this isn't a backup.
- [ ] Validate against the provider schema and review every computed/optional
  setting for reproduction intent. Commit
  `feat: model imported Google foundation and Cloud SQL resources`.

### Task 3: Model runtime and operational settings with safety tests

**Files:** Create `sandbox/run.tf`, `operations.tf`, `outputs.tf`,
`tests/safety.tftest.hcl`; update input examples and README import map.

**Interfaces:** `google_cloud_run_v2_service.api`,
`google_cloud_run_v2_job.migrate`, optional `google_billing_budget.sandbox`, and optional
`google_monitoring_uptime_check_config.api` and
`google_monitoring_alert_policy.api`. Outputs are `api_uri`,
`sql_connection_name`, `registry_path`, `service_account_emails`, and
`managed_resource_ids`.

- [ ] Add a mocked-provider plan test before implementing Run resources.
  Use a shared fictitious fixture in the test file's `variables` block; override
  computed dependencies when needed. Start with these real assertions:

```hcl
mock_provider "google" {}

run "protected_runtime" {
  command = plan
  assert {
    condition     = google_cloud_run_v2_service.api.deletion_protection
    error_message = "The adopted API must have deletion protection."
  }
  assert {
    condition     = google_sql_database_instance.primary.deletion_protection
    error_message = "Terraform must protect Cloud SQL from destruction."
  }
}
```

This run uses a protected follow-up fixture with observed protection inputs
set to true. Add an adoption run with those inputs false asserting the resource
flags equal their inputs; lifecycle `prevent_destroy` still applies. Do not
force true flags into the import-only configuration. Mock the project data
source's number and ID. Run `terraform -chdir=infra/terraform/sandbox test` and
confirm it fails on missing resources before implementing. Set all inputs from the task 1 example
contract inside the test, without requiring local/cloud credentials.

- [ ] Model Cloud Run API and migration job from inventory using v2 schema.
  Generate env blocks separately for plain values and `value_source` references;
  generate CORS with `jsonencode(var.api.cors_origins)`. Preserve SQL socket
  volume/mount, identity, port/probes, CPU idle/boost, memory, scaling,
  concurrency, ingress, timeout, command/args and job execution settings.
  Model explicit dependencies on owned API and IAM grants so a future creation
  has required services/permissions first. Importing does not execute the job.
- [ ] Preserve traffic and existing public invocation policy. No implicit
  traffic move to an unverified latest revision, no current revision name
  hardcoded as a new template revision, no broad `ignore_changes`. Capture
  provider normalization/default-label behavior in the import review notes.
- [ ] Make the budget conditional (`count = var.budget == null ? 0 : 1`), using
  address `google_billing_budget.sandbox[0]` when present. If absent in the
  inventory, use null during adoption; obtain learner-approved amount/config
  and enable it only in the separate follow-up plan. Final acceptance requires
  the budget to be managed. Model billing-account/project filters, amount, period,
  thresholds and current notifications. Never choose a new monetary amount.
  Model existing uptime/alert settings, or leave `monitoring = null` for the
  import pass and supply explicit additive configuration afterward. A new
  check uses HTTPS `/health` on the stable API and an existing channel; it
  proves liveness only. Preserve existing operational settings when importing.
- [ ] Add tests for generated exact-origin CORS, secret references with no plain
  credentials, protected durable resources, and API disable-on-destroy behavior.
  Add negative input tests using `expect_failures = [var.api]` for invalid
  digest, blank model, overlapping env keys, malformed CORS and secret versions.
  Do not write assertions that merely repeat every resource property.
- [ ] Run `fmt`, `validate`, and mocked tests without ADC; record the limits of
  mocked results. Commit `feat: model Cloud Run and operational resources`.

### Task 4: Isolate exercises and add credential-free CI

**Files:** Create `infra/terraform/drill/{versions.tf,backend.tf,main.tf,outputs.tf,
backend.hcl.example,terraform.tfvars.example,.terraform.lock.hcl}`;
modify `.github/workflows/quality.yml` and `.github/workflows/security.yml`.

**Interfaces:** The drill contains only `google_storage_bucket.disposable`,
required project/region/unique bucket name, separate `phase18/drill` state,
`force_destroy = false`, and a literal `prevent_destroy = true` guard. It has
no sandbox resource dependencies, remote-state reads or shared resource names.

- [ ] Implement the tiny drill root with the same version pins. Require a
  learner-supplied unique bucket name containing `phase18-drill`; output only
  its name. The actual state bucket is never its target.
- [ ] Add a quality job that installs Terraform 1.14.7 using a reviewed,
  commit-SHA-pinned setup action (resolve its official release SHA during
  implementation, never invent one). Initialize each root with `-backend=false
  -lockfile=readonly`, validate both roots and run sandbox mocked tests. Locally,
  run tests before creating `imports.tf`; if it exists, move it to ignored
  `.local/imports.tf.disabled` outside the root for the test run and restore it
  only for adoption. Archive it there after successful adoption. Never run
  mocked tests against the real local import file.
- [ ] Reuse the existing Trivy action SHA from `security.yml` for a separate
  configuration scan of `infra/terraform`, `scan-type: config`, failing on
  HIGH/CRITICAL findings. Pin the scanner version explicitly after verifying
  support in the action release. No Google credentials, live speculative plans,
  saved-plan uploads or deploy steps in CI.
- [ ] Exercise a temporary unsafe configuration locally to show the scanner
  detects it, then remove it. Document narrow exceptions for intentional public
  API ingress or established sandbox tradeoffs by exact finding ID, resource,
  rationale and review condition. No blanket skip or automatic weakening of
  live settings to make scans green.
- [ ] Validate both roots, run tests/scan and inspect the workflow diff. Commit
  `ci: validate Terraform and scan infrastructure configuration`.

### Task 5: Write the complete manual adoption guide

**Files:** Create `docs/guides/18-terraform.md`; update `README.md`,
`docs/curriculum-roadmap.md`, `infra/terraform/README.md` and the Phase 18 spec
status only to indicate repository readiness when implementation is done.

**Interfaces:** The guide consumes all roots/input contracts and exposes
numbered commands plus A1–A12 evidence rows. Commands operate from the Phase 18
worktree, and shell variables are explicitly assigned before use.

- [ ] Write a read-only inventory stage with gcloud describe/list commands for
  every mandatory resource and budget/monitoring scope. Map each exact ID to its
  Terraform address and classify import vs explicit later addition. Inspect
  active traffic and template separately. Require learner input for missing
  IDs/settings and budget/channel prerequisites before dependent commands.
- [ ] Include an input table with where each value comes from. Record the known
  Pages production origin and `openrouter/free` as confirmed Phase 17 context,
  while instructing re-verification. Do not reuse its removed preview origin
  or historical revision/secret version as the final live baseline.
- [ ] Provide tool installation, CLI/ADC distinction, quota-project selection,
  required permissions, and state-bucket bootstrap commands with project/name
  checks, private access, versioning and bucket-scoped operator access. Explain
  external ownership of the project, bucket, credentials and secret values.
- [ ] Show the full init and adoption sequence with a local variable file and
  local reviewed import blocks. Verify import IDs against pinned docs. Before
  any import/apply, demonstrate the plan review below:

```sh
umask 077
terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
terraform -chdir=infra/terraform/sandbox plan -out=adoption.tfplan
terraform -chdir=infra/terraform/sandbox show adoption.tfplan
```

Require imports only, zero remote add/change/destroy actions. Explain that
`apply adoption.tfplan` applies an already-approved plan without another prompt,
so approval/review must precede that command. Show separate commands to apply,
remove the local plan, and run `plan -detailed-exitcode`; explain 0/1/2 and
avoid shell `set -e` accidentally treating expected drift (2) as a fatal script.
Generated config may aid local discovery but must be pruned/reviewed and ignored;
no unreviewed generated config apply, broad targeting, or secret data sources.

- [ ] Explain `terraform graph` output and trace the project data lookup,
  budget filter, SQL connection, secret and identity references, and explicit
  service/IAM readiness edges. Graphviz rendering is optional, not a dependency.
- [ ] Separate adoption from the additive protection/monitoring/budget plan.
  Recheck service availability and run the Phase 17 production auth/todo/AI
  journey after any Run update. Execute the migration job only as a separately
  explained manual idempotency check, never a Terraform provisioner or
  automatically triggered apply action.
- [ ] Give exact steps for harmless label drift, detecting it, reconciling in
  code, reviewing/applying, and returning to a no-change plan. Establish that
  future console edits are exceptions, not an ongoing competing deployment path.
- [ ] Provide the drill bucket creation, two state generations, state-entry loss
  simulation, and GCS version recovery commands. Verify the backend object path
  from actual initialized state rather than guessing. Keep a current backup,
  stop writers, inspect generation/lineage/serial, restore only drill state,
  and reconcile with live resources. No `-force`, `-lock=false`, or sandbox
  state manipulation. A denied lock is inspected, not blindly force-unlocked.
- [ ] Demonstrate destruction refusal using the drill lifecycle guard, then
  explicitly remove that guard in the drill file, review the single-resource
  destroy plan, and destroy only its empty bucket. Restore the checked-in
  guard afterward. Leave the state bucket and sandbox untouched; capture costs
  and cleanup state-object handling without a broad bucket deletion command.
- [ ] Add A1–A12 evidence rows, expected commands/results, troubleshooting, and
  honest unrecorded-metadata handling. Link official backend/import/provider/
  recovery references. Phase 18 stays pending until learner sign-off; Phase 19
  stays future work. Link spec/plan/guide from README.
- [ ] Run Markdown lint, external link checks, shell-block syntax checks,
  Terraform checks/scan and `git diff --check`; commit
  `docs: add Phase 18 Terraform adoption walkthrough`.

## Review and handoff

- [ ] Self-review every spec section against tasks 1–5. Verify references,
  resource names, input/test interfaces and the separation of import-only and
  additive plans. Ensure imports/tests coexist without live reads in CI.
- [ ] Obtain final Sol medium whole-branch review before implementation handoff.
  Review state exposure, IAM scope, replacement risk, Cloud Run traffic,
  migration ownership, and destructive drill isolation in particular.
- [ ] Deliver the guide and local check results. Stop before manual cloud work;
  do not claim an empty live plan or cloud acceptance based on mock tests.
- [ ] After learner-reported A1–A12 success, update acceptance/README, then
  commit/push/merge when authorized. Phase 19 must explicitly define Terraform
  vs release-pipeline field ownership before enabling automated deployment.
