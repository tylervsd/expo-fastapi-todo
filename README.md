# Expo + FastAPI Todo Tutorial

## What this project teaches

This is a production-shaped, local-first tutorial for building a todo application with Expo, React Native, FastAPI, and PostgreSQL. It teaches how a feature moves from an approved specification through implementation, tests, an explanatory guide, and an annotated Git checkpoint.

Phase 0 establishes the developer environment and quality bar that Phase 1 uses as its prerequisite foundation. Phase 1 introduces the first runnable application boundary, and later phases add feature slices one vertical slice at a time. Phase 4 adds durable PostgreSQL persistence to the existing API contract, Phase 5 completes CRUD with one resilient TanStack Query cache, and Phase 6 gives every todo an owner behind username/password sign-in.

## Who this is for

This tutorial is for developers who know basic Git and TypeScript or Python and want a guided path through a cross-platform application. It is also suitable for a mixed team: the setup guide explains what each tool owns, why it is present, and how to recover safely when a check fails.

## Current checkpoint

The current implementation on `main` includes **Phase 11 — interactive AI workflows with assistant-ui and AG-UI**, merged in PR #8 (`e99eca0`). Phases 7–9 add guided todo creation, server-directed screens, and owner-scoped discovery/resume with revision checks and idempotent request recovery. Earlier numbered guides and checkpoints remain available.

Implementation and acceptance are distinct. [Guide 09](docs/guides/09-workflow-reliability.md#phase-9-acceptance-record) records observed web acceptance and partial iOS Simulator acceptance. The iOS record includes quick-add, sign-in, the declined-breakdown path, cancellation, restart/resume, and lost-action retry; several scenarios remain unexercised, including the full breakdown path, lost-start/confirmation responses, competing revisions, and accessibility. Consult the guide for the exact observations and gaps. Earlier acceptance records in [Guide 06](docs/guides/06-auth.md#phase-6-acceptance-record), [Guide 07](docs/guides/07-backend-workflows.md#phase-7-acceptance-record), and [Guide 08](docs/guides/08-server-directed-ui.md#phase-8-acceptance-record) are not retroactively marked complete by the merge.

**Phase 10 is merged; its documented acceptance gaps remain open.** [Guide 10](docs/guides/10-llm-assisted-planning.md) records the 398-test PostgreSQL-backed API suite, 375-test mobile suite, quality gate, and one successful `openrouter/free` structured-output smoke on 2026-09-10. Interactive web and iOS acceptance rows remain unobserved there.

**Phase 11 is merged, with the acceptance follow-up included in this revision.** The follow-up (`61fb30c`) fixes validation of assistant-ui's opaque run IDs and records interactive acceptance. [Guide 11](docs/guides/11-agentic-ui.md#9-acceptance-record) records 501 passing API tests, 522 passing mobile tests, and 14 live OpenRouter calls. Web birthday/hiking and iOS birthday flows completed with edited/removable suggestions and explicit confirmation. Cancellation and sign-out passed on both platforms using controlled delays. Some live responses were invalid and required explicit retries; full assistive-technology and manually injected malformed-tool checks remain unobserved.

The [Phase 11 spec](docs/superpowers/specs/2026-09-10-agentic-ui-design.md) and [implementation plan](docs/superpowers/plans/2026-09-10-agentic-ui.md) describe the direct connection from assistant-ui to the existing FastAPI server over AG-UI, with no additional backend service. **Next curriculum phase: Phase 12 — cross-platform E2E.** A CI security baseline precedes it, followed by the provisional Google Cloud, Cloudflare Pages, Terraform, and startup-services track in Phases 13–27. Phase 11 acceptance does not retroactively close earlier guides' acceptance gaps.

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

Clone the repository after the browser bootstrap, then follow [the linear macOS setup guide](docs/setup/macos.md). It installs the declared tools in ownership order, verifies each layer, and links every doctor failure to a stable [troubleshooting entry](docs/setup/troubleshooting.md). Once Phase 0 setup is complete, review the [Phase 1 project foundation guide](docs/guides/01-project-foundation.md), [Phase 2 local todo guide](docs/guides/02-local-todo.md), and [Phase 3 API vertical slice guide](docs/guides/03-api-vertical-slice.md), then continue with the [Phase 4 persistence guide](docs/guides/04-persistence.md), the [Phase 5 CRUD server-state guide](docs/guides/05-crud-server-state.md), and the [Phase 6 auth guide](docs/guides/06-auth.md). Continue with [Phase 7 workflows](docs/guides/07-backend-workflows.md), [Phase 8 server-directed screens](docs/guides/08-server-directed-ui.md), [Phase 9 reliability](docs/guides/09-workflow-reliability.md), [Phase 10 LLM-assisted planning](docs/guides/10-llm-assisted-planning.md), and [Phase 11 agentic UI](docs/guides/11-agentic-ui.md) for the current merged application. [Phase 12 cross-platform E2E](docs/guides/12-cross-platform-e2e.md) is in progress on its branch with local acceptance green and CI pending.

The repository's `scripts/doctor` command is read-only. It inspects versions, paths, availability, and authenticated state; it does not install software, accept licenses, modify shell profiles, boot simulators, start Docker, or print credentials.

## Curriculum roadmap

See the [provisional curriculum roadmap](docs/curriculum-roadmap.md) for the 28 phases (0–27). Each phase gets an approved spec before implementation, so later details can be refined without hiding the boundary between decisions and code.

Phases 7–9 are merged and provide backend workflow modeling, server-directed screens, and reliable resumption through one guided-todo creation feature. Phase 10 is merged with automated verification and a provider smoke; its documented interactive acceptance remains incomplete. Phase 11 is merged and adds interactive AI workflows with assistant-ui and AG-UI; its acceptance results and remaining limits are described above. Cross-platform E2E follows in Phase 12. Phases 13–27 then progress from Google Cloud foundations through Cloud Run, IAM, Secret Manager, Cloud SQL, Cloudflare Pages, Terraform, delivery, async work, observability, KMS, recovery, object storage, events, analytics, and push notifications. A2UI remains an optional later exercise in declarative UI composition. These future phases are planned curriculum additions, not implemented functionality or completed guides.

## Testing strategy

Phase 0 establishes the testing pyramid's foundation, and later phases apply it across the application and database boundaries:

- Static checks are broad and fast: Markdown, links, ShellCheck, and repository contracts.
- Unit and component tests will be the largest application layer. They should cover parsing, state transitions, validation, accessibility behavior, and rendering without requiring external services.
- Integration tests are fewer and verify the real PostgreSQL repository and API boundaries plus assembled doctor behavior.
- End-to-end tests are thin and reserved for critical journeys. Once those suites exist, web E2E runs on pull requests and iOS Simulator E2E runs on `main`.

The pyramid is a guide to feedback speed and confidence, not a ban on a useful test at another layer. Every later phase states its layer in its approved spec.

## License

This tutorial is released under the [MIT License](LICENSE).
