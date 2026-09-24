# Phase 26 product analytics (opt-in via var.analytics). The worker loads the
# PostgreSQL outbox into analytics_raw; analysts read only the curated,
# deduplicating views in analytics. All dataset grants use
# google_bigquery_dataset_access so they never conflict with dataset IAM
# resources on the same dataset. Datasets also keep BigQuery's default
# project-role access (Viewers read, Editors write), so analysts must not hold
# basic project roles if the curated views are to be their only surface.

locals {
  analytics_enabled = var.analytics != null
  analytics_table   = local.analytics_enabled ? "${var.project_id}.${var.analytics.raw_dataset}.events" : null
}

resource "google_bigquery_dataset" "analytics_raw" {
  count = local.analytics_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = var.analytics.raw_dataset
  location                   = var.region
  description                = "Phase 26 raw product events; worker-written. No reader grants beyond BigQuery default project-role access."
  delete_contents_on_destroy = false

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "events" {
  count = local.analytics_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics_raw[0].dataset_id
  table_id            = "events"
  deletion_protection = true
  clustering          = ["event_name"]

  time_partitioning {
    type          = "DAY"
    field         = "occurred_at"
    expiration_ms = 34560000000 # 400 days
  }

  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_name", type = "STRING", mode = "REQUIRED" },
    { name = "user_key", type = "STRING", mode = "REQUIRED" },
    { name = "workflow_key", type = "STRING", mode = "NULLABLE" },
    { name = "outcome", type = "STRING", mode = "NULLABLE" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "schema_version", type = "INTEGER", mode = "REQUIRED" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_dataset" "analytics" {
  count = local.analytics_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = var.analytics.dataset
  location                   = var.region
  description                = "Phase 26 curated, deduplicated analytics views; the only analyst surface."
  delete_contents_on_destroy = false

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "events_deduped" {
  count = local.analytics_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "events_deduped"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/events_deduped.sql.tftpl", {
      project     = var.project_id
      raw_dataset = var.analytics.raw_dataset
    })
  }

  depends_on = [google_bigquery_table.events]
}

resource "google_bigquery_table" "activation_funnel" {
  count = local.analytics_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "activation_funnel"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/activation_funnel.sql.tftpl", {
      project = var.project_id
      dataset = var.analytics.dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_table" "suggestion_success" {
  count = local.analytics_enabled ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "suggestion_success"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/suggestion_success.sql.tftpl", {
      project = var.project_id
      dataset = var.analytics.dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_dataset_access" "raw_writer" {
  count = local.analytics_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics_raw[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  iam_member = "serviceAccount:${google_service_account.async_worker[0].email}"
}

resource "google_bigquery_dataset_access" "authorized_view" {
  count = local.analytics_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics_raw[0].dataset_id

  view {
    project_id = var.project_id
    dataset_id = google_bigquery_dataset.analytics[0].dataset_id
    table_id   = google_bigquery_table.events_deduped[0].table_id
  }
}

resource "google_bigquery_dataset_access" "readers" {
  for_each = local.analytics_enabled ? toset(var.analytics.readers) : toset([])

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = "roles/bigquery.dataViewer"
  iam_member = each.value
}

# BigQuery requires a project-level role to run any job, including loads.
resource "google_project_iam_member" "analytics_job_user" {
  count = local.analytics_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.async_worker[0].email}"
}

resource "google_cloud_scheduler_job" "analytics_export" {
  count = local.analytics_enabled ? 1 : 0

  project          = var.project_id
  region           = var.region
  name             = var.analytics.scheduler_name
  description      = "Loads the analytics outbox into BigQuery at least once."
  schedule         = "*/15 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker[0].uri}/internal/analytics/export"
    body        = base64encode("{}")
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = google_service_account.async_invoker[0].email
      audience              = google_cloud_run_v2_service.worker[0].uri
    }
  }

  depends_on = [google_project_service.required]
}
