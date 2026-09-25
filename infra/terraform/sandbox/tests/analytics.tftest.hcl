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

override_resource {
  target          = google_service_account.hex_reader
  override_during = plan
  values = {
    email = "example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.rudderstack_loader
  override_during = plan
  values = {
    email = "example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    name  = "projects/example-phase18-project/serviceAccounts/example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
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
    error_message = "The worker must get the only Terraform-managed write grant on raw events (BigQuery default project-role access still applies)."
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
    condition     = google_cloud_scheduler_job.analytics_export[0].retry_config[0].retry_count == 0 && google_cloud_scheduler_job.analytics_export[0].retry_config[0].min_backoff_duration == "5s" && google_cloud_scheduler_job.analytics_export[0].retry_config[0].max_backoff_duration == "3600s" && google_cloud_scheduler_job.analytics_export[0].retry_config[0].max_doublings == 5
    error_message = "The export job must keep zero retries with explicit backoff values, so the API retains retryConfig and plans stay clean."
  }
  assert {
    condition     = strcontains(google_bigquery_table.data_freshness[0].view[0].query, "MAX(loaded_at) AS last_loaded_at") && !strcontains(google_bigquery_table.data_freshness[0].view[0].query, "user_key") && !strcontains(google_bigquery_table.data_freshness[0].view[0].query, "event_id")
    error_message = "data_freshness must expose only the latest load time."
  }
  assert {
    condition     = google_bigquery_dataset_access.freshness_authorized_view[0].dataset_id == "analytics_raw" && google_bigquery_dataset_access.freshness_authorized_view[0].view[0].table_id == "data_freshness"
    error_message = "data_freshness must be an authorized view on the raw dataset."
  }
  assert {
    condition     = length(google_service_account.hex_reader) == 0
    error_message = "Hex identity must not exist unless hex is enabled."
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

run "hex_enabled" {
  command = plan

  variables {
    analytics = { readers = ["user:learner@example.test"] }
    hex       = {}
  }

  assert {
    condition     = google_service_account.hex_reader[0].account_id == "hex-reader"
    error_message = "The Hex identity must use the default account id."
  }
  assert {
    condition     = google_bigquery_dataset_access.hex_reader[0].dataset_id == "analytics" && google_bigquery_dataset_access.hex_reader[0].role == "roles/bigquery.dataViewer" && google_bigquery_dataset_access.hex_reader[0].iam_member == "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Hex must read only the curated analytics dataset."
  }
  assert {
    condition     = google_project_iam_member.hex_job_user[0].role == "roles/bigquery.jobUser" && google_project_iam_member.hex_job_user[0].member == "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Hex needs project jobUser to run queries, nothing broader."
  }
  assert {
    condition     = google_bigquery_dataset_access.raw_writer[0].iam_member != "serviceAccount:example-hex-reader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Hex must have no access to the raw dataset."
  }
}

run "hex_requires_analytics" {
  command = plan

  variables {
    analytics = null
    hex       = {}
  }

  expect_failures = [var.hex]
}

run "rudderstack_disabled_by_default" {
  command = plan

  variables {
    analytics = { readers = [] }
  }

  assert {
    condition     = length(google_bigquery_dataset.rudderstack_raw) == 0 && length(google_storage_bucket.rudderstack_staging) == 0 && length(google_iam_workload_identity_pool.rudderstack) == 0 && length(google_service_account.rudderstack_loader) == 0
    error_message = "RudderStack must create nothing unless enabled."
  }
}

run "rudderstack_enabled" {
  command = plan

  variables {
    analytics   = { readers = ["user:learner@example.test"] }
    rudderstack = { workspace_id = "2AbCdEfGh123" }
  }

  assert {
    condition     = google_bigquery_dataset.rudderstack_raw[0].dataset_id == "rudderstack_raw" && google_bigquery_dataset.rudderstack_raw[0].location == "us-west1"
    error_message = "The raw client dataset must be rudderstack_raw in the sandbox region."
  }
  assert {
    condition     = google_bigquery_dataset_access.rudderstack_loader[0].dataset_id == "rudderstack_raw" && google_bigquery_dataset_access.rudderstack_loader[0].role == "roles/bigquery.dataEditor" && google_bigquery_dataset_access.rudderstack_loader[0].iam_member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The loader must get dataEditor on rudderstack_raw only."
  }
  assert {
    condition     = google_project_iam_member.rudderstack_job_user[0].role == "roles/bigquery.jobUser" && google_project_iam_member.rudderstack_job_user[0].member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The loader needs project jobUser for load jobs, nothing broader."
  }
  assert {
    condition     = google_storage_bucket.rudderstack_staging[0].uniform_bucket_level_access && google_storage_bucket.rudderstack_staging[0].public_access_prevention == "enforced" && tolist(google_storage_bucket.rudderstack_staging[0].lifecycle_rule[0].condition)[0].age == 7 && tolist(google_storage_bucket.rudderstack_staging[0].lifecycle_rule[0].action)[0].type == "Delete"
    error_message = "The staging bucket must be uniform, non-public, and delete objects after 7 days."
  }
  assert {
    condition     = toset([for m in google_storage_bucket_iam_member.rudderstack_staging : m.role]) == toset(["roles/storage.objectCreator", "roles/storage.objectViewer"]) && alltrue([for m in google_storage_bucket_iam_member.rudderstack_staging : m.member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"])
    error_message = "The loader gets only object create and view, on the staging bucket only."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.rudderstack[0].aws[0].account_id == "422074288268" && google_iam_workload_identity_pool_provider.rudderstack[0].attribute_condition == "attribute.workspace == '2AbCdEfGh123'" && google_iam_workload_identity_pool_provider.rudderstack[0].attribute_mapping["attribute.workspace"] == "assertion.arn.extract('assumed-role/data-plane-service-account/{workspace}')"
    error_message = "The pool must trust only RudderStack's AWS account and this workspace."
  }
  assert {
    condition     = google_service_account_iam_member.rudderstack_wif[0].role == "roles/iam.workloadIdentityUser" && google_service_account_iam_member.rudderstack_wif[0].member == "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/rudderstack/attribute.workspace/2AbCdEfGh123"
    error_message = "Only this workspace's federated identity may impersonate the loader."
  }
  assert {
    condition     = length(google_bigquery_table.signup_funnel) == 0 && length(google_bigquery_table.suggestion_taps) == 0
    error_message = "Curated client views wait for curated_views = true (tables exist only after the first sync)."
  }
}

run "rudderstack_curated_views" {
  command = plan

  variables {
    analytics   = { readers = ["user:learner@example.test"] }
    rudderstack = { workspace_id = "2AbCdEfGh123", curated_views = true }
  }

  assert {
    condition     = strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "example-phase18-project.rudderstack_raw.identifies") && strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "example-phase18-project.analytics.events_deduped") && strcontains(google_bigquery_table.suggestion_taps[0].view[0].query, "INTERVAL 30 MINUTE")
    error_message = "The views must join client tables to the curated server events."
  }
  assert {
    condition     = alltrue([for q in [google_bigquery_table.signup_funnel[0].view[0].query, google_bigquery_table.suggestion_taps[0].view[0].query] : !strcontains(q, "context_") && strcontains(q, "PARTITION BY id")])
    error_message = "Views must deduplicate by message id and select no context (IP, user agent, URL) columns."
  }
  assert {
    condition     = toset([for a in google_bigquery_dataset_access.rudderstack_authorized_view : a.view[0].table_id]) == toset(["signup_funnel", "suggestion_taps"]) && alltrue([for a in google_bigquery_dataset_access.rudderstack_authorized_view : a.dataset_id == "rudderstack_raw"])
    error_message = "Both views must be authorized on rudderstack_raw."
  }
  assert {
    condition     = strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "example-phase18-project.rudderstack_raw.signin_submitted") && strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "returning_24h")
    error_message = "signup_funnel must exclude returning users (signin_submitted) from signup drop-off and report returning_24h."
  }
  assert {
    condition     = strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "INTERVAL 1 MINUTE")
    error_message = "signup_funnel must allow 1 minute of client/server clock slack when matching a signup submit to the server signup."
  }
}

run "rudderstack_requires_analytics" {
  command = plan

  variables {
    analytics   = null
    rudderstack = { workspace_id = "2AbCdEfGh123" }
  }

  expect_failures = [var.rudderstack]
}

run "rudderstack_rejects_unsafe_workspace_id" {
  command = plan

  variables {
    analytics   = { readers = [] }
    rudderstack = { workspace_id = "x' || true || '" }
  }

  expect_failures = [var.rudderstack]
}
