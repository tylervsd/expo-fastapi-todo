variable "project_id" {
  description = "Google Cloud project containing the disposable drill bucket."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.project_id)) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "Location for the disposable drill bucket."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.region)) > 0
    error_message = "region must not be empty."
  }
}

variable "bucket_name" {
  description = "Learner-supplied globally unique bucket name for this drill."
  type        = string
  nullable    = false

  validation {
    condition     = contains(var.bucket_name, "phase18-drill")
    error_message = "bucket_name must contain phase18-drill."
  }
}

resource "google_storage_bucket" "disposable" {
  name          = var.bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}
