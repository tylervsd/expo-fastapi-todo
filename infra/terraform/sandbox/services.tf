data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "required" {
  for_each = var.enabled_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "api" {
  project                = var.project_id
  location               = var.registry.location
  repository_id          = var.registry.repository_id
  format                 = var.registry.format
  description            = var.registry.description
  labels                 = var.registry.labels
  kms_key_name           = var.registry.kms_key_name
  mode                   = var.registry.mode
  cleanup_policy_dry_run = var.registry.cleanup_policy_dry_run

  dynamic "cleanup_policies" {
    for_each = var.registry.cleanup_policies
    content {
      id     = cleanup_policies.key
      action = cleanup_policies.value.action

      dynamic "condition" {
        for_each = cleanup_policies.value.condition == null ? [] : [cleanup_policies.value.condition]
        content {
          newer_than            = condition.value.newer_than
          older_than            = condition.value.older_than
          package_name_prefixes = condition.value.package_name_prefixes
          tag_prefixes          = condition.value.tag_prefixes
          tag_state             = condition.value.tag_state
          version_name_prefixes = condition.value.version_name_prefixes
        }
      }

      dynamic "most_recent_versions" {
        for_each = cleanup_policies.value.most_recent_versions == null ? [] : [cleanup_policies.value.most_recent_versions]
        content {
          keep_count            = most_recent_versions.value.keep_count
          package_name_prefixes = most_recent_versions.value.package_name_prefixes
        }
      }
    }
  }

  dynamic "docker_config" {
    for_each = var.registry.docker_immutable_tags == null ? [] : [var.registry.docker_immutable_tags]
    content {
      immutable_tags = docker_config.value
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}
