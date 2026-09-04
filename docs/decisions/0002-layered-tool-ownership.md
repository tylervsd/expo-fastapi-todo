# ADR 0002: Layered tool ownership

## Status

Accepted for Phase 0.

## Context

The setup must be predictable for a mixed audience and must keep repository-specific language runtimes from moving when general Mac packages upgrade. A single version manager would overlap responsibilities, especially for Python.

## Decision

Use Homebrew for general Mac tools declared in `Brewfile`, Volta for Node 24.20.0, Corepack for pnpm 11.25.0, uv for Python 3.14.7 and Python dependencies, and Docker Desktop for containers and Compose. Keep macOS system Python untouched. The doctor reports state but never installs software or rewrites shell profiles.

## Consequences

Each ecosystem has a clear owner and a small, teachable verification command. Setup has several tools to explain, and users must make a few explicit profile edits. Repository pins remain deliberate maintenance changes rather than accidental results of a system package upgrade.

## Alternatives considered

`mise` could unify version management, but its broader ownership model is less clear for this tutorial. Homebrew-managed Node or Python runtimes could be convenient, but they would let general package upgrades move repository runtimes implicitly. Those alternatives are rejected for this curriculum.
