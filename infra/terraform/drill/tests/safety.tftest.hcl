mock_provider "google" {}

variables {
  project_id  = "example-phase18-project"
  region      = "us-west1"
  bucket_name = "example-phase18-drill-12345"
}

run "accepts_example_bucket" {
  command = plan
}

run "rejects_bucket_without_marker" {
  command         = plan
  expect_failures = [var.bucket_name]

  variables {
    bucket_name = "example-disposable-bucket-12345"
  }
}
