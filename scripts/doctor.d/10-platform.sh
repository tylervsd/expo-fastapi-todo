#!/bin/sh

check_platform_macos() {
  version=$(sw_vers -productVersion 2>/dev/null) || {
    doctor_fail 'unable to determine macOS version'
    return
  }
  if [ "$version" = '26.6.2' ]; then
    doctor_pass "macOS $version"
  else
    doctor_fail "requires macOS 26.6.2; detected $version"
  fi
}

check_platform_arch() {
  architecture=$(uname -m 2>/dev/null) || {
    doctor_fail 'unable to determine architecture'
    return
  }
  if [ "$architecture" = 'arm64' ]; then
    doctor_pass 'Apple Silicon arm64'
  else
    doctor_fail "requires Apple Silicon arm64; detected $architecture"
  fi
}

doctor_register platform.macos required check_platform_macos
doctor_register platform.arch required check_platform_arch
