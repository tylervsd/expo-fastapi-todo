#!/bin/sh

check_git_version() {
  if ! command -v git >/dev/null 2>&1; then
    doctor_missing 'Git is missing; install it before continuing; see troubleshooting#git-version.'
    return
  fi

  git_output=$(git --version 2>/dev/null) || {
    doctor_fail 'Git version could not be detected; see troubleshooting#git-version.'
    return
  }
  git_first_line=$(printf '%s\n' "$git_output" | sed -n '1p')
  doctor_pass "$git_first_line"
}

doctor_register git.version required check_git_version
