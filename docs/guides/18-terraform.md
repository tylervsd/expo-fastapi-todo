# Phase 18: Terraform adoption walkthrough

Phase 18 **core adoption is complete**, with recovery/destruction drills
**deferred by learner agreement**. It adopts the existing Google sandbox manually. CI never reads or changes cloud state.
Cloudflare Pages, the project and billing link, state bucket, credentials,
secret payloads/versions, SQL passwords, and Alembic execution are external.

Use two plans: an import-only adoption plan, then optional additive
budget/monitoring/protection work. Never combine them.

## Learner progress and agreed deferrals

Recorded from this learning session on 2026-09-14:

- **Completed:** inventory/input mapping, backend initialization and validation,
  reviewed import-only plan for 25 resources, learner-run import apply, and
  learner-reported follow-up “No changes” with detailed exit code 0.
- **Completed:** dependency graph generation and inspection commands.
- **Not yet confirmed:** step 6 label drift/reconciliation and its final
  no-change check. Instructions were provided; a passing result was not reported.
- **Deferred by learner choice:** step 7 state recovery and step 8 guarded
  destruction. A10/A11 and the drill portions of A3 are deferred, not passed.
  Keep backend versioning enabled and retain these exercises for later.
- **Optional additions deferred:** monitoring remains absent. The existing
  account-wide budget stays outside the project-filtered Terraform resource.
- **Not repeated during adoption:** hosted application verification. The
  reviewed adoption plan changed no remote configuration; Phase 17's prior
  sign-off remains the recorded application evidence.

This records completion of core adoption, not an assertion that every original
A1–A12 acceptance check passed. Steps 7–8 are no longer required for this
learner's current phase scope; their instructions remain below for future use.

## 1. Maintenance window and inputs

Stop console edits and manual deployment during adoption. Run commands in this
worktree. Angle-bracket values are learner input, not real values.

```sh
cd /path/to/expo-fastapi-todo/.worktrees/phase-18-terraform
command -v gcloud jq curl shasum unzip >/dev/null || { echo 'Install gcloud and jq first: brew install --cask google-cloud-sdk && brew install jq'; exit 1; }
export PROJECT_ID='fullstack-sandbox-tylervsd'
export REGION='us-west1'
export OPERATOR_EMAIL='<your-Google-account-email>'
export STATE_BUCKET='<globally-unique-state-bucket-name>'
export BILLING_ACCOUNT='<billing-account-ID>'
export API_SERVICE='fullstack-api'
export API_ORIGIN='https://expo-fastapi-todo.pages.dev'
export MODEL='openrouter/free'
test "$PROJECT_ID" = fullstack-sandbox-tylervsd
test "$REGION" = us-west1
test "$API_ORIGIN" = https://expo-fastapi-todo.pages.dev
test "$MODEL" = openrouter/free
gcloud config set project "$PROJECT_ID"
gcloud projects describe "$PROJECT_ID" --format='value(projectNumber,projectId)'
gcloud auth list
```

The production origin and model are recorded Phase 17 context; re-verify both.
Do not restore the removed preview origin, historical revision/image digest, or
historical secret version.

| Input | Obtain from | Local destination |
| --- | --- | --- |
| project, region | project/resource describes | `project_id`, `region` |
| APIs/registry/image | Service Usage, Artifact Registry, Run template | services, registry, images |
| identities/grants | project and secret IAM policies | account and IAM maps |
| secret metadata/version reference | secret metadata and Run/Job template, never payload | secret and env maps |
| SQL/database | SQL describes | `database` |
| API/job and traffic | Run service, revisions and job describes | `api`, `migration_job` |
| operations | billing/Monitoring describes | `budget`, `monitoring`, or `null` |

## 2. Read-only inventory and mapping

Retain raw output outside Git and redact sensitive metadata. These reads do not
read secret payloads or SQL credentials.

```sh
export INVENTORY="$HOME/phase18-inventory-$(date +%Y%m%d)"
umask 077; mkdir -p "$INVENTORY"
gcloud services list --enabled --project="$PROJECT_ID" --format=json > "$INVENTORY/services.json"
gcloud artifacts repositories list --project="$PROJECT_ID" --location="$REGION" --format=json > "$INVENTORY/repositories.json"
gcloud iam service-accounts list --project="$PROJECT_ID" --format=json > "$INVENTORY/service-accounts.json"
gcloud projects get-iam-policy "$PROJECT_ID" --format=json > "$INVENTORY/project-iam.json"
gcloud run services get-iam-policy "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json > "$INVENTORY/api-service-iam.json"
gcloud secrets list --project="$PROJECT_ID" --format=json > "$INVENTORY/secrets.json"
gcloud sql instances list --project="$PROJECT_ID" --format=json > "$INVENTORY/sql-instances.json"
gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json > "$INVENTORY/api-service.json"
gcloud run revisions list --service="$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" --format=json > "$INVENTORY/api-revisions.json"
gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" --format=json > "$INVENTORY/jobs.json"
gcloud monitoring uptime list-configs --project="$PROJECT_ID" --format=json > "$INVENTORY/uptime.json"
gcloud monitoring policies list --project="$PROJECT_ID" --format=json > "$INVENTORY/alert-policies.json"
gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format=json > "$INVENTORY/budgets.json"
```

Set only IDs found in those lists, then describe each selected object:

```sh
export REGISTRY_ID='<repository-id>'
export RUNTIME_SA='fullstack-run@fullstack-sandbox-tylervsd.iam.gserviceaccount.com'
export MIGRATION_SA='<migration-service-account-email>'
export SQL_INSTANCE='<SQL-instance-name>'
export SQL_DATABASE='<application-database-name>'
export MIGRATION_JOB='<job-name>'
gcloud artifacts repositories describe "$REGISTRY_ID" --project="$PROJECT_ID" --location="$REGION" --format=json > "$INVENTORY/registry.json"
gcloud iam service-accounts describe "$RUNTIME_SA" --project="$PROJECT_ID" --format=json > "$INVENTORY/runtime-sa.json"
gcloud iam service-accounts describe "$MIGRATION_SA" --project="$PROJECT_ID" --format=json > "$INVENTORY/migration-sa.json"
gcloud secrets describe openrouter-api-key --project="$PROJECT_ID" --format=json > "$INVENTORY/openrouter-secret.json"
gcloud secrets describe fullstack-database-url --project="$PROJECT_ID" --format=json > "$INVENTORY/database-secret.json"
gcloud secrets get-iam-policy openrouter-api-key --project="$PROJECT_ID" --format=json > "$INVENTORY/openrouter-secret-iam.json"
gcloud secrets get-iam-policy fullstack-database-url --project="$PROJECT_ID" --format=json > "$INVENTORY/database-secret-iam.json"
gcloud sql instances describe "$SQL_INSTANCE" --project="$PROJECT_ID" --format=json > "$INVENTORY/sql.json"
gcloud sql databases list --instance="$SQL_INSTANCE" --project="$PROJECT_ID" --format=json > "$INVENTORY/sql-databases.json"
gcloud run jobs describe "$MIGRATION_JOB" --project="$PROJECT_ID" --region="$REGION" --format=json > "$INVENTORY/migration-job.json"
```

Inventory all selected APIs, registry fields, dedicated accounts, additive IAM
grants and conditions, secret container metadata and secret IAM, SQL edition,
tier, network, flags, backup/PITR/protections, database, and every Run/job
template field. Compare the API template separately with traffic and active
revisions. Record only numeric secret references. If a material field is absent
or unsupported by the pinned schema, stop that import and record it unadopted.

| Terraform address | exact import ID |
| --- | --- |
| `google_project_service.required["SERVICE"]` | `$PROJECT_ID/SERVICE` |
| `google_artifact_registry_repository.api` | `projects/$PROJECT_ID/locations/$REGION/repositories/$REGISTRY_ID` |
| `google_service_account.dedicated["runtime"]` | `projects/$PROJECT_ID/serviceAccounts/$RUNTIME_SA` |
| `google_service_account.dedicated["migration"]` | `projects/$PROJECT_ID/serviceAccounts/$MIGRATION_SA` |
| `google_project_iam_member.owned["KEY"]` | `$PROJECT_ID ROLE MEMBER [CONDITION_TITLE]` |
| `google_secret_manager_secret.containers["KEY"]` | `projects/$PROJECT_ID/secrets/SECRET_ID` |
| `google_secret_manager_secret_iam_member.access["KEY"]` | `projects/$PROJECT_ID/secrets/SECRET_ID ROLE MEMBER [CONDITION_TITLE]` |
| `google_sql_database_instance.primary` | `projects/$PROJECT_ID/instances/$SQL_INSTANCE` |
| `google_sql_database.app` | `projects/$PROJECT_ID/instances/$SQL_INSTANCE/databases/$SQL_DATABASE` |
| `google_cloud_run_v2_service.api` | `projects/$PROJECT_ID/locations/$REGION/services/$API_SERVICE` |
| `google_cloud_run_v2_job.migrate` | `projects/$PROJECT_ID/locations/$REGION/jobs/$MIGRATION_JOB` |
| `google_billing_budget.sandbox[0]` | `billingAccounts/$BILLING_ACCOUNT/budgets/BUDGET_ID` |
| `google_monitoring_uptime_check_config.api[0]` | `projects/$PROJECT_ID/uptimeCheckConfigs/CHECK_ID` |
| `google_monitoring_alert_policy.api[0]` | `projects/$PROJECT_ID/alertPolicies/POLICY_ID` |

Verify supported formats against the pinned [ownership/import table](../../infra/terraform/README.md#ownership-and-imports). The project/data lookup,
service agents, secret values/versions, SQL users, and state bucket are never
imported.

## 3. Tooling, ADC and backend bootstrap

Request least-privilege inventory/import access, `iam.serviceAccounts.actAs`
for Run adoption, billing-account budget access, Monitoring access, and
bucket-scoped state access. Do not grant Owner/Editor. Runtime and migration
identities get no state access.

```sh
mkdir -p infra/terraform/.local/bin
export PATH="$PWD/infra/terraform/.local/bin:$PATH"
command -v terraform gcloud jq curl shasum unzip
curl --fail --location --proto '=https' --tlsv1.2 -o infra/terraform/.local/terraform_1.14.7_darwin_arm64.zip https://releases.hashicorp.com/terraform/1.14.7/terraform_1.14.7_darwin_arm64.zip
curl --fail --location --proto '=https' --tlsv1.2 -o infra/terraform/.local/terraform_1.14.7_SHA256SUMS https://releases.hashicorp.com/terraform/1.14.7/terraform_1.14.7_SHA256SUMS
(cd infra/terraform/.local && grep ' terraform_1.14.7_darwin_arm64.zip$' terraform_1.14.7_SHA256SUMS | shasum -a 256 -c -)
unzip -o infra/terraform/.local/terraform_1.14.7_darwin_arm64.zip -d infra/terraform/.local/bin
terraform version
test "$(terraform version -json | jq -r .terraform_version)" = 1.14.7
gcloud auth application-default login
gcloud auth application-default set-quota-project "$PROJECT_ID"
gcloud auth application-default print-access-token >/dev/null
```

CLI login and ADC are separate; do not use service-account key files. If the
bucket exists, stop until its owner proves it is intended. Otherwise create the
private, versioned backend bucket with Google-managed encryption.

```sh
gcloud storage buckets create "gs://$STATE_BUCKET" --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access || { echo 'STOP: state bucket creation failed; it may already exist or access may be denied'; exit 1; }
gcloud storage buckets update "gs://$STATE_BUCKET" --public-access-prevention --versioning || { echo 'STOP: state bucket update failed'; exit 1; }
gcloud storage buckets add-iam-policy-binding "gs://$STATE_BUCKET" --member="user:$OPERATOR_EMAIL" --role=roles/storage.objectAdmin || { echo 'STOP: state bucket IAM grant failed'; exit 1; }
gcloud storage buckets describe "gs://$STATE_BUCKET" --format='yaml(name,location,iamConfiguration,versioning)' || { echo 'STOP: cannot verify state bucket'; exit 1; }
gcloud storage buckets get-iam-policy "gs://$STATE_BUCKET" --format=json || { echo 'STOP: cannot verify state bucket IAM'; exit 1; }
```

No locked retention policy or lifecycle deletion rule: backend locking needs
object deletion. State costs money. The bucket and its scoped access remain
external ownership.

```sh
cat > infra/terraform/sandbox/backend.hcl <<EOF
bucket = "$STATE_BUCKET"
prefix = "phase18/sandbox"
EOF
cat > infra/terraform/drill/backend.hcl <<EOF
bucket = "$STATE_BUCKET"
prefix = "phase18/drill"
EOF
```

These ignored local files contain no credential. Serialize writers. Inspect a
denied lock and its owner; never use `-lock=false` or blind force-unlock.

## 4. Local configuration and import gate

```sh
cp infra/terraform/sandbox/terraform.tfvars.example infra/terraform/sandbox/terraform.tfvars
vi infra/terraform/sandbox/terraform.tfvars
git check-ignore -v infra/terraform/sandbox/terraform.tfvars infra/terraform/sandbox/backend.hcl
umask 077
terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
terraform -chdir=infra/terraform/sandbox fmt -check -recursive
terraform -chdir=infra/terraform/sandbox validate
```

The example is mock input only. Fill every observed schema-supported field.
CORS is only `https://expo-fastapi-todo.pages.dev` unless inventory proves an
approved replacement; preserve traffic and immutable digest images. Keep absent
budget/monitoring as `null`. Generated config can aid discovery but is ignored:
prune/review it and copy only understood settings to tfvars. Never apply
generated config, broad-target, or use secret data sources.

Create the ignored import file only after each ID is verified. Replace every
placeholder row with inventory-confirmed entries and remove placeholders before
planning.

```sh
export IMPORTS=infra/terraform/sandbox/imports.tf
cat > "$IMPORTS" <<EOF
import {
  to = google_artifact_registry_repository.api
  id = "projects/$PROJECT_ID/locations/$REGION/repositories/$REGISTRY_ID"
}
import {
  to = google_service_account.dedicated["runtime"]
  id = "projects/$PROJECT_ID/serviceAccounts/$RUNTIME_SA"
}
import {
  to = google_service_account.dedicated["migration"]
  id = "projects/$PROJECT_ID/serviceAccounts/$MIGRATION_SA"
}
import {
  to = google_secret_manager_secret.containers["openrouter_api_key"]
  id = "projects/$PROJECT_ID/secrets/openrouter-api-key"
}
import {
  to = google_secret_manager_secret.containers["database_url"]
  id = "projects/$PROJECT_ID/secrets/fullstack-database-url"
}
import {
  to = google_sql_database_instance.primary
  id = "projects/$PROJECT_ID/instances/$SQL_INSTANCE"
}
import {
  to = google_sql_database.app
  id = "projects/$PROJECT_ID/instances/$SQL_INSTANCE/databases/$SQL_DATABASE"
}
import {
  to = google_cloud_run_v2_service.api
  id = "projects/$PROJECT_ID/locations/$REGION/services/$API_SERVICE"
}
import {
  to = google_cloud_run_v2_job.migrate
  id = "projects/$PROJECT_ID/locations/$REGION/jobs/$MIGRATION_JOB"
}
EOF
while IFS= read -r service; do
  printf 'import {\n  to = google_project_service.required["%s"]\n  id = "%s/%s"\n}\n' "$service" "$PROJECT_ID" "$service" >> "$IMPORTS"
done <<'EOF'
<verified-required-api-name>
EOF
while IFS='|' read -r key role member condition; do
  [ -n "$key" ] || continue; id="$PROJECT_ID $role $member"
  [ -z "$condition" ] || id="$id $condition"
  printf 'import {\n  to = google_project_iam_member.owned["%s"]\n  id = "%s"\n}\n' "$key" "$id" >> "$IMPORTS"
done <<'EOF'
<key>|<role>|<member>|<observed-condition-title-or-empty>
EOF
while IFS='|' read -r key secret role member condition; do
  [ -n "$key" ] || continue; id="projects/$PROJECT_ID/secrets/$secret $role $member"
  [ -z "$condition" ] || id="$id $condition"
  printf 'import {\n  to = google_secret_manager_secret_iam_member.access["%s"]\n  id = "%s"\n}\n' "$key" "$id" >> "$IMPORTS"
done <<'EOF'
<key>|<secret-id>|<role>|<member>|<observed-condition-title-or-empty>
EOF
vi "$IMPORTS"
```

Append only confirmed existing operation objects:

```hcl
import {
  to = google_billing_budget.sandbox[0]
  id = "billingAccounts/BILLING_ACCOUNT/budgets/BUDGET_ID"
}
import {
  to = google_monitoring_uptime_check_config.api[0]
  id = "projects/PROJECT_ID/uptimeCheckConfigs/CHECK_ID"
}
import {
  to = google_monitoring_alert_policy.api[0]
  id = "projects/PROJECT_ID/alertPolicies/POLICY_ID"
}
```

Before every import/apply, the plan must say imports only: zero add/change/
replace/destroy actions.

```sh
umask 077
terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
terraform -chdir=infra/terraform/sandbox plan -out=adoption.tfplan
terraform -chdir=infra/terraform/sandbox show adoption.tfplan
terraform -chdir=infra/terraform/sandbox show -json adoption.tfplan > "$INVENTORY/adoption-plan.json"
jq -e '([.resource_changes[]? | select(.mode == "managed")] | all(.change.actions == ["no-op"])) and any(.resource_changes[]?; .mode == "managed" and .change.importing != null)' "$INVENTORY/adoption-plan.json" || { echo 'STOP: plan has a managed remote action or no import'; exit 1; }
```

Inspect all addresses and IDs. `apply adoption.tfplan` has no another prompt,
so approval belongs before it.

```sh
terraform -chdir=infra/terraform/sandbox apply adoption.tfplan
rm infra/terraform/sandbox/adoption.tfplan
terraform -chdir=infra/terraform/sandbox plan -detailed-exitcode
plan_status=$?
case "$plan_status" in 0) echo no-change;; 2) echo 'STOP: differences-investigate'; exit 2;; 1) echo 'STOP: plan error'; exit 1;; *) exit "$plan_status";; esac
```

Do not put the final command under `set -e`: 0 is no change, 2 is drift, 1 is
an error. Archive imports outside Git afterward; state and plans remain
sensitive and untracked.

## 5. Graph and the separate additive plan

```sh
terraform -chdir=infra/terraform/sandbox graph > "$INVENTORY/sandbox.dot"
head -40 "$INVENTORY/sandbox.dot"
```

The graph traces the project data lookup into the budget filter, SQL into API/job
connections, secret containers into secret IAM/env references, identities into
Run, and explicit required-service/IAM readiness edges into the API and job.
Graphviz rendering is optional.

For a missing budget obtain a billing account, currency/amount, exact threshold
percentages/spend bases, and a manually created verified notification channel.
A budget alerts; it does not cap spending. For missing monitoring obtain the
health path, period/timeout, verified channel, and exact alert
filter/comparison/duration/alignment. Record these required values in the
nullable objects. Recheck service/channel availability, then review a separate
plan with only intentional additions/protection updates.

```sh
gcloud services list --enabled --project="$PROJECT_ID" --filter='config.name:(billingbudgets.googleapis.com monitoring.googleapis.com)' --format='value(config.name)'
gcloud components install alpha
gcloud alpha monitoring channels list --project="$PROJECT_ID" --format='table(name,displayName,verificationStatus)'
terraform -chdir=infra/terraform/sandbox plan -out=operations.tfplan
terraform -chdir=infra/terraform/sandbox show operations.tfplan
terraform -chdir=infra/terraform/sandbox apply operations.tfplan
rm infra/terraform/sandbox/operations.tfplan
terraform -chdir=infra/terraform/sandbox plan -detailed-exitcode; test $? = 0
```

This is also the separate reviewed point to enable supported Run/SQL deletion
protections. Never use adoption to redesign SQL/networking, rotate credentials,
release an image, change traffic/CORS, or execute migrations. After intentional
Run updates, repeat Phase 17 production signup/login, todo CRUD/persistence and
isolation, guided workflow, and live `openrouter/free` AI. A migration is a
separate manual idempotency check, never a provisioner:

```sh
gcloud run jobs execute "$MIGRATION_JOB" --project="$PROJECT_ID" --region="$REGION" --wait
```

## 6. Harmless drift exercise

Record an existing API service label. In the console change only that label;
do not use image, IAM, network, CORS, credentials or schema. Then detect,
reconcile in code, review/apply and restore a no-change plan.

```sh
gcloud run services describe "$API_SERVICE" --project="$PROJECT_ID" --region="$REGION" --format='value(metadata.labels)'
terraform -chdir=infra/terraform/sandbox plan -detailed-exitcode; plan_status=$?
test "$plan_status" = 2
vi infra/terraform/sandbox/terraform.tfvars
terraform -chdir=infra/terraform/sandbox plan -out=label.tfplan
terraform -chdir=infra/terraform/sandbox show label.tfplan
terraform -chdir=infra/terraform/sandbox apply label.tfplan
rm infra/terraform/sandbox/label.tfplan
terraform -chdir=infra/terraform/sandbox plan -detailed-exitcode; test $? = 0
```

Console edits are exceptions after handoff. Terraform owns its declared Run
fields; Phase 19 must define release-pipeline ownership before automation.

## 7. Separate state recovery drill

**Deferred for this learner; skip this section for now.**

Use only the drill root and an empty globally unique bucket containing
`phase18-drill`. Never manipulate sandbox state. Verify the initialized
backend object path rather than guessing it.

```sh
export DRILL_BUCKET='<globally-unique-name-containing-phase18-drill>'
cp infra/terraform/drill/terraform.tfvars.example infra/terraform/drill/terraform.tfvars
vi infra/terraform/drill/terraform.tfvars
terraform -chdir=infra/terraform/drill init -backend-config=backend.hcl
test "$(terraform -chdir=infra/terraform/drill workspace show)" = default || { echo 'STOP: drill workspace is not default'; exit 1; }
jq -e --arg bucket "$STATE_BUCKET" '.backend.type == "gcs" and .backend.config.bucket == $bucket and .backend.config.prefix == "phase18/drill"' infra/terraform/drill/.terraform/terraform.tfstate || { echo 'STOP: drill backend is not the expected bucket/prefix'; exit 1; }
export DRILL_STATE_OBJECT='phase18/drill/default.tfstate'
terraform -chdir=infra/terraform/drill plan -out=drill-create.tfplan
terraform -chdir=infra/terraform/drill show drill-create.tfplan
terraform -chdir=infra/terraform/drill apply drill-create.tfplan
rm infra/terraform/drill/drill-create.tfplan
gcloud storage ls -L "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT" > "$INVENTORY/drill-object.txt" || { echo 'STOP: drill state object is unavailable'; exit 1; }
test "$DRILL_STATE_OBJECT" = phase18/drill/default.tfstate || { echo 'STOP: unexpected drill state path'; exit 1; }
grep -F "/$DRILL_STATE_OBJECT" "$INVENTORY/drill-object.txt" || { echo 'STOP: observed state path differs'; exit 1; }
gcloud storage cp "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT" "$INVENTORY/drill-current.tfstate" || { echo 'STOP: cannot back up drill state'; exit 1; }
terraform -chdir=infra/terraform/drill state pull > "$INVENTORY/drill-before.json" || { echo 'STOP: cannot read drill state'; exit 1; }
terraform -chdir=infra/terraform/drill state rm google_storage_bucket.disposable
terraform -chdir=infra/terraform/drill state pull > "$INVENTORY/drill-damaged-pulled.json" || { echo 'STOP: cannot read damaged drill state'; exit 1; }
gcloud storage ls -a "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT" | tee "$INVENTORY/drill-generations.txt"
```

This makes two state generations and simulates loss of only the drill entry.
Stop writers, inspect any lock and the generations, select the known-good
generation, inspect lineage/serial, and restore only drill state.

```sh
export GOOD_GENERATION='<known-good-generation>'
export CURRENT_GENERATION='<current-live-generation-from-generation-list>'
gcloud storage cp "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT#$GOOD_GENERATION" "$INVENTORY/drill-good.tfstate" || { echo 'STOP: cannot download selected good generation'; exit 1; }
gcloud storage cp "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT#$CURRENT_GENERATION" "$INVENTORY/drill-damaged.tfstate" || { echo 'STOP: cannot download damaged generation'; exit 1; }
{ jq -e '.resources[]? | select(.type == "google_storage_bucket" and .name == "disposable")' "$INVENTORY/drill-good.tfstate" >/dev/null &&
  jq -e 'all(.resources[]?; (.type != "google_storage_bucket" or .name != "disposable"))' "$INVENTORY/drill-damaged.tfstate" &&
  jq -e --arg lineage "$(jq -r .lineage "$INVENTORY/drill-good.tfstate")" --argjson serial "$(jq -r .serial "$INVENTORY/drill-good.tfstate")" '.lineage == $lineage and .serial > $serial' "$INVENTORY/drill-damaged.tfstate" &&
  jq -e --argjson before "$(jq -c . "$INVENTORY/drill-before.json")" '. == $before' "$INVENTORY/drill-good.tfstate" >/dev/null
} || { echo 'STOP: invalid state generations'; exit 1; }
gcloud storage ls -a "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT"
gcloud storage cp "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT#$GOOD_GENERATION" "gs://$STATE_BUCKET/$DRILL_STATE_OBJECT" --if-generation-match="$CURRENT_GENERATION" || { echo 'STOP: restore precondition failed'; exit 1; }
terraform -chdir=infra/terraform/drill state pull > "$INVENTORY/drill-restored.json" || { echo 'STOP: cannot read restored drill state'; exit 1; }
terraform -chdir=infra/terraform/drill plan -detailed-exitcode; plan_status=$?
test "$plan_status" = 0 || { echo 'STOP: restored drill state differs'; exit 1; }
```

The current-generation precondition prevents overwriting a concurrent writer.
GCS recovery bypasses Terraform serial checks, so compare lineage/serial and reconcile with the live bucket.
It never rolls back cloud resources/databases. A denied lock is inspected, not
force-unlocked.

## 8. Guarded destruction drill

**Deferred with step 7; skip this section for now.**

First demonstrate refusal. Then temporarily remove only the literal
`prevent_destroy = true` in `infra/terraform/drill/main.tf`, review one
single-resource destroy, destroy only its empty bucket, and restore the guard.

```sh
terraform -chdir=infra/terraform/drill destroy
# Expect lifecycle protection refusal. Never use -force or -lock=false.
vi infra/terraform/drill/main.tf
terraform -chdir=infra/terraform/drill plan -destroy -out=drill-destroy.tfplan
terraform -chdir=infra/terraform/drill show drill-destroy.tfplan
terraform -chdir=infra/terraform/drill show -json drill-destroy.tfplan > "$INVENTORY/drill-destroy-plan.json"
jq -e '[.resource_changes[]? | select(.mode == "managed")] as $changes | ($changes | length) == 1 and $changes[0].address == "google_storage_bucket.disposable" and $changes[0].change.actions == ["delete"]' "$INVENTORY/drill-destroy-plan.json" || { echo 'STOP: destroy plan is not the single drill bucket'; exit 1; }
terraform -chdir=infra/terraform/drill apply drill-destroy.tfplan
rm infra/terraform/drill/drill-destroy.tfplan
git checkout -- infra/terraform/drill/main.tf
terraform -chdir=infra/terraform/drill plan -out=drill-recreate.tfplan
terraform -chdir=infra/terraform/drill show -json drill-recreate.tfplan > "$INVENTORY/drill-recreate-plan.json"
jq -e '[.resource_changes[]? | select(.mode == "managed")] as $changes | ($changes | length) == 1 and $changes[0].address == "google_storage_bucket.disposable" and $changes[0].change.actions == ["create"]' "$INVENTORY/drill-recreate-plan.json" || { echo 'STOP: recreate plan is not the single drill bucket'; exit 1; }
rm infra/terraform/drill/drill-recreate.tfplan
```

Never run sandbox destroy, delete the state bucket, or issue a broad bucket
delete. Record drill/storage cost; state-object cleanup is a separate
state-bucket-owner decision.

## 9. A1–A12 evidence and troubleshooting

| ID | Required evidence |
| --- | --- |
| A1 | Terraform 1.14.7, provider locks, fmt and validate |
| A2 | redacted inventory and mandatory address/import map |
| A3 | private/versioned bucket, scoped access, prefixes, lock/recovery |
| A4 | no payload/password in config/input/output/new state; ignored local files |
| A5 | reviewed import-only plan/apply and addresses |
| A6 | preserved API/job, IAM, SQL, registry, secrets, operations and reviewed additions |
| A7 | final sandbox detailed plan exit 0 |
| A8 | Phase 17 production auth/todo/AI after Run update |
| A9 | label drift, reconciliation, final no-change |
| A10 | drill generation, lineage/serial, lock/recovery evidence |
| A11 | guard refusal and disposable-only destroy |
| A12 | credential-free CI, mocked tests, scanner and SQL exception rationale |

If ADC/quota access fails, repeat the separate ADC/quota steps; do not add a
key. If a provider normalizes a field, compare it with inventory and pinned
documentation before changing configuration. If budget/channel access is
missing, leave the nullable object absent and record the prerequisite. Local
checks do not prove cloud access, state, no-change plan, recovery or hosted
behavior. Use the progress record above to distinguish completed adoption,
unconfirmed checks, and agreed deferrals. Phase 19 remains future work.

## References

- [Phase 18 design](../superpowers/specs/2026-09-14-terraform-design.md)
- [Terraform ownership and pinned import IDs](../../infra/terraform/README.md)
- [GCS backend and locking](https://developer.hashicorp.com/terraform/language/backend/gcs)
- [Terraform import blocks](https://developer.hashicorp.com/terraform/language/block/import)
- [Cloud Run provider resource](https://registry.terraform.io/providers/hashicorp/google/8.2.0/docs/resources/cloud_run_v2_service)
- [Versioned-object recovery](https://docs.cloud.google.com/storage/docs/using-versioned-objects)
