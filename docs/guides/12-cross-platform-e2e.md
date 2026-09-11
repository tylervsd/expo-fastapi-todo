# 12 — Cross-platform E2E

> Status: toolchain established (Task 1). Suites, CI, and acceptance are pending.
> Spec: [Phase 12 design](../superpowers/specs/2026-09-11-cross-platform-e2e-design.md) ·
> Plan: [Phase 12 implementation plan](../superpowers/plans/2026-09-11-cross-platform-e2e.md)

## Toolchain (observed 2026-09-11, local macOS host)

| Tool | Observed version | Notes |
| --- | --- | --- |
| Xcode | 26.6 (Build 17F113) | `xcodebuild -version` |
| macOS | 26.6.2 (Build 25G83) | `sw_vers` |
| Simulator runtime | iOS 26.5 (23F77) | `xcrun simctl list runtimes` |
| E2E Simulator device | iPhone 17, UDID `9EA9E5A4-89DB-455F-B82D-4CE20713B629` | Shutdown before build; `run:ios` boots it |
| CocoaPods | 1.17.0 | `pod --version` |
| Java | OpenJDK 26.0.2.1 (Homebrew, `/opt/homebrew/opt/openjdk/bin/java`) | Not on default `PATH`; Maestro 2.10.0 runs with it (one picocli reflective-access warning, harmless) |
| Maestro | 2.10.0 (`~/.maestro/bin/maestro`) | Latest release at time of check (`cli-2.10.0`); pin in CI with `MAESTRO_VERSION=2.10.0` |
| Node / pnpm | 24.20.0 / 11.25.0 | Pins preserved |
| Playwright | 1.63.0 exact (`@playwright/test@1.63.0`, `pnpm exec playwright --version` → `Version 1.63.0`) | Pinned by controller 2026-09-11 |
| Playwright Chromium | chromium-1243 + chromium_headless_shell-1243 (`pnpm exec playwright install chromium`, 2026-09-11) | Headless shell reports `Google Chrome for Testing 153.0.8010.12` |
| Expo / React Native | 57.0.19 / 0.86.3 | Pins preserved |

## Native build (validated)

Prebuild and Release build both succeed with Xcode 26.6 against Expo SDK 57:

```sh
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8001 \
  pnpm --dir apps/mobile exec expo prebuild --platform ios --no-install
EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8001 \
  pnpm --dir apps/mobile exec expo run:ios --configuration Release \
  --device "$E2E_SIMULATOR_UDID" --no-bundler
```

- Generated Xcode project: `apps/mobile/ios/mobile.xcodeproj`, scheme `mobile`
  (`.xcworkspace` appears after pod install, which `run:ios` performs).
- App output: `.../DerivedData/mobile-*/Build/Products/Release-iphonesimulator/mobile.app`.
- Bundle identifier: `dev.codex.fullstack.todo` (set in `apps/mobile/app.json`).
- The Release build launches without Metro and renders the app sign-in screen
  from bundled JavaScript (verified via Simulator screenshot).
- No `apps/mobile/ios/` directory existed before prebuild; generated output is
  git-ignored and is not committed.
- Side effect to be aware of: `expo prebuild` rewrote the `ios`/`android`
  scripts in `apps/mobile/package.json` to `expo run:ios` / `expo run:android`.
  The controller owns that file; keep or revert deliberately.

## Maestro (validated)

- Install (pinned, requires `java` on `PATH` — the installer exits if missing):

  ```sh
  curl -Ls "https://get.maestro.mobile.dev" | MAESTRO_VERSION=2.10.0 bash
  ```

  The variable must be set for the installer (`bash`), not for `curl`.

- Target a Simulator explicitly: `maestro --device "$E2E_SIMULATOR_UDID" test …`
  (also `--udid`; `maestro list-devices` lists local Simulators).
- State reset between independent cases (syntax verified with
  `maestro check-syntax`):

  ```yaml
  appId: dev.codex.fullstack.todo
  ---
  - clearState
  - clearKeychain
  - launchApp
  ```

  `clearState`/`clearKeychain` run before each independent case; the resume
  case relaunches without them. Never erase the whole Simulator.
- Per-run artifacts: `maestro test --test-output-dir <dir> --format JUNIT …`
  (`--flatten-debug-output` and `--debug-output` available for CI layout).

## CI runner selection (for Task 5)

- Selected runner: `macos-26` (high confidence — verified 2026-09-11 against the
  public `actions/runner-images` release list and the pinned `macos-26-arm64`
  readme for image `20260907.0351.1`). It ships **Xcode 26.6 (Build 17F113) as
  default**, plus 26.5–26.0.1 side-by-side, on **macOS 26.6.2 (25G83)** —
  byte-identical to the locally validated toolchain above. iOS 26.5 SDK is
  present (via Xcode 26.5/26.6).
- Java on the image: 11 / 17 / 21 (default) / 25 via `JAVA_HOME_<ver>_arm64`.
  The Maestro installer exits unless `java` is on `PATH`, so Task 5 must export
  one (e.g. Java 17 or 21) onto `PATH` before installing Maestro.
- Do not use the `macos-15` doctor job image (Xcode 16.x family). Repo convention
  (`quality.yml`) pins `runs-on` labels and SHA-pins actions; follow both.
- Residual step (Task 5): verify at runtime with `xcodebuild -version` and
  `xcrun simctl list runtimes` as the first native-job steps, and fail setup
  (never skip) if Xcode 26.x or the iOS 26.5 runtime is absent.
- macOS jobs must provision PostgreSQL 18.6 directly (no Docker service
  containers) and create only the `todo_e2e` role/database.

## Compatibility blockers

None. No Expo Go substitution was needed; no pins were changed.
Loopback API connectivity (`/health` from the Release build) is verified in
Task 2 once the fixture harness exists.
