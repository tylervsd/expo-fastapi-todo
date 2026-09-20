variable "project_id" {
  description = "Existing non-production Google Cloud project; never a customer production project."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Supply a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Explicit regional KMS location selected for the lab's residency needs."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "Use a regional location such as us-west1, not global or a multi-region."
  }
}

variable "operator_member" {
  description = "One learner user allowed to impersonate the two lab identities."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^user:[^ @]+@[^ @]+\\.[^ @]+$", var.operator_member))
    error_message = "Use one explicit user:email principal, never a public principal or group."
  }
}

# IAM and IAM Credentials APIs are prerequisites owned by the sandbox root.
resource "google_project_service" "kms" {
  project            = var.project_id
  service            = "cloudkms.googleapis.com"
  disable_on_destroy = false
}

resource "google_kms_key_ring" "lab" {
  project  = var.project_id
  location = var.region
  name     = "phase22-lab"

  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_project_service.kms]
}

resource "google_kms_crypto_key" "fixture" {
  name                       = "synthetic-pii"
  key_ring                   = google_kms_key_ring.lab.id
  purpose                    = "ENCRYPT_DECRYPT"
  rotation_period            = "7776000s"
  destroy_scheduled_duration = "2592000s"
  deletion_policy            = "PREVENT"
  labels                     = { phase = "22", data = "synthetic" }

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "lab" {
  for_each     = toset(["reader", "writer"])
  project      = var.project_id
  account_id   = "phase22-${each.key}"
  display_name = "Phase 22 synthetic fixture ${each.key}"
}

resource "google_kms_crypto_key_iam_member" "reader" {
  crypto_key_id = google_kms_crypto_key.fixture.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.lab["reader"].email}"
}

resource "google_kms_crypto_key_iam_member" "writer" {
  crypto_key_id = google_kms_crypto_key.fixture.id
  role          = "roles/cloudkms.cryptoKeyEncrypter"
  member        = "serviceAccount:${google_service_account.lab["writer"].email}"
}

resource "google_service_account_iam_member" "operator" {
  for_each           = google_service_account.lab
  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.operator_member
}
