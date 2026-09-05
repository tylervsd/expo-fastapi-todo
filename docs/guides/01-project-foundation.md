# Phase 1: project foundation

This phase gives the tutorial its first runnable application boundary. You will run an Expo TypeScript app in a browser or the reference iOS Simulator, run FastAPI in a second terminal, and use the app to check the API health contract. The screen has no todo data or persistence yet; it teaches package ownership, a browser CORS boundary, explicit connection states, and a repeatable quality gate.

## Package ownership and outcome

The repository root owns the pnpm workspace, JavaScript installation, and quality commands. `apps/mobile` owns the Expo web and iOS app. `apps/api` is an independent uv-managed Python project that owns FastAPI, Uvicorn, and its tests. The two development commands are separate visible host processes, so keep their terminals and logs available while diagnosing a connection.

The API exposes one side-effect-free endpoint:

```text
GET http://127.0.0.1:8000/health
```

A healthy response is HTTP `200` with exactly `{"status":"ok"}`. It has no authentication, parameters, request body, database, or other side effects.

## Prerequisites

Complete the [Phase 0 macOS setup guide](../setup/macos.md) first. It establishes the reference platform, Node.js `24.20.0`, pnpm `11.25.0`, Python `3.14.7`, uv, Xcode, and the iOS 26 Simulator. Use the [Phase 0 troubleshooting guide](../setup/troubleshooting.md) when a prerequisite check fails.

This phase accepts the browser target and the designated iPhone 17 Pro iOS Simulator. Android and physical devices are outside this phase's acceptance boundary.

## Install dependencies and configure the client

Run these commands from the repository root:

```bash
pnpm install
uv sync --project apps/api --frozen --python 3.14.7
cp apps/mobile/.env.example apps/mobile/.env.local
```

The copied local file contains:

```dotenv
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

Any variable prefixed with `EXPO_PUBLIC_` is bundled into the client and visible to users. Treat it as public configuration: it must never contain a password, token, private key, or other secret.

## Start the two processes

Open two terminals at the repository root. Start FastAPI first so the initial health check can complete:

Terminal 1 — API:

```bash
pnpm dev:api
```

This binds FastAPI to `127.0.0.1:8000`.

Terminal 2 — Expo:

```bash
pnpm dev:mobile
```

Expo uses the stable web origin `http://localhost:8081`. In the interactive Expo terminal, press `w` to open the web target or press `i` to open Expo Go in the iOS Simulator. On macOS, `i` is the standard Expo shortcut. If host automation blocks the shortcut, keep Metro running or restart it with the same `pnpm dev:mobile` command, then open Expo Go directly in the Simulator and use the development server URL shown by Metro.

## Read the connection states

When the app opens, it starts in **Connecting** and makes one health request. A successful HTTP `200` response with the exact JSON body changes the screen to **Connected**. The screen offers **Retry** after Connected so you can check the service again manually.

A network failure, five-second timeout, non-`200` response, invalid JSON, or unexpected response body changes the screen to **Unavailable** with a short safe explanation such as `Could not reach the API.` or `The API check timed out.`. **Retry** starts exactly one new request and is unavailable while Connecting. The app does not poll, retry automatically, back off, or refresh in the background.

If the API stops after the screen is Connected, the screen stays Connected until you select Retry. On Retry, observe Connecting and then Unavailable. After the API is running again, select Retry once more and observe Connecting followed by Connected.

## Diagnose the API directly

From a third terminal, or after stopping the Expo command, call the endpoint directly:

```bash
curl http://127.0.0.1:8000/health
```

The response should be exactly:

```json
{"status":"ok"}
```

This direct check confirms the FastAPI process and route. It helps isolate a service problem, but it does not replace the browser or iOS recovery journey because those targets also exercise the mobile client and its visible states.

## Understand browser CORS

The browser page runs at the exact origin `http://localhost:8081`, and FastAPI grants CORS permission to that origin for the health request. The origin includes the scheme, host, and port: `http://127.0.0.1:8081` is a different origin from `http://localhost:8081` and is not an equivalent substitute. FastAPI does not use a wildcard origin. iOS uses the same API URL and response contract but does not rely on browser CORS enforcement.

## Run the quality checks

The aggregate quality gate runs every focused check in order:

```bash
pnpm quality
```

You can run the focused checks while working on one layer:

```bash
pnpm lint
pnpm test
pnpm lint:mobile
pnpm lint:api
pnpm typecheck
pnpm test:mobile
pnpm test:api
pnpm build:web
```

The mobile tests use controlled health-check outcomes and do not start FastAPI. The API tests run in-process and verify the exact health and CORS contracts. `pnpm build:web` performs a non-interactive Expo web export; it is a build compatibility check, not browser end-to-end testing.

## Recover from common local failures

### Port conflicts

The documented ports are part of the boundary. Find the process listening on each port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:8081 -sTCP:LISTEN
```

Identify the process and confirm that it is one you own before stopping it. Stop the identified process with its reported PID, for example:

```bash
kill <PID>
```

Then rerun the matching root command. Do not accept another port as a workaround: changing the Expo port changes the browser origin and changing the API port changes the client URL and documented contract.

### Stale Metro cache or client configuration

If the app loads stale JavaScript or behaves as though the environment file changed but the URL did not, stop the Metro process you own and restart Expo with its cache cleared:

```bash
pnpm --dir apps/mobile start --port 8081 --clear
```

If needed, recopy the example configuration and restart Metro:

```bash
cp apps/mobile/.env.example apps/mobile/.env.local
pnpm --dir apps/mobile start --port 8081 --clear
```

Keep `EXPO_PUBLIC_API_URL=http://127.0.0.1:8000` in the local file and never put secrets in it.

## Manual recovery journey

Run this exact journey on both the browser target and the designated iOS Simulator:

1. Start FastAPI and Expo in separate terminals.
2. Open the app and observe Connecting followed by Connected.
3. Stop FastAPI, select Retry, and observe Unavailable with a short explanation.
4. Restart FastAPI, select Retry, and observe Connecting followed by Connected.

Calling `/health` directly may aid diagnosis, but it does not replace either journey. Browser and simulator end-to-end automation are deferred to a later phase.

## Phase 1 acceptance record

| Target | Date | Runtime | Connected | API stopped + Retry → Unavailable | API restarted + Retry → Connected |
| --- | --- | --- | --- | --- | --- |
| Web | 2026-09-04 | `http://localhost:8081` | ☑ | ☑ | ☑ |
| iOS Simulator | 2026-09-04 | iPhone 17 Pro, iOS 26.5, Expo Go version: 57.0.9 | ☑ | ☑ | ☑ |
