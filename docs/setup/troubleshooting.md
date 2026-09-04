# Troubleshooting by check ID

Use the stable check ID printed by `./scripts/doctor` to find a symptom, safe diagnosis, and explicit remediation. The doctor is read-only: it never applies these remedies automatically and never prints credentials.

<a id="platform-macos"></a>

## `platform.macos`

**Symptom:** The doctor reports that the macOS version is unsupported or cannot be determined.

**Likely cause:** The Mac is not running macOS 26.6.2, or `sw_vers` is unavailable.

**Diagnose:** Run `sw_vers -productVersion` and compare the result with `26.6.2`.

**Remediate:** Use a Mac running macOS 26.6.2 for this phase. If the command is missing or errors, resolve the host shell/platform issue and rerun `./scripts/doctor --check platform.macos`. Do not claim support for an unverified OS release.

<a id="platform-arch"></a>

## `platform.arch`

**Symptom:** The doctor reports an unsupported architecture.

**Likely cause:** The Mac is Intel (`x86_64`) rather than Apple Silicon (`arm64`).

**Diagnose:** Run `uname -m`.

**Remediate:** Use an Apple Silicon Mac for this phase, then rerun `./scripts/doctor --check platform.arch`. Do not install translation layers and treat them as satisfying the support contract.

<a id="xcode-version"></a>

## `xcode.version`

**Symptom:** Xcode is missing, the wrong developer directory is selected, or the Xcode version is not 26.6.

**Likely cause:** Command Line Tools are selected instead of full Xcode, or the installed Xcode release differs from the reference.

**Diagnose:** Run `xcode-select -p` and `xcodebuild -version`.

**Remediate:** If full Xcode 26.6 is already installed at `/Applications/Xcode.app`, run `sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer` yourself and rerun `./scripts/doctor --check xcode.version`. Only if diagnosis shows that full Xcode is absent or reports the wrong version should you install or update it through the Mac App Store, open it once, select the developer directory, and rerun the focused check.

<a id="xcode-first-launch"></a>

## `xcode.first-launch`

**Symptom:** Xcode's first-launch check fails.

**Likely cause:** The license or first-launch components have not been accepted and configured.

**Diagnose:** Run `xcodebuild -checkFirstLaunchStatus` and read its exit status; do not pass credentials or logs to the doctor.

**Remediate:** In Terminal, accept the license and complete setup with `sudo xcodebuild -license accept` followed by `xcodebuild -runFirstLaunch`. Rerun `./scripts/doctor --check xcode.first-launch`.

<a id="xcode-simulator"></a>

## `xcode.simulator`

**Symptom:** No available iOS 26 runtime or iPhone 17 Pro device is found.

**Likely cause:** The iOS platform runtime has not been downloaded, or the designated device has not been created.

**Diagnose:** Run `xcrun simctl list runtimes available` and `xcrun simctl list devices available`.

**Remediate:** Run `xcodebuild -downloadPlatform iOS` and use Xcode's Simulator management UI to add an iPhone 17 Pro if it is absent. Rerun `./scripts/doctor --check xcode.simulator`. The doctor only inspects availability; boot the device manually during acceptance. Do not erase simulator data as a first-line remedy.

<a id="brew-bundle"></a>

## `brew.bundle`

**Symptom:** Homebrew is missing or the Brewfile bundle check fails.

**Likely cause:** Homebrew's shell environment is not loaded, or one declared formula/cask is absent.

**Diagnose:** Run `command -v brew` and `brew bundle check --file Brewfile`.

**Remediate:** Install Homebrew using the current [official installer](https://brew.sh/), follow its printed shell-environment instructions manually, and run `brew bundle --file Brewfile`. Rerun `./scripts/doctor --check brew.bundle`. Do not delete Homebrew state or reinstall unrelated packages.

<a id="git-version"></a>

## `git.version`

**Symptom:** Git is missing or its version cannot be detected.

**Likely cause:** The fresh shell cannot find Git, or the executable returned an error.

**Diagnose:** Run `command -v git` and `git --version`.

**Remediate:** Install Git through the approved Xcode Command Line Tools/Homebrew path, open a fresh shell, and rerun `./scripts/doctor --check git.version`. Do not copy a credential or token into diagnostic output.

<a id="js-volta"></a>

## `js.volta`

**Symptom:** Volta is missing.

**Likely cause:** The Brewfile bundle has not been installed, or Volta's manually configured bin directory is not on `PATH`.

**Diagnose:** Run `command -v volta` and inspect `printf '%s\n' "$VOLTA_HOME"` without printing unrelated environment variables.

**Remediate:** Run `brew bundle --file Brewfile`, add `export VOLTA_HOME="$HOME/.volta"` and `export PATH="$VOLTA_HOME/bin:$PATH"` manually to `~/.zprofile`, open a fresh login shell, and rerun `./scripts/doctor --check js.volta`. Do not rewrite the profile automatically.

<a id="js-node"></a>

## `js.node`

**Symptom:** Node is missing, cannot report a version, or is not `v24.20.0`.

**Likely cause:** Volta is not active in this shell, or the pinned Node release has not been installed.

**Diagnose:** Run `command -v node`, `node --version`, and `volta which node`.

**Remediate:** Open a fresh shell after the manual Volta profile setup and run `volta install node@24.20.0`. Rerun `./scripts/doctor --check js.node`. Do not add another version manager or silently substitute a different Node version.

<a id="js-corepack"></a>

## `js.corepack`

**Symptom:** Corepack is missing.

**Likely cause:** The shell is not using the Volta-managed Node installation.

**Diagnose:** Run `node --version`, `command -v corepack`, and `corepack --version`.

**Remediate:** Activate Node 24.20.0 with Volta and run `corepack enable --install-directory "$VOLTA_HOME/bin"`. Open a fresh shell, then rerun `./scripts/doctor --check js.corepack`. Do not use a package manager supplied by a different Node installation.

<a id="js-pnpm"></a>

## `js.pnpm`

**Symptom:** pnpm is missing, cannot report a version, or is not `11.25.0`.

**Likely cause:** Corepack's shim is absent from the Volta bin directory, or the command is being resolved outside the repository's pinned package-manager contract.

**Diagnose:** Run `command -v pnpm`, `corepack --version`, and `pnpm --version` from the repository root.

**Remediate:** With Node 24.20.0 active, run `corepack enable --install-directory "$VOLTA_HOME/bin"`, open a fresh shell, and rerun `./scripts/doctor --check js.pnpm`. Do not substitute an unpinned global pnpm.

<a id="python-uv"></a>

## `python.uv`

**Symptom:** uv is missing.

**Likely cause:** uv has not been installed, or its user-local bin directory is not on `PATH`.

**Diagnose:** Run `command -v uv` and `uv --version`.

**Remediate:** Follow the current [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) manually, open a fresh shell, and rerun `./scripts/doctor --check python.uv`. Do not install Python packages into macOS system Python.

<a id="python-runtime"></a>

## `python.runtime`

**Symptom:** uv cannot find Python 3.14.7, or the project resolves to `/usr/bin/python3`.

**Likely cause:** The uv-managed interpreter has not been provisioned, or a system interpreter was selected.

**Diagnose:** Run `UV_PYTHON_DOWNLOADS=never uv python find 3.14.7` and `/usr/bin/python3 --version`.

**Remediate:** Run `uv python install 3.14.7`, then repeat `UV_PYTHON_DOWNLOADS=never uv python find 3.14.7` and `./scripts/doctor --check python.runtime`. Leave `/usr/bin/python3` unchanged; do not rewrite system paths or install into system Python.

<a id="docker-cli"></a>

## `docker.cli`

**Symptom:** Docker is missing or its version cannot be detected.

**Likely cause:** Docker Desktop is not installed, or the shell cannot find its CLI.

**Diagnose:** Run `command -v docker` and `docker --version`.

**Remediate:** Run `brew bundle --file Brewfile`, open Docker Desktop with `open -a Docker`, and wait for its first launch to finish. Rerun `./scripts/doctor --check docker.cli`. Do not delete Docker data or reinstall as a first-line remedy.

<a id="docker-daemon"></a>

## `docker.daemon`

**Symptom:** Docker is installed, but the doctor cannot reach its daemon.

**Likely cause:** Docker Desktop has not finished starting.

**Diagnose:** Open Docker Desktop and wait for its engine status to become ready. Then run `docker info`.

**Remediate:** Run `docker info` again, followed by `./scripts/doctor --check docker.daemon`. Do not delete Docker data or reset the daemon to address a startup wait.

<a id="docker-compose"></a>

## `docker.compose`

**Symptom:** Docker Compose is unavailable.

**Likely cause:** The Docker CLI is missing or the Compose plugin is not available in Docker Desktop.

**Diagnose:** Run `docker compose version` after `docker --version` succeeds.

**Remediate:** Open Docker Desktop, wait for it to finish starting, and rerun `docker compose version` followed by `./scripts/doctor --check docker.compose`. If the Brewfile bundle is incomplete, rerun `brew bundle --file Brewfile`. Do not delete Docker data.

<a id="github-cli"></a>

## `github.cli`

**Symptom:** GitHub CLI is missing or its version cannot be detected.

**Likely cause:** The Brewfile bundle is incomplete or the fresh shell cannot find `gh`.

**Diagnose:** Run `command -v gh` and `gh --version`.

**Remediate:** Run `brew bundle --file Brewfile`, open a fresh shell, and rerun `./scripts/doctor --check github.cli`. Do not print credential files or tokens while diagnosing.

<a id="github-auth"></a>

## `github.auth`

**Symptom:** GitHub CLI is installed but is not authenticated for `github.com`.

**Likely cause:** Interactive login has not completed, or the session has expired.

**Diagnose:** Run `gh auth status --hostname github.com`.

**Remediate:** Run `gh auth login --hostname github.com --git-protocol https --web` and complete the browser flow. Rerun `./scripts/doctor --check github.auth`. Never print a token, paste one into a log, or commit credential material.

<a id="repository-files"></a>

## `repository.files`

**Symptom:** Required repository files are missing.

**Likely cause:** The command is running outside the repository root, or a checkout is incomplete.

**Diagnose:** Run `pwd`, `git rev-parse --show-toplevel`, and `ls` for the named paths in the doctor output.

**Remediate:** Change to the checked-out repository root and confirm the current branch contains the Phase 0 files, then rerun `./scripts/doctor --check repository.files`. Do not generate placeholder application files; Phase 0 intentionally contains no application code.
