# Phase 19 delivery identity. One CI deploy identity authenticated through
# short-lived Workload Identity Federation credentials. All resources are
# opt-in: github_delivery defaults to null and creates nothing.
# No state-bucket, infrastructure administration, or secret-access grants.

resource "google_iam_workload_identity_pool" "delivery" {
  count = var.github_delivery == null ? 0 : 1

  project                   = var.project_id
  workload_identity_pool_id = "github-delivery"
  display_name              = "GitHub delivery"
  description               = "Federates the release workflow for sandbox delivery."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count = var.github_delivery == null ? 0 : 1

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.delivery[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub Actions"
  description                        = "Trusts the release workflow on refs/heads/main."

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner"    = "assertion.repository_owner"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
    "attribute.environment"         = "assertion.environment"
  }

  # Numeric IDs are the trust anchors; names alone are not.
  attribute_condition = "assertion.repository_id == '${var.github_delivery.repository_id}' && assertion.repository_owner_id == '${var.github_delivery.owner_id}' && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == '${var.github_delivery.repository}/.github/workflows/release.yml@refs/heads/main'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "deploy" {
  count = var.github_delivery == null ? 0 : 1

  project      = var.project_id
  account_id   = "github-deploy"
  display_name = "GitHub delivery deploy"
  description  = "Single CI identity for sandbox releases. Never used at runtime."

  depends_on = [google_project_service.required]
}

# Only the immutable sandbox environment subject may impersonate the deploy account.
# GitHub includes owner/repository IDs in this repository's OIDC subject.
resource "google_service_account_iam_member" "deploy_wif" {
  count = var.github_delivery == null ? 0 : 1

  service_account_id = google_service_account.deploy[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.delivery[0].workload_identity_pool_id}/subject/repo:${split("/", var.github_delivery.repository)[0]}@${var.github_delivery.owner_id}/${split("/", var.github_delivery.repository)[1]}@${var.github_delivery.repository_id}:environment:sandbox"

  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "deploy_push" {
  count = var.github_delivery == null ? 0 : 1

  project    = var.project_id
  location   = var.registry.location
  repository = google_artifact_registry_repository.api.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "deploy_api" {
  count = var.github_delivery == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_job_iam_member" "deploy_migrate" {
  count = var.github_delivery == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migrate.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

# Lets the deploy job act as the existing runtime identities where required.
resource "google_service_account_iam_member" "deploy_runtime_user" {
  for_each = var.github_delivery == null ? toset([]) : toset(["runtime", "migration"])

  service_account_id = google_service_account.dedicated[each.value].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

# Phase 20 worker-scoped deployment grants. All require both delivery and
# async configuration; CI gets no queue administration, worker secret payload
# access, infrastructure apply, or state-bucket access.
resource "google_cloud_run_v2_service_iam_member" "deploy_worker" {
  count = var.github_delivery == null || var.async_suggestions == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

# Lets the deploy job act as the worker runtime identity where required.
resource "google_service_account_iam_member" "deploy_worker_user" {
  count = var.github_delivery == null || var.async_suggestions == null ? 0 : 1

  service_account_id = google_service_account.async_worker[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}

# Lets the deploy job mint short-lived ID tokens as the invocation identity
# for authenticated worker smoke only. This is the sole Token Creator grant.
resource "google_service_account_iam_member" "deploy_invoker_token" {
  count = var.github_delivery == null || var.async_suggestions == null ? 0 : 1

  service_account_id = google_service_account.async_invoker[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.deploy[0].email}"

  depends_on = [google_project_service.required]
}
