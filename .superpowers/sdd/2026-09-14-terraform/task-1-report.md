# Phase 18 Task 1 Report: Terraform input boundary

## Result

Created the sandbox Terraform root's pinned CLI/provider boundary, typed
non-secret inputs, sanitized examples, backend example, provider lock, and
Terraform-specific ignore rules. No cloud API, credential, backend, import,
plan, or apply operation was run.

## Tooling and schema

- Downloaded HashiCorp Terraform 1.14.7 for Darwin ARM64 into ignored
  `infra/terraform/.local/bin`.
- Verified `terraform_1.14.7_darwin_arm64.zip` against HashiCorp's official
  `terraform_1.14.7_SHA256SUMS`; `terraform version` reported `v1.14.7`.
- Initialized the root with `terraform -chdir=infra/terraform/sandbox init
  -backend=false` and pinned `hashicorp/google` to 8.2.0.
- Captured the Google 8.2.0 provider schema locally from the ignored,
  backend-free `infra/terraform/.local/schema` copy of the same exact provider
  constraint. It confirmed the v2 Cloud Run service/job, SQL, Artifact
  Registry, IAM, Secret Manager, billing, and monitoring fields used by the
  typed boundary.
- `terraform providers schema -json` and `terraform console` refuse to run in
  the actual root while the declared GCS backend is intentionally
  uninitialized, even after `init -backend=false`. This is a Terraform CLI
  limitation, not a request to initialize a real backend. Downstream mocked
  checks must use a backend-free test/schema workspace or Terraform's test
  facilities rather than a real backend.

## Interface for later tasks

`sandbox/variables.tf` exposes `project_id`, `region`, required `registry`,
`database`, `api`, and `migration_job` objects; stable-key maps for service
accounts, project IAM, secret IAM, and secret containers; required enabled API
set; and nullable `budget` and `monitoring` objects. It requires explicit SQL
and Cloud Run settings and has no lower-cost defaults.

API and migration-job images require a lower-case SHA-256 digest. Secret maps
contain references and numeric versions only. API plain environment requires
nonempty `OPENROUTER_MODEL`, rejects `DATABASE_URL`, `OPENROUTER_API_KEY`, and
reserved `CORS_ALLOWED_ORIGINS`, and cannot overlap the secret map. Job plain
environment has the same secret-key and overlap protections. API CORS accepts
only a plain HTTPS origin without credentials, paths, wildcards, whitespace,
or a trailing slash, with a port in the parser-compatible 0–65535 range.

## Verification

All commands ran from the Phase 18 worktree on 2026-09-14:

```sh
terraform -chdir=infra/terraform/sandbox init -backend=false -reconfigure
terraform -chdir=infra/terraform/sandbox fmt -check -recursive
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox providers lock \
  -platform=darwin_arm64 -platform=linux_amd64
git check-ignore --no-index <state, plan, tfvars, backend, imports, and .local representatives>
git diff --check
```

The root initialized with the backend disabled, formatting and validation
passed, both provider platform checksums were already tracked, ignore checks
matched all sensitive/generated representatives while retaining the lock and
example file, and `git diff --check` had no output.

## Concerns for adoption

Repository records do not contain the actual Phase 16 SQL settings or current
migration-job configuration. The examples are deliberately fictional. Before
imports, inventory the live resource fields and stop if a material setting is
not mapped; do not substitute example values. The Cloud Run service template
must also be compared with the revision receiving traffic before populating
the API runtime and traffic inputs.

## Review fix round 1

Added the provider-schema fields needed by later tasks without adding resources:

- `database.deletion_protection` maps to the Cloud SQL resource-level provider
  flag; it is separate from the unconditional `lifecycle.prevent_destroy`
  guard. Task 2 consumes these foundation SQL fields.
- `database.deletion_protection_enabled` maps separately to the Cloud SQL
  `settings.deletion_protection_enabled` API/provider field.
- `database.connector_enforcement` and `database.database_flags` map to the
  corresponding Cloud SQL settings fields.
- `api.runtime.command`, `args`, `container_port`, optional `port_name`,
  `startup_cpu_boost`, optional `liveness_probe`, and optional `startup_probe`
  map to the Cloud Run v2 container schema. Each configured probe requires one
  of `grpc`, `http_get`, or `tcp_socket`.

The fictional example now supplies all added required fields, including
`/health` HTTP probes on port 8080. Task 3 consumes the API runtime field
names; every task must still populate them only from the adoption inventory.

After this correction, the actual root again passed backend-disabled
`init -reconfigure`, `fmt -check -recursive`, and `validate`. Copying only its
variables into the ignored backend-free schema workspace also let
`terraform plan -input=false -var-file=../../sandbox/terraform.tfvars.example`
evaluate the sanitized example's new required fields and probe validation; it
returned `No changes` without provider configuration or cloud access.
