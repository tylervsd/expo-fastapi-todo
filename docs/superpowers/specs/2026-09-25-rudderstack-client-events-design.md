# Phase 30a: Client-side product events with RudderStack (web)

**Status:** Design approved in conversation by the learner on 2026-09-25; written spec awaiting review.

**Context:** Based on `main` at `281c342`, after Phase 28b. The learner will be CTO of Accountable, a pre-launch fintech that uses BigQuery and Hex and has **not yet chosen** a customer data platform or product-analytics tool. Phase 26 measures only confirmed server outcomes; it can't see screens, taps, or drop-off before signup. This phase adds a small, deliberate client event plan on **Expo web**, collected by **RudderStack Cloud (free plan)** and loaded into BigQuery next to the Phase 26 events. Phase 30b adds the iOS development build and the React Native SDK behind the same wrapper. Educational sandbox work with invented data, not Accountable's analytics design or compliance evidence.

**Related:** [Curriculum](../../curriculum-roadmap.md#30a-client-side-product-events-with-rudderstack), [Phase 26 design](2026-09-23-bigquery-analytics-design.md), [Phase 28b design](2026-09-24-hex-analytics-design.md).

## Decisions

1. **RudderStack Cloud with its BigQuery warehouse destination.** Chosen over a webhook into the FastAPI outbox (skips the vendor-to-warehouse connection a CTO must evaluate) and a self-hosted data plane (an extra service to operate; deferred with the argument recorded).
2. **Keyless access.** RudderStack reaches Google Cloud through workload identity federation (available on all plans, including Free). No service-account key exists.
3. **Four client events, answering what server events can't:** pre-signup drop-off, and taps versus confirmed outcomes.
4. **Opt-out consent** (US-launch default): on until the user turns it off; the browser's Global Privacy Control forces it off. Opt-in (EU) is one function away.
5. **Identity joins on the existing pseudonymous key.** `identify(user.id)`, where `user.id` from `/auth/me` is `users.public_id`, the same value as `user_key` in Phase 26. No traits. Sending this key to RudderStack is a deliberate, recorded choice.
6. **Measure ad-blocker loss rather than proxy around it.** A custom-domain proxy is deferred.

## 1. The client

### Event plan

All events use `track`; none carries free text. Automatic page tracking stays off.

| Event | Fired when | Properties |
| --- | --- | --- |
| `auth_screen_viewed` | The auth screen mounts, and when the user switches between sign-in and sign-up | `mode`: `signin` / `signup` |
| `signup_submitted` | The signup form passes client validation and the request is sent | none |
| `signin_submitted` | The sign-in form is sent | none |
| `suggestion_requested` | The user taps the suggest action on a workflow | `workflow_key` (the id the server's suggestion events use) |

`signin_submitted` exists so returning users' auth-screen views aren't read as signup drop-off.

### Identity

- Before sign-in: RudderStack's anonymous ID, stored in browser `localStorage` (not cookies).
- After signup or sign-in succeeds, and when a stored session is restored on start: `identify(user.id)` with no traits (no username, no real name).
- Sign-out: `reset()`, so the next person on a shared device gets a new anonymous ID.

### Consent

- A device-stored toggle, default on, shown as a small "Share usage analytics" switch on the todo screen (the app has no settings screen).
- On web, `navigator.globalPrivacyControl === true` forces it off and the switch shows why.
- Turning it off stops sending and calls `reset()`. Turning it back on starts a new anonymous ID.

### The wrapper, `apps/mobile/src/analytics/`

- The only module that imports the SDK (`@rudderstack/analytics-js`, pinned).
- Exports `track(name, props)`, `identify(id)`, `reset()`, `setConsent(enabled)`, `getConsent()`. Event names are a fixed TypeScript union, so a typo doesn't compile.
- Does nothing when `EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY` or `EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL` is unset, so local development and tests never send.
- Never throws into the UI; SDK failures are swallowed and logged at debug level.
- Phase 30b puts the React Native SDK behind the same interface.

The write key is public by design (it only permits sending events to one source). It lives in the Cloudflare Pages build environment next to `EXPO_PUBLIC_API_URL`. The existing `_headers` CSP has no `connect-src` or `script-src`, so the SDK isn't blocked; the plan confirms which hosts it contacts and records them.

## 2. The pipeline (Terraform)

An opt-in `rudderstack` object variable in the sandbox root, default `null`, in `infra/terraform/sandbox/rudderstack.tf`. It requires `analytics` (validation, like `hex`). Fields: `workspace_id` (required), `curated_views` (default `false`), and names with defaults.

- **Dataset `rudderstack_raw`** in `us-west1`, created by Terraform. RudderStack's namespace setting points at it, so RudderStack needs Data Editor, not Data Owner, and can't create datasets or change access. The namespace can't be changed later; the guide sets it before the first sync.
- **Staging bucket** in `us-west1`: uniform bucket-level access, public access prevention enforced, lifecycle delete after 7 days (a backstop to RudderStack's post-sync cleanup).
- **Service account `rudderstack-loader`:**
  - `roles/bigquery.dataEditor` on `rudderstack_raw` only, via `google_bigquery_dataset_access` (never mixed with dataset IAM resources, as in Phase 26).
  - `roles/bigquery.jobUser` on the project.
  - `roles/storage.objectCreator` and `roles/storage.objectViewer` on the staging bucket only.
- **Workload identity pool and AWS provider:** RudderStack authenticates from AWS account `422074288268`. Attribute mapping `google.subject = assertion.arn` plus a workspace attribute from the ARN, and an attribute condition that admits only `var.rudderstack.workspace_id`. That principal gets `roles/iam.workloadIdentityUser` on `rudderstack-loader` only. `sts` and `iamcredentials` are already enabled services.
- **Curated views and their authorization** (section 3), created only when `curated_views = true`, because RudderStack creates its tables on the first sync. The learner applies twice.

Setup inside RudderStack (a JavaScript source and the BigQuery destination with WIF) is done in its dashboard, with the steps in the guide. RudderStack's Terraform provider isn't adopted for two objects.

**Data flow:** browser → RudderStack Cloud (US region) → staging bucket → `rudderstack_raw` (`tracks`, `identifies`, `users`, one table per event), every 3 hours on the free plan (30 minutes on Growth).

## 3. Metrics

Two curated views in `analytics`, authorized on `rudderstack_raw` and on `analytics_raw` as needed, following the Phase 26 template pattern (`*.sql.tftpl`). Both deduplicate client events by RudderStack's message `id` (RudderStack's own `_view`s cover only 60 days) and use UTC ISO weeks. Neither selects IP address, user agent, locale, or page URL.

**`analytics.signup_funnel`**, one row per week:

- `visitors`: anonymous IDs whose first `auth_screen_viewed` falls in the week.
- `submitted_24h`: of those, with a `signup_submitted` within 24 hours of the first view.
- `signed_up_24h`: of those, linked through `identifies` to a `user_key` whose server `user_signed_up` is within 24 hours after the first `signup_submitted`.
- `server_signups`: server `user_signed_up` events in the week, from `analytics.events_deduped`.
- `server_signups_identified`: those whose `user_key` appears in `identifies`. `client_coverage = server_signups_identified / server_signups` measures ad-blocker and opt-out loss.
- `cohort_complete`: the week ended at least 48 hours before `CURRENT_DATE('UTC')`.

**`analytics.suggestion_taps`**, one row per week of the tap:

- `taps` and `workflows_tapped`.
- Each tap's outcome: the first server `suggestion_finished` for the same `workflow_key` after the tap, within 30 minutes (the 15-minute reservation TTL plus expiry-scheduler slack) and before that workflow's next tap. Columns `taps_ready`, `taps_failed`, `taps_expired`, and `taps_no_outcome` (superseded, abandoned, or lost).

Written definitions go in the guide, in the Phase 26 style, including why taps and confirmed outcomes are counted separately.

## 4. Synthetic client events

`analytics_practice/seed_client_events.py` sends deterministic, backdated events to RudderStack's HTTP API (`/v1/batch`, write key as basic auth, explicit `timestamp`), so they travel the real pipeline:

- For each of the 400 synthetic users from the 28b seed: `auth_screen_viewed` (signup) and `signup_submitted` shortly before the server signup time, an `identify` at that time, and a `suggestion_requested` shortly before each server suggestion outcome. It reproduces the 28b times with the same `md5` rule as `pg_temp.u`.
- About 8% of users send no client events (simulated ad blockers and opt-outs); about 10% of taps get an extra retap with no outcome.
- About 600 anonymous visitors who never sign up, some of whom submit.
- Anonymous IDs use the prefix `00000000-0000-4000-9000-`; user IDs keep `00000000-0000-4000-8000-`.
- About 3,000 events, well under 250K a month. `--dry-run` prints the batch JSON and sends nothing; a rerun sends the same message IDs, which the views deduplicate.

The plan verifies with one event that an explicit `timestamp` lands in the warehouse's `timestamp` column before sending the rest. Reference results are recorded from the live run into `analytics_practice/expected_client.md`. `analytics_practice/unseed_client.sql` deletes rows with either prefix from every `rudderstack_raw` table.

## 5. Governance, cost and deletion

- **What leaves the device:** the anonymous ID, `user.id`, event names, `workflow_key`, and the SDK's automatic context (IP address, user agent, locale, page URL, screen size). The raw dataset is Owner-only; curated views select none of the context.
- **Processor:** RudderStack processes events in its US region. The guide records this as the question to take to Accountable, alongside Hex (28b) and Gemini (28a).
- **Deletion:** RudderStack's user suppression API is Growth/Enterprise only and **doesn't delete from warehouse destinations**. Deleting a person's client events is a BigQuery `DELETE` across every `rudderstack_raw` table by `user_id` and every linked `anonymous_id`, plus the staging bucket's 7-day lifecycle and BigQuery time travel. The guide records what "fully deleted" required.
- **Cost:** free plan; BigQuery load jobs are free; staging storage is negligible.

## Testing and acceptance

**Local:**

- **Jest, wrapper:** no sends without the write key, with consent off, or under GPC; `reset()` on sign-out and on opt-out; `identify` sends no traits; SDK exceptions never reach the caller; payloads contain no username, todo title, or prompt.
- **Jest, screens:** each of the four events fires exactly once at the right moment (auth mount and mode switch, signup submit, sign-in submit, suggest tap); `identify` on sign-in, signup and session restore.
- **Terraform mock tests:** nothing when disabled; `rudderstack` requires `analytics`; the WIF condition binds the workspace ID; bucket-only storage roles; `dataEditor` on `rudderstack_raw` only; no views until `curated_views = true`; views select no context columns.
- **pytest:** the seed generator is deterministic and reproduces the 28b signup and suggestion times.
- Markdown and link checks.

**Live, learner-run and recorded:**

- Terraform plan reviewed and applied; RudderStack source and destination set up with WIF.
- The web app deployed with the write key; events visible in RudderStack Live Events.
- After a sync, the synthetic seed run, and `curated_views = true` applied: the views match `expected_client.md`.
- Opt-out and GPC: no network requests to the data plane. Sign-out: a new anonymous ID.
- A real ad blocker: the gap appears in `client_coverage`.
- The deletion drill done and recorded.

**Deferred (not passed):** iOS and the React Native SDK (30b); a custom-domain proxy; EU opt-in; device-mode destinations; self-hosted data plane; Hex tiles for the new views (once Hex is active); RudderStack's Terraform provider.

## Sources checked on 2026-09-25

- [RudderStack BigQuery destination](https://www.rudderstack.com/docs/destinations/warehouse-destinations/bigquery/) (permissions, WIF, namespace, staging, 60-day views)
- [RudderStack pricing](https://www.rudderstack.com/pricing/) (free plan limits, sync frequency)
- [JavaScript SDK](https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-javascript-sdk/)
- [HTTP API](https://www.rudderstack.com/docs/api/http-api/)
- [User suppression API](https://www.rudderstack.com/docs/api/user-suppression-api/)
- [React Native SDK](https://www.rudderstack.com/docs/sources/event-streams/sdks/rudderstack-react-native-sdk/) (for 30b)
