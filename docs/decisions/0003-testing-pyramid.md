# ADR 0003: Testing pyramid

## Status

Accepted for Phase 0 and future phase specifications.

## Context

The tutorial needs fast feedback for everyday changes while still proving service boundaries and a few critical cross-platform journeys. Phase 0 has no application code, so it demonstrates the same shape with static checks, doctor unit tests, a smaller integration layer, and manual acceptance.

## Decision

Use broad static checks, many unit and component tests, fewer integration tests, and thin web/iOS end-to-end coverage. Web E2E runs on pull requests and iOS Simulator E2E runs on `main` once those suites exist. Each phase's approved spec identifies the tests that belong at each layer.

## Consequences

Most failures stay fast and local, while integration and E2E tests protect the boundaries most likely to regress. The suite needs stable fixtures and explicit CI scheduling. A useful test may live at another layer when its behavior cannot be proved clearly elsewhere.

## Alternatives considered

An E2E-heavy strategy would be slower and more brittle for routine feedback. A unit-only strategy would miss API, database, platform, and authentication boundaries. Equal test counts at every layer would optimize for symmetry rather than feedback speed and confidence.
