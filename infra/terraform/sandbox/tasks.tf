# Phase 20 async suggestion delivery. Opt-in: async_suggestions defaults to
# null and creates nothing. When enabled, this file owns the Cloud Tasks
# queue, the private worker service, the shared invocation identity plus the
# worker runtime identity, least-privilege grants, and the paused expiry
# schedule. Secret payloads and versions stay external; Terraform records only
# metadata references and numeric versions.
#
# "Private" means Cloud Run IAM protected: invocation requires the shared
# invocation identity and there is no allUsers/allAuthenticatedUsers binding.
# Cloud Tasks and Cloud Scheduler intentionally share that invocation
# authority; they are not route-isolated from each other.

locals {
  async_enabled = var.async_suggestions != null
  async_worker_secrets = local.async_enabled ? {
    DATABASE_URL = {
      secret_key = var.async_suggestions.database_secret_key
      version    = var.async_suggestions.database_secret_version
    }
    OPENROUTER_API_KEY = {
      secret_key = var.async_suggestions.provider_secret_key
      version    = var.async_suggestions.provider_secret_version
    }
  } : {}
}

resource "google_service_account" "async_invoker" {
  count = local.async_enabled ? 1 : 0

  project      = var.project_id
  account_id   = var.async_suggestions.invoker_account_id
  display_name = "Suggestion task invoker"
  description  = "Shared invocation identity for Cloud Tasks dispatch and Scheduler expiry. No database, secret, enqueue, or deployment rights."

  depends_on = [google_project_service.required]
}

resource "google_service_account" "async_worker" {
  count = local.async_enabled ? 1 : 0

  project      = var.project_id
  account_id   = var.async_suggestions.worker_account_id
  display_name = "Suggestion worker runtime"
  description  = "Runtime identity for the private suggestion worker. Accesses only Cloud SQL and the configured database/provider secret versions."

  depends_on = [google_project_service.required]
}

resource "google_cloud_tasks_queue" "suggestions" {
  count = local.async_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.async_suggestions.queue_name

  rate_limits {
    max_dispatches_per_second = 1
    max_concurrent_dispatches = 2
  }

  retry_config {
    max_attempts       = 5
    max_retry_duration = "0s"
    min_backoff        = "10s"
    max_backoff        = "60s"
    max_doublings      = 3
  }

  stackdriver_logging_config {
    sampling_ratio = 1.0
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "worker" {
  count = local.async_enabled ? 1 : 0

  project             = var.project_id
  name                = var.async_suggestions.worker_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  template {
    service_account                  = google_service_account.async_worker[0].email
    timeout                          = "60s"
    max_instance_request_concurrency = 2

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image   = var.async_suggestions.worker_image
      command = ["sh", "-c"]
      args    = ["exec uvicorn app.worker:app --host 0.0.0.0 --port \"$${PORT:-8080}\""]

      env {
        name  = "OPENROUTER_MODEL"
        value = var.async_suggestions.provider_model
      }

      # Observability-owned runtime input, mirroring the API seam: set only
      # when observability is enabled, without touching release-owned image
      # or revision fields. Terraform normalizes 1.0 to "1"; the app
      # parses it back to 1.0.
      dynamic "env" {
        for_each = var.observability == null ? [] : [var.observability.trace_sample_rate]
        content {
          name  = "TRACE_SAMPLE_RATE"
          value = tostring(env.value)
        }
      }

      # Cloud Trace export switch, mirroring the API seam: set only when
      # observability is enabled. The worker has no caller-supplied env
      # maps, so no manual-collision guard is needed here.
      dynamic "env" {
        for_each = var.observability == null ? [] : [true]
        content {
          name  = "TRACE_EXPORT_ENABLED"
          value = "true"
        }
      }

      dynamic "env" {
        for_each = local.async_worker_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.containers[env.value.secret_key].secret_id
              version = env.value.version
            }
          }
        }
      }

      ports {
        container_port = 8080
        name           = "http1"
      }

      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [var.api.sql_connection_name] }
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.worker_sql_client,
    google_secret_manager_secret_iam_member.worker_secret_access,
    google_project_iam_member.trace_worker,
  ]

  # Release-owned field: the release workflow deploys worker revisions by
  # digest. Terraform keeps all stable configuration.
  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      client,
      client_version,
    ]
  }
}

# The API runtime may enqueue on this queue only.
resource "google_cloud_tasks_queue_iam_member" "api_enqueuer" {
  count = local.async_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_tasks_queue.suggestions[0].name
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${var.api.identity}"

  depends_on = [google_project_service.required]
}

# The API runtime mints OIDC tokens as the invocation identity when creating
# tasks, so it may act as that identity and nothing else.
resource "google_service_account_iam_member" "api_invoker_user" {
  count = local.async_enabled ? 1 : 0

  service_account_id = google_service_account.async_invoker[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.api.identity}"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "worker_sql_client" {
  count = local.async_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.async_worker[0].email}"

  depends_on = [google_project_service.required, google_service_account.async_worker]
}

resource "google_secret_manager_secret_iam_member" "worker_secret_access" {
  for_each = local.async_worker_secrets

  project   = var.project_id
  secret_id = google_secret_manager_secret.containers[each.value.secret_key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.async_worker[0].email}"

  depends_on = [google_project_service.required, google_service_account.async_worker]
}

# Mandatory invocation IAM: only the shared invocation identity (used by both
# Cloud Tasks dispatch and the Scheduler expiry job) may invoke the worker.
resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  count = local.async_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.async_invoker[0].email}"

  depends_on = [google_project_service.required]
}

resource "google_cloud_scheduler_job" "suggestion_expiry" {
  count = local.async_enabled ? 1 : 0

  project          = var.project_id
  region           = var.region
  name             = var.async_suggestions.scheduler_name
  description      = "Expires abandoned pending suggestion reservations in bounded batches."
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "30s"
  paused           = var.async_suggestions.scheduler_paused

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker[0].uri}/internal/suggestions/expire"
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
