# KMS API enablement belongs to the phase22 kms-lab root. Apply it first.
# Never use this application key for the lab's disable/destroy exercises.
variable "real_name_encryption" {
  description = "Provision the protected application profile key and enable API name encryption. Keep enabled after adoption; retain key/column on rollback."
  type        = bool
  default     = false
  nullable    = false
}

resource "google_kms_key_ring" "profile" {
  count    = var.real_name_encryption ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = "fullstack-profile"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key" "profile" {
  count                      = var.real_name_encryption ? 1 : 0
  name                       = "real-name"
  key_ring                   = google_kms_key_ring.profile[0].id
  purpose                    = "ENCRYPT_DECRYPT"
  rotation_period            = "7776000s"
  destroy_scheduled_duration = "2592000s"
  deletion_policy            = "PREVENT"

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = "SOFTWARE"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "profile_api" {
  count         = var.real_name_encryption ? 1 : 0
  crypto_key_id = google_kms_crypto_key.profile[0].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${var.api.identity}"

  depends_on = [google_service_account.dedicated]
}

output "real_name_key_id" {
  description = "Application key, distinct from the synthetic lab key; null when not adopted."
  value       = var.real_name_encryption ? google_kms_crypto_key.profile[0].id : null
}
