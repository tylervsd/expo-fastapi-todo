#!/usr/bin/env bats

setup() {
  SOURCE_ROOT="$BATS_TEST_DIRNAME/../.."
  FIXTURE_ROOT="$BATS_TEST_TMPDIR/repo"
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FIXTURE_ROOT/docs/setup" "$FAKE_BIN"

  cp -R "$SOURCE_ROOT/scripts" "$FIXTURE_ROOT/"
  cp "$SOURCE_ROOT"/Brewfile \
    "$SOURCE_ROOT"/LICENSE \
    "$SOURCE_ROOT"/README.md \
    "$SOURCE_ROOT"/package.json \
    "$SOURCE_ROOT"/pnpm-lock.yaml \
    "$SOURCE_ROOT"/pnpm-workspace.yaml \
    "$SOURCE_ROOT"/.python-version \
    "$FIXTURE_ROOT/"
  cp "$SOURCE_ROOT"/docs/curriculum-roadmap.md "$FIXTURE_ROOT/docs/"
  cp "$SOURCE_ROOT"/docs/setup/macos.md "$FIXTURE_ROOT/docs/setup/"
  cp "$SOURCE_ROOT"/docs/setup/troubleshooting.md "$FIXTURE_ROOT/docs/setup/"

  fake_command sw_vers '
if [ "$#" -ne 1 ] || [ "$1" != -productVersion ]; then exit 97; fi
printf "%s\\n" "26.6.2"
'
  fake_command uname '
if [ "$#" -ne 1 ] || [ "$1" != -m ]; then exit 97; fi
printf "%s\\n" "arm64"
'
  fake_command xcode-select '
if [ "$#" -ne 1 ] || [ "$1" != -p ]; then exit 97; fi
printf "%s\\n" "/Applications/Xcode.app/Contents/Developer"
'
  fake_command xcodebuild '
case "$*" in
  "-version") printf "%s\\n" "Xcode 26.6" "Build version 17G80" ;;
  "-checkFirstLaunchStatus") exit 0 ;;
  *) exit 97 ;;
esac
'
  fake_command xcrun '
if [ "$#" -ne 4 ] || [ "$1" != simctl ] || [ "$2" != list ] || [ "$4" != available ]; then exit 97; fi
case "$3" in
  runtimes) printf "%s\\n" "iOS 26.6 (26.6 - 23G80)" ;;
  devices) printf "%s\\n" "iPhone 17 Pro (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)" ;;
  *) exit 97 ;;
esac
'
  fake_command brew '
if [ "$#" -ne 4 ] || [ "$1" != bundle ] || [ "$2" != check ] || [ "$3" != --file ] || [ "$4" != "$PROJECT_ROOT/Brewfile" ]; then exit 97; fi
exit 0
'
  fake_command git '
if [ "$#" -ne 1 ] || [ "$1" != --version ]; then exit 97; fi
printf "%s\\n" "git version 2.50.1"
'
  fake_command volta '
if [ "$#" -ne 0 ]; then exit 97; fi
exit 0
'
  fake_command node '
if [ "$#" -ne 1 ] || [ "$1" != --version ]; then exit 97; fi
printf "%s\\n" "v24.20.0"
'
  fake_command corepack '
if [ "$#" -ne 0 ]; then exit 97; fi
exit 0
'
  fake_command pnpm '
if [ "$#" -ne 1 ] || [ "$1" != --version ]; then exit 97; fi
printf "%s\\n" "11.25.0"
'
  fake_command uv '
if [ "$#" -ne 4 ] || [ "$1" != python ] || [ "$2" != find ] || [ "$3" != --managed-python ] || [ "$4" != 3.14.7 ] || [ "$UV_PYTHON_DOWNLOADS" != never ]; then exit 97; fi
printf "%s\\n" "/Users/example/.local/share/uv/python/cpython-3.14.7/bin/python"
'
  fake_command docker '
case "$*" in
  "--version") printf "%s\\n" "Docker version 29.0.0" ;;
  "info") exit 0 ;;
  "compose version") printf "%s\\n" "Docker Compose version v2.40.0" ;;
  *) exit 97 ;;
esac
'
  fake_command gh '
case "$*" in
  "--version") printf "%s\\n" "gh version 2.80.0" ;;
  "auth status --hostname github.com") exit 0 ;;
  *) exit 97 ;;
esac
'

  PATH="$FAKE_BIN:/usr/bin:/bin"
  export PATH FIXTURE_ROOT
}

fake_command() {
  name=$1
  body=$2
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' "$body"
  } >"$FAKE_BIN/$name"
  chmod +x "$FAKE_BIN/$name"
}

@test "assembled doctor passes a complete reference fixture" {
  run "$FIXTURE_ROOT/scripts/doctor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [platform.macos]"* ]]
  [[ "$output" == *"PASS [xcode.simulator]"* ]]
  [[ "$output" == *"PASS [python.runtime]"* ]]
  [[ "$output" == *"PASS [github.auth]"* ]]
  [[ "$output" == *"0 failed"* ]]
}
