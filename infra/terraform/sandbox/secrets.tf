resource "google_secret_manager_secret" "containers" {
  for_each = var.secrets

  project     = var.project_id
  secret_id   = each.value.secret_id
  labels      = each.value.labels
  annotations = each.value.annotations

  replication {
    dynamic "auto" {
      for_each = each.value.replication.auto == null ? [] : [each.value.replication.auto]
      content {
        dynamic "customer_managed_encryption" {
          for_each = auto.value.kms_key_name == null ? [] : [auto.value.kms_key_name]
          content {
            kms_key_name = customer_managed_encryption.value
          }
        }
      }
    }

    dynamic "user_managed" {
      for_each = each.value.replication.user_managed_replicas == null ? [] : [each.value.replication.user_managed_replicas]
      content {
        dynamic "replicas" {
          for_each = user_managed.value
          content {
            location = replicas.value.location

            dynamic "customer_managed_encryption" {
              for_each = replicas.value.kms_key_name == null ? [] : [replicas.value.kms_key_name]
              content {
                kms_key_name = customer_managed_encryption.value
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each = var.secret_iam_members

  project   = var.project_id
  secret_id = google_secret_manager_secret.containers[each.value.secret_key].secret_id
  role      = each.value.role
  member    = each.value.member

  dynamic "condition" {
    for_each = each.value.condition == null ? [] : [each.value.condition]
    content {
      title       = condition.value.title
      expression  = condition.value.expression
      description = condition.value.description
    }
  }
}
