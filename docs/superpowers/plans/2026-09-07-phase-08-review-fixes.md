# Phase 8 Review Fixes Implementation Plan

> **For agentic workers:** Execute the three bounded review fixes with TDD; do not broaden scope.

**Goal:** Correct unsupported-step focus, yes/no title rendering, and duplicate reload controls in the Phase 8 mobile workflow screen.

**Files:** Modify `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`, its existing test file, and `apps/mobile/src/todos/todoApi.test.ts`. This plan is the only additional file.

**Approach:** Add regression tests that assert observable labels and reload counts, run them red, then make the minimum prop/render/visibility changes and run the focused suite plus mobile typecheck.

## Tasks

- [x] Add a focus regression that makes `findNodeHandle` return a node for every ref and asserts the focused control label is `Back to todos` on an unsupported view; pass the existing `backButton` as `backRef` and attach it to the unsupported Back pressable.
- [x] Add distinct `view.title` values to both yes/no fixtures and assert each title renders alongside its question; render `view.title` with the existing text style while retaining the question as the header.
- [x] Add invalidation/reload coverage that asserts an unsupported stale view exposes exactly one reload, then verify a working returned view hides the host reload and a failed reload preserves one control; suppress `reloadVisible` for unsupported views.
- [x] Extend the existing transport suite with valid `task_breakdown`/`review` bodies and malformed breakdown/review views so each parser branch is exercised.
- [x] Run each new regression red before production edits, then run the focused Jest suite, mobile typecheck, and `git diff --check`; record red/green evidence here.

## Checks

- Focused command: `pnpm --dir apps/mobile exec jest src/todoWorkflows/TodoWorkflowScreen.test.tsx --runInBand`
- Typecheck command: `pnpm --dir apps/mobile exec tsc --noEmit`
- Diff check: `git diff --check`

## Progress

- [x] Red tests observed before implementation: screen suite failed on missing yes/no title, unsupported Back focus, and duplicate stale reload controls (30 passed, 3 failed).
- [x] Minimal implementation complete: pass `backRef`, render `view.title`, and hide host reload for unsupported views; add bounded transport parser coverage.
- [x] Green focused suite, typecheck, and diff check verified: Jest passed 2 suites / 115 tests; `tsc --noEmit` exited 0; `git diff --check` exited 0. Jest retains the existing SafeAreaView deprecation warning.
