mock_provider "google" {}

override_data {
  target = data.google_project.current
  values = {
    project_id = "example-phase18-project"
    number     = "123456789012"
  }
}

# Pin computed async identities so IAM and output assertions stay plan-known
# under mocks. Applies only when async_suggestions resources exist.
override_resource {
  target          = google_service_account.async_invoker
  override_during = plan
  values = {
    email = "example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    name  = "projects/example-phase18-project/serviceAccounts/example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.async_worker
  override_during = plan
  values = {
    email = "example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    name  = "projects/example-phase18-project/serviceAccounts/example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_cloud_run_v2_service.worker
  override_during = plan
  values = {
    uri = "https://example-phase20-worker-abc-uc.a.run.app"
  }
}

override_resource {
  target          = google_service_account.deploy
  override_during = plan
  values = {
    email = "github-deploy@example-phase18-project.iam.gserviceaccount.com"
    name  = "projects/example-phase18-project/serviceAccounts/github-deploy@example-phase18-project.iam.gserviceaccount.com"
  }
}

variables {
  project_id = "example-phase18-project"
  region     = "us-west1"

  registry = {
    repository_id = "example-api"
    location      = "us-west1"
    format        = "DOCKER"
  }

  database = {
    instance_name               = "example-phase18-db"
    database_name               = "todo"
    database_deletion_policy    = "ABANDON"
    database_version            = "POSTGRES_16"
    region                      = "us-west1"
    deletion_protection         = true
    deletion_protection_enabled = true
    enable_dataplex_integration = true
    edition                     = "ENTERPRISE"
    tier                        = "db-custom-1-3840"
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 20
    disk_autoresize             = true
    disk_autoresize_limit       = 100
    activation_policy           = "ALWAYS"
    connector_enforcement       = "NOT_REQUIRED"
    database_flags              = {}
    backup = {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      retained_backups               = 7
      retention_unit                 = "COUNT"
    }
    network = {
      ipv4_enabled = true
      ssl_mode     = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }
  }

  service_accounts = {
    runtime   = { account_id = "example-runtime", display_name = "Example runtime" }
    migration = { account_id = "example-migration", display_name = "Example migration" }
  }
  enabled_services = ["artifactregistry.googleapis.com", "bigquery.googleapis.com", "billingbudgets.googleapis.com", "cloudscheduler.googleapis.com", "cloudtasks.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com", "sts.googleapis.com"]
  project_iam_members = {
    runtime_sql_client   = { role = "roles/cloudsql.client", member = "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com" }
    migration_sql_client = { role = "roles/cloudsql.client", member = "serviceAccount:example-migration@example-phase18-project.iam.gserviceaccount.com" }
  }
  secret_iam_members = {
    runtime_openrouter = { secret_key = "openrouter_api_key", role = "roles/secretmanager.secretAccessor", member = "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com" }
    runtime_database   = { secret_key = "database_url", role = "roles/secretmanager.secretAccessor", member = "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com" }
    migration_database = { secret_key = "database_url", role = "roles/secretmanager.secretAccessor", member = "serviceAccount:example-migration@example-phase18-project.iam.gserviceaccount.com" }
  }
  secrets = {
    openrouter_api_key = { secret_id = "example-openrouter-api-key", replication = { auto = {} } }
    database_url       = { secret_id = "example-database-url", replication = { auto = {} } }
  }

  api = {
    name                 = "example-phase18-api"
    identity             = "example-runtime@example-phase18-project.iam.gserviceaccount.com"
    image                = "us-west1-docker.pkg.dev/example-phase18-project/example-api/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    client               = "gcloud"
    client_version       = "584.0.0"
    ingress              = "INGRESS_TRAFFIC_ALL"
    invoker_iam_disabled = false
    deletion_protection  = true
    plain_env            = { OPENROUTER_MODEL = "openrouter/free" }
    secret_env = {
      OPENROUTER_API_KEY = { secret_key = "openrouter_api_key", version = "1" }
      DATABASE_URL       = { secret_key = "database_url", version = "1" }
    }
    cors_origins        = ["https://example-phase18.pages.dev"]
    sql_connection_name = "example-phase18-project:us-west1:example-phase18-db"
    service_scaling     = { min_instance_count = 0, max_instance_count = 2 }
    runtime = {
      timeout                          = "300s"
      max_instance_request_concurrency = 80
      min_instance_count               = 0
      max_instance_count               = 2
      command                          = ["sh", "-c"]
      args                             = ["exec uvicorn app.main:app --host 0.0.0.0 --port $${PORT:-8080}"]
      container_port                   = 8080
      cpu                              = "1"
      memory                           = "512Mi"
      cpu_idle                         = true
      startup_cpu_boost                = true
      revision                         = "fullstack-api-cleanup-20260914135601"
    }
    traffic = { stable = { type = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", percent = 100 } }
  }

  migration_job = {
    name                  = "example-phase18-migrate"
    identity              = "example-migration@example-phase18-project.iam.gserviceaccount.com"
    image                 = "us-west1-docker.pkg.dev/example-phase18-project/example-api/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    client                = "gcloud"
    client_version        = "584.0.0"
    command               = ["sh", "-c"]
    args                  = ["alembic upgrade head"]
    max_retries           = 1
    timeout               = "600s"
    task_count            = 1
    parallelism           = 1
    deletion_protection   = true
    sql_connection_name   = "example-phase18-project:us-west1:example-phase18-db"
    cpu                   = "1"
    memory                = "512Mi"
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    plain_env             = {}
    secret_env            = { DATABASE_URL = { secret_key = "database_url", version = "1" } }
  }

  async_suggestions = {
    worker_name             = "example-phase20-worker"
    worker_image            = "us-west1-docker.pkg.dev/example-phase18-project/example-api/api@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    queue_name              = "example-suggestions"
    scheduler_name          = "example-suggestion-expiry"
    invoker_account_id      = "example-sugg-invoker"
    worker_account_id       = "example-sugg-worker"
    scheduler_paused        = true
    database_secret_key     = "database_url"
    database_secret_version = "1"
    provider_secret_key     = "openrouter_api_key"
    provider_secret_version = "1"
    provider_model          = "openrouter/free"
  }

  budget     = null
  monitoring = null
}
run "analytics_disabled_by_default" {
  command = plan

  assert {
    condition     = length(google_bigquery_dataset.analytics_raw) == 0 && length(google_cloud_scheduler_job.analytics_export) == 0
    error_message = "Analytics must create nothing unless enabled."
  }
}

run "analytics_enabled" {
  command = plan

  variables {
    analytics = { readers = ["user:learner@example.test"] }
  }

  assert {
    condition     = google_bigquery_table.events[0].time_partitioning[0].field == "occurred_at" && google_bigquery_table.events[0].time_partitioning[0].expiration_ms == 34560000000
    error_message = "Raw events must be day-partitioned on occurred_at with 400-day expiration."
  }
  assert {
    condition     = google_bigquery_table.events[0].clustering == tolist(["event_name"]) && google_bigquery_table.events[0].deletion_protection
    error_message = "Raw events must cluster by event_name and be deletion-protected."
  }
  assert {
    condition     = google_bigquery_dataset_access.raw_writer[0].dataset_id == "analytics_raw" && google_bigquery_dataset_access.raw_writer[0].role == "roles/bigquery.dataEditor" && google_bigquery_dataset_access.raw_writer[0].iam_member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Only the worker identity may write raw events."
  }
  assert {
    condition     = google_bigquery_dataset_access.readers["user:learner@example.test"].dataset_id == "analytics" && google_bigquery_dataset_access.readers["user:learner@example.test"].role == "roles/bigquery.dataViewer"
    error_message = "Readers must be granted on the curated dataset only."
  }
  assert {
    condition     = google_bigquery_dataset_access.authorized_view[0].dataset_id == "analytics_raw" && google_bigquery_dataset_access.authorized_view[0].view[0].table_id == "events_deduped" && google_bigquery_dataset_access.authorized_view[0].view[0].dataset_id == "analytics"
    error_message = "events_deduped must be an authorized view on the raw dataset."
  }
  assert {
    condition     = strcontains(google_bigquery_table.events_deduped[0].view[0].query, "PARTITION BY event_id") && strcontains(google_bigquery_table.activation_funnel[0].view[0].query, "example-phase18-project.analytics.events_deduped")
    error_message = "Views must deduplicate by event_id and read the curated view."
  }
  assert {
    condition     = google_project_iam_member.analytics_job_user[0].role == "roles/bigquery.jobUser" && google_project_iam_member.analytics_job_user[0].member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The worker needs project jobUser to run load jobs."
  }
  assert {
    condition     = google_cloud_scheduler_job.analytics_export[0].schedule == "*/15 * * * *" && endswith(google_cloud_scheduler_job.analytics_export[0].http_target[0].uri, "/internal/analytics/export") && google_cloud_scheduler_job.analytics_export[0].http_target[0].oidc_token[0].service_account_email == "example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The export must run every 15 minutes against the worker route with the invoker identity."
  }
  assert {
    condition     = contains([for e in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : e.name if e.value == "example-phase18-project.analytics_raw.events"], "ANALYTICS_EVENTS_TABLE")
    error_message = "The worker must receive ANALYTICS_EVENTS_TABLE."
  }
}

run "analytics_requires_async_worker" {
  command = plan

  variables {
    async_suggestions = null
    analytics         = { readers = [] }
  }

  expect_failures = [var.analytics]
}
