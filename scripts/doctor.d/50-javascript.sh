#!/bin/sh

check_js_volta() {
  if command -v volta >/dev/null 2>&1; then
    doctor_pass 'Volta is available'
  else
    doctor_missing 'Volta is missing; install it before continuing; see troubleshooting#js-volta.'
  fi
}

check_js_node() {
  if ! command -v node >/dev/null 2>&1; then
    doctor_missing 'Node.js is missing; install the pinned version; see troubleshooting#js-node.'
    return
  fi

  node_output=$(node --version 2>/dev/null) || {
    doctor_fail 'Node.js version could not be detected; see troubleshooting#js-node.'
    return
  }
  detected=$(printf '%s\n' "$node_output" | sed -n '1p')
  if [ "$detected" = 'v24.20.0' ]; then
    doctor_pass "Node.js $detected"
  else
    doctor_fail "requires Node.js v24.20.0; detected $detected; see troubleshooting#js-node."
  fi
}

check_js_corepack() {
  if command -v corepack >/dev/null 2>&1; then
    doctor_pass 'Corepack is available'
  else
    doctor_missing 'Corepack is missing; enable it with the pinned Node release; see troubleshooting#js-corepack.'
  fi
}

check_js_pnpm() {
  if ! command -v pnpm >/dev/null 2>&1; then
    doctor_missing 'pnpm is missing; activate it through Corepack; see troubleshooting#js-pnpm.'
    return
  fi

  pnpm_output=$(pnpm --version 2>/dev/null) || {
    doctor_fail 'pnpm version could not be detected; see troubleshooting#js-pnpm.'
    return
  }
  detected=$(printf '%s\n' "$pnpm_output" | sed -n '1p')
  if [ "$detected" = '11.25.0' ]; then
    doctor_pass "pnpm $detected"
  else
    doctor_fail "requires pnpm 11.25.0; detected $detected; see troubleshooting#js-pnpm."
  fi
}

doctor_register js.volta required check_js_volta
doctor_register js.node required check_js_node
doctor_register js.corepack required check_js_corepack
doctor_register js.pnpm required check_js_pnpm
