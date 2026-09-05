# Phase 2: local todo experience

Phase 2 replaces the default health screen with a small local todo experience shared by Expo web and iOS. You can add todos, complete or reactivate them, and filter the list without starting FastAPI. Todo data lives only in the mounted screen, so reloading or remounting intentionally clears it.

The historical Phase 1 health example remains available at the annotated `phase-01-foundation` tag. The Phase 1 source, tests, API, and [project foundation guide](01-project-foundation.md) stay in the repository, but the health screen is no longer the default app.

## Start the app

Complete the [Phase 0 macOS setup guide](../setup/macos.md), then run these commands from the repository root:

```bash
pnpm install --frozen-lockfile
pnpm dev:mobile
```

FastAPI is not required. Expo serves the web target at `http://localhost:8081`; press `w` in the Expo terminal to open it. Press `i` to open the app in the reference iPhone 17 Pro iOS Simulator.

## How the screen works

`TodoScreen` keeps four values in local React state:

- `todos`: todo objects with a stable ID, title, and completed flag.
- `draft`: the current title field value.
- `filter`: the selected `All`, `Active`, or `Completed` view.
- `error`: the current validation message, or no message.

The visible rows are derived from `todos` and `filter` during render. Keeping one source of truth prevents the filtered view from becoming stale when a row is toggled. A per-mount ID counter gives every row an independent identity, so duplicate titles are allowed and can be completed separately.

## Add and validate todos

Press **Add todo** or submit the title field from the keyboard. Submission trims leading and trailing whitespace, then checks the trimmed JavaScript string's `length`:

- An empty result keeps the draft and shows **Enter a todo title.**
- A result longer than 120 JavaScript string characters keeps the draft and shows **Todo titles must be 120 characters or fewer.**
- A valid result appends an active todo, clears the draft and error, and returns focus to the title field.

The field is not truncated while typing. Duplicate titles are valid. The selected filter is preserved after adding: for example, a new active todo added while **Completed** is selected is created successfully but remains hidden until **All** or **Active** is selected.

Each todo row is a checkbox named by its title, with checked state matching completion. Completion is reversible, and completed titles also use strikethrough so the state is not conveyed by color alone. Filter controls expose their selected state, validation is announced as an alert, and every press target is at least 44 points high. The list shows one contextual empty message when its current view has no rows:

- **All:** `No todos yet. Add one above.`
- **Active:** `No active todos.`
- **Completed:** `No completed todos.`

## Test the behavior

Run the focused component suite while working on the todo screen:

```bash
pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx
```

Run the complete repository quality gate before acceptance:

```bash
pnpm quality
```

The component tests cover the empty state, selected filter, trimming, required and 120-character validation, keyboard and button submission, duplicate independence, reversible completion, derived filters, contextual empty states, checkbox state, filter state, and alert semantics. They do not start FastAPI or require a browser or simulator.

## Manual journey

Run this journey on `http://localhost:8081` and then on the designated iPhone 17 Pro iOS Simulator. Confirm keyboard submission, independent duplicate toggles, and comfortable operation of the 44-point controls on each target.

1. Open the app and observe the All empty state.
2. Verify whitespace-only input is rejected, then add `Buy milk` by keyboard.
3. Add a second `Buy milk` with the button and confirm both rows are present.
4. Complete one row and verify Active and Completed each show the correct row.
5. Toggle the completed row active again and verify Completed is empty.
6. Reload the app and verify the list resets to the All empty state.

The journey was observed on both targets on 2026-09-05. On web, a 121-character JavaScript string was rejected, a trimmed 120-character title was accepted, and the DOM exposed checkbox state and filter `aria-pressed` state with Space and Enter activation. On iOS, the software-keyboard Done action submitted the title, and the safe-area full reload, focus, show, type, and hide regression passed after the `SafeAreaView` fix. The core `SafeAreaView` deprecation warning is known; no dependency was added for it.

## Phase 2 acceptance record

Observed accessibility includes native selected state mapped to web `aria-pressed`, checked checkbox state, keyboard activation on web, and Done submission from the iOS software keyboard.

| Target | Date | Runtime | Add + validation | Toggle + filters | Reload resets |
| --- | --- | --- | --- | --- | --- |
| Web | 2026-09-05 | `http://localhost:8081` | ☑ | ☑ | ☑ |
| iOS Simulator | 2026-09-05 | iPhone 17 Pro, iOS 26.5, Expo Go 57.0.9 | ☑ | ☑ | ☑ |
