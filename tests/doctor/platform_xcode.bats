#!/usr/bin/env bats

load test_helper

setup() {
  PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
  export PROJECT_ROOT
  setup_fake_path
  INVOCATION_LOG="$BATS_TEST_TMPDIR/invocations"
  export INVOCATION_LOG
  . "$PROJECT_ROOT/scripts/doctor.d/00-core.sh"
}

@test "reference platform passes" {
  fake_command sw_vers "printf '%s\\n' '26.6.2'"
  fake_command uname "printf '%s\\n' 'arm64'"
  . "$PROJECT_ROOT/scripts/doctor.d/10-platform.sh"
  run doctor_run_registered platform.macos
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [platform.macos] macOS 26.6.2"* ]]
}

@test "wrong architecture fails with remediation" {
  fake_command sw_vers "printf '%s\\n' '26.6.2'"
  fake_command uname "printf '%s\\n' 'x86_64'"
  . "$PROJECT_ROOT/scripts/doctor.d/10-platform.sh"
  run doctor_run_registered platform.arch
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires Apple Silicon arm64; detected x86_64"* ]]
}

@test "command line tools selection is not accepted as full Xcode" {
  fake_command xcode-select "printf '%s\\n' '/Library/Developer/CommandLineTools'"
  fake_command xcodebuild "printf '%s\\n' 'Xcode 26.6' 'Build version 17G80'"
  fake_command xcrun "printf '%s\\n' 'iPhone 17 Pro (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 1 ]
  [[ "$output" == *"select /Applications/Xcode.app/Contents/Developer"* ]]
}

@test "Xcode 26.60 does not satisfy the exact Xcode 26.6 contract" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild "printf '%s\\n' 'Xcode 26.60' 'Build version 17G80'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"requires Xcode 26.6; detected Xcode 26.60"* ]]
}

@test "malformed Xcode version reports only its first line" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild "printf '%s\\n' 'unexpected version output' 'token=secret-value'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"requires Xcode 26.6; detected unexpected version output"* ]] || return 1
  [[ "$output" != *"secret-value"* ]]
}

@test "Xcode version ignores a secret on the second line" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild "printf '%s\\n' 'Xcode 26.6' 'token=secret-value'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 0 ] || return 1
  [[ "$output" == *"PASS [xcode.version] Xcode 26.6 selected"* ]] || return 1
  [[ "$output" != *"secret-value"* ]]
}

@test "empty Xcode version output uses a safe placeholder" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild 'exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"requires Xcode 26.6; detected <no output>"* ]]
}

@test "available designated simulator passes without booting it" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild "exit 0"
  fake_command xcrun "printf '%s\\n' \"xcrun \$*\" >>\"\$INVOCATION_LOG\"; printf '%s\\n' 'iOS 26.6 (26.6 - 23G80)' 'iPhone 17 Pro (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.simulator
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [xcode.simulator] iOS 26 simulator includes iPhone 17 Pro"* ]]
  run grep -Fx 'xcrun simctl list runtimes available' "$INVOCATION_LOG"
  [ "$status" -eq 0 ]
  run grep -Fx 'xcrun simctl list devices available' "$INVOCATION_LOG"
  [ "$status" -eq 0 ]
  run wc -l "$INVOCATION_LOG"
  [ "$status" -eq 0 ]
  [[ "$output" =~ (^|[[:space:]])2[[:space:]] ]]
  run grep -E '(boot|create|delete|shutdown|erase)' "$INVOCATION_LOG"
  [ "$status" -eq 1 ]
}

@test "iOS 260 runtime does not satisfy iOS 26" {
  fake_command xcrun "printf '%s\\n' 'iOS 260.0 (260.0 - 99A)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.simulator
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires an available iOS 26 simulator runtime"* ]]
}

@test "iPhone 17 Pro Max does not satisfy iPhone 17 Pro" {
  fake_command xcrun "printf '%s\\n' 'iOS 26.6 (26.6 - 23G80)' 'iPhone 17 Pro Max (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.simulator
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires an available iPhone 17 Pro simulator device"* ]]
}
