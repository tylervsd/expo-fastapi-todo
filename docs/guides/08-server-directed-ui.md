# Phase 8: Server-directed screens

## 1. Domain state versus presentation type

Phase 7 taught one mapping: backend state → dedicated screen. Phase 8 splits
that mapping in two. The domain still decides the business state
(`OFFER_BREAKDOWN` is new; the other five are unchanged). A separate pure
function, `present_workflow`, converts the authoritative snapshot into a
*view description*: a small typed object naming a template (`yes_no`,
`task_breakdown`, `review`, `completion`) plus exactly the content that
template needs. The frontend switches on `view.type` through a template
registry and never reads business state to decide what to render — the
screen contains zero references to workflow states.

The practical consequence: adding a step, rewording a question, or rerouting
a branch changes backend files only. The client renders whatever supported
view the server describes.

## 2. One yes/no component serving two questions

`ASSESS_TASK` and `OFFER_BREAKDOWN` both map to the `yes_no` template with
different questions, different step identities, and the same Yes/No actions:

- `ASSESS_TASK` asks **Does this task involve multiple steps?**
- `OFFER_BREAKDOWN` asks **Would you like to split it into smaller todos?**

One `YesNoTemplate` component renders both. It receives the question, the two
labelled actions, and callbacks — it knows nothing about which business
question it displays, and answering Yes sends the same
`answer_multiple_steps` command in both cases. The current state on the
backend disambiguates the meaning, exactly as it did for action validation
in Phase 7.

## 3. Step identity and stale-state prevention

Every view carries `step_id`, derived as `"{workflow_id}:{state}"` — for
example, `a5693d6a-…:OFFER_BREAKDOWN`. The two yes/no steps therefore have
different identities despite sharing a component. The template host mounts
each template with `key={view.step_id}`, so React discards the previous
question's draft text, selection, and error the moment the step changes.
Refetching the same current step recomputes the identical string, so reloads
and remounts keep local state intact.

Step identity is a rendering correctness tool only. It is never stored in
PostgreSQL, never used in cache keys, and never claimed as concurrency or
idempotency control. It works because the state graph is acyclic — no
transition re-enters a state — a property pinned by a domain unit test that
walks every valid path. If a future phase ever adds a cycle, identity must
be revisited then.

## 4. When backend changes do and do not require frontend changes

No frontend change needed: rewording any question or title, rerouting a
branch between existing states, adding another yes/no question and its
branching rule, changing breakdown limits (the view carries `min_titles`
and `max_titles`, and the breakdown screen formats its own count error
from them).

Frontend change needed: a genuinely new template type (the registry has no
component for it — by design, the fallback screen appears instead), or a
new field on an existing template (strict validation rejects unknown
fields, so both sides change together deliberately).

## 5. The backend-only additional-question experiment

`OFFER_BREAKDOWN` is the worked example of section 4. Landing it required
only backend files: two rows in the domain transition table, two view cases
in the presentation mapper, a widened state CHECK constraint, and contract
tests. No new component was added and no frontend branching rule changed —
the OFFER view renders through the pre-existing yes/no path with a fresh
step identity. A component test proves exactly this: it feeds an
`OFFER_BREAKDOWN` snapshot and asserts the shared template, the new
question, the new identity, and a cleared draft.

## 6. The three birthday-party paths

- **No:** start → No → `REVIEW` with `["Plan birthday party"]` → confirm
  creates one todo.
- **Yes, then No:** start → Yes → `OFFER_BREAKDOWN` → No → `REVIEW` with
  `["Plan birthday party"]` → confirm creates one todo. The saved answer
  records that both questions were asked.
- **Yes, then Yes:** start → Yes → `OFFER_BREAKDOWN` → Yes →
  `COLLECT_TASKS` → enter 2–10 titles → `REVIEW` shows exactly those titles
  → confirm creates exactly those todos in order.

Cancel from `OFFER_BREAKDOWN` (like every nonterminal state) enters
`CANCELLED` with no todos. Misplaced actions there (`submit_tasks`,
`confirm`) get the exact wrong-state `409`. Terminal, ownership,
validation, and outage behavior are unchanged from Phase 7.

## 7. Unknown templates and malformed responses

A view whose `type` is not one of the four supported templates is accepted
into a normalized `unsupported` fallback — it is not treated as corrupt
data. The registry renders a fallback screen: an explanation that the step
needs a newer app version, plus **Back to todos** and **Reload plan**. It
submits nothing and guesses no component. Genuinely malformed responses
(bad UUID, missing keys, mistyped fields, wrong step identity) still take
the existing invalid-data path with safe copy.

## 8. Focused commands that were actually verified

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_workflow_presentation.py tests/test_workflow_persistence.py tests/test_workflows.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx src/todos/todoApi.test.ts src/auth/authenticatedApi.test.ts
pnpm quality
```

Domain transition tests run database-free; the presentation mapper is pure
and database-free; persistence, transaction, and API tests run against the
real guarded `todo_test` database; transport and component tests use
injected fakes with a fresh `QueryClient` per case. The full `pnpm quality`
gate (lint, typecheck, all suites, web export) passed during
implementation; rerun it before any further change.

## 9. What remains for Phase 9

Discovery of unfinished workflows, atomic revisions, submission
idempotency, definition versions, and cross-device reliability are still
forthcoming. There is still no `step_id` in storage, no revision column,
no submission record, and no idempotency key. Lost-start recovery is still
limited to the honest warning that retrying may create another draft.

## 10. Phase 8 acceptance record

| Target | Date/runtime | Simple path | Declined breakdown | Accepted breakdown | Cancel/terminal | Invalid action | Restart/outage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Web | — | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| iOS Simulator | — | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
