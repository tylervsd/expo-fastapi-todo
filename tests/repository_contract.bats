#!/usr/bin/env bats

@test "repository pins the supported package manager and Python versions" {
  run grep -F '"packageManager": "pnpm@11.25.0"' package.json
  [ "$status" -eq 0 ]
  run grep -Fx '3.14.7' .python-version
  [ "$status" -eq 0 ]
}

@test "runtime pin contracts independently scope root, workflow, and doctor versions" {
  run awk '
    /"engines"[[:space:]]*:/ { in_block = 1; next }
    in_block && /^[[:space:]]*}[[:space:]]*,?[[:space:]]*$/ { exit }
    in_block && /"node"[[:space:]]*:[[:space:]]*"24.20.0"/ { found = 1 }
    END { exit(found ? 0 : 1) }
  ' package.json
  [ "$status" -eq 0 ] || return 1

  run awk '
    /"volta"[[:space:]]*:/ { in_block = 1; next }
    in_block && /^[[:space:]]*}[[:space:]]*,?[[:space:]]*$/ { exit }
    in_block && /"node"[[:space:]]*:[[:space:]]*"24.20.0"/ { found = 1 }
    END { exit(found ? 0 : 1) }
  ' package.json
  [ "$status" -eq 0 ] || return 1

  run grep -Fx '  "packageManager": "pnpm@11.25.0",' package.json
  [ "$status" -eq 0 ] || return 1
  run grep -Fx '3.14.7' .python-version
  [ "$status" -eq 0 ] || return 1
  run grep -F 'node-version: 24.20.0' .github/workflows/quality.yml
  [ "$status" -eq 0 ] || return 1
  run grep -F 'corepack prepare pnpm@11.25.0 --activate' .github/workflows/quality.yml
  [ "$status" -eq 0 ] || return 1
  run grep -F "[ \"\$detected\" = 'v24.20.0' ]" scripts/doctor.d/50-javascript.sh
  [ "$status" -eq 0 ] || return 1
  run grep -F "[ \"\$detected\" = '11.25.0' ]" scripts/doctor.d/50-javascript.sh
  [ "$status" -eq 0 ] || return 1
  run grep -F 'uv python find --managed-python 3.14.7' scripts/doctor.d/60-python.sh
  [ "$status" -eq 0 ]
}

@test "workflow action refs are full 40-character SHAs" {
  invalid_ref='3d3c42e5aac5ba805825da76410c181273ba90b'
  run bash -c '
    ref="$1"
    if [[ ! "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
      printf "action ref must be exactly 40 hex chars (got %d): %s\n" "${#ref}" "$ref"
      exit 1
    fi
  ' _ "$invalid_ref"
  [ "$status" -eq 1 ]
  [[ "$output" == *"action ref must be exactly 40 hex chars"* ]]

  run awk '
    /^[[:space:]]*-[[:space:]]*uses:/ {
      ref = $0
      sub(/^[^@]*@/, "", ref)
      sub(/[[:space:]]+#.*/, "", ref)
      sub(/[[:space:]]*$/, "", ref)
      if (length(ref) != 40 || ref !~ /^[0-9a-fA-F]+$/) {
        print "action ref must be exactly 40 hex chars: " ref
        invalid = 1
      }
    }
    END { exit invalid }
  ' .github/workflows/quality.yml
  [ "$status" -eq 0 ]
}

@test "phase 1 exposes approved application boundaries and root command metadata" {
  for path in apps/mobile/package.json apps/mobile/.env.example apps/api/pyproject.toml apps/api/uv.lock; do
    [ -f "$path" ]
  done

  run node -e '
    const pkg = require("./package.json");
    const scripts = pkg.scripts;
    const required = [
      "dev:mobile",
      "dev:api",
      "lint:mobile",
      "lint:api",
      "typecheck",
      "test:mobile",
      "test:api",
      "build:web",
      "quality"
    ];
    for (const name of required) {
      if (typeof scripts[name] !== "string" || scripts[name].trim() === "") {
        throw new Error(`missing root script: ${name}`);
      }
    }

    const mobile = scripts["dev:mobile"].split(/\s+/);
    if (mobile.slice(0, 4).join(" ") !== "pnpm --dir apps/mobile start") {
      throw new Error("mobile command must run Expo from apps/mobile");
    }
    if (mobile.slice(-2).join(" ") !== "--port 8081") {
      throw new Error("mobile command must use the stable Expo port");
    }

    const api = scripts["dev:api"].split(/\s+/);
    if (api.slice(0, 6).join(" ") !== "uv run --directory apps/api uvicorn app.main:app") {
      throw new Error("API command must run uvicorn from apps/api");
    }
    if (!api.includes("app.main:app") || api.slice(-4).join(" ") !== "--host 127.0.0.1 --port 8000") {
      throw new Error("API command must bind the stable localhost address");
    }

    const quality = scripts.quality.split(/\s+&&\s+/);
    for (const name of ["lint", "test", "lint:mobile", "lint:api", "typecheck", "test:mobile", "test:api", "build:web"]) {
      if (!quality.includes(`pnpm ${name}`)) {
        throw new Error(`quality gate is missing: ${name}`);
      }
    }
  '
  [ "$status" -eq 0 ]
}

@test "persistence commands use the isolated PostgreSQL services and Alembic" {
  run node -e '
    const scripts = require("./package.json").scripts;
    const required = {
      "db:up": "docker compose up -d --wait db",
      "db:test:up": "docker compose --profile test up -d --wait db-test",
      "db:migrate": "uv run --directory apps/api alembic upgrade head",
    };
    for (const [name, command] of Object.entries(required)) {
      if (scripts[name] !== command) {
        throw new Error(`${name} must be ${command}`);
      }
    }
  '
  [ "$status" -eq 0 ] || return 1

  run grep -F 'image: postgres:18.6' compose.yaml
  [ "$status" -eq 0 ] || return 1
  run grep -F '127.0.0.1:5432:5432' compose.yaml
  [ "$status" -eq 0 ] || return 1
  run grep -F '127.0.0.1:5433:5432' compose.yaml
  [ "$status" -eq 0 ] || return 1
  run grep -F 'profiles: [test]' compose.yaml
  [ "$status" -eq 0 ] || return 1
  run grep -F 'tmpfs:' compose.yaml
  [ "$status" -eq 0 ]
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

@test "publication plan protects the reviewed feature history from stale local main" {
  plan=docs/superpowers/plans/2026-09-04-developer-environment.md

  grep -F 'feature/phase-00-environment' "$plan" || return 1
  grep -F 'git merge-base --is-ancestor "$reviewed_head" HEAD' "$plan" || return 1
  grep -F 'git push --set-upstream origin HEAD:refs/heads/main' "$plan" || return 1
  grep -F 'Never run `git push origin main`, `git push --set-upstream origin main`, or `git merge main`' "$plan"
}

@test "Python guidance requires an installed managed interpreter without downloads" {
  command='UV_PYTHON_DOWNLOADS=never uv python find --managed-python 3.14.7'
  for path in \
    docs/setup/macos.md \
    docs/setup/troubleshooting.md \
    docs/superpowers/plans/2026-09-04-developer-environment.md; do
    grep -F "$command" "$path" || return 1
  done
}

@test "manual acceptance documents the disposable Docker smoke workload" {
  guide=docs/setup/macos.md
  grep -Fx 'docker run --rm hello-world' "$guide" || return 1
  grep -F 'disposable smoke container exits successfully' "$guide" || return 1
  grep -F 'Do not reset Docker or delete Docker data' "$guide"
}
