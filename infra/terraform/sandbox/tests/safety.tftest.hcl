mock_provider "google" {}

override_data {
  target = data.google_project.current
  values = {
    project_id = "example-phase18-project"
    number     = "123456789012"
  }
}

# Pin computed delivery identities so membership and output assertions stay
# plan-known under mocks. Applies only when delivery resources exist.
override_resource {
  target          = google_service_account.dedicated["runtime"]
  override_during = plan
  values = {
    name = "projects/example-phase18-project/serviceAccounts/example-runtime@example-phase18-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.dedicated["migration"]
  override_during = plan
  values = {
    name = "projects/example-phase18-project/serviceAccounts/example-migration@example-phase18-project.iam.gserviceaccount.com"
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
  target          = google_iam_workload_identity_pool_provider.github
  override_during = plan
  values = {
    name = "projects/example-phase18-project/locations/global/workloadIdentityPools/github-delivery/providers/github"
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
  enabled_services = ["artifactregistry.googleapis.com", "billingbudgets.googleapis.com", "iam.googleapis.com", "iamcredentials.googleapis.com", "monitoring.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com", "sts.googleapis.com"]
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
    condition     = google_cloud_run_v2_service.api.client == "gcloud" && google_cloud_run_v2_service.api.client_version == "584.0.0" && google_cloud_run_v2_job.migrate.client == "gcloud" && google_cloud_run_v2_job.migrate.client_version == "584.0.0"
    error_message = "Imported Cloud Run client metadata must be retained."
  }
  assert {
    condition     = google_cloud_run_v2_service.api.template[0].revision == "fullstack-api-cleanup-20260914135601"
    error_message = "Imported Cloud Run service revision metadata must be retained."
  }
  assert {
    condition     = try(google_cloud_run_v2_service.api.scaling[0].scaling_mode, null) == null
    error_message = "An absent imported scaling mode must remain absent."
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
    condition     = google_sql_database_instance.primary.settings[0].enable_dataplex_integration
    error_message = "The adoption fixture must preserve Cloud SQL Dataplex integration."
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

run "delivery_disabled" {
  command = plan
  variables { github_delivery = null }

  assert {
    condition     = length(google_iam_workload_identity_pool.delivery) == 0
    error_message = "No delivery pool must exist when github_delivery is null."
  }
  assert {
    condition     = length(google_iam_workload_identity_pool_provider.github) == 0
    error_message = "No delivery provider must exist when github_delivery is null."
  }
  assert {
    condition     = length(google_service_account.deploy) == 0
    error_message = "No deploy service account must exist when github_delivery is null."
  }
  assert {
    condition     = output.github_workload_identity_provider == null
    error_message = "The provider output must be null when delivery is disabled."
  }
  assert {
    condition     = output.github_deploy_service_account == null
    error_message = "The deploy account output must be null when delivery is disabled."
  }
}

run "delivery_identity" {
  command = plan
  variables {
    github_delivery = {
      repository    = "example-owner/example-repo"
      repository_id = "123456789"
      owner_id      = "987654321"
    }
  }
  assert {
    condition = strcontains(
      google_iam_workload_identity_pool_provider.github[0].attribute_condition,
      "assertion.repository_id == '123456789'"
    )
    error_message = "Federation must restrict the numeric repository ID."
  }
  assert {
    condition = strcontains(
      google_iam_workload_identity_pool_provider.github[0].attribute_condition,
      "assertion.repository_owner_id == '987654321'"
    )
    error_message = "Federation must restrict the numeric repository owner ID."
  }
  assert {
    condition = strcontains(
      google_iam_workload_identity_pool_provider.github[0].attribute_condition,
      "assertion.ref == 'refs/heads/main'"
    )
    error_message = "Federation must restrict deployment to refs/heads/main."
  }
  assert {
    condition = strcontains(
      google_iam_workload_identity_pool_provider.github[0].attribute_condition,
      "assertion.workflow_ref == 'example-owner/example-repo/.github/workflows/release.yml@refs/heads/main'"
    )
    error_message = "Federation must restrict the exact release workflow ref."
  }
  assert {
    condition     = google_iam_workload_identity_pool.delivery[0].workload_identity_pool_id == "github-delivery"
    error_message = "The delivery pool must use the fixed github-delivery ID."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.github[0].workload_identity_pool_provider_id == "github"
    error_message = "The delivery provider must use the fixed github ID."
  }
  assert {
    condition     = google_service_account.deploy[0].account_id == "github-deploy"
    error_message = "The deploy account must use the fixed github-deploy ID."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_wif[0].member == "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/github-delivery/subject/repo:example-owner@987654321/example-repo@123456789:environment:sandbox"
    error_message = "Workload Identity binding must accept only the sandbox environment subject."
  }
  assert {
    condition     = google_artifact_registry_repository_iam_member.deploy_push[0].role == "roles/artifactregistry.writer"
    error_message = "The deploy identity must hold Artifact Registry Writer on the API repository."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.deploy_api[0].role == "roles/run.developer"
    error_message = "The deploy identity must hold Cloud Run Developer on the API service."
  }
  assert {
    condition     = google_cloud_run_v2_job_iam_member.deploy_migrate[0].role == "roles/run.developer"
    error_message = "The deploy identity must hold Cloud Run Developer on the migration job."
  }
  assert {
    condition     = length(google_service_account_iam_member.deploy_runtime_user) == 2
    error_message = "The deploy identity must hold Service Account User on both runtime identities."
  }
  assert {
    condition     = sort(keys(google_service_account_iam_member.deploy_runtime_user)) == tolist(["migration", "runtime"])
    error_message = "The Service Account User bindings must target the distinct runtime and migration identities."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_runtime_user["runtime"].service_account_id == google_service_account.dedicated["runtime"].name
    error_message = "The runtime binding must target the runtime service account."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_runtime_user["migration"].service_account_id == google_service_account.dedicated["migration"].name
    error_message = "The migration binding must target the migration service account."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_runtime_user["runtime"].service_account_id != google_service_account_iam_member.deploy_runtime_user["migration"].service_account_id
    error_message = "The two identity bindings must target different service accounts."
  }
  assert {
    condition = alltrue([
      for binding in google_service_account_iam_member.deploy_runtime_user :
      binding.member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com"
      && binding.role == "roles/iam.serviceAccountUser"
    ])
    error_message = "Both identity bindings must grant the deploy account Service Account User."
  }
  assert {
    condition = alltrue([
      google_artifact_registry_repository_iam_member.deploy_push[0].member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com",
      google_cloud_run_v2_service_iam_member.deploy_api[0].member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com",
      google_cloud_run_v2_job_iam_member.deploy_migrate[0].member == "serviceAccount:github-deploy@example-phase18-project.iam.gserviceaccount.com",
    ])
    error_message = "Every delivery grant must belong to the deploy service account."
  }
  assert {
    condition     = output.github_workload_identity_provider == "projects/example-phase18-project/locations/global/workloadIdentityPools/github-delivery/providers/github"
    error_message = "The provider output must expose the delivery provider name."
  }
  assert {
    condition     = output.github_deploy_service_account == "github-deploy@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The deploy account output must expose the deploy service account email."
  }
  assert {
    condition = alltrue([
      for grant in google_project_iam_member.owned :
      !contains(["roles/owner", "roles/editor", "roles/run.admin"], grant.role)
    ])
    error_message = "Delivery must not introduce broad project grants."
  }
  assert {
    condition = alltrue([
      for grant in google_secret_manager_secret_iam_member.access :
      !startswith(grant.member, "serviceAccount:github-deploy@")
    ])
    error_message = "The deploy identity must hold no secret-access grants."
  }
}
