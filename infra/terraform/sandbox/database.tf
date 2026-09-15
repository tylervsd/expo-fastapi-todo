# Adoption exception: preserve the observed sandbox TLS and public-IP settings.
# Review condition: remove after a reviewed private-only, TLS-enforced cutover.
#trivy:ignore:AVD-GCP-0015 trivy:ignore:AVD-GCP-0017
resource "google_sql_database_instance" "primary" {
  project                              = var.project_id
  name                                 = var.database.instance_name
  database_version                     = var.database.database_version
  region                               = var.database.region
  deletion_protection                  = var.database.deletion_protection
  deletion_policy                      = var.database.deletion_policy
  maintenance_version                  = var.database.maintenance_version
  encryption_key_name                  = var.database.encryption_key_name
  enforce_new_sql_network_architecture = var.database.enforce_new_sql_network_architecture

  settings {
    edition                     = var.database.edition
    tier                        = var.database.tier
    availability_type           = var.database.availability_type
    disk_type                   = var.database.disk_type
    disk_size                   = var.database.disk_size
    disk_autoresize             = var.database.disk_autoresize
    disk_autoresize_limit       = var.database.disk_autoresize_limit
    activation_policy           = var.database.activation_policy
    connector_enforcement       = var.database.connector_enforcement
    deletion_protection_enabled = var.database.deletion_protection_enabled
    enable_dataplex_integration = var.database.enable_dataplex_integration
    user_labels                 = var.database.user_labels

    backup_configuration {
      enabled                        = var.database.backup.enabled
      point_in_time_recovery_enabled = var.database.backup.point_in_time_recovery_enabled
      transaction_log_retention_days = var.database.backup.transaction_log_retention_days
      start_time                     = var.database.backup.start_time
      location                       = var.database.backup.location

      backup_retention_settings {
        retained_backups = var.database.backup.retained_backups
        retention_unit   = var.database.backup.retention_unit
      }
    }

    ip_configuration {
      ipv4_enabled                                  = var.database.network.ipv4_enabled
      ssl_mode                                      = var.database.network.ssl_mode
      private_network                               = var.database.network.private_network
      allocated_ip_range                            = var.database.network.allocated_ip_range
      enable_private_path_for_google_cloud_services = var.database.network.enable_private_path_for_google_cloud_services

      dynamic "authorized_networks" {
        for_each = var.database.network.authorized_networks
        content {
          name            = authorized_networks.value.name
          value           = authorized_networks.value.value
          expiration_time = authorized_networks.value.expiration_time
        }
      }
    }

    dynamic "database_flags" {
      for_each = var.database.database_flags
      content {
        name  = database_flags.key
        value = database_flags.value
      }
    }

    dynamic "maintenance_window" {
      for_each = var.database.maintenance_window == null ? [] : [var.database.maintenance_window]
      content {
        day          = maintenance_window.value.day
        hour         = maintenance_window.value.hour
        update_track = maintenance_window.value.update_track
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "app" {
  project         = var.project_id
  instance        = google_sql_database_instance.primary.name
  name            = var.database.database_name
  deletion_policy = var.database.database_deletion_policy
  charset         = var.database.database_charset
  collation       = var.database.database_collation

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}
