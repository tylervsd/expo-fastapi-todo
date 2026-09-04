#!/bin/sh

DOCTOR_REGISTRY=''
DOCTOR_STATUS=''
DOCTOR_MESSAGE=''

doctor_register() {
  entry="$1|$2|$3"
  if [ -z "$DOCTOR_REGISTRY" ]; then
    DOCTOR_REGISTRY="$entry"
  else
    DOCTOR_REGISTRY="$DOCTOR_REGISTRY
$entry"
  fi
}

doctor_pass() { DOCTOR_STATUS='PASS'; DOCTOR_MESSAGE=$1; }
doctor_warn() { DOCTOR_STATUS='WARN'; DOCTOR_MESSAGE=$1; }
doctor_fail() { DOCTOR_STATUS='FAIL'; DOCTOR_MESSAGE=$1; }

doctor_missing() {
  if [ "$DOCTOR_REQUIREMENT" = 'required' ]; then
    doctor_fail "$1"
  else
    doctor_warn "$1"
  fi
}

doctor_run_registered() {
  filter=${1:-}
  passed=0
  warned=0
  failed=0
  found=0

  while IFS='|' read -r check_id requirement function_name; do
    [ -n "$check_id" ] || continue
    if [ -n "$filter" ] && [ "$filter" != "$check_id" ]; then
      continue
    fi
    found=1
    DOCTOR_REQUIREMENT=$requirement
    DOCTOR_STATUS=''
    DOCTOR_MESSAGE=''
    "$function_name"
    case "$DOCTOR_STATUS" in
      PASS) passed=$((passed + 1)) ;;
      WARN) warned=$((warned + 1)) ;;
      FAIL) failed=$((failed + 1)) ;;
      *) doctor_fail "check returned no valid result"; failed=$((failed + 1)) ;;
    esac
    printf '%s [%s] %s\n' "$DOCTOR_STATUS" "$check_id" "$DOCTOR_MESSAGE"
  done <<EOF
$DOCTOR_REGISTRY
EOF

  if [ "$found" -eq 0 ]; then
    printf 'Unknown check: %s\n' "$filter"
    return 64
  fi
  printf 'Summary: %s passed, %s warning, %s failed\n' "$passed" "$warned" "$failed"
  [ "$failed" -eq 0 ]
}
