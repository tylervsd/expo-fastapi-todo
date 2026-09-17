# Phase 21 Task 4: native trace access, dashboard, and alerts. Mock-plan tests
# for the default-disabled observability additions. The deployment inputs
# (notification channel, SQL threshold, runbook URL) are sanitized mock
# values only; never commit real channels or thresholds.

mock_provider "google" {}

override_data {
  target = data.google_project.current
  values = {
    project_id = "example-phase18-project"
    number     = "123456789012"
  }
}

# Pin computed async identities so trace IAM and queue-filter assertions
# stay plan-known under mocks. Applies only when async resources exist.
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

# Pin the dashboard ID so the enabled output assertion stays plan-known
# under mocks. Applies only when the dashboard resource exists.
override_resource {
  target          = google_monitoring_dashboard.observability
  override_during = plan
  values = {
    id = "projects/example-phase18-project/dashboards/phase21-observability"
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
  enabled_services = ["artifactregistry.googleapis.com", "billingbudgets.googleapis.com", "cloudscheduler.googleapis.com", "cloudtasks.googleapis.com", "cloudtrace.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com", "sts.googleapis.com"]
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

  observability = {
    notification_channels    = ["projects/example-phase18-project/notificationChannels/1234567890123456789"]
    sql_connection_threshold = 40
    runbook_url              = "https://example.invalid/runbooks/observability"
    trace_sample_rate        = 0.1
  }

  budget     = null
  monitoring = null
}

run "observability_disabled" {
  command = plan
  variables {
    observability   = null
    async_suggestions = null
  }

  assert {
    condition     = length(google_logging_metric.provider_calls) == 0
    error_message = "No provider-call log metric must exist when observability is null."
  }
  assert {
    condition     = length(google_logging_metric.provider_duration) == 0
    error_message = "No provider-duration log metric must exist when observability is null."
  }
  assert {
    condition     = length(google_logging_metric.suggestion_outcomes) == 0
    error_message = "No suggestion-outcome log metric must exist when observability is null."
  }
  assert {
    condition     = length(google_monitoring_dashboard.observability) == 0
    error_message = "No observability dashboard must exist when observability is null."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.app_failure) == 0
    error_message = "No application-failure alert must exist when observability is null."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.queue_backlog) == 0
    error_message = "No queue-backlog alert must exist when observability is null."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.sql_connections) == 0
    error_message = "No SQL-connections alert must exist when observability is null."
  }
  assert {
    condition     = length(google_project_iam_member.trace_api) == 0 && length(google_project_iam_member.trace_worker) == 0
    error_message = "No trace IAM grants must exist when observability is null."
  }
  assert {
    condition     = output.observability_dashboard_id == null
    error_message = "The dashboard output must be null when observability is disabled."
  }
  assert {
    condition     = output.observability_log_metrics == null
    error_message = "The log-metric output must be null when observability is disabled."
  }
  assert {
    condition     = output.observability_alert_policies == null
    error_message = "The alert-policy output must be null when observability is disabled."
  }
  assert {
    condition     = output.observability_trace_sample_rate == null
    error_message = "The sample-rate output must be null when observability is disabled."
  }
  assert {
    condition     = !contains([for e in google_cloud_run_v2_service.api.template[0].containers[0].env : e.name], "TRACE_SAMPLE_RATE")
    error_message = "The API must not carry TRACE_SAMPLE_RATE when observability is disabled."
  }
}

run "trace_iam_least_privilege" {
  command = plan

  assert {
    condition     = google_project_iam_member.trace_api[0].role == "roles/cloudtrace.agent"
    error_message = "The API runtime identity must hold the Cloud Trace agent role."
  }
  assert {
    condition     = google_project_iam_member.trace_api[0].member == "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The API trace grant must belong to the API runtime identity."
  }
  assert {
    condition     = google_project_iam_member.trace_worker[0].role == "roles/cloudtrace.agent"
    error_message = "The worker runtime identity must hold the Cloud Trace agent role."
  }
  assert {
    condition     = google_project_iam_member.trace_worker[0].member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The worker trace grant must belong to the worker runtime identity."
  }
  assert {
    condition = alltrue([
      for grant in concat(
        [google_project_iam_member.trace_api[0].member],
        [google_project_iam_member.trace_worker[0].member],
      ) : grant != "serviceAccount:example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    ])
    error_message = "The task invoker must hold no trace-writing role."
  }
  assert {
    condition = alltrue([
      for grant in concat(
        [google_project_iam_member.trace_api[0].member],
        [google_project_iam_member.trace_worker[0].member],
      ) : !contains(["allUsers", "allAuthenticatedUsers"], grant)
    ])
    error_message = "No trace grant may use an unauthenticated principal."
  }
}

run "trace_worker_absent_without_async" {
  command = plan
  variables { async_suggestions = null }

  assert {
    condition     = length(google_project_iam_member.trace_api) == 1
    error_message = "The API trace grant must exist without async delivery."
  }
  assert {
    condition     = length(google_project_iam_member.trace_worker) == 0
    error_message = "No worker trace grant must exist without async delivery."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.queue_backlog) == 0
    error_message = "No queue-backlog alert must exist without a queue to watch."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.app_failure) == 1
    error_message = "The application-failure alert must exist without async delivery."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.sql_connections) == 1
    error_message = "The SQL-connections alert must exist without async delivery."
  }
}

run "log_metrics" {
  command = plan

  assert {
    condition     = google_logging_metric.provider_calls[0].name == "phase21_provider_calls"
    error_message = "The provider-call metric must use the specified name."
  }
  assert {
    condition     = strcontains(google_logging_metric.provider_calls[0].filter, "jsonPayload.event=\"provider_call\"")
    error_message = "The provider-call metric must filter on the provider_call event."
  }
  assert {
    condition     = sort(keys(google_logging_metric.provider_calls[0].label_extractors)) == tolist(["operation", "outcome"])
    error_message = "The provider-call metric must expose exactly the bounded operation and outcome labels."
  }
  assert {
    condition     = google_logging_metric.provider_calls[0].metric_descriptor[0].metric_kind == "DELTA" && google_logging_metric.provider_calls[0].metric_descriptor[0].value_type == "INT64"
    error_message = "The provider-call metric must be a delta int64 counter."
  }
  assert {
    condition     = google_logging_metric.provider_duration[0].name == "phase21_provider_duration_ms"
    error_message = "The provider-duration metric must use the specified name."
  }
  assert {
    condition     = strcontains(google_logging_metric.provider_duration[0].filter, "jsonPayload.event=\"provider_call\"")
    error_message = "The provider-duration metric must filter on the provider_call event."
  }
  assert {
    condition     = google_logging_metric.provider_duration[0].value_extractor == "EXTRACT(jsonPayload.duration_ms)"
    error_message = "The provider-duration metric must extract the provider duration field."
  }
  assert {
    condition     = sort(keys(google_logging_metric.provider_duration[0].label_extractors)) == tolist(["operation"])
    error_message = "The provider-duration metric must expose exactly the bounded operation label."
  }
  assert {
    condition     = google_logging_metric.provider_duration[0].metric_descriptor[0].value_type == "DISTRIBUTION"
    error_message = "The provider-duration metric must be a distribution."
  }
  assert {
    condition     = google_logging_metric.suggestion_outcomes[0].name == "phase21_suggestion_outcomes"
    error_message = "The suggestion-outcome metric must use the specified name."
  }
  assert {
    condition     = strcontains(google_logging_metric.suggestion_outcomes[0].filter, "jsonPayload.event=\"suggestion_finished\"")
    error_message = "The suggestion-outcome metric must filter on committed suggestion_finished events."
  }
  assert {
    condition     = sort(keys(google_logging_metric.suggestion_outcomes[0].label_extractors)) == tolist(["error_code", "outcome"])
    error_message = "The suggestion-outcome metric must expose exactly the bounded outcome and error-code labels."
  }
  assert {
    condition     = google_logging_metric.suggestion_outcomes[0].metric_descriptor[0].metric_kind == "DELTA" && google_logging_metric.suggestion_outcomes[0].metric_descriptor[0].value_type == "INT64"
    error_message = "The suggestion-outcome metric must be a delta int64 counter."
  }
  assert {
    condition = alltrue([
      for metric in [
        google_logging_metric.provider_calls[0],
        google_logging_metric.provider_duration[0],
        google_logging_metric.suggestion_outcomes[0],
      ] : !strcontains(jsonencode(metric.label_extractors), "workflow")
    ])
    error_message = "No log metric may carry a workflow label."
  }
  assert {
    condition = alltrue([
      for metric in [
        google_logging_metric.provider_calls[0],
        google_logging_metric.provider_duration[0],
        google_logging_metric.suggestion_outcomes[0],
      ] : !strcontains(jsonencode(metric.label_extractors), "attempt_id")
    ])
    error_message = "No log metric may carry an attempt ID label."
  }
}

run "failure_alert" {
  command = plan

  assert {
    condition     = google_monitoring_alert_policy.app_failure[0].combiner == "OR"
    error_message = "The application-failure alert must combine its failure signals with OR."
  }
  assert {
    condition     = google_monitoring_alert_policy.app_failure[0].notification_channels == tolist(["projects/example-phase18-project/notificationChannels/1234567890123456789"])
    error_message = "The application-failure alert must notify the inventoried channel."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"suggestion_finished\"")
    error_message = "The failure filter must include saved suggestion failures."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"maintenance_finished\"")
    error_message = "The failure filter must include maintenance failures."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"agent_finished\"")
    error_message = "The failure filter must include agent failures."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"unexpected_fault\"")
    error_message = "The failure filter must include unexpected faults."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "claim_unavailable")
    error_message = "The failure filter must include claim unavailability."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "invalid_stored_row")
    error_message = "The failure filter must include fail-closed stored-row rejections."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "claim_failed")
    error_message = "The failure filter must include unexpected claim failures."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "finalize_unavailable")
    error_message = "The failure filter must include finalize unavailability."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "finalize_failed")
    error_message = "The failure filter must include finalize failures."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "malformed")
    error_message = "The failure filter must include malformed worker-task rejections."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "oversized")
    error_message = "The failure filter must include oversized worker-task rejections."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"direct_log\"")
    error_message = "Rejected worker tasks travel as redacted direct logs; the filter must match that event."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "jsonPayload.event=\"http_request\"")
    error_message = "The failure filter must include server-error HTTP signals for enqueue unavailability."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "/todo-workflows/{workflow_id}/suggestions")
    error_message = "The enqueue-unavailability clause must stay scoped to the suggestion request route."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "provider_call")
    error_message = "The failure filter must not double-alert transport logs alongside saved outcomes."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "ai_output_rejected")
    error_message = "The failure filter must not double-alert output-rejection diagnostics alongside saved outcomes."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "invalid_request")
    error_message = "The failure filter must exclude normal 4xx agent validation outcomes."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "no_work")
    error_message = "The failure filter must exclude no-work replays."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "live_claim_retry")
    error_message = "The failure filter must exclude expected live-claim retries."
  }
  assert {
    condition     = !strcontains(google_monitoring_alert_policy.app_failure[0].conditions[0].condition_matched_log[0].filter, "discarded")
    error_message = "The failure filter must exclude discarded late work."
  }
  assert {
    condition     = google_monitoring_alert_policy.app_failure[0].alert_strategy[0].notification_rate_limit[0].period == "3600s"
    error_message = "The failure alert must throttle to one notification per hour."
  }
  assert {
    condition     = google_monitoring_alert_policy.app_failure[0].alert_strategy[0].auto_close == "86400s"
    error_message = "The failure alert must auto-close after 24 hours."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.app_failure[0].documentation[0].content, "https://example.invalid/runbooks/observability")
    error_message = "The failure alert must attach the runbook URL."
  }
}

run "queue_alert" {
  command = plan

  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].notification_channels == tolist(["projects/example-phase18-project/notificationChannels/1234567890123456789"])
    error_message = "The queue-backlog alert must notify the inventoried channel."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].filter, "cloudtasks.googleapis.com/queue/depth")
    error_message = "The queue-backlog alert must watch queue depth, not dispatch delay."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].filter, "example-suggestions")
    error_message = "The queue-backlog alert must target the configured queue."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].comparison == "COMPARISON_GT"
    error_message = "The queue-backlog alert must fire when depth is greater than zero."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].threshold_value == 0
    error_message = "The queue-backlog threshold must be zero."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].duration == "300s"
    error_message = "The queue-backlog alert must require five continuous minutes."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].aggregations[0].alignment_period == "60s"
    error_message = "The queue-backlog alert must align on 60-second windows."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].aggregations[0].per_series_aligner == "ALIGN_MAX"
    error_message = "The queue-backlog alert must use 60-second maxima."
  }
  assert {
    condition     = google_monitoring_alert_policy.queue_backlog[0].conditions[0].condition_threshold[0].evaluation_missing_data == "EVALUATION_MISSING_DATA_NO_OP"
    error_message = "Missing queue data must hold the prior state: absence is not proof of health."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.queue_backlog[0].documentation[0].content, "https://example.invalid/runbooks/observability")
    error_message = "The queue-backlog alert must attach the runbook URL."
  }
}

run "sql_alert" {
  command = plan

  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].notification_channels == tolist(["projects/example-phase18-project/notificationChannels/1234567890123456789"])
    error_message = "The SQL-connections alert must notify the inventoried channel."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].filter, "cloudsql.googleapis.com/database/postgresql/num_backends")
    error_message = "The SQL-connections alert must watch summed backend connections."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].filter, "example-phase18-project:example-phase18-db")
    error_message = "The SQL-connections alert must target the selected instance."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].comparison == "COMPARISON_GT"
    error_message = "The SQL-connections alert must fire above the capacity threshold."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].threshold_value == 40
    error_message = "The SQL-connections alert must use the deployment threshold input."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].duration == "300s"
    error_message = "The SQL-connections alert must require five continuous minutes."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].aggregations[0].alignment_period == "60s"
    error_message = "The SQL-connections alert must align on 60-second windows."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].aggregations[0].per_series_aligner == "ALIGN_MAX"
    error_message = "The SQL-connections alert must use 60-second maxima."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].aggregations[0].cross_series_reducer == "REDUCE_SUM"
    error_message = "The SQL-connections alert must sum connection series across database and state series."
  }
  assert {
    condition     = google_monitoring_alert_policy.sql_connections[0].conditions[0].condition_threshold[0].evaluation_missing_data == "EVALUATION_MISSING_DATA_NO_OP"
    error_message = "Missing SQL data must hold the prior state: absence is not proof of health."
  }
  assert {
    condition     = strcontains(google_monitoring_alert_policy.sql_connections[0].documentation[0].content, "https://example.invalid/runbooks/observability")
    error_message = "The SQL-connections alert must attach the runbook URL."
  }
}

run "dashboard" {
  command = plan

  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "phase21_provider_calls")
    error_message = "The dashboard must chart provider-call signals."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "phase21_provider_duration_ms")
    error_message = "The dashboard must chart provider latency."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "phase21_suggestion_outcomes")
    error_message = "The dashboard must chart saved suggestion outcomes."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "run.googleapis.com/request_count")
    error_message = "The dashboard must chart native Cloud Run request status."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "response_code_class")
    error_message = "Native request-count charts must break down by status/error class."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "run.googleapis.com/request_latencies")
    error_message = "The dashboard must chart native Cloud Run latency."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "cloudtasks.googleapis.com/queue/depth")
    error_message = "The dashboard must chart queue depth."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "cloudtasks.googleapis.com/queue/task_attempt_count")
    error_message = "The dashboard must chart task attempt outcomes."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "cloudsql.googleapis.com/database/postgresql/num_backends")
    error_message = "The dashboard must chart SQL connections."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "console.cloud.google.com/traces")
    error_message = "The dashboard must link to Cloud Trace."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "console.cloud.google.com/logs")
    error_message = "The dashboard must link to diagnostic logs."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "console.cloud.google.com/billing")
    error_message = "The dashboard must link to billing views."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "console.cloud.google.com/error-reporting")
    error_message = "The dashboard must link to Error Reporting."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "https://example.invalid/runbooks/observability")
    error_message = "The dashboard must link the runbook."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "HTTP success is not a saved suggestion")
    error_message = "The dashboard must keep native request status distinct from saved outcomes."
  }
}

run "dashboard_without_async" {
  command = plan
  variables { async_suggestions = null }

  assert {
    condition     = !strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "cloudtasks.googleapis.com/queue/depth")
    error_message = "The dashboard must omit queue signals without async delivery."
  }
  assert {
    condition     = strcontains(google_monitoring_dashboard.observability[0].dashboard_json, "phase21_suggestion_outcomes")
    error_message = "The dashboard must keep suggestion outcomes without async delivery."
  }
}

run "trace_sample_rate_env" {
  command = plan

  assert {
    condition     = ({ for e in google_cloud_run_v2_service.api.template[0].containers[0].env : e.name => e.value if e.value != null })["TRACE_SAMPLE_RATE"] == "0.1"
    error_message = "The API runtime must receive TRACE_SAMPLE_RATE 0.1 from the default observability setting."
  }
  assert {
    condition     = ({ for e in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : e.name => e.value if e.value != null })["TRACE_SAMPLE_RATE"] == "0.1"
    error_message = "The worker runtime must receive TRACE_SAMPLE_RATE 0.1 from the default observability setting."
  }
}

run "trace_sample_rate_env_drill" {
  command = plan
  variables {
    observability = merge(var.observability, { trace_sample_rate = 1.0 })
  }

  assert {
    condition     = ({ for e in google_cloud_run_v2_service.api.template[0].containers[0].env : e.name => e.value if e.value != null })["TRACE_SAMPLE_RATE"] == "1"
    error_message = "The API runtime must receive the drill TRACE_SAMPLE_RATE 1.0."
  }
  assert {
    condition     = ({ for e in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : e.name => e.value if e.value != null })["TRACE_SAMPLE_RATE"] == "1"
    error_message = "The worker runtime must receive the drill TRACE_SAMPLE_RATE 1.0."
  }
}

run "sample_configuration" {
  command = plan

  assert {
    condition     = output.observability_trace_sample_rate == 0.1
    error_message = "The default trace sample rate must be 0.1 for ordinary sandbox operation."
  }
}

run "sample_configuration_drill" {
  command = plan
  variables {
    observability = merge(var.observability, { trace_sample_rate = 1.0 })
  }

  assert {
    condition     = output.observability_trace_sample_rate == 1.0
    error_message = "The trace sample rate must accept 1.0 for bounded acceptance drills."
  }
}

run "rejects_sample_rate_above_one" {
  command         = plan
  expect_failures = [var.observability]
  variables {
    observability = merge(var.observability, { trace_sample_rate = 1.5 })
  }
}

run "rejects_negative_sample_rate" {
  command         = plan
  expect_failures = [var.observability]
  variables {
    observability = merge(var.observability, { trace_sample_rate = -0.1 })
  }
}

run "rejects_empty_notification_channels" {
  command         = plan
  expect_failures = [var.observability]
  variables {
    observability = merge(var.observability, { notification_channels = [] })
  }
}

run "rejects_nonpositive_sql_threshold" {
  command         = plan
  expect_failures = [var.observability]
  variables {
    observability = merge(var.observability, { sql_connection_threshold = 0 })
  }
}

run "rejects_missing_trace_api" {
  command         = plan
  expect_failures = [var.observability]
  variables {
    enabled_services = ["artifactregistry.googleapis.com", "cloudscheduler.googleapis.com", "cloudtasks.googleapis.com", "logging.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "sqladmin.googleapis.com"]
  }
}

run "rejects_manual_trace_sample_rate_plain_env" {
  command         = plan
  expect_failures = [google_cloud_run_v2_service.api]
  variables {
    api = merge(var.api, { plain_env = merge(var.api.plain_env, { TRACE_SAMPLE_RATE = "0.5" }) })
  }
}

run "rejects_manual_trace_sample_rate_secret_env" {
  command         = plan
  expect_failures = [google_cloud_run_v2_service.api]
  variables {
    api = merge(var.api, { secret_env = merge(var.api.secret_env, { TRACE_SAMPLE_RATE = { secret_key = "database_url", version = "1" } }) })
  }
}

run "allows_manual_trace_sample_rate_when_disabled" {
  command = plan
  variables {
    observability = null
    api           = merge(var.api, { plain_env = merge(var.api.plain_env, { TRACE_SAMPLE_RATE = "0.5" }) })
  }

  assert {
    condition     = ({ for e in google_cloud_run_v2_service.api.template[0].containers[0].env : e.name => e.value if e.value != null })["TRACE_SAMPLE_RATE"] == "0.5"
    error_message = "The API must keep a manually set TRACE_SAMPLE_RATE when observability is disabled."
  }
}

run "preserves_existing" {
  command = plan
  variables {
    budget = {
      billing_account = "billingAccounts/000000-111111-222222"
      display_name    = "Example sandbox budget"
      amount          = { currency_code = "USD", units = "100", nanos = 0 }
      calendar_period = "CALENDAR_PERIOD_UNSPECIFIED"
      threshold_rules = [{ percent = 50 }, { percent = 80 }, { percent = 100 }]
    }
    monitoring = {
      uptime_check = {
        display_name              = "Example API uptime"
        monitored_resource_type   = "uptime_url"
        monitored_resource_labels = { host = "example-phase18.run.app" }
        path                      = "/health"
        period                    = "300s"
        timeout                   = "10s"
        use_ssl                   = true
        validate_ssl              = true
      }
      alert_policy = {
        display_name          = "Example uptime alert"
        combiner              = "OR"
        notification_channels = ["projects/example-phase18-project/notificationChannels/1234567890123456789"]
        filter                = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\""
        comparison            = "COMPARISON_LT"
        threshold_value       = 1
        duration              = "300s"
        alignment_period      = "300s"
      }
    }
  }

  assert {
    condition     = length(google_billing_budget.sandbox) == 1
    error_message = "Enabling observability must preserve the existing budget resource."
  }
  assert {
    condition     = google_billing_budget.sandbox[0].display_name == "Example sandbox budget"
    error_message = "Enabling observability must preserve the budget amount identity."
  }
  assert {
    condition     = length(google_monitoring_uptime_check_config.api) == 1
    error_message = "Enabling observability must preserve the existing uptime check."
  }
  assert {
    condition     = length(google_monitoring_alert_policy.api) == 1
    error_message = "Enabling observability must preserve the existing uptime alert."
  }
  assert {
    condition     = google_cloud_run_v2_service.api.template[0].containers[0].resources[0].cpu_idle == true
    error_message = "The API must keep request-based CPU allocation; observability must not enable always-allocated CPU."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].containers[0].resources[0].cpu_idle == true
    error_message = "The worker must keep request-based CPU allocation; observability must not enable always-allocated CPU."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].scaling[0].max_instance_count == 1
    error_message = "The worker instance limit must stay at 1."
  }
  assert {
    condition     = output.observability_dashboard_id != null
    error_message = "The dashboard output must be set when observability is enabled."
  }
  assert {
    condition     = output.observability_log_metrics[0] == "phase21_provider_calls" && output.observability_log_metrics[1] == "phase21_provider_duration_ms" && output.observability_log_metrics[2] == "phase21_suggestion_outcomes"
    error_message = "The log-metric output must list exactly the three specified metrics."
  }
}
