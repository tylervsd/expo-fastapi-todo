# Phase 30a: Client-side product events with RudderStack

**Status:** Implemented; live walkthrough pending. [Spec](../superpowers/specs/2026-09-25-rudderstack-client-events-design.md), [implementation plan](../superpowers/plans/2026-09-25-rudderstack-client-events.md).

## 1. Why client events

Phase 26 counts confirmed server outcomes: a signup, a workflow completed, a suggestion that finished. It can't see what happens before a server event exists at all — someone opening the auth screen and leaving, or tapping a button that never turns into a confirmed result. This phase adds four small client events, on Expo web only, to answer four questions server events can't:

| Event | Question it answers |
| --- | --- |
| `auth_screen_viewed` | How many people saw the auth screen, and in which mode, before any server event exists for them? |
| `signup_submitted` | Of those, how many tried to sign up? |
| `signin_submitted` | Which auth-screen views are returning users, not drop-off? |
| `suggestion_requested` | How many times did someone tap "suggest", regardless of whether the AI request ever finished? |

The last one is the reason to keep taps and confirmed outcomes in separate columns rather than one number: a tap tells you what a person asked for, `suggestion_finished` (Phase 26) tells you what the system delivered. Counting only one hides either the demand or the failure rate.

## 2. The event plan and definitions

### Event plan

All four events use `track`; none carries free text, and automatic page tracking is off.

| Event | Fired when | Properties |
| --- | --- | --- |
| `auth_screen_viewed` | The auth screen mounts (except right after a sign-out or a rejected stored session — see below), and when the user switches between sign-in and sign-up | `mode`: `signin` / `signup` |
| `signup_submitted` | The signup form passes client validation and the request is sent | none |
| `signin_submitted` | The sign-in form is sent | none |
| `suggestion_requested` | The user taps the suggest action on a workflow | `workflow_key` (the id the server's suggestion events use) |

### Identity

- Before sign-in: RudderStack's own anonymous ID, stored in browser `localStorage` (not a cookie).
- `identify(user.id)`, no traits, at three moments: after a signup succeeds, after a sign-in succeeds, and when a stored session is restored on app start. `user.id` is `/auth/me`'s `id`, the same pseudonymous key as Phase 26's `user_key`.
- `reset()` at two moments: sign-out, and when a stored session's token is rejected on start. The second case matters on a shared browser — without it, the next anonymous visitor would inherit the previous (revoked) user's identity in `auth_screen_viewed`/`signin_submitted`. After either reset, the auth screen that appears skips its mount-time `auth_screen_viewed` (§2's funnel behaviors explain why); switching between sign-in and sign-up still records a view.

### Consent and Global Privacy Control

- A device-stored toggle on the todo screen, **"Share usage analytics,"** default **on** (opt-out, matching the planned US launch).
- If the browser sends `navigator.globalPrivacyControl === true`, the switch is forced off and disabled, with the reason shown in place of the label.
- Turning the switch off stops sending and calls `reset()`. Turning it back on starts a new anonymous ID.
- If the browser refuses to persist the stored choice — private browsing, blocked site data — the read simply fails and consent falls back to its default, **on**. There is no separate "consent unknown" state.

### `signup_funnel` (one row per UTC ISO week)

- **`visitors`** — anonymous IDs whose first `auth_screen_viewed` falls in the week, **excluding returning visitors** (below).
- **`returning_24h`** — of that week's first-view anonymous IDs, the ones excluded from `visitors`: a visitor is "returning" if it has a `signin_submitted` within 24 hours of its first view and **no** `signup_submitted` in that same 24-hour window. This keeps a returning user's auth-screen view from being read as signup drop-off.
- **`submitted_24h`** — of the (non-returning) `visitors`, those with a `signup_submitted` within 24 hours of the first view.
- **`signed_up_24h`** — of those, the ones linked through `identifies` to a `user_key` whose server `user_signed_up` (Phase 26) falls within 24 hours after that `signup_submitted`. The window opens **1 minute before** the submit, as slack between the browser's clock and the server's: a signup the server recorded a few seconds "before" the client's submit timestamp still counts.
- **`server_signups`** — server `user_signed_up` events in the week, from `analytics.events_deduped`, independent of any client event.
- **`server_signups_identified`** — of those, the ones whose `user_key` appears anywhere in `identifies`.
- **`client_coverage`** — `server_signups_identified ÷ server_signups`. This is the ad-blocker/opt-out loss measure: a real signup the client pipeline never saw.
- **`cohort_complete`** — true once the week ended at least 48 hours ago (`CURRENT_DATE('UTC')`), so a week still filling in its 24-hour windows isn't compared against a finished one.

Behaviors worth knowing before reading the numbers:

- After a **successful signup**, the app switches the screen to sign-in, which fires another `auth_screen_viewed` with `mode: "signin"`. Visitors are counted by anonymous ID, not by view count, so this doesn't inflate `visitors`.
- If the in-browser storage read for consent fails, consent is **on** by default (see above) — a silently-blocked switch doesn't silently reduce coverage.
- **Sign-out doesn't create a visitor.** `reset()` gives the browser a new anonymous ID at sign-out (including a sign-out forced by an expired session) and when a stored session is rejected on start. The auth screen that appears next therefore skips its mount-time `auth_screen_viewed`: otherwise every sign-out would add a "visitor" who never submits, read as signup drop-off. If that person then switches to sign-up, the mode-switch view still records, so a real signup attempt after a sign-out is counted. A fresh visitor with no stored token — or a browser whose token storage can't be read — still records the mount-time view.
- **A signup keeps its ID until the next sign-in, sign-out, or reset.** After a successful signup the app identifies the browser as the new user and returns to the sign-in screen. If the person leaves without signing in, the next person on that browser is attributed to that user until one of those happens.

### `suggestion_taps` (one row per UTC ISO week of the tap)

- **`taps`** — count of `suggestion_requested` events (deduplicated by RudderStack's message `id`).
- **`workflows_tapped`** — distinct `workflow_key` values tapped.
- Each tap is matched to an outcome: the first server `suggestion_finished` (Phase 26) for the same `workflow_key`, **within 30 minutes** of the tap (the 15-minute suggestion-reservation TTL plus expiry-scheduler slack) and **before that workflow's next tap** (so a retap before a slow first outcome doesn't double-credit the first tap).
- **`taps_ready`**, **`taps_failed`**, **`taps_expired`** — taps matched to a `suggestion_finished` outcome of `ready`, `failed`, or `expired`.
- **`taps_no_outcome`** — taps matched to nothing within the window: superseded by a retap, abandoned, or lost.

Behaviors worth knowing before reading the numbers:

- The in-app **AI agent** can also request a suggestion (a clarification round-trip), and that path does **not** fire `suggestion_requested` — it isn't a tap. Server `suggestion_finished` events therefore include outcomes the client never tapped for, so server suggestion volume can be **higher** than `taps` without anything being wrong.
- Turning consent **back on while signed in** stays anonymous (a new anonymous ID, no user ID) until the next sign-in or session restore. Taps still join their outcomes, because that join is by `workflow_key`, not by user.

Both views deduplicate by RudderStack's own `id` (its own `_view`s only cover 60 days; these views don't rely on that), use UTC ISO weeks, and select no IP address, user agent, locale, page URL, or screen size — even though the raw tables underneath hold that context (§5). `rudderstack_raw` has no grants beyond BigQuery's own default project-role access (§3), so these two views, not the raw tables, are the only surface analysts should be given.

## 3. Keyless vendor access

This phase is the opposite of Phase 28b's key exception: no service-account key exists for RudderStack at all. It reaches Google Cloud through workload identity federation (WIF), available on every RudderStack plan including Free.

| | |
| --- | --- |
| **Mechanism** | A Google Cloud workload identity pool trusts AWS account `422074288268` — the account RudderStack's own data-plane loader runs under, shared across all its customers. |
| **What scopes it to you** | An attribute condition on the pool's AWS provider admits only assertions whose extracted workspace attribute equals *your* RudderStack workspace ID. Anyone else's workspace is rejected at the trust boundary, before any Google credential is issued. |
| **What the trusted principal can do** | Impersonate one service account, `rudderstack-loader` — nothing else. That's `roles/iam.workloadIdentityUser`, scoped to that one account. |
| **What `rudderstack-loader` can do** | `roles/bigquery.dataEditor` on the `rudderstack_raw` dataset only (a dataset-level grant, not a project role); `roles/bigquery.jobUser` on the project (needed to run load jobs, grants no data access by itself); `roles/storage.objectCreator` and `roles/storage.objectViewer` on the staging bucket only. It cannot create datasets, change access, read `analytics_raw`, or touch any other bucket. |
| **Who can read raw client data** | `rudderstack_raw` has **no grants beyond BigQuery's default project-role access** — the same posture as `analytics_raw` in Phase 26. With that default, project **Viewers can read**, **Editors can write**, and **Owners own** the dataset. So analysts must not hold basic project roles (Viewer, Editor, Owner), or they could query the raw tables directly. `roles/bigquery.user` alone does not read table data (it runs jobs and lists datasets). The curated views in §7 are analysts' only intended surface. |
| **What never exists** | A downloaded key, a credential file, a secret in RudderStack's dashboard for this connection. There is nothing to leak, rotate, or forget to delete. |

**The question for Accountable:** *Which vendors hold keys to our warehouse, and which could authenticate through federation instead?* A vendor that insists on a long-lived key when its platform supports WIF is a design choice worth pushing back on.

## 4. Setup

Run this from your **main checkout** after this phase's PR is merged and pulled.

1. **Create a free RudderStack Cloud account** (choose the **US** region — RudderStack then processes the events in the US, on its own infrastructure, before loading them into your `us-west1` dataset). In the dashboard, open **Settings → Workspace** (the exact menu wording may differ slightly; look for the workspace identifier) and copy the workspace ID.

2. **Terraform.** In `infra/terraform/sandbox/terraform.tfvars`:

   ```hcl
   rudderstack = {
     workspace_id = "your-rudderstack-workspace-id"
   }
   ```

   ```sh
   PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox plan
   ```

   Expect: the `rudderstack_raw` dataset, the staging bucket, the `rudderstack-loader` service account and its four scoped grants (dataset access, job user, two bucket roles), the workload identity pool, its AWS provider, and the service-account impersonation binding. Nothing destroyed. Apply, then:

   ```sh
   PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox output rudderstack_settings
   ```

   Keep this output open; the next step needs every field in it.

3. **In RudderStack, add a source.** Choose a **JavaScript** source. Copy its write key and data plane URL — you'll put both in Cloudflare Pages in step 5.

4. **In RudderStack, add a destination** for that source: **BigQuery**, authenticated with **Workload Identity Federation** (not a service-account key). Fill in, from the Terraform output and your project:

   | Field (purpose — the exact label may differ) | Value |
   | --- | --- |
   | Google Cloud project | your sandbox project id |
   | Dataset location | `us-west1` |
   | Staging bucket | `bucket` from the output |
   | Namespace (the dataset RudderStack writes into — **cannot be changed after the first sync**) | `rudderstack_raw` |
   | Workload identity pool's project number | `pool_project_number` |
   | Workload identity pool ID | `pool_id` |
   | Workload identity provider ID | `provider_id` |
   | Target/impersonated service account | `service_account` |

   Leave any **staging-file cleanup** setting **off**: the loader has no delete permission on the bucket (only `objectCreator`/`objectViewer`), so it can't clean up after itself even if asked to. The bucket's own 7-day lifecycle rule is the actual cleanup. Connect the source to this destination.

5. **Cloudflare Pages.** As `EXPO_PUBLIC_API_URL` was added in [Guide 17](17-cloudflare-pages.md), add two more **production** environment variables and redeploy:

   | Variable | Value |
   | --- | --- |
   | `EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY` | the source's write key |
   | `EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL` | the source's data plane URL |

   The write key is public by design — it only lets a client send events to this one source, the same trust level as a Stripe publishable key. It's meant to end up in the compiled web bundle.

## 5. See it live

Open the deployed site and RudderStack's **Live Events** view side by side. Watch events arrive while you: load the auth screen, switch to sign-up and back, sign in, and tap **Suggest todos** on a workflow.

In DevTools Network, with consent on, record **every RudderStack host** the page contacts — the data plane and the control plane alike. The wrapper loads the **bundled** SDK build (`@rudderstack/analytics-js/bundled`), so its plugins ship inside that one script — no separate plugin scripts load from RudderStack's CDN at runtime. The SDK also loads **lazily**: nothing contacts RudderStack until the first event (on a fresh page, the auth screen's view). Expect at least:

| Host | What it's for |
| --- | --- |
| your data plane URL | every `track`/`identify` call |
| `api.rudderstack.com` (control plane) | source configuration fetched when the SDK loads |

Record the actual list observed — an SDK version change could add or drop a host. §8 uses this list to check that consent-off and GPC pages contact none of them.

Inspect a few outgoing payloads. Expect to see:

- The anonymous ID, and `user.id`/`userId` once you're signed in.
- The event name and, for `auth_screen_viewed`/`suggestion_requested`, their one property (`mode` / `workflow_key`).
- The SDK's automatic `context` object — IP address (added server-side by RudderStack, not sent by the browser), user agent, locale, page URL, and screen size. This is normal SDK behavior, not a leak; it's why `rudderstack_raw`'s tables carry columns the curated views deliberately don't select (§2, §3).

Confirm none of these ever appear: a username, a password, a real name, a todo title, or an AI prompt. If any of those show up in a payload, that's a defect in the wrapper, not an expected field.

## 6. Synthetic events

`analytics_practice/seed_client_events.py` sends deterministic, backdated events through RudderStack's own HTTP API, reproducing the Phase 28b seed's 400 users and suggestion times, plus 600 anonymous visitors who never sign up.

The repo's Python is uv-managed ([setup](../setup/macos.md#5-uv-and-python-3147)); there is normally no bare `python` on `PATH`, so run it through `uv run`:

```sh
uv run python analytics_practice/seed_client_events.py --dry-run
```

The current dry run reports **3907 events**: `auth_screen_viewed` 1643, `identify` 371, `signin_submitted` 487, `signup_submitted` 442, `suggestion_requested` 964. Well under the free plan's 250K/month limit.

Verify the pipe end to end with one event before sending everything:

```sh
RUDDERSTACK_WRITE_KEY=... RUDDERSTACK_DATA_PLANE_URL=https://... \
  uv run python analytics_practice/seed_client_events.py --probe
```

Trigger **Sync now** on the BigQuery destination (or wait up to 3 hours on the free plan), then in BigQuery confirm the probe row landed with its `timestamp` column backdated into **2026-07** — not the time you ran the script. The probe is the seed's first event (`--dry-run` prints it as `first`): an `auth_screen_viewed` with `mode: "signin"`. Look it up by its message ID or anonymous ID in `rudderstack_raw.auth_screen_viewed` (or `rudderstack_raw.tracks`):

```sh
bq query --use_legacy_sql=false \
  'SELECT id, anonymous_id, timestamp, received_at FROM rudderstack_raw.auth_screen_viewed WHERE id = "PROBE_MESSAGE_ID"'
```

The warehouse `id` column holds the event's `messageId`. A 2026-07 `timestamp` there confirms RudderStack respects an explicit `timestamp` rather than stamping arrival time. Then send the rest and sync again:

```sh
RUDDERSTACK_WRITE_KEY=... RUDDERSTACK_DATA_PLANE_URL=https://... \
  uv run python analytics_practice/seed_client_events.py --send
```

A rerun sends the same message IDs; the curated views deduplicate by `id`, so nothing double-counts.

## 7. Curated views

`curated_views = true` creates `analytics.signup_funnel` and `analytics.suggestion_taps` — but only once RudderStack's first sync has already created all five tables it writes into `rudderstack_raw` (`auth_screen_viewed`, `signup_submitted`, `signin_submitted`, `suggestion_requested`, `identifies`). Applying earlier fails with `Not found: Table` on whichever table hasn't synced yet. Check first:

```sh
bq ls rudderstack_raw
```

Once all five tables (plus RudderStack's own `tracks`/`users`) are listed, set the flag and apply:

```hcl
rudderstack = {
  workspace_id  = "your-rudderstack-workspace-id"
  curated_views = true
}
```

```sh
PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox plan
```

Expect two views and two authorized-view grants (each view authorized on `rudderstack_raw`, since it selects from it). Apply, then query both:

```sh
bq query --use_legacy_sql=false 'SELECT * FROM analytics.signup_funnel ORDER BY week'
bq query --use_legacy_sql=false 'SELECT * FROM analytics.suggestion_taps ORDER BY week'
```

Compare against `analytics_practice/expected_client.md` (the reference results are recorded there after the first live seed run and sync). Expect `client_coverage` around **0.92**, a visible dip in `taps_ready` for the week of 2026-09-07 (matching the Phase 28b dip), and a nonzero `taps_no_outcome` from the seed's deliberate retaps.

## 8. Consent, GPC, sign-out

The "Share usage analytics" switch lives in the **signed-in header** — it only renders once you're signed in, so there's nothing to toggle from the auth screen itself.

1. **Sign-out identity reset, first, with consent on and no GPC.** Sign in, then sign out and sign back in (or as a different account). Confirm Live Events shows a **new anonymous ID** for the pre-sign-in events — not the previous session's. Do this before opt-out or GPC below: both of those stop sending, and a browser that isn't sending anything would make the "new anonymous ID" check impossible to observe.
2. **Opt-out.** Turn the switch off. That one moment may load the SDK so it can clear the stored identity; that's expected. Then, still signed in, **reload the page** with DevTools Network open and use the app (tap **Suggest todos**). Confirm the fresh page load makes **no request to any RudderStack host** from §5's list — data plane or control plane. (Signing out would load the SDK once more to clear the identity, so check before signing out.) Turn the switch back on afterward, or move to a fresh browser/profile for the next check — an opted-out browser sends nothing, which would look identical to GPC working even if GPC weren't wired up at all.
3. **Global Privacy Control**, in a browser/profile where consent is still on. Enable GPC (Brave ships it on by default; in Firefox set `privacy.globalprivacycontrol.enabled` to `true` in `about:config`) and reload. The switch should render disabled with the GPC explanation in place of the label. Confirm the fresh page load, and using the app, make **no request to any RudderStack host** from §5's list, even if you try to toggle the switch.

## 9. Ad blocker experiment

With uBlock Origin (or similar) enabled, sign up a fresh disposable test account through the normal UI. After the next Phase 26 export and RudderStack sync:

- The server `user_signed_up` event appears in `analytics.events_deduped`, as always.
- No client events for that signup appear in `rudderstack_raw` — the ad blocker stopped the SDK from loading or sending.
- `client_coverage` for that week drops, because `server_signups` counted the signup but `server_signups_identified` didn't.

This is the measurement Decision 6 (spec) chose over building a proxy to route around ad blockers: the gap is visible and honest rather than hidden.

## 10. Deletion drill

RudderStack's user-suppression API is a Growth/Enterprise feature and, even where available, does not reach warehouse destinations — it stops future sends, not past rows. Deleting a real person's client data is a warehouse-owner job:

1. Pick one real test user's `user_id` and every `anonymous_id` ever linked to it (via `identifies`).
2. In BigQuery, `DELETE` matching rows from every `rudderstack_raw` table that could hold them. The event tables and `identifies` (`tracks`, `auth_screen_viewed`, `signup_submitted`, `signin_submitted`, `suggestion_requested`, `identifies`) match by `user_id` or any of the linked `anonymous_id`s; the `users` table is keyed by **`id`**, not `user_id`:

   ```sql
   DELETE FROM rudderstack_raw.tracks
   WHERE user_id = 'USER_ID' OR anonymous_id IN ('ANON_ID_1', 'ANON_ID_2');
   -- …the same for each event table and identifies…
   DELETE FROM rudderstack_raw.users WHERE id = 'USER_ID';
   ```

3. Remove the synthetic rows with [`unseed_client.sql`](../../analytics_practice/unseed_client.sql) (it matches the `00000000-0000-4000-9000-` anonymous-ID prefix and the `00000000-0000-4000-8000-` user-ID prefix):

   ```sh
   bq query --use_legacy_sql=false < analytics_practice/unseed_client.sql
   ```

4. Verify against the **raw tables**, not the weekly views: re-run the step 2 `WHERE` clauses as `SELECT COUNT(*)` on every table (and `users` by `id`) and confirm each returns 0. The curated views only show weekly counts, so a missing row there proves little.
5. Note what "deleted" doesn't immediately mean here. BigQuery keeps deleted rows recoverable through **time travel for up to 7 days**, then in **fail-safe for another 7 days** (recoverable only by Google), so up to about **14 days** in all. Separately, a staged copy may still sit in the staging bucket until its **7-day lifecycle rule** removes it: the loader has no delete permission, so nothing cleans the bucket sooner. Record what "fully deleted" required — the DELETEs, plus waiting out those windows if the record needs to be final.

## 11. Cost

- RudderStack's **free plan**: 250K events/month (the seed uses under 4K), 3-hour sync interval.
- BigQuery **load jobs are free**; only storage and query costs apply, and this data is tiny.
- Staging bucket storage is negligible and self-cleans after 7 days.

## 12. Acceptance record

| Check | Result |
| --- | --- |
| Terraform plan reviewed and applied (dataset, bucket, loader, WIF pool/provider/binding) | Pending |
| RudderStack source and BigQuery destination created with Workload Identity Federation | Pending |
| Web app deployed with the write key; events visible in Live Events | Pending |
| SDK-contacted hosts recorded | Pending |
| Probe event confirmed backdated to 2026-07 | Pending |
| Synthetic seed sent and synced | Pending |
| Curated views applied (after all five tables existed) and matched against `expected_client.md` | Pending |
| Opt-out verified: fresh page load makes no request to any RudderStack host | Pending |
| GPC verified: switch disabled, fresh page load makes no request to any RudderStack host | Pending |
| Sign-out verified: new anonymous ID | Pending |
| Ad-blocker gap observed in `client_coverage` | Pending |
| Deletion drill completed and recorded | Pending |

### Deferred, not passed

- iOS and the React Native SDK (Phase 30b).
- A custom-domain proxy for the data plane.
- EU opt-in consent (one function away; not switched on).
- A pre-signup opt-out. The consent switch appears only after sign-in, so an anonymous visitor's only opt-out before signup is GPC. That's a question for Accountable's counsel.
- Device-mode destinations.
- A self-hosted data plane.
- Hex tiles for `signup_funnel`/`suggestion_taps` (once Hex, from Phase 28b, is active again).
- RudderStack's own Terraform provider (two objects didn't justify adopting it).

## 13. Local verification

Observed on 2026-09-25 on `codex/phase-30a-rudderstack`:

- `pnpm test:api`: 756 passed, including five deterministic seed tests (reproduces the 28b signup/suggestion times, no free text or traits, blocked-user/visitor/retap shape, and the userId presence/absence contract for `signin_submitted`).
- `pnpm test:mobile`: 582 passed across 20 suites, including the wrapper's no-send-without-key/consent-off/GPC tests, the SDK loading only on its first call, `reset()` on sign-out and on a revoked restored session, no mount-time `auth_screen_viewed` after either reset, and one `suggestion_requested` tap per sent request.
- `terraform test` (sandbox): 60 passed, including `rudderstack` requiring `analytics`, the WIF attribute condition binding the workspace ID, bucket-only storage roles, `dataEditor` scoped to `rudderstack_raw` only, no curated views until `curated_views = true`, and the signup match's 1-minute clock slack.
- Markdown and link checks pass.

## Sources

- [RudderStack BigQuery destination](https://www.rudderstack.com/docs/destinations/warehouse-destinations/bigquery/) (permissions, WIF, namespace, staging, 60-day views)
- [RudderStack pricing](https://www.rudderstack.com/pricing/) (free plan limits, sync frequency)
- [JavaScript SDK](https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-javascript-sdk/)
- [HTTP API](https://www.rudderstack.com/docs/api/http-api/)
- [User suppression API](https://www.rudderstack.com/docs/api/user-suppression-api/)
- [React Native SDK](https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-react-native-sdk/) (for 30b)
