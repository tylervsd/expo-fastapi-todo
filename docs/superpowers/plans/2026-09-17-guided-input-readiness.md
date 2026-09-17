# Guided Input Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent lost task titles when the initial suggestion probe finishes during browser input.

**Architecture:** Reuse `agentProbeReady` to gate editing until the collect input has mounted inside `AgentRuntimeProvider`. Preserve editing during subsequent suggestion requests; add no state, dependencies, or provider restructuring.

**Tech Stack:** React Native, TypeScript, Jest, React Native Testing Library, Playwright.

**Spec:** This bugfix follows the existing [agentic UI design](../specs/2026-09-10-agentic-ui-design.md). The traced failure is a collect input editable outside the runtime provider while the initial suggestion probe is pending; the provider then remounts that input during Playwright `fill`. An unchanged local E2E run passed 4/4, confirming intermittent timing rather than disproving the trace.

## Global Constraints

- Keep the fix in the existing screen and its test file; introduce no architecture or dependencies.
- Preserve user editing during suggestion requests after the initial probe.
- Use branch `codex/fix-guided-input-readiness`; implementation is authorized.

## Task 1: Gate initial draft editing and verify the race

**Files:**

- Modify: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx` (task-breakdown call site, template props, input `editable`).
- Test: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx` (existing host and deferred promise helpers).

**Interfaces:** Consume existing `agentProbeReady: boolean`; add required `draftReady: boolean` to `TaskBreakdownTemplate`.

- [x] Add the following regression using existing fixtures and imports:

```tsx
it("waits for initial suggestion probe before editing", async () => {
    const api = makeApi();
    const probe = deferred<WorkflowSuggestion>();
    api.getWorkflow.mockResolvedValue(collectWorkflow);
    api.getSuggestion.mockReturnValueOnce(probe.promise);
    await renderHost(api, createAppQueryClient(), {
      initialWorkflowId: WORKFLOW_ID,
    });
    const input = () => screen.getByLabelText("Todo titles (one per line)");
    await waitFor(() => expect(api.getSuggestion).toHaveBeenCalled());
    expect(input()).toHaveProp("editable", false);
    await act(async () => {
      probe.reject(new TodoApiError("not-found", "No saved suggestions."));
    });
    await waitFor(() => expect(input()).toHaveProp("editable", true));
    await fireEvent.changeText(input(), "Pack bag\nCheck weather");
    await waitForQuiescence();
    expect(input()).toHaveProp("value", "Pack bag\nCheck weather");
});
```

- [x] Run `pnpm --dir apps/mobile test --runInBand TodoWorkflowScreen.test.tsx -t 'waits for initial suggestion probe before editing'`; verify failure because `editable` is currently true before settlement.
- [x] Pass `draftReady={agentProbeReady}` at the sole task-breakdown template call site; add `draftReady` to template destructuring and `draftReady: boolean` to its prop type. Replace only the input expression:

```tsx
editable={draftReady && (!disabled || suggesting || suggestion?.status === "pending")}
```

- [x] Run `pnpm --dir apps/mobile test --runInBand TodoWorkflowScreen.test.tsx`. All cases must pass, including the existing deferred suggestion user-edit regression.
- [x] Run the broader checks:

```sh
pnpm test:mobile
pnpm typecheck
pnpm lint:mobile
pnpm lint:markdown
```

- [x] Run full real E2E against the existing disposable E2E database, then repeat the guided journey ten times with the freshly built export:

```sh
E2E_DATABASE_URL=postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e pnpm test:e2e:web
E2E_DATABASE_URL=postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e pnpm exec playwright test -c e2e/web/playwright.config.ts --grep 'guided creation survives reload' --repeat-each=10
```

Expected: full journey suite 4/4 and guided repetitions 10/10 pass without retries or added sleeps. Use the already established local E2E database URL if it differs from the CI default above.

- [x] Obtain final whole-branch review with gpt-5.6-sol medium, inspecting both the initial readiness gate and preservation of post-mount editing. Fix any actionable findings, rerun affected checks, and report verified results. Commit the screen, test, and plan together if committing is part of the controller's delivery workflow.

## Verification results

- Regression failed before the fix and passed afterward.
- Mobile suite: 539 tests passed; typecheck passed; lint had no errors.
- Browser journeys: 4 passed; guided creation repetitions: 10 passed.
- Markdown lint: no issues. Independent whole-branch review: no findings.
