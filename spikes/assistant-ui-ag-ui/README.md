# assistant-ui + AG-UI compatibility spike

Validated September 10, 2026 in `codex/phase-11-agentic-ui`. This is an isolated
fixture demo, not the Phase 11 implementation. App dependencies are unchanged.
No OpenRouter calls, API keys, database access, or hosted assistant-ui service.

## Finding

Recommend assistant-ui + AG-UI for Phase 11. React Native components and the
AG-UI runtime talk directly to a Python FastAPI streaming endpoint. Node is
needed for Expo tooling, not as a deployed backend service.

Tested versions (npm lockfile included):

| Package | Version | Published license |
| --- | --- | --- |
| @assistant-ui/react-native | 0.1.40 | MIT |
| @assistant-ui/react-ag-ui | 0.0.58 | MIT |
| @ag-ui/client | 0.0.59 | MIT |
| Expo | 57.0.19 | MIT |
| React / React Native | 19.2.3 / 0.86.3 | MIT |

The three candidate packages declare MIT in their published package metadata.
This direct integration uses no cloud account, runtime license key, or
CopilotKit development-only agent registration. Pin versions; the adapter and
native package still have pre-1.0 versions.

## Observed checks

- Expo web: native primitives rendered through React Native Web.
- iOS 26.5, iPhone 17 Pro simulator, Expo Go 57.0.9: native form rendered.
- On both: authenticated request → TOOL_CALL events → clarification form →
  addToolResult → automatic second POST with role=tool → streamed response.
- On both: partial text appeared before the fixture's delayed second chunk.
- Web and iOS cancellation stopped the delayed chunk from appearing.
- Fixture check: missing authorization rejected with 401; missing required
  envelope fields rejected with 422; tool event order and continuation passed.
- TypeScript check and final web/iOS production bundle exports passed.

Native startup initially failed because AG-UI's UUID dependency expected
`crypto.getRandomValues`. `polyfills.ts`, imported first by `index.ts`, supplies
it with `expo-crypto`, already present in our real app. No streaming fetch or
TextEncoder polyfill was required on this tested Expo SDK.

## Run again

From this directory:

```sh
npm ci --ignore-scripts
npx tsc --noEmit
# Use the existing app's Python environment or one with fastapi, uvicorn, httpx:
python check_server.py
python -m uvicorn server:app --port 8001
# In another terminal:
npx expo start --port 8082
```

Open web at localhost:8082, or use Expo Go in the iOS simulator. The fixture
uses a public, hardcoded test token, not a secret. Physical devices need a
reachable host address instead of loopback. Run “Plan birthday party”, enter
an answer, and submit. “Test slow stream” allows ten seconds to cancel.

## Implications for Phase 11

- Use `@assistant-ui/react-native` UI/provider and `useAgUiRuntime` with an
  `HttpAgent` pointed at the existing FastAPI server.
- Render a small allowlist of native tool cards; this is tool-driven UI, not
  arbitrary model-generated layouts or A2UI rendering.
- Keep workflow ownership, revisions, idempotency, validation, and todo
  confirmation in the existing backend. Client tool results are untrusted input.
- Integrate real session authentication and existing workflow endpoints during
  implementation. The fixture does not validate those integrations.
- Android, physical devices, production builds/deployment, token refresh,
  reconnection, and real-model behavior remain untested.
- The [Phase 11 spec](../../docs/superpowers/specs/2026-09-10-agentic-ui-design.md)
  and [implementation plan](../../docs/superpowers/plans/2026-09-10-agentic-ui.md)
  adopt this stack; application integration remains pending.

Official references:

- <https://www.assistant-ui.com/docs/runtimes/ag-ui/quickstart>
- <https://www.assistant-ui.com/docs/react-native/primitives>
- <https://docs.expo.dev/versions/v57.0.0/sdk/crypto/>
- <https://github.com/assistant-ui/assistant-ui>
- <https://github.com/ag-ui-protocol/ag-ui>
