# ADR 0001: Monorepo and checkpoint tags

## Status

Accepted for Phase 0 and the provisional curriculum.

## Context

The tutorial needs to show an evolving Expo and FastAPI application without making learners compare disconnected repositories or guess which branch contains the next lesson. Each phase has its own guide, tests, approved spec, implementation plan, and reviewable checkpoint.

## Decision

Use one evolving monorepo. Number phase guides and mark completed phases with annotated checkpoint tags, such as `phase-00-environment`. Keep the normal development line on `main`; do not maintain permanent per-phase branches or duplicate repositories.

## Consequences

Learners can follow one history and inspect the decisions that led to each checkpoint. Later phases can reuse shared tooling and contracts. The repository grows over time, so guides must identify their phase and later specs must preserve compatibility deliberately.

## Alternatives considered

Permanent phase branches would fragment the learner path and complicate fixes. Duplicate repositories would hide history and duplicate maintenance. A single unannotated stream would make stable checkpoint references harder to teach.
