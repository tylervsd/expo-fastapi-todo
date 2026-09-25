# Phase 30a: RudderStack Cloud loads client events into BigQuery through a
# staging bucket. It authenticates from its AWS account through workload
# identity federation and impersonates one loader account: no key exists.
# Curated views join client events to the Phase 26 server events.

locals {
  rudderstack_enabled = var.rudderstack != null && local.analytics_enabled
  rudderstack_views   = local.rudderstack_enabled && try(var.rudderstack.curated_views, false)
  rudderstack_bucket  = local.rudderstack_enabled ? coalesce(var.rudderstack.bucket_name, "${var.project_id}-rudderstack-staging") : null
}

resource "google_bigquery_dataset" "rudderstack_raw" {
  count = local.rudderstack_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = var.rudderstack.raw_dataset
  location                   = var.region
  description                = "Phase 30a raw client events, written by RudderStack. Owner-only; analysts use the curated views."
  delete_contents_on_destroy = false

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "rudderstack_staging" {
  count = local.rudderstack_enabled ? 1 : 0

  project                     = var.project_id
  name                        = local.rudderstack_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true # staging files only

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_service_account" "rudderstack_loader" {
  count = local.rudderstack_enabled ? 1 : 0

  project      = var.project_id
  account_id   = var.rudderstack.account_id
  display_name = "RudderStack loader (rudderstack_raw only)"
}

resource "google_bigquery_dataset_access" "rudderstack_loader" {
  count = local.rudderstack_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.rudderstack_raw[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  iam_member = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

# Required to run load jobs; grants no data access.
resource "google_project_iam_member" "rudderstack_job_user" {
  count = local.rudderstack_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

resource "google_storage_bucket_iam_member" "rudderstack_staging" {
  for_each = local.rudderstack_enabled ? toset(["roles/storage.objectCreator", "roles/storage.objectViewer"]) : toset([])

  bucket = google_storage_bucket.rudderstack_staging[0].name
  role   = each.value
  member = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

resource "google_iam_workload_identity_pool" "rudderstack" {
  count = local.rudderstack_enabled ? 1 : 0

  project                   = var.project_id
  workload_identity_pool_id = var.rudderstack.pool_id
  display_name              = "RudderStack"
  description               = "Federates RudderStack's warehouse loader for one workspace."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "rudderstack" {
  count = local.rudderstack_enabled ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "rudderstack-aws"
  display_name                       = "RudderStack AWS"

  attribute_mapping = {
    "google.subject"      = "assertion.arn"
    "attribute.workspace" = "assertion.arn.extract('assumed-role/data-plane-service-account/{workspace}')"
  }

  # RudderStack's AWS account is shared by all its customers; the workspace
  # condition is what makes this pool yours.
  attribute_condition = "attribute.workspace == '${var.rudderstack.workspace_id}'"

  aws {
    account_id = "422074288268"
  }
}

resource "google_service_account_iam_member" "rudderstack_wif" {
  count = local.rudderstack_enabled ? 1 : 0

  service_account_id = google_service_account.rudderstack_loader[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id}/attribute.workspace/${var.rudderstack.workspace_id}"
}

resource "google_bigquery_table" "signup_funnel" {
  count = local.rudderstack_views ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "signup_funnel"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/signup_funnel.sql.tftpl", {
      project     = var.project_id
      dataset     = var.analytics.dataset
      raw_dataset = var.rudderstack.raw_dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_table" "suggestion_taps" {
  count = local.rudderstack_views ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "suggestion_taps"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/suggestion_taps.sql.tftpl", {
      project     = var.project_id
      dataset     = var.analytics.dataset
      raw_dataset = var.rudderstack.raw_dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_dataset_access" "rudderstack_authorized_view" {
  for_each = local.rudderstack_views ? toset(["signup_funnel", "suggestion_taps"]) : toset([])

  project    = var.project_id
  dataset_id = google_bigquery_dataset.rudderstack_raw[0].dataset_id

  view {
    project_id = var.project_id
    dataset_id = google_bigquery_dataset.analytics[0].dataset_id
    table_id   = each.value
  }

  depends_on = [google_bigquery_table.signup_funnel, google_bigquery_table.suggestion_taps]
}

output "rudderstack_settings" {
  description = "Values for the RudderStack BigQuery destination (workload identity federation)."
  value = local.rudderstack_enabled ? {
    pool_project_number = data.google_project.current.number
    pool_id             = google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id
    provider_id         = google_iam_workload_identity_pool_provider.rudderstack[0].workload_identity_pool_provider_id
    service_account     = google_service_account.rudderstack_loader[0].email
    bucket              = google_storage_bucket.rudderstack_staging[0].name
    dataset             = google_bigquery_dataset.rudderstack_raw[0].dataset_id
  } : null
}
