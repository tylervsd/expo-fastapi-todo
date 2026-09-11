# Cloud Curriculum Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the provisional curriculum from Phase 13 through Phase 27 with an early CI security baseline, Google Cloud, Terraform, Cloudflare Pages, and later startup-oriented Google services.

**Architecture:** Keep Phases 0–12 and their existing guide/checkpoint numbers unchanged. Replace the single planned production-hardening phase with a sequential cloud track, then align the README, workflow learning plan, and Phase 11 forward reference with that track.

**Tech Stack:** Markdown, repository link checker, markdownlint

**Spec:** `docs/curriculum-roadmap.md`

## Global Constraints

- Documentation must not claim that planned cloud services, scans, guides, or checkpoints already exist.
- Existing Phase 0–12 numbers, guides, tags, and implementation status remain unchanged.
- Terraform follows manual service introduction and becomes the provisioning path for later Google Cloud phases.
- Security scanning begins before Phase 12 and expands as dependencies, containers, Terraform, and Google Cloud resources appear.

---

### Task 1: Expand the curriculum roadmap

**Files:**

- Modify: `docs/curriculum-roadmap.md`

**Interfaces:**

- Consumes: Existing Phase 0–12 sequence and the approved Phase 13–27 curriculum decisions.
- Produces: The canonical provisional phase sequence referenced by the README and workflow learning plan.

- [x] **Step 1: Update roadmap scope and status language**

Change the roadmap count to 28 phases (0–27), preserve the existing implementation status through Phase 11, and identify Phase 12 as next.

- [x] **Step 2: Add the cross-phase CI security baseline**

Document secret scanning, dependency scanning, CodeQL, scheduled rescans, and later container/Terraform/Google Cloud extensions without claiming implementation.

- [x] **Step 3: Replace Phase 13 with Phases 13–27**

Give every phase a learning goal, visible outcome, new technology or pattern, testing/verification emphasis, practical experiment, non-goals, and spec gate.

- [x] **Step 4: Review the sequence**

Confirm manual Google Cloud learning precedes Terraform, Terraform precedes automated delivery, Cloud Tasks precedes Pub/Sub, and optional services remain tied to application needs.

### Task 2: Align supporting curriculum documents

**Files:**

- Modify: `README.md`
- Modify: `docs/workflow-learning-plan.md`
- Modify: `docs/guides/11-agentic-ui.md`
- Modify: `tests/repository_contract.bats`

**Interfaces:**

- Consumes: The expanded canonical roadmap from Task 1.
- Produces: Consistent phase counts, next-phase language, workflow follow-through, and deferred-hardening ownership.

- [x] **Step 1: Update README roadmap summaries**

Replace the fourteen-phase and Phase 13 hardening language with the 28-phase sequence and concise cloud-track summary.

- [x] **Step 2: Update workflow follow-through**

Keep Phase 12 E2E details, move workflow diagnostics and provider quotas to the appropriate cloud phases, and identify Phase 20 as the asynchronous suggestion-processing lesson.

- [x] **Step 3: Update the Phase 11 forward reference**

Point measured provider hardening to Phase 21 while keeping Phase 12 responsible for cross-platform E2E.

- [x] **Step 4: Run documentation verification**

Run `pnpm lint:markdown` and expect exit code 0.

Run `pnpm lint:links` and expect exit code 0.

Run `CI=true pnpm test:contracts` and expect all repository contracts to pass, including the expanded roadmap-theme contract.

- [x] **Step 5: Inspect the final diff**

Run `git diff --check` and `git diff -- README.md docs/curriculum-roadmap.md docs/workflow-learning-plan.md docs/guides/11-agentic-ui.md docs/superpowers/plans/2026-09-11-cloud-curriculum-expansion.md`; confirm no unrelated files changed.
