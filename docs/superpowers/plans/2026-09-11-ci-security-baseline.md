# CI Security Baseline Implementation Plan

**Goal:** Block pull requests that introduce secrets or high/critical security findings before Phase 12 begins.

## Tasks

1. Add a failing repository contract for the security workflow's triggers, permissions, pinned actions, and severity gates.
2. Add one GitHub Actions workflow with Gitleaks, Trivy, and CodeQL jobs.
3. Update the curriculum to name Trivy as the selected dependency scanner and document the merge-rule activation step.
4. Run the repository contracts, workflow linting, and the available local security scans.

## Constraints

- Never commit a realistic test secret; validate configuration rather than poisoning Git history.
- Use `pull_request`, never `pull_request_target`, and grant only the permissions each job needs.
- Pin third-party actions to full commit SHAs.
- Gitleaks blocks on every finding; Trivy and CodeQL block at high/critical severity.
