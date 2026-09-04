#!/usr/bin/env bats

setup() {
  PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
  . "$PROJECT_ROOT/scripts/doctor.d/00-core.sh"
}

check_ok() { doctor_pass "ready"; }
check_optional_missing() { doctor_missing "optional tool is absent"; }
check_required_missing() { doctor_missing "required tool is absent"; }

@test "aggregates pass warning and failure with a failing exit" {
  doctor_register ok required check_ok
  doctor_register optional optional check_optional_missing
  doctor_register required required check_required_missing
  run doctor_run_registered
  [ "$status" -eq 1 ]
  [[ "$output" == *"PASS [ok] ready"* ]]
  [[ "$output" == *"WARN [optional] optional tool is absent"* ]]
  [[ "$output" == *"FAIL [required] required tool is absent"* ]]
  [[ "$output" == *"Summary: 1 passed, 1 warning, 1 failed"* ]]
}

@test "runs one focused check" {
  doctor_register ok required check_ok
  doctor_register required required check_required_missing
  run doctor_run_registered ok
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [ok] ready"* ]]
  [[ "$output" != *"required tool"* ]]
}

@test "unknown focused check returns usage status" {
  doctor_register ok required check_ok
  run doctor_run_registered unknown
  [ "$status" -eq 64 ]
  [[ "$output" == *"Unknown check: unknown"* ]]
}
