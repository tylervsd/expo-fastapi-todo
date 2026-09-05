# Task 3 report

## Scope

Added the Expo SDK 57 mobile scaffold and the cancellable health client. The
client reads `EXPO_PUBLIC_API_URL` by default, accepts an injected URL,
`fetchImpl`, timeout, and caller `AbortSignal`, and resolves only the exact
`{ status: "ok" }` payload. It maps transport, response, JSON, URL, timeout,
and validation failures to safe `HealthCheckError` messages. Timeout covers
both transport and response body consumption, and all completion paths clear
the timer and caller abort listener. Caller cancellation rejects with an
`AbortError` immediately, including when the injected fetch ignores abort.

The scaffold retains the template's startup scripts and generated assets,
adds the requested lint, typecheck, test, and web export scripts, and ignores
`node_modules`, `.expo`, `dist`, native output, and other generated files.
The test renderer dependency is `test-renderer@1.2.0` as required.

## TDD evidence

RED:

```text
./node_modules/.bin/jest --runInBand src/health/checkHealth.test.ts
FAIL src/health/checkHealth.test.ts
Cannot find module './checkHealth'
```

GREEN:

```text
./node_modules/.bin/jest --runInBand src/health/checkHealth.test.ts
PASS src/health/checkHealth.test.ts
Test Suites: 1 passed, 1 total
Tests:       11 passed, 11 total
```

## Verification

```text
./node_modules/.bin/tsc --noEmit
exit 0

./node_modules/.bin/eslint .
exit 0

CI=1 ./node_modules/.bin/expo install --check
Dependencies are up to date

CI=1 ./node_modules/.bin/expo export --platform web --output-dir dist
Web Bundled ...
Exported: dist
```

The requested `pnpm --dir apps/mobile test ...` wrapper repeatedly tried to
recreate the app link farm and access the registry in this restricted
environment. The direct local binaries above exercised the same configured
Jest, TypeScript, ESLint, and Expo toolchains successfully.

The current Expo config selected ESLint 10.9.1, which is incompatible with
`eslint-plugin-react` from `eslint-config-expo@57.0.2` (`contextOrFilename` was
removed). ESLint was pinned to 9.39.1, the compatible major, and the lockfile
was updated. pnpm also requires the workspace build policy entry
`allowBuilds: unrs-resolver: false` to avoid its interactive ignored-build
prompt; this narrow root change was authorized by the controller.

## Review fix

The first frozen-install review rejected the 57.0.20 graph because its
`@expo/cli@57.0.22`, `expo-modules-core@57.0.16`, `expo-modules-jsi@57.0.8`,
and `expo@57.0.20` entries were younger than the repository's minimum
release-age policy. A clean lockfile rebuild after changing the app requirement
to `expo@57.0.19` selected the controller-approved eligible graph:
`@expo/cli@57.0.21`, `expo-modules-core@57.0.15`, and
`expo-modules-jsi@57.0.7`. No release-age or global security policy was
relaxed.

The previously failing command was:

```text
pnpm install --frozen-lockfile
ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION
@expo/cli@57.0.22, expo-modules-core@57.0.16,
expo-modules-jsi@57.0.8, and expo@57.0.20 were too new
```

After the clean rebuild, the required frozen install and pnpm wrappers passed:

```text
pnpm install --frozen-lockfile
Already up to date

pnpm --dir apps/mobile test --runInBand src/health/checkHealth.test.ts
PASS src/health/checkHealth.test.ts
Test Suites: 1 passed, 1 total
Tests:       11 passed, 11 total

pnpm --dir apps/mobile typecheck
$ tsc --noEmit

pnpm --dir apps/mobile lint
$ expo lint

pnpm --dir apps/mobile exec expo install --check
Dependencies are up to date

pnpm --dir apps/mobile export:web
Web Bundled ...
Exported: dist
```
