# Expo + FastAPI Todo Tutorial

## What this project teaches

This is a production-shaped, local-first tutorial for building a todo application with Expo, React Native, FastAPI, and PostgreSQL. It teaches how a feature moves from an approved specification through implementation, tests, an explanatory guide, and an annotated Git checkpoint.

Phase 0 is deliberately about the developer environment and the quality bar. Later phases will add the application one vertical slice at a time.

## Who this is for

This tutorial is for developers who know basic Git and TypeScript or Python and want a guided path through a cross-platform application. It is also suitable for a mixed team: the setup guide explains what each tool owns, why it is present, and how to recover safely when a check fails.

## Current checkpoint

The current checkpoint is **Phase 0 — developer environment**. There is intentionally no application code, Expo app, FastAPI service, database, or application package yet. The repository contains the setup contracts, a read-only doctor, tests for those contracts, and the curriculum that future phases will specify before implementation.

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

Clone the repository after the browser bootstrap, then follow [the linear macOS setup guide](docs/setup/macos.md). It installs the declared tools in ownership order, verifies each layer, and links every doctor failure to a stable [troubleshooting entry](docs/setup/troubleshooting.md).

The repository's `scripts/doctor` command is read-only. It inspects versions, paths, availability, and authenticated state; it does not install software, accept licenses, modify shell profiles, boot simulators, start Docker, or print credentials.

## Curriculum roadmap

See the [provisional curriculum roadmap](docs/curriculum-roadmap.md) for the nine phases. Each phase gets an approved spec before implementation, so later details can be refined without hiding the boundary between decisions and code.

## Testing strategy

Phase 0 demonstrates the testing pyramid before application code exists:

- Static checks are broad and fast: Markdown, links, ShellCheck, and repository contracts.
- Unit and component tests will be the largest application layer. They should cover parsing, state transitions, validation, accessibility behavior, and rendering without requiring external services.
- Integration tests are fewer and verify boundaries such as API, database, and assembled doctor behavior.
- End-to-end tests are thin and reserved for critical journeys. Once those suites exist, web E2E runs on pull requests and iOS Simulator E2E runs on `main`.

The pyramid is a guide to feedback speed and confidence, not a ban on a useful test at another layer. Every later phase states its layer in its approved spec.

## License

This tutorial is released under the [MIT License](LICENSE).
