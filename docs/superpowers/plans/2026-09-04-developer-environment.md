# Phase 0 Mac Developer Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the reference Apple Silicon Mac and publish a verified, public `tylervsd/expo-fastapi-todo` teaching repository without scaffolding either application.

**Architecture:** System software is installed intentionally on the host, while repository files declare the supported language toolchain and quality commands. A dependency-free POSIX shell doctor loads small check modules, aggregates `PASS`/`WARN`/`FAIL` results, and points learners to stable troubleshooting identifiers without mutating their machine.

**Tech Stack:** macOS 26.6.2 arm64, Xcode 26.6 with iOS 26 simulator, Homebrew, Volta, Node.js 24.20.0, Corepack, pnpm 11.25.0, uv, Python 3.14.7, Docker Desktop, GitHub CLI, POSIX shell, Bats Core, ShellCheck, Markdownlint CLI2, markdown-link-check, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-04-developer-environment-design.md`

## Global Constraints

- The only supported developer host is the maintainer's Apple Silicon Mac running macOS 26.6.2 (build 25G83).
- The repository is public, MIT licensed, owned by `tylervsd`, named `expo-fastapi-todo`, and uses `main` as its default branch.
- Phase 0 must not scaffold Expo, FastAPI, PostgreSQL, todo features, authentication, or application E2E tests.
- Node.js is pinned to `24.20.0`; pnpm is pinned to `11.25.0`; Python is pinned to `3.14.7`.
- Volta owns Node selection, Corepack activates pnpm, and uv owns project Python; macOS system Python is never modified or used by project commands.
- Docker Desktop supplies Docker Engine and Compose.
- Installation is guided and explicit. Scripts must not install software, invoke hidden `sudo`, accept licenses, authenticate accounts, rewrite shell profiles, or expose credentials.
- The doctor is POSIX shell, dependency-free at runtime, modular, read-only, and returns nonzero when any required check fails.
- `PASS`, `WARN`, and `FAIL` are the only result classes; warnings do not make the doctor fail.
- Static checks and doctor tests run on each pull request and push to `main`; third-party Actions are pinned by full commit SHA.
- The final `phase-00-environment` tag is created only after local acceptance and GitHub Actions pass.
- Preserve the existing untracked `AGENTS.md`; do not stage or publish it unless the user separately requests that change.

---

## Planned file map

- `Brewfile` — declarative Mac CLI and Docker Desktop prerequisites.
- `.gitignore` — local dependency, editor, OS, and test artifacts.
- `.python-version` — the exact uv-managed Python pin.
- `package.json` — Node/pnpm pins and root quality command interface.
- `pnpm-lock.yaml` — exact documentation-tool dependency resolution.
- `pnpm-workspace.yaml` — future monorepo package boundaries without application packages.
- `.markdownlint-cli2.jsonc` — Markdown style exclusions and rule adjustments.
- `.markdown-link-check.json` — external-link retry and localhost exclusion policy.
- `LICENSE` — MIT license.
- `README.md` — public project entry point and pre-clone bootstrap.
- `scripts/check-doc-links` — deterministic discovery of Markdown files for link checking.
- `scripts/doctor` — dependency-free entry point, option parsing, module loading, and exit propagation.
- `scripts/doctor.d/00-core.sh` — check registration, result helpers, aggregation, and output.
- `scripts/doctor.d/10-platform.sh` — macOS and architecture checks.
- `scripts/doctor.d/20-xcode.sh` — Xcode, first-launch, and simulator checks.
- `scripts/doctor.d/30-homebrew.sh` — Homebrew and `Brewfile` checks.
- `scripts/doctor.d/40-git.sh` — Git check.
- `scripts/doctor.d/50-javascript.sh` — Volta, Node, Corepack, and pnpm checks.
- `scripts/doctor.d/60-python.sh` — uv and non-system Python checks.
- `scripts/doctor.d/70-docker.sh` — Docker installation, daemon, and Compose checks.
- `scripts/doctor.d/80-github.sh` — GitHub CLI installation and authentication checks.
- `scripts/doctor.d/90-repository.sh` — required-file and version-contract checks.
- `tests/repository_contract.bats` — tests for repository pins and metadata.
- `tests/doctor/test_helper.bash` — isolated fake-command and fixture helpers.
- `tests/doctor/core.bats` — runner, classification, summary, filtering, and redaction unit tests.
- `tests/doctor/platform_xcode.bats` — platform and Xcode module unit tests.
- `tests/doctor/tooling.bats` — Homebrew, Git, JavaScript, Python, Docker, GitHub, and repository unit tests.
- `tests/doctor/integration.bats` — assembled-doctor test with a complete fake environment.
- `docs/setup/macos.md` — linear, resumable setup guide.
- `docs/setup/troubleshooting.md` — remediation indexed by doctor check ID.
- `docs/curriculum-roadmap.md` — provisional nine-phase teaching path.
- `docs/decisions/0001-monorepo-and-checkpoint-tags.md` — repository evolution decision.
- `docs/decisions/0002-layered-tool-ownership.md` — tool ownership decision.
- `docs/decisions/0003-testing-pyramid.md` — project test strategy decision.
- `.github/workflows/quality.yml` — static, unit, and macOS integration jobs.

### Task 1: Install and verify the Apple development toolchain

**Files:**

- No repository files change.

**Interfaces:**

- Consumes: macOS 26.6.2 on Apple Silicon with Command Line Tools selected.
- Produces: `/Applications/Xcode.app`, Xcode 26.6 selected at `/Applications/Xcode.app/Contents/Developer`, completed first-launch setup, and an available iPhone 17 Pro simulator on iOS 26.

- [ ] **Step 1: Capture the failing preflight evidence**

Run:

```bash
uname -m
sw_vers -productVersion
xcode-select -p
xcodebuild -version
xcrun simctl list devices available
```

Expected: `arm64` and `26.6.2` pass; `xcodebuild` and `simctl` fail because only `/Library/Developer/CommandLineTools` is selected.

- [ ] **Step 2: Install full Xcode 26.6**

Ask the user to install Xcode 26.6 from the Mac App Store and open it once. This download and Apple license interaction are intentionally user-controlled.

- [ ] **Step 3: Select Xcode and complete first-launch setup**

Ask the user to run the privileged commands directly in Terminal so the password is never handled by the agent:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -runFirstLaunch
xcodebuild -downloadPlatform iOS
```

Expected: each command exits `0`; the platform download reports completion.

- [ ] **Step 4: Verify and boot the designated simulator**

Run:

```bash
xcodebuild -version
xcrun simctl list runtimes | grep 'iOS 26'
xcrun simctl list devices available | grep 'iPhone 17 Pro'
open -a Simulator
xcrun simctl boot 'iPhone 17 Pro' 2>/dev/null || true
xcrun simctl bootstatus 'iPhone 17 Pro' -b
```

Expected: Xcode reports `26.6`; an iOS 26 runtime and iPhone 17 Pro device are listed; `bootstatus` reaches a finished state.

### Task 2: Install declared host tools and correct local Git identity

**Files:**

- Create: `Brewfile`
- Existing: `docs/superpowers/plans/2026-09-04-developer-environment.md`

**Interfaces:**

- Consumes: working Xcode Command Line Tools from Task 1 and the approved plan/spec.
- Produces: Homebrew, Bats Core, GitHub CLI, ShellCheck, Volta, Docker Desktop, uv-managed Python 3.14.7, Node 24.20.0, authenticated GitHub CLI, and a repository-local Git identity.

- [ ] **Step 1: Install Homebrew with its official interactive installer**

Open [brew.sh](https://brew.sh/) for the user to verify the current official command, then ask the user to run it. Do not run a downloaded script without that explicit confirmation.

Ask the user to open `~/.zprofile` in their editor and add this line once; do not append it automatically:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Open a fresh terminal and run `brew --version`.

Expected: `brew --version` succeeds from a fresh terminal.

- [ ] **Step 2: Add the explicit Homebrew bundle**

Create `Brewfile` with:

```ruby
brew "bats-core"
brew "gh"
brew "shellcheck"
brew "volta"
cask "docker-desktop"
```

Run:

```bash
brew bundle --file Brewfile
brew bundle check --file Brewfile
```

Expected: the first command installs missing entries; the second reports that dependencies are satisfied.

- [ ] **Step 3: Configure Volta without an automated profile rewrite**

Ask the user to add these lines to `~/.zprofile` manually:

```bash
export VOLTA_HOME="$HOME/.volta"
export PATH="$VOLTA_HOME/bin:$PATH"
```

Open a fresh terminal and run:

```bash
volta --version
volta install node@24.20.0
node --version
corepack --version
corepack enable --install-directory "$VOLTA_HOME/bin"
```

Expected: Node reports `v24.20.0`; Corepack is available.

- [ ] **Step 4: Install the project Python without touching system Python**

Run:

```bash
uv python install 3.14.7
UV_PYTHON_DOWNLOADS=never uv python find --managed-python 3.14.7
/usr/bin/python3 --version
```

Expected: uv finds the managed Python 3.14.7 interpreter; `/usr/bin/python3` still reports the Apple-supplied version.

- [ ] **Step 5: Start and verify Docker Desktop**

Run:

```bash
open -a Docker
```

Wait for Docker Desktop to report that the engine is running, then run:

```bash
docker version
docker compose version
docker info >/dev/null
```

Expected: all commands exit `0`.

- [ ] **Step 6: Authenticate GitHub CLI and set a private commit address**

Run the interactive login:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth status --hostname github.com
```

Then set repository-local identity using GitHub's no-reply address and repair the unpublished root commit's generated host email:

```bash
git config user.name "Tyler Vallillee"
github_id=$(gh api user --jq '.id')
github_login=$(gh api user --jq '.login')
git config user.email "${github_id}+${github_login}@users.noreply.github.com"
git commit --amend --no-edit --reset-author
git log -1 --format='%an <%ae>'
```

Expected: the email ends in `@users.noreply.github.com`; no personal token or email is printed.

- [ ] **Step 7: Commit the environment manifest and approved plan**

Run:

```bash
git add Brewfile docs/superpowers/specs/2026-09-04-developer-environment-design.md docs/superpowers/plans/2026-09-04-developer-environment.md
git commit -m "chore: declare phase 0 development tools"
```

Expected: only the two named files are committed; `AGENTS.md` remains untracked.

### Task 3: Add repository metadata, tool pins, and contract tests

**Files:**

- Create: `.gitignore`
- Create: `.python-version`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `.markdownlint-cli2.jsonc`
- Create: `.markdown-link-check.json`
- Create: `LICENSE`
- Create: `scripts/check-doc-links`
- Create: `tests/repository_contract.bats`
- Create: `pnpm-lock.yaml`

**Interfaces:**

- Consumes: Bats, Volta Node 24.20.0, Corepack, and pnpm 11.25.0.
- Produces: machine-readable tool pins; `pnpm lint:markdown`, `pnpm lint:links`, and `bats tests/repository_contract.bats` command contracts.

- [ ] **Step 1: Write the failing repository contract test**

Create `tests/repository_contract.bats`:

```bash
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bats tests/repository_contract.bats`

Expected: FAIL because `package.json`, `.python-version`, `LICENSE`, and `pnpm-workspace.yaml` do not exist.

- [ ] **Step 3: Add root metadata and exact pins**

Create `.python-version`:

```text
3.14.7
```

Create `package.json`:

```json
{
  "name": "expo-fastapi-todo",
  "version": "0.0.0",
  "private": true,
  "description": "A phased tutorial for production-shaped Expo and FastAPI development.",
  "license": "MIT",
  "engines": {
    "node": "24.20.0"
  },
  "packageManager": "pnpm@11.25.0",
  "volta": {
    "node": "24.20.0"
  },
  "scripts": {
    "doctor": "./scripts/doctor",
    "lint": "pnpm lint:markdown && pnpm lint:links && shellcheck scripts/doctor scripts/check-doc-links scripts/doctor.d/*.sh",
    "lint:links": "./scripts/check-doc-links",
    "lint:markdown": "markdownlint-cli2 \"**/*.md\" \"#node_modules\"",
    "test": "pnpm test:contracts && pnpm test:doctor",
    "test:contracts": "bats tests/repository_contract.bats",
    "test:doctor": "bats tests/doctor"
  }
}
```

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - "apps/*"
  - "services/*"
  - "packages/*"
```

Create `.gitignore`:

```gitignore
.DS_Store
.idea/
.vscode/
node_modules/
.pnpm-store/
.venv/
coverage/
dist/
*.log
```

- [ ] **Step 4: Add documentation quality configuration**

Create `.markdownlint-cli2.jsonc`:

```jsonc
{
  "config": {
    "MD013": false,
    "MD024": { "siblings_only": true },
    "MD033": false
  },
  "globs": ["**/*.md", "#node_modules"]
}
```

Create `.markdown-link-check.json`:

```json
{
  "retryOn429": true,
  "retryCount": 3,
  "fallbackRetryDelay": "5s",
  "ignorePatterns": [
    { "pattern": "^http://localhost" },
    { "pattern": "^http://127\\.0\\.0\\.1" }
  ]
}
```

Create executable `scripts/check-doc-links`:

```sh
#!/bin/sh
set -eu

find README.md docs -type f -name '*.md' -print0 \
  | xargs -0 -n 1 pnpm exec markdown-link-check --quiet --config .markdown-link-check.json
```

- [ ] **Step 5: Add the MIT license**

Create `LICENSE` using the unmodified MIT License text with `Copyright (c) 2026 Tyler Vallillee`.

- [ ] **Step 6: Activate pnpm and lock documentation dependencies exactly**

Run:

```bash
corepack enable
corepack prepare pnpm@11.25.0 --activate
pnpm add --save-dev --save-exact markdown-link-check markdownlint-cli2
chmod +x scripts/check-doc-links
pnpm install --lockfile-only
```

Expected: `pnpm --version` prints `11.25.0`; `package.json` contains exact dev dependency versions; `pnpm-lock.yaml` is created.

- [ ] **Step 7: Run the contract test and metadata checks**

Run:

```bash
bats tests/repository_contract.bats
pnpm lint:markdown
```

Expected: both commands pass. `pnpm lint:links` is deferred until the public docs exist in Task 7.

- [ ] **Step 8: Commit root project contracts**

Run:

```bash
git add .gitignore .python-version package.json pnpm-workspace.yaml pnpm-lock.yaml .markdownlint-cli2.jsonc .markdown-link-check.json LICENSE scripts/check-doc-links tests/repository_contract.bats
git commit -m "chore: pin phase 0 project toolchain"
```

### Task 4: Build the doctor runner through unit tests

**Files:**

- Create: `scripts/doctor`
- Create: `scripts/doctor.d/00-core.sh`
- Create: `tests/doctor/core.bats`

**Interfaces:**

- Consumes: POSIX `sh`; modules call `doctor_register ID required|optional FUNCTION` and set results with `doctor_pass`, `doctor_warn`, or `doctor_missing`.
- Produces: `doctor_run_registered [CHECK_ID] -> exit 0|1|64` and CLI forms `scripts/doctor` and `scripts/doctor --check CHECK_ID`.

- [ ] **Step 1: Write failing runner tests**

Create `tests/doctor/core.bats`:

```bash
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
```

- [ ] **Step 2: Run the runner tests to verify they fail**

Run: `bats tests/doctor/core.bats`

Expected: FAIL because `scripts/doctor.d/00-core.sh` does not exist.

- [ ] **Step 3: Implement the result and registration interface**

Create `scripts/doctor.d/00-core.sh` with this behavior:

```sh
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
```

- [ ] **Step 4: Implement the dependency-free entry point**

Create executable `scripts/doctor`:

```sh
#!/bin/sh
set -u

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
export PROJECT_ROOT

. "$PROJECT_ROOT/scripts/doctor.d/00-core.sh"
for module in "$PROJECT_ROOT"/scripts/doctor.d/[1-9][0-9]-*.sh; do
  [ -f "$module" ] && . "$module"
done

case $# in
  0) doctor_run_registered ;;
  2)
    if [ "$1" != '--check' ]; then
      printf 'Usage: %s [--check CHECK_ID]\n' "$0" >&2
      exit 64
    fi
    doctor_run_registered "$2"
    ;;
  *)
    printf 'Usage: %s [--check CHECK_ID]\n' "$0" >&2
    exit 64
    ;;
esac
```

Run: `chmod +x scripts/doctor`

- [ ] **Step 5: Run runner tests and static analysis**

Run:

```bash
bats tests/doctor/core.bats
shellcheck scripts/doctor scripts/doctor.d/00-core.sh
```

Expected: all tests pass and ShellCheck reports no findings.

- [ ] **Step 6: Commit the doctor runner**

Run:

```bash
git add scripts/doctor scripts/doctor.d/00-core.sh tests/doctor/core.bats
git commit -m "feat: add modular environment doctor runner"
```

### Task 5: Add platform and Xcode checks test-first

**Files:**

- Create: `scripts/doctor.d/10-platform.sh`
- Create: `scripts/doctor.d/20-xcode.sh`
- Create: `tests/doctor/test_helper.bash`
- Create: `tests/doctor/platform_xcode.bats`

**Interfaces:**

- Consumes: the registration and result helpers from Task 4 and fake commands placed first on `PATH` by tests.
- Produces: focused checks `platform.macos`, `platform.arch`, `xcode.version`, `xcode.first-launch`, and `xcode.simulator`.

- [ ] **Step 1: Add an isolated fake-command helper**

Create `tests/doctor/test_helper.bash`:

```bash
setup_fake_path() {
  FAKE_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$FAKE_BIN"
  ORIGINAL_PATH=$PATH
  PATH="$FAKE_BIN:$PATH"
  export PATH
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
```

- [ ] **Step 2: Write failing platform and Xcode tests**

Create `tests/doctor/platform_xcode.bats` with isolated cases that fake each external command and assert these exact outcomes:

```bash
#!/usr/bin/env bats

load test_helper

setup() {
  PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
  export PROJECT_ROOT
  setup_fake_path
  . "$PROJECT_ROOT/scripts/doctor.d/00-core.sh"
}

@test "reference platform passes" {
  fake_command sw_vers "printf '%s\\n' '26.6.2'"
  fake_command uname "printf '%s\\n' 'arm64'"
  . "$PROJECT_ROOT/scripts/doctor.d/10-platform.sh"
  run doctor_run_registered platform.macos
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [platform.macos] macOS 26.6.2"* ]]
}

@test "wrong architecture fails with remediation" {
  fake_command sw_vers "printf '%s\\n' '26.6.2'"
  fake_command uname "printf '%s\\n' 'x86_64'"
  . "$PROJECT_ROOT/scripts/doctor.d/10-platform.sh"
  run doctor_run_registered platform.arch
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires Apple Silicon arm64; detected x86_64"* ]]
}

@test "command line tools selection is not accepted as full Xcode" {
  fake_command xcode-select "printf '%s\\n' '/Library/Developer/CommandLineTools'"
  fake_command xcodebuild "printf '%s\\n' 'Xcode 26.6' 'Build version 17G80'"
  fake_command xcrun "printf '%s\\n' 'iPhone 17 Pro (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.version
  [ "$status" -eq 1 ]
  [[ "$output" == *"select /Applications/Xcode.app/Contents/Developer"* ]]
}

@test "available designated simulator passes without booting it" {
  fake_command xcode-select "printf '%s\\n' '/Applications/Xcode.app/Contents/Developer'"
  fake_command xcodebuild "exit 0"
  fake_command xcrun "printf '%s\\n' 'iOS 26.6 (26.6 - 23G80)' 'iPhone 17 Pro (AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE) (Shutdown)'"
  . "$PROJECT_ROOT/scripts/doctor.d/20-xcode.sh"
  run doctor_run_registered xcode.simulator
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [xcode.simulator] iOS 26 simulator includes iPhone 17 Pro"* ]]
}
```

- [ ] **Step 3: Run the module tests to verify they fail**

Run: `bats tests/doctor/platform_xcode.bats`

Expected: FAIL because the two module files do not exist.

- [ ] **Step 4: Implement platform checks**

Create `scripts/doctor.d/10-platform.sh` with `check_platform_macos` and `check_platform_arch`. Invoke `sw_vers -productVersion` and `uname -m`, compare exactly with `26.6.2` and `arm64`, include detected values in failure messages, then register:

```sh
doctor_register platform.macos required check_platform_macos
doctor_register platform.arch required check_platform_arch
```

- [ ] **Step 5: Implement Xcode checks without changing simulator state**

Create `scripts/doctor.d/20-xcode.sh` with these exact behaviors:

- `check_xcode_version`: require the selected path `/Applications/Xcode.app/Contents/Developer`, extract only the first line of `xcodebuild -version`, and require it to equal exactly `Xcode 26.6`; a mismatch reports that first line only (or the safe placeholder `<no output>`).
- `check_xcode_first_launch`: run `xcodebuild -checkFirstLaunchStatus`; exit `0` is `PASS`, any other status is `FAIL` with the remediation `Run xcodebuild -runFirstLaunch after accepting the Xcode license.`
- `check_xcode_simulator`: inspect `xcrun simctl list runtimes available` and `xcrun simctl list devices available`; require an iOS 26 runtime and an iPhone 17 Pro. Never call `simctl boot` from the doctor.

Register:

```sh
doctor_register xcode.version required check_xcode_version
doctor_register xcode.first-launch required check_xcode_first_launch
doctor_register xcode.simulator required check_xcode_simulator
```

- [ ] **Step 6: Run tests and static analysis**

Run:

```bash
bats tests/doctor/platform_xcode.bats
shellcheck scripts/doctor.d/10-platform.sh scripts/doctor.d/20-xcode.sh tests/doctor/test_helper.bash
```

Expected: all tests pass and ShellCheck reports no findings.

- [ ] **Step 7: Commit platform checks**

Run:

```bash
git add scripts/doctor.d/10-platform.sh scripts/doctor.d/20-xcode.sh tests/doctor/test_helper.bash tests/doctor/platform_xcode.bats
git commit -m "feat: diagnose macOS and Xcode setup"
```

### Task 6: Add language, service, and repository checks test-first

**Files:**

- Create: `scripts/doctor.d/30-homebrew.sh`
- Create: `scripts/doctor.d/40-git.sh`
- Create: `scripts/doctor.d/50-javascript.sh`
- Create: `scripts/doctor.d/60-python.sh`
- Create: `scripts/doctor.d/70-docker.sh`
- Create: `scripts/doctor.d/80-github.sh`
- Create: `scripts/doctor.d/90-repository.sh`
- Create: `tests/doctor/tooling.bats`

**Interfaces:**

- Consumes: Task 4 result helpers, Task 5 fake-command helper, `package.json`, `.python-version`, and `Brewfile`.
- Produces: checks `brew.bundle`, `git.version`, `js.volta`, `js.node`, `js.corepack`, `js.pnpm`, `python.uv`, `python.runtime`, `docker.cli`, `docker.daemon`, `docker.compose`, `github.cli`, `github.auth`, and `repository.files`.

- [ ] **Step 1: Write failing tooling tests**

Create `tests/doctor/tooling.bats`. Use `setup_fake_path` and one test per observable failure class. The required assertions are:

```bash
#!/usr/bin/env bats

load test_helper

setup() {
  PROJECT_ROOT="$BATS_TEST_DIRNAME/../.."
  export PROJECT_ROOT
  cd "$PROJECT_ROOT"
  setup_fake_path
}

@test "stopped Docker daemon is distinct from a missing CLI" {
  fake_command docker 'if [ "$1" = info ]; then exit 1; fi; printf "%s\\n" "Docker version 29.0.0"'
  . "$PROJECT_ROOT/scripts/doctor.d/70-docker.sh"
  run doctor_run_registered docker.daemon
  [ "$status" -eq 1 ]
  [[ "$output" == *"Docker is installed but the daemon is not reachable"* ]]
}

@test "GitHub auth failure with connectivity succeeds recommends login without exposing output" {
  fake_command gh 'printf "%s\\n" "token=secret-value"; exit 1'
  fake_command curl 'exit 0'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  [ "$status" -eq 1 ]
  [[ "$output" == *"run gh auth login --hostname github.com"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "GitHub connectivity failure recommends network recovery without exposing output" {
  fake_command gh 'printf "%s\\n" "token=secret-value"; exit 1'
  fake_command curl 'printf "%s\\n" "network-secret-value"; exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/80-github.sh"
  run doctor_run_registered github.auth
  [ "$status" -eq 1 ]
  [[ "$output" == *"cannot reach github.com; check network connectivity"* ]]
  [[ "$output" != *"secret-value"* ]]
}

@test "system Python cannot satisfy the project runtime" {
  fake_command uv 'exit 1'
  . "$PROJECT_ROOT/scripts/doctor.d/60-python.sh"
  run doctor_run_registered python.runtime
  [ "$status" -eq 1 ]
  [[ "$output" == *"uv-managed Python 3.14.7 is not installed"* ]]
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
  . "$module"
  run doctor_run_registered repository.files
  [ "$status" -eq 0 ]
}
```

Also cover command absence for each module, a wrong Node version, a wrong pnpm version, missing Corepack, a failing `brew bundle check`, missing Compose, and successful paths for every registered ID. In `setup`, change to `$PROJECT_ROOT` and restore it in `teardown`.

- [ ] **Step 2: Run tooling tests to verify they fail**

Run: `bats tests/doctor/tooling.bats`

Expected: FAIL because the tooling modules do not exist.

- [ ] **Step 3: Implement Homebrew, Git, and JavaScript modules**

Implement these rules:

```text
brew.bundle: command -v brew, then brew bundle check --file "$PROJECT_ROOT/Brewfile"
git.version: command -v git, then include only the first line of git --version
js.volta: command -v volta
js.node: node --version must equal v24.20.0
js.corepack: command -v corepack
js.pnpm: pnpm --version must equal 11.25.0
```

Every missing required command calls `doctor_missing` with a command and troubleshooting anchor; detected version mismatches call `doctor_fail` with both expected and detected values. Register each check with the exact IDs from the Interfaces block.

- [ ] **Step 4: Implement the uv-managed Python module**

`python.uv` requires `uv`. `python.runtime` must run this read-only probe:

```sh
python_path=$(UV_PYTHON_DOWNLOADS=never uv python find --managed-python 3.14.7 2>/dev/null) || {
  doctor_fail 'uv-managed Python 3.14.7 is not installed; see troubleshooting#python-runtime.'
  return
}
case "$python_path" in
  /usr/bin/*|/opt/homebrew/bin/*) doctor_fail 'project Python is not uv-managed; see troubleshooting#python-runtime.' ;;
  *) doctor_pass "uv-managed Python 3.14.7 at $python_path" ;;
esac
```

Do not run `uv python install`, `uv run`, or any command that can download Python from the doctor.

- [ ] **Step 5: Implement Docker and GitHub modules with redacted probes**

Implement these rules:

```text
docker.cli: require command -v docker and report docker --version
docker.daemon: run docker info with stdout and stderr redirected to /dev/null
docker.compose: run docker compose version and report only its first line
github.cli: require command -v gh and report gh --version first line
github.auth: run gh auth status --hostname github.com with all output redirected to /dev/null; on failure, run a fully suppressed bounded unauthenticated curl probe beginning with `--disable` to https://api.github.com/ so curl configuration cannot alter the probe. Report network remediation if the probe fails, and login remediation only if it succeeds. A missing curl reports a safe connectivity remediation.
```

No diagnostic output from `docker info`, `gh auth status`, or the GitHub connectivity probe may be copied into the doctor's messages.

- [ ] **Step 6: Implement repository contract checks**

`repository.files` requires these paths and reports all missing names in one failure:

```text
Brewfile
LICENSE
README.md
package.json
pnpm-lock.yaml
pnpm-workspace.yaml
.python-version
docs/curriculum-roadmap.md
docs/setup/macos.md
docs/setup/troubleshooting.md
```

Because the three documentation files arrive in Task 7, the test creates empty fixture files in a temporary copied repository before asserting success. Add a separate failure test proving the exact missing paths are reported.

- [ ] **Step 7: Run all doctor tests and static analysis**

Run:

```bash
bats tests/doctor/core.bats tests/doctor/platform_xcode.bats tests/doctor/tooling.bats
shellcheck scripts/doctor scripts/doctor.d/*.sh tests/doctor/test_helper.bash
```

Expected: all tests pass and ShellCheck reports no findings.

- [ ] **Step 8: Commit tooling checks**

Run:

```bash
git add scripts/doctor.d/30-homebrew.sh scripts/doctor.d/40-git.sh scripts/doctor.d/50-javascript.sh scripts/doctor.d/60-python.sh scripts/doctor.d/70-docker.sh scripts/doctor.d/80-github.sh scripts/doctor.d/90-repository.sh tests/doctor/tooling.bats
git commit -m "feat: diagnose local development services"
```

### Task 7: Write the self-guided documentation and decision records

**Files:**

- Create: `README.md`
- Create: `docs/setup/macos.md`
- Create: `docs/setup/troubleshooting.md`
- Create: `docs/curriculum-roadmap.md`
- Create: `docs/decisions/0001-monorepo-and-checkpoint-tags.md`
- Create: `docs/decisions/0002-layered-tool-ownership.md`
- Create: `docs/decisions/0003-testing-pyramid.md`
- Modify: `tests/repository_contract.bats`

**Interfaces:**

- Consumes: all check IDs and exact remediation strings from Tasks 5 and 6.
- Produces: a browser-accessible bootstrap, repository-driven setup, stable troubleshooting anchors, provisional roadmap, and ADR context for future phase authors.

- [ ] **Step 1: Extend the failing documentation contract tests**

Add tests to `tests/repository_contract.bats` that assert:

```bash
@test "README exposes the setup path and reference platform" {
  [ -f README.md ]
  grep -F 'docs/setup/macos.md' README.md
  grep -F 'macOS 26.6.2' README.md
  grep -F 'Apple Silicon' README.md
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
```

- [ ] **Step 2: Run documentation contracts to verify they fail**

Run: `bats tests/repository_contract.bats`

Expected: FAIL because the README, setup guides, roadmap, and anchors do not exist.

- [ ] **Step 3: Write the public README and browser bootstrap**

Use these sections in this order:

```markdown
# Expo + FastAPI Todo Tutorial

## What this project teaches
## Who this is for
## Current checkpoint
## Reference Mac
## Before you clone
## Continue the guided setup
## Curriculum roadmap
## Testing strategy
## License
```

`Before you clone` must contain the exact Task 1 checks and explain that only macOS 26.6.2 on Apple Silicon is supported. `Continue the guided setup` links to `docs/setup/macos.md`. `Current checkpoint` identifies Phase 0 and explains that there is intentionally no application code.

- [ ] **Step 4: Write the linear Mac setup guide**

Create `docs/setup/macos.md` with one section per step below. Every section contains `Why`, `Install`, `Verify`, and `If it fails` subsections:

```text
1. Xcode 26.6 and iOS 26 Simulator
2. Homebrew and Brewfile
3. Volta and Node 24.20.0
4. Corepack and pnpm 11.25.0
5. uv and Python 3.14.7
6. Docker Desktop and Compose
7. GitHub CLI authentication
8. Focused doctor checks
9. Complete doctor
10. Manual acceptance journey
```

Use commands already proven in Tasks 1–3. Link failures to the matching anchors in `docs/setup/troubleshooting.md`. Explicitly state that `scripts/doctor` is read-only and that install/authentication commands are intentionally not part of it.

- [ ] **Step 5: Write troubleshooting by stable check ID**

Create `docs/setup/troubleshooting.md` with an HTML anchor for every check ID, converting dots to hyphens. Each entry includes symptom, likely cause, safe diagnosis, and explicit remediation. For example:

```markdown
<a id="docker-daemon"></a>
## `docker.daemon`

**Symptom:** Docker is installed, but the doctor cannot reach its daemon.

**Likely cause:** Docker Desktop has not finished starting.

**Diagnose:** Open Docker Desktop and wait for its engine status to become ready.

**Remediate:** Run `docker info` again, followed by `./scripts/doctor --check docker.daemon`.
```

Never advise deleting Docker data, reinstalling Xcode, rewriting a profile automatically, or printing GitHub tokens as a first-line remedy.

- [ ] **Step 6: Write the provisional roadmap**

Create `docs/curriculum-roadmap.md` with the nine phase names from the approved spec. For each phase include: learning goal, visible outcome, new technology/pattern, testing-pyramid layer introduced, and an explicit statement that the phase receives its own approved spec before implementation.

- [ ] **Step 7: Write three concise ADRs**

Each ADR uses `Status`, `Context`, `Decision`, `Consequences`, and `Alternatives considered` headings:

- ADR 0001 records one evolving monorepo, numbered phase guides, and annotated checkpoint tags instead of phase branches or duplicate repositories.
- ADR 0002 records Homebrew for general Mac tools, Volta for Node, Corepack for pnpm, uv for Python, and Docker Desktop for containers; it rejects `mise` and Homebrew-managed language runtimes for this tutorial.
- ADR 0003 records static checks, many unit/component tests, fewer integration tests, and thin web/iOS E2E coverage; it states web E2E will run on pull requests and iOS E2E on `main` when those suites exist.

- [ ] **Step 8: Run documentation, contract, doctor, and link checks**

Run:

```bash
pnpm lint:markdown
pnpm lint:links
bats tests/repository_contract.bats
bats tests/doctor
```

Expected: all commands pass. If an authoritative external URL is temporarily unavailable, verify it manually before adding a narrow, documented ignore; never disable all external checking.

- [ ] **Step 9: Commit the teaching documentation**

Run:

```bash
git add README.md docs/setup docs/curriculum-roadmap.md docs/decisions tests/repository_contract.bats
git commit -m "docs: add self-guided mac setup curriculum"
```

### Task 8: Add the assembled-doctor integration test and CI workflow

**Files:**

- Create: `tests/doctor/integration.bats`
- Create: `.github/workflows/quality.yml`
- Modify: `package.json`

**Interfaces:**

- Consumes: root quality scripts, complete doctor, fake-command helper, and committed lockfile.
- Produces: `pnpm quality`; GitHub checks named `static`, `doctor-unit`, and `doctor-macos-integration`.

- [ ] **Step 1: Write the failing assembled-doctor test**

Create `tests/doctor/integration.bats`. In `setup`, copy the repository contract files to `$BATS_TEST_TMPDIR/repo`, copy `scripts/`, create all fake external commands with successful reference outputs, and set `PATH` to the fake directory plus `/usr/bin:/bin`. The test is:

```bash
@test "assembled doctor passes a complete reference fixture" {
  run "$FIXTURE_ROOT/scripts/doctor"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASS [platform.macos]"* ]]
  [[ "$output" == *"PASS [xcode.simulator]"* ]]
  [[ "$output" == *"PASS [python.runtime]"* ]]
  [[ "$output" == *"PASS [github.auth]"* ]]
  [[ "$output" == *"0 failed"* ]]
}
```

- [ ] **Step 2: Run the integration test to expose fixture or assembly gaps**

Run: `bats tests/doctor/integration.bats`

Expected: FAIL until every required fake command, expected repository file, and module output is present in the fixture.

- [ ] **Step 3: Complete only the missing integration seams**

Add successful fake outputs for `sw_vers`, `uname`, `xcode-select`, `xcodebuild`, `xcrun`, `brew`, `git`, `volta`, `node`, `corepack`, `pnpm`, `uv`, `docker`, and `gh`. Copy all required repository files. Do not relax production checks to make the fixture pass.

- [ ] **Step 4: Add one root quality command**

Add this script to `package.json`:

```json
"quality": "pnpm lint && pnpm test"
```

Run: `pnpm quality`

Expected: Markdown, links, ShellCheck, repository contracts, doctor unit tests, and the integration test all pass.

- [ ] **Step 5: Create the SHA-pinned GitHub Actions workflow**

Create `.github/workflows/quality.yml`:

```yaml
name: quality

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b # v7.0.1
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: 24.20.0
      - run: corepack enable
      - run: corepack prepare pnpm@11.25.0 --activate
      - run: sudo apt-get update && sudo apt-get install -y shellcheck
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint

  doctor-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b # v7.0.1
      - run: sudo apt-get update && sudo apt-get install -y bats
      - run: bats tests/repository_contract.bats tests/doctor/core.bats tests/doctor/platform_xcode.bats tests/doctor/tooling.bats

  doctor-macos-integration:
    runs-on: macos-15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b # v7.0.1
      - run: brew install bats-core
      - run: bats tests/doctor/integration.bats
```

- [ ] **Step 6: Validate workflow syntax and run the complete local suite**

Run:

```bash
pnpm quality
git diff --check
```

Expected: all checks pass and `git diff --check` prints nothing.

- [ ] **Step 7: Commit continuous integration**

Run:

```bash
git add .github/workflows/quality.yml tests/doctor/integration.bats package.json pnpm-lock.yaml
git commit -m "ci: verify phase 0 quality pyramid"
```

### Task 9: Safely publish the reviewed feature, run acceptance, and create the Phase 0 checkpoint

**Files:**

- No new files expected; update documentation only if acceptance exposes an inaccurate command or remediation.

**Interfaces:**

- Consumes: a clean, fully tested, final-review-approved `feature/phase-00-environment` HEAD, authenticated GitHub CLI, and the prepared reference Mac.
- Produces: public `https://github.com/tylervsd/expo-fastapi-todo`, passing GitHub Actions, a passing local doctor, and the pushed annotated tag `phase-00-environment`.

This task is deferred until final-review approval. It must never publish, push, or merge the stale local `main` history. The repository-creation action and the object-publication action are deliberately separate; this implementation pass performs neither action.

- [ ] **Step 1: Verify the exact publication target and local state**

Run:

```bash
gh auth status --hostname github.com
gh repo view tylervsd/expo-fastapi-todo >/dev/null 2>&1; test $? -ne 0
test "$(git branch --show-current)" = 'feature/phase-00-environment'
reviewed_head='<full commit SHA approved by final whole-branch review>'
git merge-base --is-ancestor "$reviewed_head" HEAD
test "$reviewed_head" = "$(git rev-parse HEAD)"
if git merge-base --is-ancestor main "$reviewed_head"; then
  printf '%s\n' 'refusing publication: stale local main is an ancestor of the reviewed feature HEAD' >&2
  exit 1
fi
git status --short
pnpm quality
```

Expected: authentication succeeds; the target repository does not already exist; the current branch is `feature/phase-00-environment`; the final review's recorded commit is the current reviewed HEAD and belongs to its ancestry; stale local `main` is not an ancestor; `git status --short` is empty; quality passes.

- [ ] **Step 2: Create the public repository without publishing Git objects**

Run:

```bash
gh repo create tylervsd/expo-fastapi-todo \
  --public \
  --source=. \
  --remote=origin \
  --description="A phased tutorial for production-shaped Expo and FastAPI development."
```

Expected: the repository URL is `https://github.com/tylervsd/expo-fastapi-todo`, visibility is public, and `origin` is configured. This step creates the remote only; it does not publish a branch, tag, or stale local `main` history.

- [ ] **Step 3: Publish exactly the reviewed feature HEAD as remote `main`**

Run:

```bash
test "$(git rev-parse HEAD)" = "$reviewed_head"
git push --set-upstream origin HEAD:refs/heads/main
```

Expected: exactly the approved current `HEAD` is published as `origin/main`. Never run `git push origin main`, `git push --set-upstream origin main`, or `git merge main` for this publication; the local `main` ref is stale and must remain unpublished.

- [ ] **Step 4: Wait for GitHub Actions and inspect failures if any**

Run:

```bash
run_id=$(gh run list --workflow quality.yml --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --exit-status
```

Expected: `static`, `doctor-unit`, and `doctor-macos-integration` pass. If a job fails, inspect with `gh run view --log-failed`, make the narrowest tested correction, commit it, push, and wait for the replacement run.

- [ ] **Step 5: Run the manual reference-Mac acceptance journey**

Run:

```bash
./scripts/doctor
xcrun simctl boot 'iPhone 17 Pro' 2>/dev/null || true
xcrun simctl bootstatus 'iPhone 17 Pro' -b
docker run --rm hello-world
docker compose version
gh auth status --hostname github.com
```

Expected: the doctor reports zero failures; the simulator boots; Docker's disposable smoke container exits successfully; Compose and GitHub authentication succeed. Confirm that no credential value appears in doctor output.

- [ ] **Step 6: Create and push the checkpoint only after acceptance passes**

Run:

```bash
git status --short
git tag -a phase-00-environment -m "Phase 0: verified Mac developer environment"
git push origin phase-00-environment
gh repo view tylervsd/expo-fastapi-todo --json nameWithOwner,visibility,defaultBranchRef
```

Expected: `git status --short` is empty before tagging; GitHub reports `tylervsd/expo-fastapi-todo`, `PUBLIC`, and default branch `main`; the annotated tag exists on the accepted commit.
