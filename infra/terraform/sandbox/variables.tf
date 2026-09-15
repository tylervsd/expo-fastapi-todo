variable "project_id" {
  description = "Google Cloud project ID to adopt."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.project_id)) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "Region containing the adopted regional resources."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.region)) > 0
    error_message = "region must not be empty."
  }
}

variable "registry" {
  description = "Observed Artifact Registry repository settings."
  type = object({
    repository_id          = string
    location               = string
    format                 = string
    description            = optional(string)
    labels                 = optional(map(string), {})
    kms_key_name           = optional(string)
    mode                   = optional(string)
    cleanup_policy_dry_run = optional(bool)
    docker_immutable_tags  = optional(bool)
    cleanup_policies = optional(map(object({
      action = optional(string)
      condition = optional(object({
        newer_than            = optional(string)
        older_than            = optional(string)
        package_name_prefixes = optional(list(string))
        tag_prefixes          = optional(list(string))
        tag_state             = optional(string)
        version_name_prefixes = optional(list(string))
      }))
      most_recent_versions = optional(object({
        keep_count            = number
        package_name_prefixes = optional(list(string))
      }))
    })), {})
  })
  nullable = false
}

variable "database" {
  description = "Observed Cloud SQL instance and application database settings; never includes credentials."
  type = object({
    instance_name                        = string
    database_name                        = string
    database_deletion_policy             = string
    database_charset                     = optional(string)
    database_collation                   = optional(string)
    database_version                     = string
    region                               = string
    deletion_protection                  = bool
    deletion_protection_enabled          = bool
    deletion_policy                      = optional(string)
    maintenance_version                  = optional(string)
    encryption_key_name                  = optional(string)
    enforce_new_sql_network_architecture = optional(bool)
    enable_dataplex_integration          = optional(bool)
    edition                              = string
    tier                                 = string
    availability_type                    = string
    disk_type                            = string
    disk_size                            = number
    disk_autoresize                      = bool
    disk_autoresize_limit                = number
    activation_policy                    = string
    connector_enforcement                = string
    database_flags                       = map(string)
    backup = object({
      enabled                        = bool
      point_in_time_recovery_enabled = bool
      transaction_log_retention_days = number
      retained_backups               = number
      retention_unit                 = string
      start_time                     = optional(string)
      location                       = optional(string)
    })
    network = object({
      ipv4_enabled                                  = bool
      ssl_mode                                      = string
      private_network                               = optional(string)
      allocated_ip_range                            = optional(string)
      enable_private_path_for_google_cloud_services = optional(bool)
      authorized_networks = optional(map(object({
        name            = string
        value           = string
        expiration_time = optional(string)
      })), {})
    })
    maintenance_window = optional(object({
      day          = number
      hour         = number
      update_track = optional(string)
    }))
    user_labels = optional(map(string), {})
  })
  nullable = false

  validation {
    condition = contains([
      "ALLOW_UNENCRYPTED_AND_ENCRYPTED",
      "ENCRYPTED_ONLY",
      "TRUSTED_CLIENT_CERTIFICATE_REQUIRED",
    ], var.database.network.ssl_mode)
    error_message = "database.network.ssl_mode must be a supported Cloud SQL SSL mode."
  }
}

variable "service_accounts" {
  description = "Dedicated service accounts keyed by stable Terraform addresses."
  type = map(object({
    account_id   = string
    display_name = string
    description  = optional(string)
    disabled     = optional(bool, false)
  }))
  nullable = false
}

variable "enabled_services" {
  description = "Google APIs Terraform owns, as service names."
  type        = set(string)
  nullable    = false
}

variable "project_iam_members" {
  description = "Additive project IAM grants keyed by stable Terraform addresses."
  type = map(object({
    role   = string
    member = string
    condition = optional(object({
      title       = string
      expression  = string
      description = optional(string)
    }))
  }))
  nullable = false
}

variable "secret_iam_members" {
  description = "Additive secret-scoped IAM grants keyed by stable Terraform addresses."
  type = map(object({
    secret_key = string
    role       = string
    member     = string
    condition = optional(object({
      title       = string
      expression  = string
      description = optional(string)
    }))
  }))
  nullable = false
}

variable "secrets" {
  description = "Secret container metadata only. Secret payloads and versions are external."
  type = map(object({
    secret_id   = string
    labels      = optional(map(string), {})
    annotations = optional(map(string), {})
    replication = object({
      auto = optional(object({
        kms_key_name = optional(string)
      }))
      user_managed_replicas = optional(map(object({
        location     = string
        kms_key_name = optional(string)
      })))
    })
  }))
  nullable = false

  validation {
    condition = alltrue([
      for secret in values(var.secrets) :
      (secret.replication.auto == null ? 0 : 1) + (secret.replication.user_managed_replicas == null ? 0 : 1) == 1
    ])
    error_message = "Each secret replication setting must select exactly one of auto or user_managed_replicas."
  }
}

variable "api" {
  description = "Observed Cloud Run service configuration. Plain and secret environment maps stay separate."
  type = object({
    name                 = string
    identity             = string
    image                = string
    client               = optional(string)
    client_version       = optional(string)
    ingress              = string
    invoker_iam_disabled = bool
    deletion_protection  = bool
    plain_env            = map(string)
    secret_env = map(object({
      secret_key = string
      version    = string
    }))
    cors_origins        = set(string)
    sql_connection_name = string
    labels              = optional(map(string), {})
    service_scaling = optional(object({
      scaling_mode          = optional(string)
      min_instance_count    = optional(number)
      max_instance_count    = optional(number)
      manual_instance_count = optional(number)
    }))
    runtime = object({
      timeout                          = string
      max_instance_request_concurrency = number
      min_instance_count               = number
      max_instance_count               = number
      command                          = list(string)
      args                             = list(string)
      container_port                   = number
      port_name                        = optional(string)
      cpu                              = string
      memory                           = string
      cpu_idle                         = bool
      startup_cpu_boost                = bool
      execution_environment            = optional(string)
      revision                         = optional(string)
      liveness_probe = optional(object({
        failure_threshold     = number
        initial_delay_seconds = number
        period_seconds        = number
        timeout_seconds       = number
        grpc = optional(object({
          port    = number
          service = optional(string)
        }))
        http_get = optional(object({
          path = string
          port = number
        }))
        tcp_socket = optional(object({
          port = number
        }))
      }))
      startup_probe = optional(object({
        failure_threshold     = number
        initial_delay_seconds = number
        period_seconds        = number
        timeout_seconds       = number
        grpc = optional(object({
          port    = number
          service = optional(string)
        }))
        http_get = optional(object({
          path = string
          port = number
        }))
        tcp_socket = optional(object({
          port = number
        }))
      }))
    })
    traffic = map(object({
      percent  = number
      type     = string
      revision = optional(string)
      tag      = optional(string)
    }))
  })
  nullable = false

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api.image))
    error_message = "api.image must end with an immutable SHA-256 digest."
  }

  validation {
    condition = alltrue([
      for origin in var.api.cors_origins :
      can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?$", origin)) && (
        length(regexall(":[0-9]+$", origin)) == 0 || (
          tonumber(trimprefix(regexall(":[0-9]+$", origin)[0], ":")) >= 0 &&
          tonumber(trimprefix(regexall(":[0-9]+$", origin)[0], ":")) <= 65535
        )
      )
    ])
    error_message = "api.cors_origins must contain exact HTTPS origins without paths, wildcards, whitespace, or trailing slashes."
  }

  validation {
    condition     = try(length(trimspace(var.api.plain_env.OPENROUTER_MODEL)) > 0, false)
    error_message = "api.plain_env.OPENROUTER_MODEL must be a nonempty non-secret value."
  }

  validation {
    condition     = !contains(keys(var.api.plain_env), "DATABASE_URL") && !contains(keys(var.api.plain_env), "OPENROUTER_API_KEY") && !contains(keys(var.api.plain_env), "CORS_ALLOWED_ORIGINS")
    error_message = "api.plain_env must not contain DATABASE_URL, OPENROUTER_API_KEY, or CORS_ALLOWED_ORIGINS."
  }

  validation {
    condition     = length(setintersection(toset(keys(var.api.plain_env)), toset(keys(var.api.secret_env)))) == 0
    error_message = "api plain_env and secret_env keys must not overlap."
  }

  validation {
    condition     = alltrue([for reference in values(var.api.secret_env) : can(regex("^[1-9][0-9]*$", reference.version))])
    error_message = "api secret versions must be positive numeric Secret Manager versions."
  }

  validation {
    condition = alltrue([
      for probe in [var.api.runtime.liveness_probe, var.api.runtime.startup_probe] :
      probe == null ? true : (
        (try(probe.grpc != null, false) ? 1 : 0) +
        (try(probe.http_get != null, false) ? 1 : 0) +
        (try(probe.tcp_socket != null, false) ? 1 : 0) == 1
      )
    ])
    error_message = "Each API probe must select exactly one of grpc, http_get, or tcp_socket."
  }
}

variable "migration_job" {
  description = "Observed Cloud Run migration job configuration. Terraform records it but never executes migrations."
  type = object({
    name                  = string
    identity              = string
    image                 = string
    client                = optional(string)
    client_version        = optional(string)
    command               = list(string)
    args                  = list(string)
    max_retries           = number
    timeout               = string
    task_count            = number
    parallelism           = number
    deletion_protection   = bool
    sql_connection_name   = string
    cpu                   = string
    memory                = string
    execution_environment = optional(string)
    plain_env             = map(string)
    secret_env = map(object({
      secret_key = string
      version    = string
    }))
    labels = optional(map(string), {})
  })
  nullable = false

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.migration_job.image))
    error_message = "migration_job.image must end with an immutable SHA-256 digest."
  }

  validation {
    condition     = !contains(keys(var.migration_job.plain_env), "DATABASE_URL") && !contains(keys(var.migration_job.plain_env), "OPENROUTER_API_KEY") && !contains(keys(var.migration_job.plain_env), "CORS_ALLOWED_ORIGINS")
    error_message = "migration_job.plain_env must not contain DATABASE_URL, OPENROUTER_API_KEY, or CORS_ALLOWED_ORIGINS."
  }

  validation {
    condition     = length(setintersection(toset(keys(var.migration_job.plain_env)), toset(keys(var.migration_job.secret_env)))) == 0
    error_message = "migration_job plain_env and secret_env keys must not overlap."
  }

  validation {
    condition     = alltrue([for reference in values(var.migration_job.secret_env) : can(regex("^[1-9][0-9]*$", reference.version))])
    error_message = "migration_job secret versions must be positive numeric Secret Manager versions."
  }
}

variable "github_delivery" {
  description = "GitHub continuous-delivery identity settings, or null when delivery is not configured. Learner supplies real values locally; never commit them."
  type = object({
    repository    = string
    repository_id = string
    owner_id      = string
  })
  default  = null
  nullable = true

  validation {
    condition     = var.github_delivery == null || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_delivery.repository))
    error_message = "github_delivery.repository must be an owner/repository pair."
  }

  validation {
    condition     = var.github_delivery == null || can(regex("^[0-9]+$", var.github_delivery.repository_id))
    error_message = "github_delivery.repository_id must contain only digits."
  }

  validation {
    condition     = var.github_delivery == null || can(regex("^[0-9]+$", var.github_delivery.owner_id))
    error_message = "github_delivery.owner_id must contain only digits."
  }
}

variable "budget" {
  description = "Observed project-scoped billing budget, or null when none exists."
  type = object({
    billing_account = string
    display_name    = string
    amount = object({
      currency_code = string
      units         = string
      nanos         = number
    })
    calendar_period = string
    threshold_rules = set(object({
      percent     = number
      spend_basis = optional(string)
    }))
    notification_channels          = optional(set(string), [])
    disable_default_iam_recipients = optional(bool, false)
  })
  default  = null
  nullable = true
}

variable "monitoring" {
  description = "Observed basic monitoring resources, or null when absent pending an explicit additive plan."
  type = object({
    uptime_check = object({
      display_name              = string
      monitored_resource_type   = string
      monitored_resource_labels = map(string)
      path                      = string
      period                    = string
      timeout                   = string
      use_ssl                   = bool
      validate_ssl              = bool
    })
    alert_policy = object({
      display_name          = string
      combiner              = string
      notification_channels = set(string)
      filter                = string
      comparison            = string
      threshold_value       = number
      duration              = string
      alignment_period      = string
    })
  })
  default  = null
  nullable = true
}
