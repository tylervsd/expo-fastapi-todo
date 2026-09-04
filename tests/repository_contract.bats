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
