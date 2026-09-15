output "github_workload_identity_provider" {
  description = "Full WIF provider name for CI authentication, or null when delivery is disabled."
  value       = var.github_delivery == null ? null : google_iam_workload_identity_pool_provider.github[0].name
}

output "github_deploy_service_account" {
  description = "Deploy service account email for CI authentication, or null when delivery is disabled."
  value       = var.github_delivery == null ? null : google_service_account.deploy[0].email
}

output "api_uri" { value = google_cloud_run_v2_service.api.uri }
output "sql_connection_name" { value = var.api.sql_connection_name }
output "registry_path" { value = google_artifact_registry_repository.api.id }
output "service_account_emails" { value = { for key, account in google_service_account.dedicated : key => account.email } }
output "managed_resource_ids" {
  value = {
    api       = google_cloud_run_v2_service.api.id
    migration = google_cloud_run_v2_job.migrate.id
    database  = google_sql_database_instance.primary.id
    budget    = try(google_billing_budget.sandbox[0].id, null)
    uptime    = try(google_monitoring_uptime_check_config.api[0].id, null)
    alert     = try(google_monitoring_alert_policy.api[0].id, null)
  }
}
