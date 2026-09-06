# Expo + FastAPI Todo Tutorial

## What this project teaches

This is a production-shaped, local-first tutorial for building a todo application with Expo, React Native, FastAPI, and PostgreSQL. It teaches how a feature moves from an approved specification through implementation, tests, an explanatory guide, and an annotated Git checkpoint.

Phase 0 establishes the developer environment and quality bar that Phase 1 uses as its prerequisite foundation. Phase 1 introduces the first runnable application boundary, and later phases add feature slices one vertical slice at a time. Phase 4 adds durable PostgreSQL persistence to the existing API contract.

## Who this is for

This tutorial is for developers who know basic Git and TypeScript or Python and want a guided path through a cross-platform application. It is also suitable for a mixed team: the setup guide explains what each tool owns, why it is present, and how to recover safely when a check fails.

## Current checkpoint

The current implementation is **Phase 4 — PostgreSQL persistence**. The app loads, creates, completes, and reactivates todos through FastAPI on web and iOS, and committed rows survive API and PostgreSQL container restarts. Guide 04 explains the durable development database, disposable test database, migrations, transactions, recovery, and acceptance journey. Earlier annotated checkpoints and guides remain available. The Phase 4 release checkpoint is created only after integration, passing GitHub CI, and observed local acceptance.

## Reference Mac

Phase 0 officially supports one reference platform:

- macOS **26.6.2**
- Apple Silicon (`arm64`)
- Xcode **26.6**, selected at `/Applications/Xcode.app/Contents/Developer`
- iOS 26 simulator runtime with an available iPhone 17 Pro

Intel Macs, older macOS versions, Android, Windows, and Linux are outside this phase's support boundary. Other Macs may work, but this tutorial does not make an unverified portability promise.

## Before you clone

Use these read-only checks in Terminal before cloning. They are the exact preflight checks used to establish the reference Mac:

```bash
uname -m
sw_vers -productVersion
xcode-select -p
xcodebuild -version
xcrun simctl list devices available
```

The expected architecture is `arm64`, and the expected macOS version is `26.6.2`. Install full Xcode 26.6 from the Mac App Store, open it once, and run these user-controlled setup commands in Terminal:

```bash
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -runFirstLaunch
xcodebuild -downloadPlatform iOS
```

Next, install Homebrew using the current [official installation instructions](https://brew.sh/), open a fresh terminal, and verify `brew --version` and `git --version`. Then verify the selected Xcode, runtime, and device:

```bash
xcodebuild -version
xcrun simctl list runtimes | grep 'iOS 26'
xcrun simctl list devices available | grep 'iPhone 17 Pro'
```

Xcode must report 26.6, an iOS 26 runtime must be listed, and an available iPhone 17 Pro must be present. Once those checks pass, clone the repository and enter it:

```bash
git clone https://github.com/tylervsd/expo-fastapi-todo.git
cd expo-fastapi-todo
```

Only macOS 26.6.2 on Apple Silicon is supported by this Phase 0 guide. If a preflight check fails, resolve it before cloning or continue to [the linear setup guide](docs/setup/macos.md) once the browser bootstrap is complete.

## Continue the guided setup

Clone the repository after the browser bootstrap, then follow [the linear macOS setup guide](docs/setup/macos.md). It installs the declared tools in ownership order, verifies each layer, and links every doctor failure to a stable [troubleshooting entry](docs/setup/troubleshooting.md). Once Phase 0 setup is complete, review the [Phase 1 project foundation guide](docs/guides/01-project-foundation.md), [Phase 2 local todo guide](docs/guides/02-local-todo.md), and [Phase 3 API vertical slice guide](docs/guides/03-api-vertical-slice.md), then continue with the [Phase 4 persistence guide](docs/guides/04-persistence.md) to run the current persisted application.

The repository's `scripts/doctor` command is read-only. It inspects versions, paths, availability, and authenticated state; it does not install software, accept licenses, modify shell profiles, boot simulators, start Docker, or print credentials.

## Curriculum roadmap

See the [provisional curriculum roadmap](docs/curriculum-roadmap.md) for the nine phases. Each phase gets an approved spec before implementation, so later details can be refined without hiding the boundary between decisions and code.

## Testing strategy

Phase 0 establishes the testing pyramid's foundation, and later phases apply it across the application and database boundaries:

- Static checks are broad and fast: Markdown, links, ShellCheck, and repository contracts.
- Unit and component tests will be the largest application layer. They should cover parsing, state transitions, validation, accessibility behavior, and rendering without requiring external services.
- Integration tests are fewer and verify the real PostgreSQL repository and API boundaries plus assembled doctor behavior.
- End-to-end tests are thin and reserved for critical journeys. Once those suites exist, web E2E runs on pull requests and iOS Simulator E2E runs on `main`.

The pyramid is a guide to feedback speed and confidence, not a ban on a useful test at another layer. Every later phase states its layer in its approved spec.

## License

This tutorial is released under the [MIT License](LICENSE).
