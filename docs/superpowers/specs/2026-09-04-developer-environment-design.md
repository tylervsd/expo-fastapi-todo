# Phase 0: Mac Developer Environment Design

**Status:** Approved  
**Date:** 2026-09-04  
**Repository:** `tylervsd/expo-fastapi-todo`  
**Checkpoint tag:** `phase-00-environment`

## Purpose

This phase establishes a reproducible development environment for a self-guided tutorial that teaches production-shaped React Native and FastAPI practices. It prepares the reference Mac, creates the public teaching repository, explains which tool owns each part of the environment, and gives learners a read-only way to diagnose setup problems.

The phase deliberately stops before either application is scaffolded. Expo, FastAPI, PostgreSQL, and product features enter in later, independently designed phases.

## Audience and teaching model

The curriculum serves a mixed audience:

- Newer full-stack developers follow a linear path with explanations, commands, expected output, and troubleshooting.
- Experienced web developers can use the reference sections, decision records, and verification commands without reading every introductory explanation.

The overall project is production-shaped and local-first. Each phase has its own approved spec, implementation plan, tests, explanatory guide, and Git checkpoint tag. The repository evolves on `main`; permanent per-phase branches and duplicated phase repositories are not used.

## Reference platform

Phase 0 officially supports the maintainer's current development Mac rather than promising general macOS compatibility.

| Property | Design-time state |
| --- | --- |
| Operating system | macOS 26.6.2 (build 25G83) |
| Architecture | Apple Silicon (`arm64`) |
| Xcode | Full Xcode absent; Command Line Tools selected |
| Git | Apple Git 2.50.1 |
| Homebrew | Absent |
| Node.js | 22.17.1 installed; project will move to Node 24 LTS |
| Corepack | 0.33.0 |
| Python | macOS system Python 3.9.6; never used or modified by the project |
| uv | 0.12.1, Apple Silicon build |
| Docker and Compose | Absent |
| GitHub CLI | Absent |

Other Macs may work, but support notes for Intel Macs or older macOS releases are outside this phase. The guide states this boundary prominently rather than implying unverified portability.

## Goals

1. Prepare the reference Mac for Expo development on the web and iOS and for local FastAPI/PostgreSQL development in later phases.
2. Establish explicit ownership and repository-level version pins for Node, the JavaScript package manager, and Python.
3. Create a public, MIT-licensed repository under the `tylervsd` GitHub account.
4. Provide a linear, resumable setup guide with a focused verification after every major installation.
5. Provide a modular, read-only doctor command with actionable pass, warning, and failure output.
6. Establish documentation and test-quality checks in GitHub Actions.
7. Preview the curriculum while keeping later phase designs intentionally provisional.

## Non-goals

Phase 0 does not:

- Scaffold an Expo application or select application UI libraries.
- Scaffold FastAPI or select its persistence architecture.
- Start PostgreSQL or define application data models.
- Implement todo behavior, API endpoints, authentication, or generated API clients.
- Implement web or iOS application end-to-end tests.
- Support Android, Windows, Linux, Intel Macs, or older macOS releases.
- Deploy an application or create paid cloud infrastructure.
- Automatically install system software or rewrite shell configuration.

## Selected setup approach

The environment uses explicitly layered, ecosystem-native tools:

- **Xcode:** installed as the full Apple application and selected with `xcode-select`; owns the iOS SDK, simulator runtime, and native build tools.
- **Homebrew:** owns general Mac command-line utilities declared in a `Brewfile`, including GitHub CLI, ShellCheck, and Bats Core.
- **Volta:** installs and selects the repository's Node 24 LTS patch version.
- **Corepack:** activates the exact `pnpm` release declared by the root `package.json`.
- **pnpm:** owns JavaScript workspace dependencies and root documentation/test commands.
- **uv:** installs and selects the repository's Python 3.14 patch version and will own Python project dependencies in later phases.
- **Docker Desktop:** supplies the Docker engine and Compose for local infrastructure in later phases.
- **GitHub CLI:** authenticates the maintainer and supports the public GitHub workflow.

This was selected over a unified version manager because separate ownership is easier to teach and avoids overlapping Python responsibilities. It was selected over Homebrew-managed language runtimes because repository-specific versions should not move implicitly with a general system package upgrade.

The exact supported patch releases are recorded once in machine-readable repository configuration during Phase 0 implementation. Documentation links to that configuration instead of copying version strings. Patch upgrades are deliberate maintenance changes with verification; incompatible major or minor changes never happen implicitly.

The macOS system Python remains untouched. All Python commands for this repository go through `uv`.

## Repository structure

Phase 0 produces this documentation and tooling shape:

```text
.github/
  workflows/
    quality.yml
docs/
  curriculum-roadmap.md
  decisions/
  setup/
    macos.md
    troubleshooting.md
  superpowers/
    specs/
      2026-09-04-developer-environment-design.md
scripts/
  doctor
  doctor.d/
tests/
  doctor/
Brewfile
LICENSE
README.md
package.json
pnpm-workspace.yaml
.python-version
```

The root `package.json` exists only to pin Node and `pnpm`, hold documentation/test development dependencies, and expose friendly commands such as `pnpm doctor` and `pnpm test`. It is not an Expo scaffold. The workspace file reserves the future monorepo shape without adding application packages.

## Learner workflow

The setup has two stages so a learner can begin on a Mac that is not yet capable of cloning or running repository scripts.

### Browser-accessible bootstrap

The public README gives the minimal steps needed before cloning:

1. Confirm macOS 26.6.2 and Apple Silicon.
2. Install full Xcode and the designated iOS Simulator runtime.
3. Accept Xcode's license, select the full Xcode developer directory, and verify native tools.
4. Install Homebrew and Git.
5. Clone the public repository.

### Repository-driven setup

After cloning, `docs/setup/macos.md` guides the learner through:

1. Install the declared Homebrew bundle.
2. Install Volta and allow it to provision the pinned Node release.
3. Activate the pinned `pnpm` through Corepack.
4. Use `uv` to provision the pinned Python release without altering system Python.
5. Install and start Docker Desktop.
6. Authenticate GitHub CLI.
7. Run focused checks after each section.
8. Run the complete doctor and perform the manual acceptance test.

Each section explains why the tool exists, which files configure it, what a successful check looks like, and where to find targeted remediation. Steps are safe to resume after interruption.

## Doctor command

### Interface

`scripts/doctor` is an executable POSIX-compatible shell entry point so it can run before Node or project Python is usable. `pnpm doctor` is a convenience alias after Node setup succeeds.

The doctor:

- Prints one concise result per check using `PASS`, `WARN`, or `FAIL`.
- Prints detected versions without printing tokens, credential values, or unrelated environment variables.
- Ends with a summary and remediation references.
- Returns exit code `0` when all required checks pass, and a nonzero exit code when any required check fails.
- Treats optional recommendations as warnings that do not change the success exit code.
- Supports focused checks so guide sections can validate one layer at a time.

### Check modules

Modules under `scripts/doctor.d/` cover:

- macOS version and Apple Silicon architecture
- selected Xcode developer directory, license readiness, and command-line tools
- presence of the designated iOS Simulator runtime and ability to boot a simulator
- Homebrew availability and required formulae
- Git availability
- Volta and the pinned Node version
- Corepack and the pinned `pnpm` version
- `uv` and the pinned non-system Python version
- Docker Desktop daemon reachability
- Docker Compose availability
- GitHub CLI availability and authenticated state
- required repository files and version pins

Detection and presentation are separated so command probes, classification, and remediation text can be tested independently.

## Error handling and safety

The setup guide and doctor follow these rules:

- No hidden `sudo`, unattended system installation, destructive cleanup, or automatic shell-profile rewrite.
- No automatic acceptance of licenses or authentication prompts.
- No modification, replacement, or package installation into macOS system Python.
- No credential values in logs or diagnostic output.
- A missing command produces remediation instead of a shell stack trace.
- A wrong version reports the detected and required version source.
- A stopped Docker daemon is distinct from a missing Docker installation.
- Command Line Tools selected instead of full Xcode has its own remediation.
- An absent Simulator runtime is distinct from a simulator that exists but is not booted.
- GitHub CLI unauthenticated state is distinct from network failure.

The troubleshooting guide groups recovery steps by the same check identifiers emitted by the doctor, giving learners a stable path from failure to explanation.

## Testing strategy

Phase 0 demonstrates the testing pyramid at the level available before application code exists.

### Static foundation

- ShellCheck validates all shell scripts.
- Markdown linting validates documentation structure.
- A link checker validates internal paths and external documentation links.
- A documentation consistency check confirms that referenced commands and files exist.

### Unit layer

The largest test layer uses Bats Core to cover doctor behavior with fake command executables and captured fixtures:

- version parsing and comparison
- required versus optional classification
- pass, warning, and failure aggregation
- stable exit codes
- output formatting
- selection of remediation text
- secret redaction guarantees
- missing, malformed, and unexpected command output

These tests do not require Xcode, Docker, network access, or GitHub authentication.

### Integration layer

A smaller test layer assembles the doctor modules on a standard GitHub-hosted macOS runner. It validates module discovery, process execution, summary behavior, and exit-code propagation without installing software or changing runner state.

### Manual acceptance layer

The single Phase 0 environment journey is run on the reference Mac:

1. Complete the documented setup.
2. Open a fresh terminal.
3. Run the full doctor successfully.
4. Boot the designated iOS Simulator.
5. Confirm the Docker daemon and Compose work with a disposable smoke workload.
6. Confirm authenticated GitHub CLI access without exposing credentials.

Application unit tests, API/database integration tests, browser E2E tests, and iOS Simulator E2E tests are introduced only when the corresponding systems exist. Ultimately, fast checks and web E2E run on pull requests, while iOS Simulator E2E runs on merges to `main` and may also run on a schedule. Standard GitHub-hosted runners are free for this public repository under GitHub's current policy.

## Continuous integration

The Phase 0 `quality.yml` workflow runs on pull requests and pushes to `main`. It performs static checks and doctor unit tests first, then the smaller macOS integration job. Jobs use standard GitHub-hosted runners and pin third-party Actions by full commit SHA for supply-chain control.

The workflow does not attempt to prove that a developer's local Xcode, Docker Desktop, or GitHub authentication is configured; that remains the purpose of the local doctor and manual acceptance test.

## Acceptance criteria

Phase 0 is complete when all of the following are true:

1. `tylervsd/expo-fastapi-todo` exists as a public MIT-licensed GitHub repository with `main` as its default branch.
2. The root README clearly identifies the audience, reference platform, current phase, setup entry point, and provisional roadmap.
3. A learner can complete the browser bootstrap and repository-driven guide in order from a fresh terminal.
4. Full Xcode is selected, its license is accepted, and the documented iOS Simulator can boot.
5. Homebrew and all declared formulae pass verification.
6. Volta selects the repository-pinned Node 24 LTS patch and Corepack activates the repository-pinned `pnpm`.
7. `uv` selects the repository-pinned Python 3.14 patch while macOS system Python remains unchanged.
8. Docker Desktop is running and Docker Compose passes the documented smoke check.
9. GitHub CLI reports an authenticated session for the intended account without exposing credentials.
10. The doctor is read-only, reports actionable results, and returns stable success and failure exit codes.
11. Static, unit, and macOS integration checks pass in GitHub Actions.
12. The manual reference-Mac acceptance journey passes.
13. The completed commit is tagged `phase-00-environment` only after all preceding criteria pass.

## Provisional curriculum roadmap

The roadmap previews these teaching goals. Every later phase is brainstormed and specified before implementation, so phase boundaries may be split, merged, or reordered.

1. **Mac developer environment** — tools, version ownership, verification, and troubleshooting.
2. **Project foundation** — monorepo conventions, Expo on web and iOS, FastAPI health endpoint, local orchestration, and baseline CI.
3. **Local todo experience** — minimal UI, state, forms, accessibility, and React Native component tests without backend complexity.
4. **API contract and vertical slice** — REST semantics, FastAPI validation, OpenAPI generation, typed TypeScript client, and client/API integration tests.
5. **Persistence** — PostgreSQL, SQLAlchemy, Alembic migrations, transactions, and database integration tests.
6. **Complete CRUD and resilient server state** — edit, complete, delete, caching, loading, empty and error states, retries, and justified optimistic updates.
7. **Authentication and authorization** — real users, secure token handling, protected API operations, and per-user todos.
8. **Cross-platform E2E** — critical journeys in a browser and iOS Simulator, with web checks on pull requests and iOS checks on `main`.
9. **Production hardening** — configuration, secrets, structured logging, observability, security checks, deployment concepts, and upgrade maintenance.

Feature specs in later phases include goals, non-goals, user-visible behavior, acceptance criteria, API and data contracts where applicable, error cases, accessibility considerations, and placement within the testing pyramid.

## Sources informing version and platform decisions

- [Expo: Create a project](https://docs.expo.dev/get-started/create-a-project/)
- [Expo: Develop websites](https://docs.expo.dev/workflow/web/)
- [Node.js release status](https://nodejs.org/en/about/previous-releases)
- [Python version status](https://devguide.python.org/versions/)
- [uv: Installing and managing Python](https://docs.astral.sh/uv/guides/install-python/)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
