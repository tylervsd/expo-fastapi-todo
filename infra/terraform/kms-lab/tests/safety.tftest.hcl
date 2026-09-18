mock_provider "google" {}

# Resolve computed IDs at plan time, following the sandbox test pattern.
override_resource {
  target          = google_kms_key_ring.lab
  override_during = plan
  values = {
    id = "projects/example-phase22-project/locations/us-west1/keyRings/phase22-lab"
  }
}

override_resource {
  target          = google_kms_crypto_key.fixture
  override_during = plan
  values = {
    id = "projects/example-phase22-project/locations/us-west1/keyRings/phase22-lab/cryptoKeys/synthetic-pii"
  }
}

override_resource {
  target          = google_service_account.lab["reader"]
  override_during = plan
  values = {
    name  = "projects/example-phase22-project/serviceAccounts/phase22-reader@example-phase22-project.iam.gserviceaccount.com"
    email = "phase22-reader@example-phase22-project.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = google_service_account.lab["writer"]
  override_during = plan
  values = {
    name  = "projects/example-phase22-project/serviceAccounts/phase22-writer@example-phase22-project.iam.gserviceaccount.com"
    email = "phase22-writer@example-phase22-project.iam.gserviceaccount.com"
  }
}

variables {
  project_id      = "example-phase22-project"
  region          = "us-west1"
  operator_member = "user:learner@example.test"
}

run "isolated_key_and_permissions" {
  command = plan

  assert {
    condition = (
      google_kms_crypto_key.fixture.purpose == "ENCRYPT_DECRYPT" &&
      google_kms_crypto_key.fixture.version_template[0].algorithm == "GOOGLE_SYMMETRIC_ENCRYPTION" &&
      google_kms_crypto_key.fixture.version_template[0].protection_level == "SOFTWARE" &&
      google_kms_crypto_key.fixture.rotation_period == "7776000s" &&
      google_kms_crypto_key.fixture.destroy_scheduled_duration == "2592000s" &&
      google_kms_crypto_key.fixture.deletion_policy == "PREVENT"
    )
    error_message = "Keep software encryption, rotation, recovery window, and deletion protection."
  }

  assert {
    condition = (
      google_kms_crypto_key_iam_member.reader.role == "roles/cloudkms.cryptoKeyEncrypterDecrypter" &&
      google_kms_crypto_key_iam_member.writer.role == "roles/cloudkms.cryptoKeyEncrypter" &&
      google_kms_crypto_key_iam_member.reader.member == "serviceAccount:phase22-reader@example-phase22-project.iam.gserviceaccount.com" &&
      google_kms_crypto_key_iam_member.writer.member == "serviceAccount:phase22-writer@example-phase22-project.iam.gserviceaccount.com" &&
      google_kms_crypto_key_iam_member.reader.crypto_key_id == google_kms_crypto_key.fixture.id &&
      google_kms_crypto_key_iam_member.writer.crypto_key_id == google_kms_crypto_key.fixture.id
    )
    error_message = "Only the reader may decrypt; both grants must be key-scoped."
  }

  assert {
    condition = alltrue([
      for name, grant in google_service_account_iam_member.operator :
      grant.role == "roles/iam.serviceAccountTokenCreator" &&
      grant.member == "user:learner@example.test" &&
      grant.service_account_id == google_service_account.lab[name].name
    ])
    error_message = "Impersonation must be restricted to the named user and lab accounts."
  }

  assert {
    condition = (
      length(google_service_account.lab) == 2 &&
      google_service_account.lab["reader"].account_id == "phase22-reader" &&
      google_service_account.lab["writer"].account_id == "phase22-writer" &&
      google_project_service.kms.disable_on_destroy == false
    )
    error_message = "Keep exactly the two lab identities and never disable the project API on removal."
  }
}

run "reject_invalid_project" {
  command         = plan
  expect_failures = [var.project_id]
  variables {
    project_id = ""
  }
}

run "reject_global_location" {
  command         = plan
  expect_failures = [var.region]
  variables {
    region = "global"
  }
}

run "reject_public_impersonation" {
  command         = plan
  expect_failures = [var.operator_member]
  variables {
    operator_member = "allUsers"
  }
}
