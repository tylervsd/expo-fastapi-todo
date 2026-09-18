output "key_id" {
  description = "Lab key resource name; versions are managed explicitly in the walkthrough."
  value       = google_kms_crypto_key.fixture.id
}

output "reader_email" {
  value = google_service_account.lab["reader"].email
}

output "writer_email" {
  value = google_service_account.lab["writer"].email
}
