#!/bin/sh

check_python_uv() {
  if command -v uv >/dev/null 2>&1; then
    doctor_pass 'uv is available'
  else
    doctor_missing 'uv is missing; install it before continuing; see troubleshooting#python-uv.'
  fi
}

check_python_runtime() {
  if ! command -v uv >/dev/null 2>&1; then
    doctor_missing 'uv is missing; install it before continuing; see troubleshooting#python-runtime.'
    return
  fi

  python_path=$(UV_PYTHON_DOWNLOADS=never uv python find --managed-python 3.14.7 2>/dev/null) || {
    doctor_fail 'uv-managed Python 3.14.7 is not installed; see troubleshooting#python-runtime.'
    return
  }
  case "$python_path" in
    /usr/bin/*|/opt/homebrew/bin/*) doctor_fail 'project Python is not uv-managed; see troubleshooting#python-runtime.' ;;
    *) doctor_pass "uv-managed Python 3.14.7 at $python_path" ;;
  esac
}

doctor_register python.uv required check_python_uv
doctor_register python.runtime required check_python_runtime
