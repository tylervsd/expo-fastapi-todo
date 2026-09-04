#!/bin/sh

check_xcode_version() {
  selected_path=$(xcode-select -p 2>/dev/null) || {
    doctor_fail 'unable to determine selected Xcode developer directory'
    return
  }
  if [ "$selected_path" != '/Applications/Xcode.app/Contents/Developer' ]; then
    doctor_fail 'select /Applications/Xcode.app/Contents/Developer with xcode-select'
    return
  fi

  version_output=$(xcodebuild -version 2>/dev/null) || {
    doctor_fail 'unable to determine Xcode version'
    return
  }
  version_first_line=$(printf '%s\n' "$version_output" | sed -n '1p')
  case "$version_first_line" in
    'Xcode 26.6') doctor_pass 'Xcode 26.6 selected' ;;
    '') doctor_fail 'requires Xcode 26.6; detected <no output>' ;;
    *) doctor_fail "requires Xcode 26.6; detected $version_first_line" ;;
  esac
}

check_xcode_first_launch() {
  if xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1; then
    doctor_pass 'Xcode first-launch setup complete'
  else
    doctor_fail 'Run xcodebuild -runFirstLaunch after accepting the Xcode license.'
  fi
}

check_xcode_simulator() {
  runtimes=$(xcrun simctl list runtimes available 2>/dev/null) || {
    doctor_fail 'unable to inspect available simulator runtimes'
    return
  }
  devices=$(xcrun simctl list devices available 2>/dev/null) || {
    doctor_fail 'unable to inspect available simulator devices'
    return
  }

  if ! printf '%s\n' "$runtimes" | grep -Eq '^[[:space:]]*iOS 26([.[:space:](]|$)'; then
    doctor_fail 'requires an available iOS 26 simulator runtime'
    return
  fi
  if printf '%s\n' "$devices" | grep -Eq '^[[:space:]]*iPhone 17 Pro[[:space:]]+\('; then
    doctor_pass 'iOS 26 simulator includes iPhone 17 Pro'
  else
    doctor_fail 'requires an available iPhone 17 Pro simulator device'
  fi
}

doctor_register xcode.version required check_xcode_version
doctor_register xcode.first-launch required check_xcode_first_launch
doctor_register xcode.simulator required check_xcode_simulator
