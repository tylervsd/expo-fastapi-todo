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
  enabled_services = ["artifactregistry.googleapis.com", "billingbudgets.googleapis.com", "cloudscheduler.googleapis.com", "cloudtasks.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com", "sts.googleapis.com"]
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

run "async_disabled" {
  command = plan
  variables { async_suggestions = null }

  assert {
    condition     = length(google_cloud_tasks_queue.suggestions) == 0
    error_message = "No suggestion queue must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_cloud_run_v2_service.worker) == 0
    error_message = "No suggestion worker must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_cloud_scheduler_job.suggestion_expiry) == 0
    error_message = "No suggestion expiry schedule must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_service_account.async_invoker) == 0 && length(google_service_account.async_worker) == 0
    error_message = "No async identities must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_cloud_tasks_queue_iam_member.api_enqueuer) == 0
    error_message = "No queue enqueuer grant must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_service_account_iam_member.api_invoker_user) == 0
    error_message = "No invoker act-as grant must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_project_iam_member.worker_sql_client) == 0
    error_message = "No worker Cloud SQL grant must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.worker_secret_access) == 0
    error_message = "No worker secret grant must exist when async_suggestions is null."
  }
  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.worker_invoker) == 0
    error_message = "No worker invocation grant must exist when async_suggestions is null."
  }
  assert {
    condition     = output.suggestion_worker_uri == null
    error_message = "The worker URI output must be null when async is disabled."
  }
  assert {
    condition     = output.suggestion_queue_name == null
    error_message = "The queue name output must be null when async is disabled."
  }
  assert {
    condition     = output.suggestion_invoker_email == null
    error_message = "The invoker email output must be null when async is disabled."
  }
}

run "async_queue" {
  command = plan

  assert {
    condition     = google_cloud_tasks_queue.suggestions[0].name == "example-suggestions"
    error_message = "The suggestion queue must use the configured queue name."
  }
  assert {
    condition     = google_cloud_tasks_queue.suggestions[0].location == "us-west1"
    error_message = "The suggestion queue must reuse the sandbox region."
  }
  assert {
    condition     = google_cloud_tasks_queue.suggestions[0].rate_limits[0].max_dispatches_per_second == 1 && google_cloud_tasks_queue.suggestions[0].rate_limits[0].max_concurrent_dispatches == 2
    error_message = "The suggestion queue must dispatch 1 per second with 2 concurrent dispatches."
  }
  assert {
    condition     = google_cloud_tasks_queue.suggestions[0].retry_config[0].max_attempts == 5 && google_cloud_tasks_queue.suggestions[0].retry_config[0].max_retry_duration == "0s" && google_cloud_tasks_queue.suggestions[0].retry_config[0].min_backoff == "10s" && google_cloud_tasks_queue.suggestions[0].retry_config[0].max_backoff == "60s" && google_cloud_tasks_queue.suggestions[0].retry_config[0].max_doublings == 3
    error_message = "The suggestion queue must use attempt-limited retries with 10s/60s backoff."
  }
  assert {
    condition     = google_cloud_tasks_queue.suggestions[0].stackdriver_logging_config[0].sampling_ratio == 1.0
    error_message = "The suggestion queue must sample operation logs at 1.0."
  }
}

run "async_worker" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.worker[0].name == "example-phase20-worker"
    error_message = "The worker service must use the configured worker name."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].location == "us-west1"
    error_message = "The worker service must reuse the sandbox region."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].service_account == "example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The worker service must run as the worker runtime identity."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].timeout == "60s"
    error_message = "The worker request timeout must be 60s."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].max_instance_request_concurrency == 2
    error_message = "The worker concurrency must be 2."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.worker[0].template[0].scaling[0].max_instance_count == 1
    error_message = "The worker must scale from 0 to 1 instances."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].containers[0].image == "us-west1-docker.pkg.dev/example-phase18-project/example-api/api@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    error_message = "The worker must run the configured immutable image."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].containers[0].command == tolist(["sh", "-c"])
    error_message = "The worker must launch through sh -c."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].containers[0].args == tolist(["exec uvicorn app.worker:app --host 0.0.0.0 --port \"$${PORT:-8080}\""])
    error_message = "The worker must serve app.worker with an escaped PORT default."
  }
  assert {
    condition     = google_cloud_run_v2_service.worker[0].template[0].containers[0].resources[0].limits.cpu == "1" && google_cloud_run_v2_service.worker[0].template[0].containers[0].resources[0].limits.memory == "512Mi"
    error_message = "The worker must use 1 CPU and 512MiB."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : env.value if env.name == "OPENROUTER_MODEL"]) == "openrouter/free"
    error_message = "The worker provider model must come from the async configuration."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : env.value_source[0].secret_key_ref[0].version if env.name == "DATABASE_URL"]) == "1"
    error_message = "The worker DATABASE_URL must reference numeric secret version 1."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : env.value_source[0].secret_key_ref[0].version if env.name == "OPENROUTER_API_KEY"]) == "1"
    error_message = "The worker OPENROUTER_API_KEY must reference numeric secret version 1."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : env.value_source[0].secret_key_ref[0].secret if env.name == "DATABASE_URL"]) == "example-database-url"
    error_message = "The worker DATABASE_URL must reference the inventoried database secret."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.worker[0].template[0].containers[0].env : env.value_source[0].secret_key_ref[0].secret if env.name == "OPENROUTER_API_KEY"]) == "example-openrouter-api-key"
    error_message = "The worker OPENROUTER_API_KEY must reference the inventoried provider secret."
  }
  assert {
    condition     = contains(toset(google_cloud_run_v2_service.worker[0].template[0].volumes[0].cloud_sql_instance[0].instances), "example-phase18-project:us-west1:example-phase18-db") && google_cloud_run_v2_service.worker[0].template[0].containers[0].volume_mounts[0].mount_path == "/cloudsql"
    error_message = "The worker must preserve the Cloud SQL socket mount."
  }
  assert {
    condition     = output.suggestion_worker_uri == "https://example-phase20-worker-abc-uc.a.run.app"
    error_message = "The worker URI output must expose the worker service URI."
  }
  assert {
    condition     = output.suggestion_queue_name == "example-suggestions"
    error_message = "The queue name output must expose the suggestion queue name."
  }
  assert {
    condition     = output.suggestion_invoker_email == "example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The invoker email output must expose the invocation identity."
  }
}

run "async_scheduler" {
  command = plan

  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].name == "example-suggestion-expiry"
    error_message = "The expiry schedule must use the configured scheduler name."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].schedule == "*/5 * * * *"
    error_message = "The expiry schedule must run every five minutes."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].time_zone == "Etc/UTC"
    error_message = "The expiry schedule must use Etc/UTC."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].attempt_deadline == "30s"
    error_message = "The expiry attempt deadline must be 30s."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].retry_config[0].retry_count == 0
    error_message = "The expiry schedule must not retry."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].paused
    error_message = "The expiry schedule must start paused."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].http_target[0].http_method == "POST"
    error_message = "The expiry schedule must POST."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].http_target[0].uri == "https://example-phase20-worker-abc-uc.a.run.app/internal/suggestions/expire"
    error_message = "The expiry schedule must call the worker expiry route."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].http_target[0].body == "e30="
    error_message = "The expiry schedule must send an empty JSON object."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].http_target[0].oidc_token[0].service_account_email == "example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The expiry schedule must mint OIDC tokens as the invocation identity."
  }
  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].http_target[0].oidc_token[0].audience == "https://example-phase20-worker-abc-uc.a.run.app"
    error_message = "The expiry OIDC audience must be the worker root URI."
  }
}

run "async_scheduler_unpaused" {
  command = plan
  variables {
    async_suggestions = merge(var.async_suggestions, { scheduler_paused = false })
  }

  assert {
    condition     = google_cloud_scheduler_job.suggestion_expiry[0].paused == false
    error_message = "The expiry schedule must honor scheduler_paused = false."
  }
}

run "async_least_privilege" {
  command = plan

  assert {
    condition     = google_cloud_tasks_queue_iam_member.api_enqueuer[0].role == "roles/cloudtasks.enqueuer"
    error_message = "The API identity must hold only the enqueuer role on the suggestion queue."
  }
  assert {
    condition     = google_cloud_tasks_queue_iam_member.api_enqueuer[0].member == "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The enqueuer grant must belong to the API runtime identity."
  }
  assert {
    condition     = google_cloud_tasks_queue_iam_member.api_enqueuer[0].name == google_cloud_tasks_queue.suggestions[0].name
    error_message = "The enqueuer grant must target only the suggestion queue."
  }
  assert {
    condition     = google_service_account_iam_member.api_invoker_user[0].role == "roles/iam.serviceAccountUser"
    error_message = "The API identity must hold Service Account User on the invocation identity."
  }
  assert {
    condition     = google_service_account_iam_member.api_invoker_user[0].member == "serviceAccount:example-runtime@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The invoker act-as grant must belong to the API runtime identity."
  }
  assert {
    condition     = google_service_account_iam_member.api_invoker_user[0].service_account_id == google_service_account.async_invoker[0].name
    error_message = "The invoker act-as grant must target the invocation identity."
  }
  assert {
    condition     = google_project_iam_member.worker_sql_client[0].role == "roles/cloudsql.client"
    error_message = "The worker identity must hold only the Cloud SQL client role."
  }
  assert {
    condition     = google_project_iam_member.worker_sql_client[0].member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The worker Cloud SQL grant must belong to the worker runtime identity."
  }
  assert {
    condition     = length(google_secret_manager_secret_iam_member.worker_secret_access) == 2
    error_message = "The worker identity must hold exactly two secret accessor grants."
  }
  assert {
    condition = alltrue([
      for grant in google_secret_manager_secret_iam_member.worker_secret_access :
      grant.role == "roles/secretmanager.secretAccessor"
      && grant.member == "serviceAccount:example-sugg-worker@example-phase18-project.iam.gserviceaccount.com"
    ])
    error_message = "Both worker secret grants must be accessor grants for the worker identity."
  }
  assert {
    condition     = sort([for grant in google_secret_manager_secret_iam_member.worker_secret_access : grant.secret_id]) == tolist(["example-database-url", "example-openrouter-api-key"])
    error_message = "The worker secret grants must target exactly the database and provider secrets."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.worker_invoker[0].role == "roles/run.invoker"
    error_message = "Worker invocation must use the Cloud Run invoker role."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.worker_invoker[0].member == "serviceAccount:example-sugg-invoker@example-phase18-project.iam.gserviceaccount.com"
    error_message = "Worker invocation must belong to the shared invocation identity used by Tasks and Scheduler."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.worker_invoker[0].name == google_cloud_run_v2_service.worker[0].name
    error_message = "The invocation grant must target only the worker service."
  }
  assert {
    condition = alltrue([
      for member in concat(
        [google_cloud_tasks_queue_iam_member.api_enqueuer[0].member],
        [google_service_account_iam_member.api_invoker_user[0].member],
        [google_project_iam_member.worker_sql_client[0].member],
        [for grant in google_secret_manager_secret_iam_member.worker_secret_access : grant.member],
        [google_cloud_run_v2_service_iam_member.worker_invoker[0].member],
      ) : !contains(["allUsers", "allAuthenticatedUsers"], member)
    ])
    error_message = "No async grant may use an unauthenticated principal."
  }
}

run "rejects_mutable_worker_image" {
  command         = plan
  expect_failures = [var.async_suggestions]
  variables {
    async_suggestions = merge(var.async_suggestions, { worker_image = "us-west1-docker.pkg.dev/example-phase18-project/example-api/api:latest" })
  }
}

run "rejects_non_numeric_worker_secret_version" {
  command         = plan
  expect_failures = [var.async_suggestions]
  variables {
    async_suggestions = merge(var.async_suggestions, { database_secret_version = "latest" })
  }
}

run "rejects_unknown_worker_secret_key" {
  command         = plan
  expect_failures = [var.async_suggestions]
  variables {
    async_suggestions = merge(var.async_suggestions, { provider_secret_key = "not-inventoried" })
  }
}

run "rejects_missing_task_apis" {
  command         = plan
  expect_failures = [var.async_suggestions]
  variables {
    enabled_services = ["artifactregistry.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "sqladmin.googleapis.com"]
  }
}

run "delivery_worker_grants" {
  command = plan
  variables {
    github_delivery = {
      repository    = "example-owner/example-repo"
      repository_id = "123456789"
      owner_id      = "987654321"
    }
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.deploy_worker[0].role == "roles/run.developer"
    error_message = "The deploy identity must hold Cloud Run Developer on the worker service."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.deploy_worker[0].name == google_cloud_run_v2_service.worker[0].name
    error_message = "The deploy worker grant must target only the worker service."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.deploy_worker[0].member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The deploy worker grant must belong to the deploy service account."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_worker_user[0].role == "roles/iam.serviceAccountUser"
    error_message = "The deploy identity must hold Service Account User on the worker runtime identity."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_worker_user[0].service_account_id == google_service_account.async_worker[0].name
    error_message = "The deploy act-as grant must target the worker runtime identity."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_invoker_token[0].role == "roles/iam.serviceAccountTokenCreator"
    error_message = "The deploy identity must hold Token Creator on the invocation identity for ID-token smoke."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_invoker_token[0].service_account_id == google_service_account.async_invoker[0].name
    error_message = "The Token Creator grant must target only the invocation identity."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_invoker_token[0].member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The Token Creator grant must belong to the deploy service account."
  }
  assert {
    condition = alltrue([
      for grant in google_secret_manager_secret_iam_member.worker_secret_access :
      !startswith(grant.member, "serviceAccount:github-deploy@")
    ])
    error_message = "The deploy identity must hold no worker secret-access grants."
  }
  assert {
    condition     = google_cloud_tasks_queue_iam_member.api_enqueuer[0].member != "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The deploy identity must hold no queue grants."
  }
}

run "delivery_worker_grants_absent_without_delivery" {
  command = plan
  variables { github_delivery = null }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.deploy_worker) == 0
    error_message = "No deploy worker grant must exist when delivery is disabled."
  }
  assert {
    condition     = length(google_service_account_iam_member.deploy_worker_user) == 0
    error_message = "No deploy worker act-as grant must exist when delivery is disabled."
  }
  assert {
    condition     = length(google_service_account_iam_member.deploy_invoker_token) == 0
    error_message = "No deploy Token Creator grant must exist when delivery is disabled."
  }
}
