# Phase 2 Local Todo Experience Design

**Status:** Approved for implementation on 2026-09-05

## Outcome

Phase 2 replaces the default health-check screen with a useful local todo experience shared by web and iOS. A learner can view todos, add a titled todo, toggle it complete or active, and filter the list without running FastAPI.

This phase teaches React state, controlled input, derived views, validation, stable list identity, and accessible interaction. It deliberately keeps the feature in one screen so those ideas remain visible.

## Scope

Phase 2 will:

1. Render the same todo screen through the existing Expo web and iOS app.
2. Start each app mount with an empty list and the **All** filter selected.
3. Add todos from a controlled title field by pressing **Add todo** or submitting from the keyboard.
4. Toggle any todo between active and complete.
5. Filter the visible list by **All**, **Active**, or **Completed**.
6. Cover user-visible state transitions with component tests.
7. Document and manually exercise the journey on web and the reference iOS Simulator.

It will not add persistence, API calls, synchronization, editing, deletion, sorting, dates, priorities, navigation, global context, a reducer, a state library, analytics, or automated browser/iOS end-to-end tests. Reloading or remounting resets the list. The existing health client, health screen, API, and their tests remain as Phase 1 examples, but the health screen is no longer the default route. Phase 2 does not add navigation solely to expose it.

## Component and state design

`apps/mobile/src/TodoScreen.tsx` is the only new product component. It owns:

```typescript
type Todo = { id: string; title: string; completed: boolean };
type TodoFilter = "all" | "active" | "completed";
```

The component keeps `todos`, the draft title, the selected filter, and the current validation message in local React state. A per-mount counter creates IDs such as `todo-1`. Rendering uses the ID as the key, and all mutations find the row by ID. Repeated titles are allowed and remain independently toggleable. New todos append to the list and start active.

The visible list is derived during render:

- **All** shows every todo in insertion order.
- **Active** shows todos whose `completed` value is false.
- **Completed** shows todos whose `completed` value is true.

No second filtered-list state or memoization is needed for this tutorial-sized list. `App.tsx` remains a composition root and renders `TodoScreen` directly.

## Input and validation

The title field is labeled **Todo title**. Submitting applies these rules in order:

1. Trim leading and trailing whitespace.
2. If the result is empty, keep the draft and show **Enter a todo title.**
3. If the trimmed result exceeds 120 characters, keep the draft and show **Todo titles must be 120 characters or fewer.**
4. Otherwise append the todo, clear the draft and any error, and return focus to the title field.

The component enforces the limit on the trimmed value when the user submits; it does not truncate the draft while the user types. Duplicate titles are not an error. A successful submission from either the button or keyboard has identical behavior.

## Visible and accessible behavior

The screen has a **Todos** heading, the labeled title field, **Add todo**, the three filters, and the visible rows. Each row exposes one checkbox control whose accessible name is its title and whose checked state matches completion. The touch target is at least 44 points high. Completed titles use a visual strikethrough in addition to checkbox state, so completion is not conveyed by color alone.

Filter controls are buttons with accessible selected state. The current validation message is announced as an alert. Keyboard submit works on web and iOS, and web buttons support keyboard activation through native React Native Web semantics. The content scrolls when it exceeds the viewport, respects automatic insets, and keeps form controls reachable while the iOS keyboard is open. Every control remains operable through press/tap interaction.

The list displays exactly one contextual empty message when its current view has no rows:

- All: **No todos yet. Add one above.**
- Active: **No active todos.**
- Completed: **No completed todos.**

Changing filters does not alter the underlying todos or draft. Adding under **Completed** preserves that filter and creates an active todo, so the new row remains hidden until the learner selects All or Active. Toggling a row can make it leave the current filtered view immediately. Toggling a completed row from **All** or **Completed** makes it active again.

## Testing and acceptance

React Native Testing Library component tests exercise behavior through labels, roles, text, keyboard submission, and presses. They prove:

- the initial empty state and selected All filter;
- trimming, required-title validation, and the 120-character limit;
- button and keyboard submission, including independent duplicate titles;
- active/complete toggling in both directions;
- All/Active/Completed filtering and each contextual empty state; and
- checkbox checked state, filter selected state, and validation alert semantics.

Existing health client, health screen, API, repository, lint, typecheck, and web-export checks continue to pass. No test starts FastAPI or uses a live browser or simulator.

Manual acceptance runs this journey on `http://localhost:8081` and the designated iPhone 17 Pro iOS Simulator:

1. Open the app and observe the All empty state.
2. Verify whitespace-only input is rejected, then add `Buy milk` by keyboard.
3. Add a second `Buy milk` with the button and confirm both rows are present.
4. Complete one row and verify Active and Completed each show the correct row.
5. Toggle the completed row active again and verify Completed is empty.
6. Reload the app and verify the list resets to the All empty state.

## Acceptance criteria

Phase 2 is complete when:

1. `App.tsx` renders `TodoScreen` on web and iOS without new dependencies.
2. All add, validation, duplicate, toggle, filter, empty-state, keyboard, and accessibility behavior above passes component tests.
3. Todo state is local to `TodoScreen` and resets on remount; no persistence or backend request is introduced.
4. Phase 1 source, tests, API behavior, guide, and checkpoint remain intact.
5. `pnpm quality` and the focused mobile suite pass.
6. The manual journey is recorded successful on web and the reference iOS Simulator in the Phase 2 guide.
7. CI passes and a `gpt-5.6-sol` whole-branch review has no unresolved findings.
8. The annotated `phase-02-local-todo` tag is created on the integrated commit only after automated and manual acceptance succeeds.
