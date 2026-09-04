#!/bin/sh

check_github_cli() {
  if ! command -v gh >/dev/null 2>&1; then
    doctor_missing 'GitHub CLI is missing; install it before continuing; see troubleshooting#github-cli.'
    return
  fi

  gh_output=$(gh --version 2>/dev/null) || {
    doctor_fail 'GitHub CLI version could not be detected; see troubleshooting#github-cli.'
    return
  }
  gh_first_line=$(printf '%s\n' "$gh_output" | sed -n '1p')
  doctor_pass "$gh_first_line"
}

check_github_auth() {
  if ! command -v gh >/dev/null 2>&1; then
    doctor_missing 'GitHub CLI is missing; install it before continuing; see troubleshooting#github-auth.'
    return
  fi

  if gh auth status --hostname github.com >/dev/null 2>&1; then
    doctor_pass 'GitHub CLI is authenticated for github.com'
  else
    doctor_fail 'GitHub CLI is not authenticated; run gh auth login --hostname github.com; see troubleshooting#github-auth.'
  fi
}

doctor_register github.cli required check_github_cli
doctor_register github.auth required check_github_auth
