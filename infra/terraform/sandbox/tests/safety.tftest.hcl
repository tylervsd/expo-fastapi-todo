mock_provider "google" {}

override_data {
  target = data.google_project.current
  values = {
    project_id = "example-phase18-project"
    number     = "123456789012"
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
  enabled_services = ["artifactregistry.googleapis.com", "billingbudgets.googleapis.com", "iam.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com"]
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
    }
    traffic = { stable = { type = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", percent = 100 } }
  }

  migration_job = {
    name                  = "example-phase18-migrate"
    identity              = "example-migration@example-phase18-project.iam.gserviceaccount.com"
    image                 = "us-west1-docker.pkg.dev/example-phase18-project/example-api/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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
  budget     = null
  monitoring = null
}

run "protected_runtime" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.api.deletion_protection
    error_message = "The adopted API must have deletion protection."
  }
  assert {
    condition     = google_cloud_run_v2_job.migrate.template[0].template[0].service_account == "example-migration@example-phase18-project.iam.gserviceaccount.com" && google_cloud_run_v2_job.migrate.template[0].template[0].containers[0].resources[0].limits.cpu == "1" && google_cloud_run_v2_job.migrate.template[0].template[0].containers[0].resources[0].limits.memory == "512Mi"
    error_message = "Migration jobs must preserve their identity and resource limits."
  }
  assert {
    condition     = contains(toset(google_cloud_run_v2_job.migrate.template[0].template[0].volumes[0].cloud_sql_instance[0].instances), "example-phase18-project:us-west1:example-phase18-db") && google_cloud_run_v2_job.migrate.template[0].template[0].containers[0].volume_mounts[0].mount_path == "/cloudsql"
    error_message = "Migration jobs must preserve the Cloud SQL socket mount."
  }
  assert {
    condition     = anytrue([for grant in google_project_iam_member.owned : grant.role == "roles/cloudsql.client" && grant.member == "serviceAccount:example-migration@example-phase18-project.iam.gserviceaccount.com"]) && anytrue([for grant in google_secret_manager_secret_iam_member.access : grant.secret_id == "example-database-url" && grant.member == "serviceAccount:example-migration@example-phase18-project.iam.gserviceaccount.com"])
    error_message = "The migration identity needs Cloud SQL and database-secret access."
  }
  assert {
    condition     = google_sql_database_instance.primary.deletion_protection
    error_message = "Terraform must protect Cloud SQL from destruction."
  }
  assert {
    condition     = google_sql_database_instance.primary.settings[0].ip_configuration[0].ssl_mode == "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    error_message = "The adoption fixture must explicitly preserve its reviewed insecure SQL TLS posture."
  }
  assert {
    condition     = one([for env in google_cloud_run_v2_service.api.template[0].containers[0].env : env.value if env.name == "CORS_ALLOWED_ORIGINS"]) == "[\"https://example-phase18.pages.dev\"]"
    error_message = "CORS must be the exact JSON origin list."
  }
  assert {
    condition     = alltrue([for env in google_cloud_run_v2_service.api.template[0].containers[0].env : env.name == "OPENROUTER_API_KEY" || env.name == "DATABASE_URL" ? try(env.value_source[0].secret_key_ref[0].version != "", false) : true])
    error_message = "Runtime credentials must use Secret Manager references."
  }
  assert {
    condition     = alltrue([for service in google_project_service.required : !service.disable_on_destroy])
    error_message = "Managed APIs must remain enabled if Terraform is removed."
  }
}

run "adoption_preserves_observed_protection" {
  command = plan
  variables {
    api           = merge(var.api, { deletion_protection = false })
    migration_job = merge(var.migration_job, { deletion_protection = false })
    database      = merge(var.database, { deletion_protection = false, deletion_protection_enabled = false })
  }

  assert {
    condition     = google_cloud_run_v2_service.api.deletion_protection == false && google_cloud_run_v2_job.migrate.deletion_protection == false
    error_message = "Import adoption must preserve observed Run protection values."
  }
  assert {
    condition     = google_sql_database_instance.primary.deletion_protection == false
    error_message = "Import adoption must preserve the observed SQL protection value."
  }
}

run "rejects_mutable_api_image" {
  command         = plan
  expect_failures = [var.api]
  variables { api = merge(var.api, { image = "us-west1-docker.pkg.dev/example/api:latest" }) }
}

run "rejects_blank_model" {
  command         = plan
  expect_failures = [var.api]
  variables { api = merge(var.api, { plain_env = merge(var.api.plain_env, { OPENROUTER_MODEL = "" }) }) }
}

run "rejects_overlapping_environment_keys" {
  command         = plan
  expect_failures = [var.api]
  variables { api = merge(var.api, { plain_env = merge(var.api.plain_env, { DATABASE_URL = "not-a-secret" }) }) }
}

run "rejects_malformed_cors_origin" {
  command         = plan
  expect_failures = [var.api]
  variables { api = merge(var.api, { cors_origins = ["https://example-phase18.pages.dev/health"] }) }
}

run "rejects_non_numeric_secret_version" {
  command         = plan
  expect_failures = [var.api]
  variables { api = merge(var.api, { secret_env = merge(var.api.secret_env, { DATABASE_URL = { secret_key = "database_url", version = "latest" } }) }) }
}
