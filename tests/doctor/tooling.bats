#!/usr/bin/env bats

load test_helper

setup() {
  PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
  export PROJECT_ROOT
  ORIGINAL_PWD=$PWD
  export ORIGINAL_PWD
  cd "$PROJECT_ROOT"
  setup_fake_path
  . "$PROJECT_ROOT/scripts/doctor.d/00-core.sh"
}

teardown() {
  cd "$ORIGINAL_PWD"
}

@test "Homebrew bundle check failure reports the Brewfile remediation" {
  fake_command brew 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/30-homebrew.sh"
  run doctor_run_registered brew.bundle
  [ "$status" -eq 1 ]
  [[ "$output" == *"brew bundle check failed; see troubleshooting#brew-bundle"* ]]
}

@test "Homebrew bundle check receives the exact Brewfile arguments" {
  fake_command brew 'if [ "$#" -ne 4 ] || [ "$1" != bundle ] || [ "$2" != check ] || [ "$3" != --file ]; then exit 97; fi; if [ "$4" != "$PROJECT_ROOT/Brewfile" ]; then exit 97; fi; exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/30-homebrew.sh"
  run doctor_run_registered brew.bundle
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [brew.bundle]"* ]]
}

@test "missing Homebrew is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/30-homebrew.sh"
  run doctor_run_registered brew.bundle
  [ "$status" -eq 1 ]
  [[ "$output" == *"Homebrew is missing; install it before continuing; see troubleshooting#brew-bundle"* ]]
}

@test "missing Git is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/40-git.sh"
  run doctor_run_registered git.version
  [ "$status" -eq 1 ]
  [[ "$output" == *"Git is missing; install it before continuing; see troubleshooting#git-version"* ]]
}

@test "Git reports only the first version line" {
  fake_command git 'printf "%s\n" "git version 2.50.1" "credential=secret-value"'
  . "$PROJECT_ROOT/scripts/doctor.d/40-git.sh"
  run doctor_run_registered git.version
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [git.version] git version 2.50.1"* ]]
  [[ "$output" != *"credential=secret-value"* ]]
}

@test "Git version execution failure reports a safe error" {
  fake_command git 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/40-git.sh"
  run doctor_run_registered git.version
  [ "$status" -eq 1 ]
  [[ "$output" == *"Git version could not be detected; see troubleshooting#git-version"* ]]
}

@test "missing Volta is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.volta
  [ "$status" -eq 1 ]
  [[ "$output" == *"Volta is missing; install it before continuing; see troubleshooting#js-volta"* ]]
}

@test "missing Node is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.node
  [ "$status" -eq 1 ]
  [[ "$output" == *"Node.js is missing; install the pinned version; see troubleshooting#js-node"* ]]
}

@test "wrong Node version reports expected and detected values" {
  fake_command node 'printf "%s\n" "v22.17.1" "secret-value"'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.node
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires Node.js v24.20.0; detected v22.17.1"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "Node version uses only its first output line" {
  fake_command node 'printf "%s\n" "v24.20.0" "secret-value"'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.node
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [js.node] Node.js v24.20.0"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "Node version execution failure reports a safe error" {
  fake_command node 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.node
  [ "$status" -eq 1 ]
  [[ "$output" == *"Node.js version could not be detected; see troubleshooting#js-node"* ]]
}

@test "missing Corepack is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.corepack
  [ "$status" -eq 1 ]
  [[ "$output" == *"Corepack is missing; enable it with the pinned Node release; see troubleshooting#js-corepack"* ]]
}

@test "missing pnpm is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.pnpm
  [ "$status" -eq 1 ]
  [[ "$output" == *"pnpm is missing; activate it through Corepack; see troubleshooting#js-pnpm"* ]]
}

@test "wrong pnpm version reports expected and detected values" {
  fake_command pnpm 'printf "%s\n" "10.0.0" "secret-value"'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.pnpm
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires pnpm 11.25.0; detected 10.0.0"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "pnpm version uses only its first output line" {
  fake_command pnpm 'printf "%s\n" "11.25.0" "secret-value"'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.pnpm
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [js.pnpm] pnpm 11.25.0"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "pnpm version execution failure reports a safe error" {
  fake_command pnpm 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  run doctor_run_registered js.pnpm
  [ "$status" -eq 1 ]
  [[ "$output" == *"pnpm version could not be detected; see troubleshooting#js-pnpm"* ]]
}

@test "missing uv is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.uv
  [ "$status" -eq 1 ]
  [[ "$output" == *"uv is missing; install it before continuing; see troubleshooting#python-uv"* ]]
}

@test "missing uv-managed Python cannot satisfy the project runtime" {
  fake_command uv 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.runtime
  [ "$status" -eq 1 ]
  [[ "$output" == *"uv-managed Python 3.14.7 is not installed"* ]]
}

@test "system Python cannot satisfy the project runtime" {
  fake_command uv 'printf "%s\n" "/usr/bin/python3"'
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.runtime
  [ "$status" -eq 1 ]
  [[ "$output" == *"project Python is not uv-managed"* ]]
}

@test "Homebrew Python cannot satisfy the managed project runtime" {
  fake_command uv 'printf "%s\n" "/opt/homebrew/bin/python3.14"'
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.runtime
  [ "$status" -eq 1 ]
  [[ "$output" == *"project Python is not uv-managed"* ]]
}

@test "uv runtime probe requires managed Python and does not allow downloads" {
  fake_command uv 'if [ "$#" -ne 4 ] || [ "$1" != python ] || [ "$2" != find ] || [ "$3" != --managed-python ] || [ "$4" != 3.14.7 ] || [ "$UV_PYTHON_DOWNLOADS" != never ]; then exit 2; fi; printf "%s\n" "/Users/example/.local/share/uv/python/cpython-3.14.7/bin/python"; exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.runtime
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [python.runtime] uv-managed Python 3.14.7 at /Users/example/.local/share/uv/python/cpython-3.14.7/bin/python"* ]]
}

@test "missing Docker is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.cli
  [ "$status" -eq 1 ]
  [[ "$output" == *"Docker is missing; install Docker Desktop; see troubleshooting#docker-cli"* ]]
}

@test "Docker version execution failure reports a safe error" {
  fake_command docker 'if [ "$1" = --version ]; then exit 1; fi'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.cli
  [ "$status" -eq 1 ]
  [[ "$output" == *"Docker version could not be detected; see troubleshooting#docker-cli"* ]]
}

@test "stopped Docker daemon is distinct from a missing CLI" {
  fake_command docker 'if [ "$1" = info ]; then exit 1; fi; printf "%s\n" "Docker version 29.0.0"'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.daemon
  [ "$status" -eq 1 ]
  [[ "$output" == *"Docker is installed but the daemon is not reachable"* ]]
}

@test "Docker daemon diagnostics are redacted" {
  fake_command docker 'if [ "$1" = info ]; then printf "%s\n" "token=secret-value"; exit 1; fi'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.daemon
  [ "$status" -eq 1 ]
  [[ "$output" != *"secret-value"* ]]
}

@test "missing Docker Compose is reported as a required command" {
  fake_command docker 'if [ "$1" = compose ]; then exit 1; fi'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.compose
  [ "$status" -eq 1 ]
  [[ "$output" == *"Docker Compose is unavailable; see troubleshooting#docker-compose"* ]]
}

@test "Docker Compose reports only its first version line" {
  fake_command docker 'if [ "$1" = compose ]; then printf "%s\n" "Docker Compose version v2.40.0" "token=secret-value"; fi'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.compose
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [docker.compose] Docker Compose version v2.40.0"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "Docker Compose receives the exact version arguments" {
  fake_command docker 'if [ "$#" -ne 2 ] || [ "$1" != compose ] || [ "$2" != version ]; then exit 97; fi; printf "%s\n" "Docker Compose version v2.40.0"; exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.compose
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [docker.compose] Docker Compose version v2.40.0"* ]]
}

@test "missing GitHub CLI is reported as a required command" {
  PATH="$FAKE_BIN:/bin"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.cli
  [ "$status" -eq 1 ]
  [[ "$output" == *"GitHub CLI is missing; install it before continuing; see troubleshooting#github-cli"* ]]
}

@test "GitHub CLI version execution failure reports a safe error" {
  fake_command gh 'if [ "$1" = --version ]; then exit 1; fi'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.cli
  [ "$status" -eq 1 ]
  [[ "$output" == *"GitHub CLI version could not be detected; see troubleshooting#github-cli"* ]]
}

@test "GitHub auth failure with connectivity succeeds recommends login without exposing output" {
  fake_command gh 'printf "%s\n" "token=secret-value"; exit 1'
  fake_command curl 'if [ "$#" -ne 8 ] || [ "$1" != --connect-timeout ] || [ "$2" != 5 ] || [ "$3" != --max-time ] || [ "$4" != 10 ] || [ "$5" != --silent ] || [ "$6" != --output ] || [ "$7" != /dev/null ] || [ "$8" != https://api.github.com/ ]; then exit 97; fi; : >"$BATS_TEST_TMPDIR/curl-called"; exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"run gh auth login --hostname github.com"* ]] || return 1
  [[ "$output" != *"secret-value"* ]] || return 1
  [ -f "$BATS_TEST_TMPDIR/curl-called" ]
}

@test "GitHub connectivity failure recommends network recovery without exposing output" {
  fake_command gh 'printf "%s\n" "token=secret-value"; exit 1'
  fake_command curl 'if [ "$#" -ne 8 ] || [ "$1" != --connect-timeout ] || [ "$2" != 5 ] || [ "$3" != --max-time ] || [ "$4" != 10 ] || [ "$5" != --silent ] || [ "$6" != --output ] || [ "$7" != /dev/null ] || [ "$8" != https://api.github.com/ ]; then exit 97; fi; printf "%s\n" "network-secret-value"; exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"cannot reach github.com; check network connectivity"* ]] || return 1
  [[ "$output" != *"run gh auth login"* ]] || return 1
  [[ "$output" != *"secret-value"* ]]
}

@test "missing curl reports safe GitHub connectivity remediation" {
  fake_command gh 'exit 1'
  saved_path=$PATH
  PATH="$FAKE_BIN"
  export PATH
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  PATH=$saved_path
  export PATH
  [ "$status" -eq 1 ] || return 1
  [[ "$output" == *"cannot verify GitHub connectivity because curl is missing"* ]] || return 1
  [[ "$output" != *"run gh auth login"* ]]
}

@test "GitHub authentication receives the exact status arguments" {
  fake_command gh 'if [ "$#" -ne 4 ] || [ "$1" != auth ] || [ "$2" != status ] || [ "$3" != --hostname ] || [ "$4" != github.com ]; then exit 97; fi; exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [github.auth] GitHub CLI is authenticated for github.com"* ]]
}

@test "repository failure reports the exact missing paths" {
  module="$PROJECT_ROOT/scripts/doctor.d/90-repository.sh"
  fixture_root="$BATS_TEST_TMPDIR/empty-repository"
  mkdir -p "$fixture_root"
  PROJECT_ROOT=$fixture_root
  export PROJECT_ROOT
  . "$module"
  run doctor_run_registered repository.files
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing required repository files: Brewfile LICENSE README.md package.json pnpm-lock.yaml pnpm-workspace.yaml .python-version docs/curriculum-roadmap.md docs/setup/macos.md docs/setup/troubleshooting.md"* ]]
}

@test "all repository contracts pass from the project root" {
  module="$PROJECT_ROOT/scripts/doctor.d/90-repository.sh"
  fixture_root="$BATS_TEST_TMPDIR/repository"
  mkdir -p "$fixture_root/docs/setup"
  cp Brewfile LICENSE package.json pnpm-lock.yaml pnpm-workspace.yaml .python-version "$fixture_root/"
  touch "$fixture_root/README.md" \
    "$fixture_root/docs/curriculum-roadmap.md" \
    "$fixture_root/docs/setup/macos.md" \
    "$fixture_root/docs/setup/troubleshooting.md"
  PROJECT_ROOT=$fixture_root
  export PROJECT_ROOT
  . "$module"
  run doctor_run_registered repository.files
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [repository.files]"* ]]
}

@test "every tooling check passes with reference command outputs" {
  fake_command brew 'exit 0'
  fake_command git 'printf "%s\n" "git version 2.50.1" "credential=secret-value"'
  fake_command volta 'exit 0'
  fake_command node 'printf "%s\n" "v24.20.0"'
  fake_command corepack 'exit 0'
  fake_command pnpm 'printf "%s\n" "11.25.0"'
  fake_command uv 'if [ "$1" = python ] && [ "$2" = find ]; then printf "%s\n" "/Users/example/.local/share/uv/python/cpython-3.14.7/bin/python"; fi'
  fake_command docker 'if [ "$1" = info ]; then exit 0; elif [ "$1" = --version ]; then printf "%s\n" "Docker version 29.0.0"; elif [ "$1" = compose ]; then printf "%s\n" "Docker Compose version v2.40.0"; fi'
  fake_command gh 'if [ "$1" = auth ]; then exit 0; else printf "%s\n" "gh version 2.80.0" "credential=secret-value"; fi'

  . "$PROJECT_ROOT/scripts/doctor.d/30-homebrew.sh"
  . "$PROJECT_ROOT/scripts/doctor.d/40-git.sh"
  . "$PROJECT_ROOT/scripts/doctor.d/50-javascript.sh"
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"

  for check_id in \
    brew.bundle git.version js.volta js.node js.corepack js.pnpm \
    python.uv python.runtime docker.cli docker.daemon docker.compose \
    github.cli github.auth; do
    run doctor_run_registered "$check_id"
    [ "$status" -eq 0 ]
    [[ "$output" == *"PASS [$check_id]"* ]]
  done
}
