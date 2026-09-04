# macOS setup

This is a linear, resumable setup for the Phase 0 reference Mac: macOS 26.6.2 on Apple Silicon. Complete each section in order. Commands that install, authenticate, or change local configuration are clearly separated from the read-only doctor checks.

## 1. Xcode 26.6 and iOS 26 Simulator

### Why

Full Xcode owns the iOS SDK, simulator runtime, and native build tools. Command Line Tools alone are not enough for this tutorial.

### Install

Install Xcode 26.6 from the Mac App Store and open it once. In Terminal, run these user-controlled commands; `sudo` may ask for your password and is intentionally not run by the doctor:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -runFirstLaunch
xcodebuild -downloadPlatform iOS
```

### Verify

```bash
xcodebuild -version
xcrun simctl list runtimes | grep 'iOS 26'
xcrun simctl list devices available | grep 'iPhone 17 Pro'
```

Xcode must report 26.6, an iOS 26 runtime must be listed, and an available iPhone 17 Pro must be present. Do not boot a simulator as part of the doctor.

### If it fails

Use [platform.macos](troubleshooting.md#platform-macos), [platform.arch](troubleshooting.md#platform-arch), [xcode.version](troubleshooting.md#xcode-version), [xcode.first-launch](troubleshooting.md#xcode-first-launch), or [xcode.simulator](troubleshooting.md#xcode-simulator), as appropriate. Keep the full Xcode selection and first-launch commands user-controlled; do not reinstall Xcode as a first-line remedy.

## 2. Homebrew and Brewfile

### Why

Homebrew owns the general Mac tools declared by this repository: Bats Core, GitHub CLI, ShellCheck, Volta, and Docker Desktop.

### Install

Read the current official command at [brew.sh](https://brew.sh/), run its interactive installer in Terminal, and follow the printed shell-environment instructions manually. Then install the repository's declared bundle:

```bash
brew bundle --file Brewfile
```

### Verify

```bash
brew --version
brew bundle check --file Brewfile
```

The bundle check should report that all dependencies are satisfied.

### If it fails

See [brew.bundle](troubleshooting.md#brew-bundle). Check the exact Homebrew path and rerun the bundle command. Do not delete Homebrew state or reinstall unrelated formulae to resolve one missing entry.

## 3. Volta and Node 24.20.0

### Why

Volta owns the repository's Node version, keeping Node 24.20.0 stable across fresh shells while Homebrew remains responsible for general command-line tools.

### Install

Add these lines manually to `~/.zprofile`; this guide never rewrites a shell profile automatically:

```bash
export VOLTA_HOME="$HOME/.volta"
export PATH="$VOLTA_HOME/bin:$PATH"
```

Open a fresh login shell and install the pinned Node release:

```bash
volta install node@24.20.0
```

### Verify

```bash
volta --version
volta which node
node --version
```

`node --version` must report `v24.20.0`, and `volta which node` should resolve into Volta's tool image.

### If it fails

See [js.volta](troubleshooting.md#js-volta) or [js.node](troubleshooting.md#js-node). Open a fresh shell after the manual profile edit, and inspect `command -v node` and `volta which node`. Do not automatically rewrite the profile or install a second Node manager.

## 4. Corepack and pnpm 11.25.0

### Why

Corepack activates the exact `pnpm` version declared in the root `package.json`; pnpm then owns JavaScript workspace dependencies and project commands.

### Install

With the Volta-managed Node active, place Corepack's shim in the Volta bin directory and let the package-manager declaration select pnpm:

```bash
corepack enable --install-directory "$VOLTA_HOME/bin"
```

### Verify

```bash
corepack --version
pnpm --version
```

Corepack must be available and pnpm must report `11.25.0`.

### If it fails

See [js.corepack](troubleshooting.md#js-corepack) or [js.pnpm](troubleshooting.md#js-pnpm). Confirm that Node is `v24.20.0`, that `$VOLTA_HOME/bin` is on `PATH`, and that the root `package.json` is the current directory's package manifest. Do not substitute an unpinned global pnpm.

## 5. uv and Python 3.14.7

### Why

uv owns this repository's Python runtime and future Python dependencies. The macOS system Python remains untouched and is never used as the project interpreter.

### Install

Install uv using the current user-controlled instructions in the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/). Do not modify `/usr/bin/python3`. Once `uv` is available, provision the exact project interpreter:

```bash
uv python install 3.14.7
```

### Verify

```bash
uv --version
UV_PYTHON_DOWNLOADS=never uv python find --managed-python 3.14.7
/usr/bin/python3 --version
```

The first Python command must resolve an uv-managed 3.14.7 interpreter, not `/usr/bin` or Homebrew's Python path, and the final command confirms the system interpreter is unchanged.

### If it fails

See [python.uv](troubleshooting.md#python-uv) or [python.runtime](troubleshooting.md#python-runtime). Check `command -v uv`, rerun the exact versioned install, and repeat the no-download lookup. Never install packages into system Python or replace it with a symlink.

## 6. Docker Desktop and Compose

### Why

Docker Desktop supplies the local Docker engine and Compose used by later FastAPI/PostgreSQL phases.

### Install

If the Brewfile cask has just been installed, open Docker Desktop and complete its user-facing first launch:

```bash
open -a Docker
```

Wait for Docker Desktop to report that its engine is running.

### Verify

```bash
docker version
docker compose version
docker info >/dev/null
```

All three commands must exit successfully. The doctor only reads this state; it does not start Docker or mutate Docker data.

### If it fails

See [docker.cli](troubleshooting.md#docker-cli), [docker.daemon](troubleshooting.md#docker-daemon), or [docker.compose](troubleshooting.md#docker-compose). Open Docker Desktop and wait for readiness before retrying. Do not delete Docker data or reinstall the application as a first-line remedy.

## 7. GitHub CLI authentication

### Why

GitHub CLI provides the authenticated workflow for this public repository. Authentication is separate from installation and is always interactive.

### Install

The `gh` executable comes from the Brewfile. Start its browser-based HTTPS login yourself:

```bash
gh auth login --hostname github.com --git-protocol https --web
```

Complete the browser flow without copying a token into a terminal or documentation.

### Verify

```bash
gh --version
gh auth status --hostname github.com
```

The status command must report an authenticated session for `github.com` without printing credential values.

### If it fails

See [github.cli](troubleshooting.md#github-cli) or [github.auth](troubleshooting.md#github-auth). If the doctor reports that `github.com` cannot be reached, restore network connectivity before retrying. Only after connectivity succeeds should an unauthenticated result be remediated with the interactive login. Do not print tokens or copy credential files into the repository.

## 8. Focused doctor checks

### Why

Focused checks provide quick feedback after each setup layer while preserving the same registered IDs used by CI and troubleshooting.

### Install

There is nothing to install. From the repository root, ensure the doctor is executable:

```bash
chmod +x scripts/doctor
```

### Verify

Run the relevant read-only checks; these examples cover the setup layers:

```bash
./scripts/doctor --check platform.macos
./scripts/doctor --check platform.arch
./scripts/doctor --check xcode.version
./scripts/doctor --check brew.bundle
./scripts/doctor --check js.node
./scripts/doctor --check js.pnpm
./scripts/doctor --check python.runtime
./scripts/doctor --check docker.daemon
./scripts/doctor --check github.auth
```

Each command prints one `PASS`, `WARN`, or `FAIL` result and a summary. `scripts/doctor` is read-only; install and authentication actions belong to the earlier sections and are intentionally not part of it.

### If it fails

Follow the anchor printed by the failed result, or use the complete [stable troubleshooting index](troubleshooting.md). A focused run never repairs state, so apply only the safe, explicit remedy in the matching entry and rerun that check.

## 9. Complete doctor

### Why

The complete doctor checks every required platform, tool, service, and repository contract before later phases begin.

### Install

There is nothing to install. Return to the repository root in the fresh shell where Volta, Corepack, uv, Docker, and GitHub CLI are available.

### Verify

```bash
./scripts/doctor
```

All required checks should pass and the summary should report zero failures. After Node and pnpm are ready, `pnpm doctor` is the equivalent convenience command.

### If it fails

Open [troubleshooting.md](troubleshooting.md) and use the exact check ID from the output. Remediate one layer at a time, then rerun either the focused check or the complete doctor. The command does not install, authenticate, boot, start, reset, or rewrite anything.

## 10. Manual acceptance journey

### Why

The doctor verifies availability without causing side effects. A separate manual journey confirms the user-controlled simulator and service actions that the doctor intentionally leaves alone.

### Install

There is nothing to install if the complete doctor passes. Open Simulator yourself and wait for the designated device to finish booting:

```bash
open -a Simulator
xcrun simctl boot 'iPhone 17 Pro' 2>/dev/null || true
xcrun simctl bootstatus 'iPhone 17 Pro' -b
```

### Verify

Confirm the following in the same fresh terminal:

```bash
xcrun simctl list devices available | grep 'iPhone 17 Pro'
docker info >/dev/null
docker run --rm hello-world
docker compose version
gh auth status --hostname github.com
```

The iPhone 17 Pro reaches a finished boot state, Docker's daemon responds, the disposable smoke container exits successfully, Compose is available, and GitHub CLI remains authenticated. This is the Phase 0 manual acceptance journey; no application code exists yet.

### If it fails

Use [xcode.simulator](troubleshooting.md#xcode-simulator), [docker.daemon](troubleshooting.md#docker-daemon), [docker.compose](troubleshooting.md#docker-compose), or [github.auth](troubleshooting.md#github-auth). Start or authenticate the relevant application interactively, then rerun the affected read-only command. Do not reset Docker or delete Docker data, erase simulator data, or expose credentials as a shortcut.
