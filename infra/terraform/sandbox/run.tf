resource "google_cloud_run_v2_service" "api" {
  project              = var.project_id
  name                 = var.api.name
  location             = var.region
  client               = var.api.client
  client_version       = var.api.client_version
  ingress              = var.api.ingress
  invoker_iam_disabled = var.api.invoker_iam_disabled
  deletion_protection  = var.api.deletion_protection
  labels               = var.api.labels

  dynamic "scaling" {
    for_each = var.api.service_scaling == null ? [] : [var.api.service_scaling]
    content {
      scaling_mode          = scaling.value.scaling_mode
      min_instance_count    = scaling.value.min_instance_count
      max_instance_count    = scaling.value.max_instance_count
      manual_instance_count = scaling.value.manual_instance_count
    }
  }

  template {
    service_account                  = var.api.identity
    timeout                          = var.api.runtime.timeout
    max_instance_request_concurrency = var.api.runtime.max_instance_request_concurrency
    execution_environment            = var.api.runtime.execution_environment
    revision                         = var.api.runtime.revision

    scaling {
      min_instance_count = var.api.runtime.min_instance_count
      max_instance_count = var.api.runtime.max_instance_count
    }

    containers {
      image   = var.api.image
      command = var.api.runtime.command
      args    = var.api.runtime.args

      dynamic "env" {
        for_each = var.api.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = jsonencode(var.api.cors_origins)
      }

      dynamic "env" {
        for_each = var.api.secret_env
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
        container_port = var.api.runtime.container_port
        name           = var.api.runtime.port_name
      }

      resources {
        limits            = { cpu = var.api.runtime.cpu, memory = var.api.runtime.memory }
        cpu_idle          = var.api.runtime.cpu_idle
        startup_cpu_boost = var.api.runtime.startup_cpu_boost
      }

      dynamic "liveness_probe" {
        for_each = var.api.runtime.liveness_probe == null ? [] : [var.api.runtime.liveness_probe]
        content {
          failure_threshold     = liveness_probe.value.failure_threshold
          initial_delay_seconds = liveness_probe.value.initial_delay_seconds
          period_seconds        = liveness_probe.value.period_seconds
          timeout_seconds       = liveness_probe.value.timeout_seconds
          dynamic "grpc" {
            for_each = liveness_probe.value.grpc == null ? [] : [liveness_probe.value.grpc]
            content {
              port    = grpc.value.port
              service = grpc.value.service
            }
          }
          dynamic "http_get" {
            for_each = liveness_probe.value.http_get == null ? [] : [liveness_probe.value.http_get]
            content {
              path = http_get.value.path
              port = http_get.value.port
            }
          }
          dynamic "tcp_socket" {
            for_each = liveness_probe.value.tcp_socket == null ? [] : [liveness_probe.value.tcp_socket]
            content { port = tcp_socket.value.port }
          }
        }
      }

      dynamic "startup_probe" {
        for_each = var.api.runtime.startup_probe == null ? [] : [var.api.runtime.startup_probe]
        content {
          failure_threshold     = startup_probe.value.failure_threshold
          initial_delay_seconds = startup_probe.value.initial_delay_seconds
          period_seconds        = startup_probe.value.period_seconds
          timeout_seconds       = startup_probe.value.timeout_seconds
          dynamic "grpc" {
            for_each = startup_probe.value.grpc == null ? [] : [startup_probe.value.grpc]
            content {
              port    = grpc.value.port
              service = grpc.value.service
            }
          }
          dynamic "http_get" {
            for_each = startup_probe.value.http_get == null ? [] : [startup_probe.value.http_get]
            content {
              path = http_get.value.path
              port = http_get.value.port
            }
          }
          dynamic "tcp_socket" {
            for_each = startup_probe.value.tcp_socket == null ? [] : [startup_probe.value.tcp_socket]
            content { port = tcp_socket.value.port }
          }
        }
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

  dynamic "traffic" {
    for_each = var.api.traffic
    content {
      type     = traffic.value.type
      percent  = traffic.value.percent
      revision = traffic.value.revision
      tag      = traffic.value.tag
    }
  }

  depends_on = [google_project_service.required, google_project_iam_member.owned, google_secret_manager_secret_iam_member.access]

  lifecycle { prevent_destroy = true }
}

resource "google_cloud_run_v2_job" "migrate" {
  project             = var.project_id
  name                = var.migration_job.name
  location            = var.region
  client              = var.migration_job.client
  client_version      = var.migration_job.client_version
  deletion_protection = var.migration_job.deletion_protection
  labels              = var.migration_job.labels

  template {
    task_count  = var.migration_job.task_count
    parallelism = var.migration_job.parallelism
    template {
      service_account       = var.migration_job.identity
      max_retries           = var.migration_job.max_retries
      timeout               = var.migration_job.timeout
      execution_environment = var.migration_job.execution_environment
      containers {
        image   = var.migration_job.image
        command = var.migration_job.command
        args    = var.migration_job.args
        resources {
          limits = { cpu = var.migration_job.cpu, memory = var.migration_job.memory }
        }
        dynamic "env" {
          for_each = var.migration_job.plain_env
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = var.migration_job.secret_env
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
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance { instances = [var.migration_job.sql_connection_name] }
      }
    }
  }

  depends_on = [google_project_service.required, google_project_iam_member.owned, google_secret_manager_secret_iam_member.access]

  # Release-owned field: the release workflow updates the job image by digest.
  lifecycle {
    prevent_destroy = true
    ignore_changes  = [template[0].template[0].containers[0].image]
  }
}
