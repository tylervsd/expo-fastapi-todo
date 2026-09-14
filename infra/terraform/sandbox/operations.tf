resource "google_billing_budget" "sandbox" {
  count           = var.budget == null ? 0 : 1
  billing_account = var.budget.billing_account
  display_name    = var.budget.display_name

  amount {
    specified_amount {
      currency_code = var.budget.amount.currency_code
      units         = var.budget.amount.units
      nanos         = var.budget.amount.nanos
    }
  }
  budget_filter {
    projects        = ["projects/${data.google_project.current.number}"]
    calendar_period = var.budget.calendar_period
  }
  dynamic "threshold_rules" {
    for_each = var.budget.threshold_rules
    content {
      threshold_percent = threshold_rules.value.percent
      spend_basis       = threshold_rules.value.spend_basis
    }
  }
  all_updates_rule {
    monitoring_notification_channels = var.budget.notification_channels
    disable_default_iam_recipients   = var.budget.disable_default_iam_recipients
  }
}

resource "google_monitoring_uptime_check_config" "api" {
  count        = var.monitoring == null ? 0 : 1
  project      = var.project_id
  display_name = var.monitoring.uptime_check.display_name
  period       = var.monitoring.uptime_check.period
  timeout      = var.monitoring.uptime_check.timeout
  monitored_resource {
    type   = var.monitoring.uptime_check.monitored_resource_type
    labels = var.monitoring.uptime_check.monitored_resource_labels
  }
  http_check {
    path           = var.monitoring.uptime_check.path
    request_method = "GET"
    use_ssl        = var.monitoring.uptime_check.use_ssl
    validate_ssl   = var.monitoring.uptime_check.validate_ssl
  }
  depends_on = [google_cloud_run_v2_service.api]
}

resource "google_monitoring_alert_policy" "api" {
  count                 = var.monitoring == null ? 0 : 1
  project               = var.project_id
  display_name          = var.monitoring.alert_policy.display_name
  combiner              = var.monitoring.alert_policy.combiner
  notification_channels = var.monitoring.alert_policy.notification_channels
  conditions {
    display_name = "Uptime check failures"
    condition_threshold {
      filter          = var.monitoring.alert_policy.filter
      comparison      = var.monitoring.alert_policy.comparison
      threshold_value = var.monitoring.alert_policy.threshold_value
      duration        = var.monitoring.alert_policy.duration
      aggregations { alignment_period = var.monitoring.alert_policy.alignment_period }
    }
  }
  depends_on = [google_monitoring_uptime_check_config.api]
}
