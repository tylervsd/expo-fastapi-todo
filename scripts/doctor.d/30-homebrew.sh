#!/bin/sh

check_brew_bundle() {
  if ! command -v brew >/dev/null 2>&1; then
    doctor_missing 'Homebrew is missing; install it before continuing; see troubleshooting#brew-bundle.'
    return
  fi

  if brew bundle check --file "$PROJECT_ROOT/Brewfile" >/dev/null 2>&1; then
    doctor_pass 'Homebrew bundle is satisfied'
  else
    doctor_fail 'brew bundle check failed; see troubleshooting#brew-bundle.'
  fi
}

doctor_register brew.bundle required check_brew_bundle
