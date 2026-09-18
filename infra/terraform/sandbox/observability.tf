# Phase 21 native observability. Opt-in: observability defaults to null and
# creates nothing. When enabled, this file owns least-privilege trace IAM,
# the three specified application log metrics, one dashboard, and three
# alert policies. It creates no notification channel, budget, uptime check,
# log bucket, or trace storage: channels are reused inventoried IDs, the
# budget/uptime resources in operations.tf are preserved untouched, and
# trace/log retention stays separately recorded (a 30-day log policy does
# not set Cloud Trace retention).
#
# Runtime telemetry identity (service name, revision, exporter) lives in the
# application; var.observability.trace_sample_rate sets TRACE_SAMPLE_RATE on
# the API and worker runtimes below (0.1 default, 1.0 bounded drills), and
# enabling this file sets TRACE_EXPORT_ENABLED=true on both runtimes so
# Cloud Trace export starts atomically with the trace IAM grants, without
# touching release ownership. Enabling this file never changes Cloud Run CPU
# allocation, instance limits, images, revisions, or traffic: request-based
# CPU and release ownership are preserved.

locals {
  observability_enabled       = var.observability != null
  observability_async_enabled = local.observability_enabled && var.async_suggestions != null
  observability_channels      = local.observability_enabled ? tolist(var.observability.notification_channels) : []
  observability_runbook       = local.observability_enabled && length(trimspace(var.observability.runbook_url)) > 0 ? var.observability.runbook_url : "not configured (set observability.runbook_url)"
  observability_queue_name    = var.async_suggestions != null ? var.async_suggestions.queue_name : ""
  observability_worker_name   = var.async_suggestions != null ? var.async_suggestions.worker_name : ""
  observability_sql_id        = "${var.project_id}:${var.database.instance_name}"

  # Explicit application-failure allowlist. Includes saved suggestion
  # failures, maintenance failures/unavailability, actionable delivery
  # failures (claim/finalize unavailability, unexpected claim/finalize
  # failures, fail-closed stored rows), rejected worker tasks, enqueue
  # unavailability, agent failures, and unexpected faults. Excludes
  # transport logs (the saved outcome already covers them),
  # content-rejection diagnostics, expected live-claim retries, committed
  # claim-time acks (timeout/superseded/delivered ride with the companion
  # suggestion_finished), discarded late work, no-work replays, and normal
  # 4xx such as agent invalid_request. Severity alone never implies
  # failure.
  #
  # Signal grounding (app vocabulary, Tasks 1-3): rejected worker tasks
  # (suggestion_task_rejected malformed/oversized) travel as redacted
  # direct_log entries because direct logger calls never serialize the
  # caller message; only the allowlisted outcome travels. Enqueue
  # unavailability matches both the dedicated suggestion_enqueue event
  # and the 503 raised on the suggestion request route, so a dropped
  # enqueue is actionable even if its log line is sampled separately.
  observability_failure_filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "AND (",
    "(jsonPayload.event=\"suggestion_finished\" AND jsonPayload.outcome=\"failed\")",
    "OR (jsonPayload.event=\"maintenance_finished\" AND (jsonPayload.outcome=\"failed\" OR jsonPayload.outcome=\"unavailable\"))",
    "OR (jsonPayload.event=\"suggestion_delivery\" AND (jsonPayload.outcome=\"claim_unavailable\" OR jsonPayload.outcome=\"claim_failed\" OR jsonPayload.outcome=\"invalid_stored_row\" OR jsonPayload.outcome=\"finalize_unavailable\" OR jsonPayload.outcome=\"finalize_failed\"))",
    "OR (jsonPayload.event=\"direct_log\" AND (jsonPayload.outcome=\"malformed\" OR jsonPayload.outcome=\"oversized\"))",
    "OR (jsonPayload.event=\"suggestion_enqueue\" AND jsonPayload.outcome=\"unavailable\")",
    "OR (jsonPayload.event=\"http_request\" AND jsonPayload.outcome=\"server_error\" AND jsonPayload.route=\"/todo-workflows/{workflow_id}/suggestions\")",
    "OR (jsonPayload.event=\"agent_finished\" AND jsonPayload.outcome=\"agent_failed\")",
    "OR (jsonPayload.event=\"unexpected_fault\")",
    ")",
  ])

  observability_api_count_query = "fetch cloud_run_revision | metric 'run.googleapis.com/request_count' | filter resource.service_name == '${var.api.name}' | group_by [metric.label.response_code_class] | align rate(60s) | every 60s"
  observability_api_latency_query = join(" ", [
    "fetch cloud_run_revision | metric 'run.googleapis.com/request_latencies'",
    "| filter resource.service_name == '${var.api.name}'",
    "| group_by [], [p95: percentile(value.request_latencies, 95)] | every 60s",
  ])

  observability_chart_tiles = concat(
    [
      {
        width  = 6
        height = 4
        widget = {
          title = "API request count by status class (native status, not saved outcomes)"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = local.observability_api_count_query }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "API request latency p95 (native, not browser-perceived)"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = local.observability_api_latency_query }
            }]
          }
        }
      },
    ],
    local.observability_async_enabled ? [
      {
        width  = 6
        height = 4
        widget = {
          title = "Worker request count by status class"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_run_revision | metric 'run.googleapis.com/request_count' | filter resource.service_name == '${local.observability_worker_name}' | group_by [metric.label.response_code_class] | align rate(60s) | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Worker request latency p95"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_run_revision | metric 'run.googleapis.com/request_latencies' | filter resource.service_name == '${local.observability_worker_name}' | group_by [], [p95: percentile(value.request_latencies, 95)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Queue depth"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_tasks_queue | metric 'cloudtasks.googleapis.com/queue/depth' | filter resource.queue_id == '${local.observability_queue_name}' | group_by [], [value_depth: max(value.depth)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Task attempt outcomes"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_tasks_queue | metric 'cloudtasks.googleapis.com/queue/task_attempt_count' | filter resource.queue_id == '${local.observability_queue_name}' | group_by [metric.label.response_code] | align rate(60s) | every 60s" }
            }]
          }
        }
      },
    ] : [],
    [
      {
        width  = 6
        height = 4
        widget = {
          title = "SQL connections (summed)"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloudsql_database | metric 'cloudsql.googleapis.com/database/postgresql/num_backends' | filter resource.database_id == '${local.observability_sql_id}' | group_by [], [value_max: max(value.num_backends)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "SQL CPU utilization"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloudsql_database | metric 'cloudsql.googleapis.com/database/cpu/utilization' | filter resource.database_id == '${local.observability_sql_id}' | group_by [], [value_mean: mean(value.utilization)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "SQL memory utilization"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloudsql_database | metric 'cloudsql.googleapis.com/database/memory/utilization' | filter resource.database_id == '${local.observability_sql_id}' | group_by [], [value_mean: mean(value.utilization)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Provider calls by operation"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_run_revision | metric 'logging.googleapis.com/user/phase21_provider_calls' | group_by [metric.label.operation] | align rate(60s) | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Provider latency p95 by operation (reliability, not billing)"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_run_revision | metric 'logging.googleapis.com/user/phase21_provider_duration_ms' | group_by [metric.label.operation], [p95: percentile(value.phase21_provider_duration_ms, 95)] | every 60s" }
            }]
          }
        }
      },
      {
        width  = 6
        height = 4
        widget = {
          title = "Saved suggestion outcomes (committed ready/failed/superseded)"
          xyChart = {
            dataSets = [{
              plotType        = "LINE"
              timeSeriesQuery = { timeSeriesQueryLanguage = "fetch cloud_run_revision | metric 'logging.googleapis.com/user/phase21_suggestion_outcomes' | group_by [metric.label.outcome] | align rate(60s) | every 60s" }
            }]
          }
        }
      },
    ],
  )

  observability_dashboard = {
    displayName = "Phase 21 suggestion observability"
    mosaicLayout = {
      columns = 12
      tiles = concat(
        [
          {
            width  = 12
            height = 2
            xPos   = 0
            yPos   = 0
            widget = {
              title = "Phase 21 links and reading guide"
              text = {
                format = "MARKDOWN"
                content = join("\n", [
                  "HTTP success is not a saved suggestion: worker 204 and queue removal do not mean a usable result was stored. Read native request status alongside saved suggestion outcomes below.",
                  "",
                  "- [Cloud Trace](https://console.cloud.google.com/traces?project=${var.project_id})",
                  "- [Diagnostic logs](https://console.cloud.google.com/logs/query?project=${var.project_id})",
                  "- [Billing views](https://console.cloud.google.com/billing?project=${var.project_id})",
                  "- [Error Reporting](https://console.cloud.google.com/error-reporting?project=${var.project_id})",
                  "- [Runbook](${local.observability_enabled ? var.observability.runbook_url : ""})",
                ])
              }
            }
          },
        ],
        [
          for i, tile in local.observability_chart_tiles : merge(tile, {
            xPos = (i % 2) * 6
            yPos = 2 + floor(i / 2) * 4
          })
        ],
      )
    }
  }
}

# Trace export needs the Cloud Trace API enabled (via enabled_services) and
# writer rights on the API/worker runtime identities only. The task invoker
# and clients receive no trace role; no service-account keys are created.
resource "google_project_iam_member" "trace_api" {
  count = local.observability_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${var.api.identity}"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "trace_worker" {
  count = local.observability_async_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.async_worker[0].email}"

  depends_on = [google_project_service.required, google_service_account.async_worker]
}

# Only three application log metrics. IDs (suggestion, workflow, task,
# request, attempt) are diagnostic fields, never metric labels. Provider
# call counts are reliability diagnostics, not AI consumption or billing
# analytics; no token, cost, or per-user metrics are added.
resource "google_logging_metric" "provider_calls" {
  count = local.observability_enabled ? 1 : 0

  project = var.project_id
  name    = "phase21_provider_calls"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"provider_call\""
  label_extractors = {
    operation = "EXTRACT(jsonPayload.operation)"
    outcome   = "EXTRACT(jsonPayload.outcome)"
  }

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    labels {
      key         = "operation"
      value_type  = "STRING"
      description = "Bounded provider operation (suggestions or clarification)."
    }
    labels {
      key         = "outcome"
      value_type  = "STRING"
      description = "Bounded transport outcome (ok, timeout, cancelled, or transport_error)."
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_logging_metric" "provider_duration" {
  count = local.observability_enabled ? 1 : 0

  project         = var.project_id
  name            = "phase21_provider_duration_ms"
  filter          = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"provider_call\""
  value_extractor = "EXTRACT(jsonPayload.duration_ms)"
  label_extractors = {
    operation = "EXTRACT(jsonPayload.operation)"
  }

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"

    labels {
      key         = "operation"
      value_type  = "STRING"
      description = "Bounded provider operation (suggestions or clarification)."
    }
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 8
      growth_factor      = 2
      scale              = 100
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_logging_metric" "suggestion_outcomes" {
  count = local.observability_enabled ? 1 : 0

  project = var.project_id
  name    = "phase21_suggestion_outcomes"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"suggestion_finished\""
  label_extractors = {
    outcome    = "EXTRACT(jsonPayload.outcome)"
    error_code = "EXTRACT(jsonPayload.error_code)"
  }

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    labels {
      key         = "outcome"
      value_type  = "STRING"
      description = "Committed terminal outcome (ready, failed, or superseded)."
    }
    labels {
      key         = "error_code"
      value_type  = "STRING"
      description = "Bounded safe error code, empty when the transition succeeded."
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_dashboard" "observability" {
  count = local.observability_enabled ? 1 : 0

  project        = var.project_id
  dashboard_json = jsonencode(local.observability_dashboard)

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "app_failure" {
  count = local.observability_enabled ? 1 : 0

  project               = var.project_id
  display_name          = "Phase 21 application failure"
  combiner              = "OR"
  notification_channels = local.observability_channels

  conditions {
    display_name = "Application failure log"
    condition_matched_log {
      filter = local.observability_failure_filter
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "3600s"
    }
    auto_close = "86400s"
  }

  documentation {
    content = join("\n", [
      "Actionable application failure. At most one notification per hour; auto-close after 24 hours is not proof of recovery.",
      "Runbook: ${local.observability_runbook}",
      "Services: ${var.api.name}${local.observability_async_enabled ? ", ${local.observability_worker_name}" : ""}.",
      "Ready-to-use log filter:",
      local.observability_failure_filter,
    ])
    links {
      display_name = "Runbook"
      url          = local.observability_enabled ? var.observability.runbook_url : "https://example.invalid/runbooks/observability"
    }
    links {
      display_name = "Cloud Trace"
      url          = "https://console.cloud.google.com/traces?project=${var.project_id}"
    }
    links {
      display_name = "Diagnostic logs"
      url          = "https://console.cloud.google.com/logs/query?project=${var.project_id}"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "queue_backlog" {
  count = local.observability_async_enabled ? 1 : 0

  project               = var.project_id
  display_name          = "Phase 21 queue backlog"
  combiner              = "OR"
  notification_channels = local.observability_channels

  conditions {
    display_name = "Queue depth above zero"
    condition_threshold {
      filter                  = "metric.type=\"cloudtasks.googleapis.com/queue/depth\" AND resource.type=\"cloud_tasks_queue\" AND resource.label.queue_id=\"${local.observability_queue_name}\""
      comparison              = "COMPARISON_GT"
      threshold_value         = 0
      duration                = "300s"
      evaluation_missing_data = "EVALUATION_MISSING_DATA_NO_OP"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  documentation {
    content = join("\n", [
      "Queue backlog: depth above zero for five continuous minutes. Check intentional pause, worker IAM/revision, and task responses; resume only after diagnosis.",
      "Runbook: ${local.observability_runbook}",
      "Queue: ${local.observability_queue_name} in ${var.region}.",
      "Metric ingestion delay applies; five minutes is not an email-delivery guarantee. Missing data holds the prior state and is not proof of health.",
    ])
    links {
      display_name = "Runbook"
      url          = local.observability_enabled ? var.observability.runbook_url : "https://example.invalid/runbooks/observability"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "sql_connections" {
  count = local.observability_enabled ? 1 : 0

  project               = var.project_id
  display_name          = "Phase 21 SQL connections"
  combiner              = "OR"
  notification_channels = local.observability_channels

  conditions {
    display_name = "Summed connections above capacity threshold"
    condition_threshold {
      filter                  = "metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${local.observability_sql_id}\""
      comparison              = "COMPARISON_GT"
      threshold_value         = var.observability.sql_connection_threshold
      duration                = "300s"
      evaluation_missing_data = "EVALUATION_MISSING_DATA_NO_OP"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.database_id"]
      }
    }
  }

  documentation {
    content = join("\n", [
      "SQL pressure: summed instance connections above the deployment threshold for five continuous minutes. Check revisions, instance counts, migrations, and pool pressure before changing capacity.",
      "Runbook: ${local.observability_runbook}",
      "Instance: ${local.observability_sql_id}.",
      "Missing data holds the prior state and is not proof of health.",
    ])
    links {
      display_name = "Runbook"
      url          = local.observability_enabled ? var.observability.runbook_url : "https://example.invalid/runbooks/observability"
    }
  }

  depends_on = [google_project_service.required]
}
