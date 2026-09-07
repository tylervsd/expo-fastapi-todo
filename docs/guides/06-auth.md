# Phase 6: Authentication and authorization

Phase 6 gives every todo an owner and every request an identity. Users sign
up with a username and password, sign in to receive a session token, and see
only their own todos on web and iOS. Sign-out revokes the session
server-side. The tutorial's first security boundary lives in SQL, not in
route code: every todo statement is scoped by owner, so one user's todo
UUIDs are unresolvable to anyone else.

## Password hashing

The server stores only an argon2 hash per user. Raw passwords exist in
request bodies and transient memory during signup and login; they are never
logged and never persisted. Passwords are 8–128 code points with no
trimming and no composition rules — length over `P@ssw0rd!` games — and NUL
is rejected before hashing. Usernames are 3–32 characters from letters,
digits, `_`, and `-`, case-sensitive, unique. There is no email anywhere:
no normalization debates, no verification flow the tutorial cannot
actually perform.

## Opaque sessions

Login generates 32 random bytes (`secrets.token_hex`), returns the token
exactly once in the login response, and stores only its SHA-256 hash with
an absolute 30-day expiry. A database read alone never yields a usable
credential. Validation is one indexed lookup constrained by
`expires_at > now()` — no second round-trip, no per-request writes, no
sliding window, no background janitor (login opportunistically deletes the
user's expired rows). Alternatives rejected: stateless JWTs would add
short expiries, refresh rotation, and awkward pre-expiry revocation for no
benefit at this scale; cookies have no native jar, force HTTPS-grade
cookie flags in cross-origin dev, and demand anti-CSRF tokens on
mutations.

## The Bearer boundary

The client sends `Authorization: Bearer <token>` on every request
(CORS gains the `Authorization` header; nothing else changes). A FastAPI
dependency resolves the token hash to a user or raises exact
`401 {"detail":"Not authenticated."}` — missing header, wrong scheme,
malformed token, unknown hash, and expired session all collapse into that
one shape with no distinguishing detail. Wrong credentials at login return
exact `401 {"detail":"Invalid username or password."}` (no
username-vs-password oracle). Duplicate usernames return `422`, keeping
the client's single validation-copy story. Logout deletes the presenting
row and returns empty `204`, even for unknown tokens. Signup returns
`201` but no token: the client performs an explicit login so the
credential round trip stays visible and testable.

## Per-user SQL scoping

Every todo statement carries `WHERE owner_id = current_user`. A UUID
belonging to another user reads as exact `404 {"detail":"Todo not
found."}` — never `403`, never data. Authorization therefore holds even
if a route forgets to check; there is no route-only enforcement to drift.
`GET /health` stays database-independent liveness, and database outages
keep the exact `503` behavior. The `2026090701` migration deletes
existing ownerless development rows first (they are recreatable in
seconds), then creates `users`/`sessions` and the non-null `owner_id`.

## Token storage split

`tokenStorage` exposes exactly `get/set/clear`. Native uses
`expo-secure-store` (Keychain/Keystore-backed); web uses `localStorage`.
The frank tradeoff: hardware-backed on native, XSS-readable on web.
There is no secure origin-bound store for a plain web SPA, and pretending
otherwise would be dishonest — the split itself is the lesson about
platform security boundaries. Memory-only storage was rejected because it
would sign users out on every reload and make restart acceptance
undemonstrable.

## Auth state machine

Identity lives in a small provider above `TodoScreen`, never in the
TanStack cache: `unknown` (launching) → `signed-out` → `signed-in`.
Launch with a stored token probes `GET /auth/me`; `200` restores the
user, anything else clears the store to a clean signed-out state.
Signed-out shows one screen with a sign-in/sign-up mode toggle.
Signed-in shows `Signed in as {username}`, a `Sign out` control, and the
unchanged todo UI operating on one user's rows. Any `401` from a todo
request drops back to signed-out with the store cleared — a revoked token
never strands the UI on a locked list. Sign-out calls logout
best-effort, then clears the store and the query cache regardless of
server reachability.

## Deliberately absent

No password reset (needs out-of-band delivery), no sign-out-everywhere
(single-session logout only), no rate limiting or lockout (no infra for
it in this stack), no OAuth/2FA/roles/teams, no refresh rotation, no
offline auth queue, no automated E2E (Phase 8's).

## Run focused checks

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_auth.py tests/test_todos.py tests/test_persistence.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts src/auth/ App.test.tsx src/TodoScreen.test.tsx
```

Then the full gate:

```bash
pnpm quality
```

The lockfile pins exact `@tanstack/react-query` `5.102.8`, SDK-resolved
`expo-secure-store`, and exact argon2 in `uv.lock`, with no other new
direct dependency. Mobile component tests use a fresh `QueryClient` per
case, an in-memory storage double, and fake timers only where timing is
asserted.

## Recover from an outage

Stop FastAPI mid-session: todo requests fail, the session row sits safely
in PostgreSQL. Restart FastAPI — no app memory was needed — and
**Refresh**; the same token validates. Restart the database container
without deleting its volume: sessions and rows survive. Stop it with the
volume deleted and every session is gone; sign in again.

## Manual auth journey

Use two users (`alice`, `bob`) and recognizable `Phase 6` titles.

1. On web, sign up both users; confirm each sees an empty list.
2. Create rows as each; confirm neither sees the other's, including direct
   cross-user UUID attempts reading as missing.
3. Restart FastAPI; confirm both sessions still validate.
4. Restart the database container without volume deletion; confirm
   sessions and rows survive.
5. On iOS, repeat sign-in and isolation; sign out and confirm the clean
   slate, then sign back in.
6. Record only observed date/runtime/results below.

## Phase 6 acceptance record

| Target | Date/runtime | Signup/login | Isolation | Restart persistence | Sign-out |
| --- | --- | --- | --- | --- | --- |
| Web | — | ☐ | ☐ | ☐ | ☐ |
| iOS Simulator | — | ☐ | ☐ | ☐ | ☐ |
