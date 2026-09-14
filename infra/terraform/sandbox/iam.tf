resource "google_service_account" "dedicated" {
  for_each = var.service_accounts

  project      = var.project_id
  account_id   = each.value.account_id
  display_name = each.value.display_name
  description  = each.value.description
  disabled     = each.value.disabled

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "owned" {
  for_each = var.project_iam_members

  project = var.project_id
  role    = each.value.role
  member  = each.value.member

  dynamic "condition" {
    for_each = each.value.condition == null ? [] : [each.value.condition]
    content {
      title       = condition.value.title
      expression  = condition.value.expression
      description = condition.value.description
    }
  }

  depends_on = [google_project_service.required, google_service_account.dedicated]
}
