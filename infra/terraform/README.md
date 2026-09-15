# Phase 18 Terraform

Core adoption is learner-completed: 25 resources imported and a no-change plan reported. Recovery/destruction drills are deferred by agreement; final label-drift verification remains unconfirmed. See the [walkthrough progress record](../../docs/guides/18-terraform.md#learner-progress-and-agreed-deferrals). Local checks do not establish live cloud acceptance.

This root adopts the Google sandbox by import. It owns explicitly declared
Google resources after handoff; it never manages the project lifecycle,
billing link, state bucket, Cloudflare Pages, Secret Manager payloads or
versions, SQL passwords, or Alembic execution. `terraform.tfvars.example` is
sanitized mock input only, not an inventory or deployment target.

## Local tooling

Terraform is pinned to 1.14.7 in `.terraform-version`. On macOS ARM64, keep
the binary local and verify HashiCorp's published checksum before use:

```sh
mkdir -p infra/terraform/.local/bin
curl --fail --location --proto '=https' --tlsv1.2 -o infra/terraform/.local/terraform_1.14.7_darwin_arm64.zip \
  https://releases.hashicorp.com/terraform/1.14.7/terraform_1.14.7_darwin_arm64.zip
curl --fail --location --proto '=https' --tlsv1.2 -o infra/terraform/.local/terraform_1.14.7_SHA256SUMS \
  https://releases.hashicorp.com/terraform/1.14.7/terraform_1.14.7_SHA256SUMS
(cd infra/terraform/.local && grep ' terraform_1.14.7_darwin_arm64.zip$' terraform_1.14.7_SHA256SUMS | shasum -a 256 -c -)
unzip infra/terraform/.local/terraform_1.14.7_darwin_arm64.zip -d infra/terraform/.local/bin
export PATH="$PWD/infra/terraform/.local/bin:$PATH"
terraform version
```

Use local Application Default Credentials for real cloud work; this is separate
from `gcloud auth login` and never uses downloaded service-account keys:

```sh
gcloud auth application-default login
```

No real backend, cloud read, import, plan, or apply belongs in repository
validation. Bootstrap a protected state bucket manually, copy
`sandbox/backend.hcl.example` to the ignored `sandbox/backend.hcl`, replace its
fictional bucket name, then initialize deliberately. The partial GCS backend
contains only bucket and prefix; it has no credentials.

```sh
terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
```

## Input boundary

All inputs are non-secret, typed observed configuration. Maps use stable
logical keys as Terraform addresses. `plain_env` and `secret_env` are separate:
the former cannot contain `DATABASE_URL` or `OPENROUTER_API_KEY`; secret maps
record a secret key and numeric version only. API CORS comes from exact HTTPS
`cors_origins`; Terraform will generate `CORS_ALLOWED_ORIGINS` with
`jsonencode`, so callers cannot set that reserved key. `OPENROUTER_MODEL` is a
required nonempty plain API variable. The API runtime also records the
container command, arguments, port, probes, and CPU-startup setting. Cloud SQL
records both Terraform lifecycle protection and the provider/API-level
`settings.deletion_protection_enabled`, connector enforcement, and database
flags. Imported protection values must match observation, including `false`;
enabling either is a separate reviewed change. `prevent_destroy` blocks
configured destruction, but removing a resource block bypasses it, so it is
neither a backup nor a substitute for tested Cloud SQL backups/PITR.

Before adoption, inventory every setting and stop if a material setting cannot
be represented. Do not introduce guessed SQL costs, instance sizes, image tags,
or defaults to produce an empty plan.

Cloud Run service template configuration and the revision currently receiving
traffic can differ. Capture and compare both before choosing `api.runtime` and
`api.traffic`; a service-level update can create an unserved revision, while a
traffic change can serve an older revision. Preserve the observed public
invocation mechanism rather than adding another one.

`api.plain_env`, `api.secret_env`, and the generated `CORS_ALLOWED_ORIGINS`
entry remain separate. Cloud Run consumes numeric Secret Manager versions only;
Terraform never sees a secret value. Record an existing budget or monitoring
configuration exactly, or keep the nullable input `null` for import adoption.
A missing budget amount or notification channel is a learner prerequisite for
the separate additive plan, not a default Terraform value. During import
review, compare provider-normalized duration, traffic, and default labels with
the inventory before accepting a no-change plan.

The migration job has its own identity, Cloud SQL socket, CPU/memory limits,
and optional execution environment. It requires an inventoried Cloud SQL client
grant plus access to the referenced database secret. API service-level scaling
is also optional, separate from template scaling, so absent observed values do
not become Terraform defaults.

## Offline validation

```sh
terraform -chdir=infra/terraform/sandbox init -backend=false
terraform -chdir=infra/terraform/sandbox fmt -check -recursive
terraform -chdir=infra/terraform/sandbox validate
```

Terraform's `providers schema -json` refuses to run in this root while its GCS
backend is intentionally uninitialized, even after `init -backend=false`.
Inspect the same exact provider constraint in the ignored backend-free schema
workspace instead; it performs no Google authentication:

```sh
terraform -chdir=infra/terraform/.local/schema init -backend=false
terraform -chdir=infra/terraform/.local/schema providers schema -json
```

## Ownership and imports

Use one Terraform address per remote object. IAM member resources are additive;
do not manage the same grant with a policy or binding. Conditional IAM imports
append the observed condition title as a fourth space-delimited field. Do not
guess a title or import a conditional grant before inventory confirms it.

| Resource address | Ownership | Accepted import ID formats |
| --- | --- | --- |
| `google_project_service.required["service"]` | Explicit required APIs; `disable_on_destroy = false` | `project/service` |
| `google_artifact_registry_repository.api` | Existing repository metadata, cleanup policy, tag mutability, and encryption | `projects/project/locations/location/repositories/repository`, `project/location/repository`, or `location/repository` |
| `google_service_account.dedicated["key"]` | Existing runtime/migration identities | `projects/project/serviceAccounts/email` |
| `google_project_iam_member.owned["key"]` | Inventoried additive project grants | `project role member` (append observed `condition-title` when conditional) |
| `google_secret_manager_secret.containers["key"]` | Existing metadata and immutable replication; never versions or payloads | `projects/project/secrets/secret`, `project/secret`, or `secret` |
| `google_secret_manager_secret_iam_member.access["key"]` | Inventoried secret-scoped accessor grants | `projects/project/secrets/secret role member` (append observed `condition-title` when conditional) |
| `google_sql_database_instance.primary` | Existing SQL settings and observed deletion protections | `projects/project/instances/name`, `project/name`, or `name` |
| `google_sql_database.app` | Existing application database only; no users or credentials | `projects/project/instances/instance/databases/name`, `instances/instance/databases/name`, `project/instance/name`, `instance/name`, or `name` |
| `google_cloud_run_v2_service.api` | Existing API image digest, runtime, SQL socket, traffic, and observed invocation/protection settings | `projects/project/locations/region/services/name`, `project/region/name`, or `region/name` |
| `google_cloud_run_v2_job.migrate` | Existing migration job configuration; Terraform never starts an execution | `projects/project/locations/region/jobs/name`, `project/region/name`, or `region/name` |
| `google_billing_budget.sandbox[0]` | Existing project-filtered budget when `budget` is non-null | `billingAccounts/billing-account/budgets/budget-id` |
| `google_monitoring_uptime_check_config.api[0]` | Existing HTTPS health check when `monitoring` is non-null | `projects/project/uptimeCheckConfigs/check-id` |
| `google_monitoring_alert_policy.api[0]` | Existing alert policy when `monitoring` is non-null | `projects/project/alertPolicies/policy-id` |

`data.google_project.current` is read-only and supplies the numeric project ID
for a future imported budget filter. Mock it in Terraform tests; it never
adopts the project or billing link.
