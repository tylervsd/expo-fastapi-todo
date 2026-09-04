#!/usr/bin/env bats

@test "repository pins the supported runtime versions" {
  run grep -F '"node": "24.20.0"' package.json
  [ "$status" -eq 0 ]
  run grep -F '"packageManager": "pnpm@11.25.0"' package.json
  [ "$status" -eq 0 ]
  run grep -Fx '3.14.7' .python-version
  [ "$status" -eq 0 ]
}

@test "phase 0 contains no application workspaces" {
  [ ! -d apps ]
  [ ! -d services ]
  [ ! -d packages ]
}

@test "required public repository files exist" {
  for path in LICENSE pnpm-workspace.yaml Brewfile; do
    [ -f "$path" ]
  done
}

@test "README exposes the setup path and reference platform" {
  [ -f README.md ]
  grep -F 'docs/setup/macos.md' README.md
  grep -F 'macOS 26.6.2' README.md
  grep -F 'Apple Silicon' README.md
  grep -F 'sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer' README.md
  grep -F 'sudo xcodebuild -license accept' README.md
  grep -F 'xcodebuild -runFirstLaunch' README.md
  grep -F 'xcodebuild -downloadPlatform iOS' README.md
  grep -F 'git clone https://github.com/tylervsd/expo-fastapi-todo.git' README.md
  grep -F 'cd expo-fastapi-todo' README.md
}

@test "every registered check has a troubleshooting anchor" {
  for id in $(grep -h '^doctor_register ' scripts/doctor.d/*.sh | awk '{print $2}'); do
    anchor=$(printf '%s' "$id" | tr '.' '-')
    grep -F "<a id=\"$anchor\"></a>" docs/setup/troubleshooting.md
  done
}

@test "roadmap names all nine phase themes" {
  for heading in \
    'Mac developer environment' \
    'Project foundation' \
    'Local todo experience' \
    'API contract and vertical slice' \
    'Persistence' \
    'Complete CRUD and resilient server state' \
    'Authentication and authorization' \
    'Cross-platform E2E' \
    'Production hardening'; do
    grep -F "$heading" docs/curriculum-roadmap.md
  done
}
