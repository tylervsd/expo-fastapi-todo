# Phase 28b: least-privilege identity for a Hex BigQuery connection.
# Reads only the curated analytics views; runs query jobs; nothing else.
# The JSON key is created/deleted with gcloud (a documented exception to the
# no-keys rule: Hex OAuth is Enterprise-only). Never create keys in Terraform.

locals {
  hex_enabled = var.hex != null && local.analytics_enabled
}

resource "google_service_account" "hex_reader" {
  count = local.hex_enabled ? 1 : 0

  project      = var.project_id
  account_id   = var.hex.account_id
  display_name = "Hex reader (curated analytics only)"
}

resource "google_bigquery_dataset_access" "hex_reader" {
  count = local.hex_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = "roles/bigquery.dataViewer"
  iam_member = "serviceAccount:${google_service_account.hex_reader[0].email}"
}

# Required to run queries; grants no data access.
resource "google_project_iam_member" "hex_job_user" {
  count = local.hex_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.hex_reader[0].email}"
}

output "hex_reader_email" {
  description = "Hex reader service account email, for creating its key with gcloud."
  value       = local.hex_enabled ? google_service_account.hex_reader[0].email : null
}
