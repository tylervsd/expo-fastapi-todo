# Phase 18 Terraform

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
flags.

Before adoption, inventory every setting and stop if a material setting cannot
be represented. Do not introduce guessed SQL costs, instance sizes, image tags,
or defaults to produce an empty plan.

Cloud Run service template configuration and the revision currently receiving
traffic can differ. Capture and compare both before choosing `api.runtime` and
`api.traffic`; a service-level update can create an unserved revision, while a
traffic change can serve an older revision. Preserve the observed public
invocation mechanism rather than adding another one.

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
