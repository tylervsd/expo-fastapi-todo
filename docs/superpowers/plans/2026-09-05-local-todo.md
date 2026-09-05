# Phase 2 Local Todo Experience Implementation Plan

**Status:** Approved for implementation on 2026-09-05

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default Expo health screen with an accessible in-memory todo experience that supports add, reversible completion, and filtering on web and iOS.

**Architecture:** One `TodoScreen` component owns the draft, todos, filter, and validation state and derives the visible list during render. `App.tsx` only composes the screen; the existing health boundary remains intact as Phase 1 source and tests.

**Tech Stack:** Expo SDK 57.0.19, React 19.2.3, React Native 0.86.3, TypeScript 6.0.3, Jest 29.7.0, React Native Testing Library 14.0.1.

**Spec:** `docs/superpowers/specs/2026-09-05-local-todo-design.md`

## Global constraints

- Implement from a commit descended from annotated tag `phase-01-foundation`.
- Before code changes, read the exact [Expo SDK 57 documentation](https://docs.expo.dev/versions/v57.0.0/) required by `apps/mobile/AGENTS.md`.
- Use the existing `apps/mobile` Expo package for both web and iOS.
- Add no dependency, navigation, persistence, API call, context, reducer, or state library.
- Start with no todos; reload or remount resets todos and the selected filter.
- Trim titles, reject empty titles, limit titles to 120 characters, and allow duplicate titles with independent stable IDs.
- Completion is reversible. Filters are exactly All, Active, and Completed.
- Preserve Phase 1 health source/tests, API source/tests, documentation, and quality checks. `App.tsx` renders `TodoScreen`; do not add a route to the old health screen.
- Use 44-point minimum press targets, checkbox checked state, filter selected state, a validation alert, and keyboard submission.
- Preserve the user's untracked `AGENTS.md`; do not stage or publish it.
- Route plan control and architecture decisions through a `gpt-5.6-sol` controller. Use `gpt-5.6-luna` only for the bounded implementation below; return scope or architecture questions to the controller.

---

## Planned file map and interfaces

- `apps/mobile/src/TodoScreen.tsx` — owns all local todo state and renders the form, filters, empty state, and checkbox rows.
- `apps/mobile/src/TodoScreen.test.tsx` — proves behavior through the public UI.
- `apps/mobile/App.tsx` — renders `TodoScreen` as the app's default screen.
- `apps/mobile/App.test.tsx` — guards the composition root.
- `docs/guides/02-local-todo.md` — learner explanation and web/iOS acceptance record.
- `README.md` — advances the current checkpoint and links the Phase 2 guide.
- `docs/curriculum-roadmap.md` — records that the local todo spec gate was met.

### Task 1: Build the complete local todo interaction

**Files:**

- Create: `apps/mobile/src/TodoScreen.tsx`
- Create: `apps/mobile/src/TodoScreen.test.tsx`

**Interfaces:**

- Consumes: React local state and React Native primitives already installed.
- Produces: `export function TodoScreen(): React.JSX.Element` and the exact visible/accessibility contracts in the spec.

- [ ] **Step 1: Write focused failing interaction tests**

Create `apps/mobile/src/TodoScreen.test.tsx`. Use the repository's async Testing Library calls. Keep one test per behavior group.

```tsx
import { fireEvent, render, screen } from "@testing-library/react-native";
import { TodoScreen } from "./TodoScreen";

it("starts empty with All selected", async () => {
  await render(<TodoScreen />);
  expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "All" })).toHaveAccessibilityState({ selected: true });
});

it("validates, trims, and permits duplicate titles", async () => {
  await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");

  await fireEvent.changeText(input, "   ");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");

  await fireEvent.changeText(input, ` ${"a".repeat(121)} `);
  await fireEvent(input, "submitEditing");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Todo titles must be 120 characters or fewer.",
  );

  await fireEvent.changeText(input, "  Buy milk  ");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getAllByRole("checkbox", { name: "Buy milk" })).toHaveLength(2);
  expect(input).toHaveProp("value", "");
});

it("toggles todos and derives filtered views", async () => {
  await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Write tests");
  await fireEvent(input, "submitEditing");

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveAccessibilityState({ checked: true });
  await fireEvent.press(screen.getByRole("button", { name: "Active" }));
  expect(screen.getByRole("button", { name: "Active" })).toHaveAccessibilityState({ selected: true });
  expect(screen.queryByText("Buy milk")).toBeNull();
  await fireEvent.press(screen.getByRole("checkbox", { name: "Write tests" }));
  expect(screen.getByText("No active todos.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getByRole("button", { name: "Completed" })).toHaveAccessibilityState({ selected: true });
  await fireEvent.changeText(input, "Hidden active todo");
  await fireEvent(input, "submitEditing");
  expect(screen.queryByText("Hidden active todo")).toBeNull();
  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  await fireEvent.press(screen.getByRole("checkbox", { name: "Write tests" }));
  expect(screen.getByText("No completed todos.")).toBeTruthy();
});

it("keeps duplicate rows independent and resets on remount", async () => {
  const view = await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  const duplicates = screen.getAllByRole("checkbox", { name: "Buy milk" });
  await fireEvent.press(duplicates[0]);
  const updated = screen.getAllByRole("checkbox", { name: "Buy milk" });
  expect(updated[0]).toHaveAccessibilityState({ checked: true });
  expect(updated[1]).toHaveAccessibilityState({ checked: false });
  await view.unmount();
  await render(<TodoScreen />);
  expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "All" })).toHaveAccessibilityState({ selected: true });
});
```

- [ ] **Step 2: Run the suite and verify the red state**

```bash
pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx
```

Expected: FAIL because `TodoScreen` does not exist.

- [ ] **Step 3: Implement the single stateful screen**

Create `apps/mobile/src/TodoScreen.tsx` around this complete state/update core, then render it with only React Native primitives and the exact copy from the spec:

```tsx
import { useRef, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";

type Todo = { id: string; title: string; completed: boolean };
type TodoFilter = "all" | "active" | "completed";
const filters: { value: TodoFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
];

export function TodoScreen() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const input = useRef<TextInput>(null);

  const addTodo = () => {
    const title = draft.trim();
    if (!title) return setError("Enter a todo title.");
    if (title.length > 120) return setError("Todo titles must be 120 characters or fewer.");
    const id = `todo-${nextId.current++}`;
    setTodos((current) => [...current, { id, title, completed: false }]);
    setDraft("");
    setError(null);
    input.current?.focus();
  };

  const toggleTodo = (id: string) => setTodos((current) => current.map((todo) =>
    todo.id === id ? { ...todo, completed: !todo.completed } : todo,
  ));
  const visible = todos.filter((todo) =>
    filter === "all" || (filter === "completed" ? todo.completed : !todo.completed),
  );

  const empty = filter === "all"
    ? "No todos yet. Add one above."
    : filter === "active" ? "No active todos." : "No completed todos.";

  return (
    <ScrollView
      automaticallyAdjustKeyboardInsets
      contentInsetAdjustmentBehavior="automatic"
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ flexGrow: 1, padding: 24, gap: 16 }}
    >
      <Text accessibilityRole="header">Todos</Text>
      <TextInput
        ref={input}
        accessibilityLabel="Todo title"
        value={draft}
        returnKeyType="done"
        onChangeText={setDraft}
        onSubmitEditing={addTodo}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Add todo"
        style={{ minHeight: 44, padding: 12 }}
        onPress={addTodo}
      >
        <Text>Add todo</Text>
      </Pressable>
      {error && <Text accessibilityRole="alert">{error}</Text>}
      <View style={{ flexDirection: "row", gap: 8 }}>
        {filters.map(({ value, label }) => (
          <Pressable
            key={value}
            accessibilityRole="button"
            accessibilityState={{ selected: filter === value }}
            style={{ minHeight: 44, padding: 12 }}
            onPress={() => setFilter(value)}
          >
            <Text>{label}</Text>
          </Pressable>
        ))}
      </View>
      {visible.length === 0 && <Text>{empty}</Text>}
      {visible.map((todo) => (
        <Pressable
          key={todo.id}
          accessibilityRole="checkbox"
          accessibilityLabel={todo.title}
          accessibilityState={{ checked: todo.completed }}
          style={{ minHeight: 44, padding: 12 }}
          onPress={() => toggleTodo(todo.id)}
        >
          <Text style={{
            textDecorationLine: todo.completed ? "line-through" : "none",
          }}>
            {todo.title}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}
```

Keep the render literal and local. Do not extract one-use helpers or add a second state model.

- [ ] **Step 4: Prove all component behavior and commit**

```bash
pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx
pnpm --dir apps/mobile typecheck
pnpm --dir apps/mobile lint
git add apps/mobile/src/TodoScreen.tsx apps/mobile/src/TodoScreen.test.tsx
git commit -m "feat: add local todo interactions"
```

Expected: the focused suite, typecheck, and lint pass with no dependency or network setup.

### Task 2: Make the todo screen the app entry point

**Files:**

- Modify: `apps/mobile/App.tsx`
- Create: `apps/mobile/App.test.tsx`
- Verify unchanged: `apps/mobile/src/HealthScreen.tsx`
- Verify unchanged: `apps/mobile/src/HealthScreen.test.tsx`
- Verify unchanged: `apps/mobile/src/health/checkHealth.ts`
- Verify unchanged: `apps/mobile/src/health/checkHealth.test.ts`

**Interfaces:**

- Consumes: `TodoScreen()` from Task 1.
- Produces: the default web/iOS application composition while retaining the complete Phase 1 health example.

- [ ] **Step 1: Write the failing composition test**

```tsx
import { render, screen } from "@testing-library/react-native";
import App from "./App";

it("opens the local todo experience", async () => {
  await render(<App />);
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByLabelText("Todo title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
});
```

- [ ] **Step 2: Run the test and verify the old screen fails it**

```bash
pnpm --dir apps/mobile test --runInBand App.test.tsx
```

Expected: FAIL because `App` still renders the **Project Foundation** health screen.

- [ ] **Step 3: Replace the composition root**

```tsx
import { TodoScreen } from "./src/TodoScreen";

export default function App() {
  return <TodoScreen />;
}
```

Do not delete or relocate any health file.

- [ ] **Step 4: Run the whole automated gate and commit**

```bash
pnpm --dir apps/mobile test --runInBand App.test.tsx
pnpm test:mobile
pnpm lint:mobile
pnpm typecheck
pnpm build:web
git diff --check
git add apps/mobile/App.tsx apps/mobile/App.test.tsx
git commit -m "feat: open todos by default"
```

Expected: the App, todo, preserved health, lint, typecheck, and web-export checks pass. The current diff is clean.

### Task 3: Document and accept the Phase 2 journey

**Files:**

- Create: `docs/guides/02-local-todo.md`
- Modify: `README.md`
- Modify: `docs/curriculum-roadmap.md`

**Interfaces:**

- Consumes: the tested UI and exact behavior from Tasks 1-2.
- Produces: a linear learner guide, an observed web/iOS record, and accurate project entry points.

- [ ] **Step 1: Write the learner guide**

Create `docs/guides/02-local-todo.md` with the phase outcome; the four local state values; why visible todos are derived; trimmed title validation and duplicate-ID behavior; checkbox and filter accessibility; the focused test command; `pnpm quality`; and the six-step manual journey from the spec. Explain that FastAPI is not required and that reloading intentionally clears todos.

End with this unchecked table before performing acceptance:

```markdown
## Phase 2 acceptance record

| Target | Date | Runtime | Add + validation | Toggle + filters | Reload resets |
| --- | --- | --- | --- | --- | --- |
| Web | — | `http://localhost:8081` | ☐ | ☐ | ☐ |
| iOS Simulator | — | iPhone 17 Pro, iOS 26.5, Expo Go 57.0.9 | ☐ | ☐ | ☐ |
```

Update README's current checkpoint to **Phase 2 — local todo experience** and link this guide after the Phase 1 guide. In the roadmap's **Local todo experience** entry, change only the spec-gate sentence to say this phase received its approved spec before implementation; do not renumber headings or change later phases.

- [ ] **Step 2: Verify documentation before manual acceptance**

```bash
pnpm lint:markdown
pnpm lint:links
```

Expected: both documentation checks pass.

- [ ] **Step 3: Run and record the exact journey on both targets**

Run `pnpm dev:mobile`. At `http://localhost:8081`, then on the designated iPhone 17 Pro iOS Simulator, perform all six manual-acceptance steps from the spec. Confirm keyboard submission on each target, each 44-point control is comfortably operable, duplicate rows toggle independently, and reload returns to the All empty state. Use the observation date and actual runtime versions; mark a cell only after observation.

- [ ] **Step 4: Run final checks and commit the observed record**

```bash
pnpm lint:markdown
pnpm lint:links
pnpm quality
git diff --check
git status --short
git add docs/guides/02-local-todo.md README.md docs/curriculum-roadmap.md
git commit -m "docs: add local todo guide"
```

Expected: every check passes, both acceptance rows contain observed values, and only the user's pre-existing unrelated files remain in status. Obtain the required final whole-branch `gpt-5.6-sol` review. When integration and publishing are separately authorized, integrate through the repository's reviewed workflow, confirm CI passes on the integrated commit, then create annotated tag `phase-02-local-todo`; never tag an unintegrated or unverified commit.

## Implementation record

Implementation and local manual acceptance were completed on 2026-09-05. The todo and App suites add six tests, with 24 mobile tests passing overall. React Native Web exposes checkbox `aria-checked` and filter `aria-pressed` state, with a Space-key handler for activation. A parent `SafeAreaView` provides keyboard-safe layout, and tests use the supported `toHaveProp` matcher. The final whole-branch Sol review passed with no actionable findings. `pnpm quality` passed all 62 repository/doctor checks, 24 mobile tests, 3 API tests, lint, typecheck, and web export. Remote CI verification and the `phase-02-local-todo` tag remain pending integration.

## Spec coverage check

- Local state, IDs, validation, duplicates, toggle, filters, empty states, keyboard, and accessibility: Task 1.
- Default web/iOS composition and Phase 1 regression preservation: Task 2.
- Learner explanation, full quality gate, and observed web/iOS journey: Task 3.

The plan intentionally adds one product component, one interaction suite, one composition test, and no dependency. The code sketches are implementation instructions, not evidence that tests or manual acceptance already pass.
