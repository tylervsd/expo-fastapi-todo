# Phase 17: Cloudflare Pages and the hosted web application

## Status

The repository changes are ready for review. Cloud deployment and browser
acceptance are **pending manual execution**. This guide deliberately contains
placeholders for observed cloud values; do not replace them with guesses or
mark an acceptance row passed from local checks alone.

This phase serves the existing Expo web export from Cloudflare Pages and sends
browser requests directly to the existing Cloud Run API. It uses the assigned
`pages.dev` hostname only. A custom domain, DNS change, Pages Function, Worker,
and a new database are outside this phase.

Pages and Cloud Run roll back independently. Neither action rolls back Cloud
SQL. Hosted browser acceptance is a manual exercise; do not point the local
Playwright suite at Cloud SQL or a hosted URL.

## Recorded local verification

The repository integration checks recorded for this prepared guide passed:
542 API tests (with 14 existing deprecation warnings), 523 mobile tests (with
existing `act` warnings), 23 Pages build tests, four local web Playwright
journeys, 13 repository-contract tests, 51 doctor tests, type checking, and
API lint. Mobile lint still reports 44 existing warnings. These results support
A10 only; they do not provide cloud-browser evidence for any pending row.

## Before starting

<!-- markdownlint-disable MD029 -->

1. Work from the implementation branch after its local checks are green. Set
   only non-secret shell variables; use the real values observed in your cloud
   account. The defaults below name the learner's existing sandbox, not a
   deployed result.

   ```sh
   export CLOUD_PROJECT=fullstack-sandbox-tylervsd
   export CLOUD_REGION=us-west1
   export CLOUD_SERVICE=fullstack-api
   export PHASE17_SUFFIX="web-$(date +%Y%m%d%H%M%S)"
   ```

   Do not put OpenRouter keys, database passwords, or service-account keys in
   this repository, a Pages variable, shell history, or an evidence record.
   `EXPO_PUBLIC_API_URL` is intentionally public: it is compiled into the web
   bundle. It must be an HTTPS API origin with no credentials, path, query, or
   fragment.

2. Confirm the Phase 16 API still works before changing it. Create a
   disposable account, sign in, create a todo, reload, edit/complete/delete
   it, sign out, and repeat with a second account to confirm owner isolation.
   Record the command output and console fields below without printing secret
   values.

   ```sh
   git rev-parse HEAD
   gcloud run services describe "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format='yaml(status.url,status.latestReadyRevisionName,status.traffic)'
   export CLOUD_URL="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
       --format='value(status.url)'
   )"
   printf '%s/docs\n' "$CLOUD_URL"
   ```

   In Cloud Run, open the current revision's **Container**, **Variables &
   Secrets**, and **Connections** panels. Record the image digest, Cloud SQL
   connection name, each secret resource and version reference, and the
   traffic allocation. Record references only, never their plaintext values.
   Open the printed `$CLOUD_URL/docs` URL and use the API documentation to run
   the disposable-account signup and todo journey. The web app is not hosted
   yet, so do not look for a Pages URL at this stage.

   | Baseline field | Observed value |
   | --- | --- |
   | Git revision | Pending |
   | Stable API origin | Pending |
   | Ready revision and image digest | Pending |
   | Traffic allocation | Pending |
   | Cloud SQL attachment | Pending |
   | Secret names and versions | Pending |
   | Intended Pages project | Pending |
   | Assigned production `pages.dev` origin | Pending |

## Local repository verification and Pages setup

3. Run the repository checks before creating cloud resources. The missing-target
   command must fail before Expo exports; the example API URL is only a local
   build input and is not a deployment target.

   ```sh
   pnpm test:pages
   env -u EXPO_PUBLIC_API_URL pnpm build:pages
   EXPO_PUBLIC_API_URL=https://api.example.test pnpm build:pages
   test -f apps/mobile/dist/index.html
   cmp apps/mobile/public/_headers apps/mobile/dist/_headers
   pnpm lint:markdown
   pnpm lint:links
   docker compose --profile e2e up -d --wait db-e2e
   export E2E_DATABASE_URL=postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e
   pnpm test:e2e:web
   ```

   `build:pages` clears Metro's export cache and disables dotenv loading. Run a
   fresh export whenever the API target changes; otherwise old
   `EXPO_PUBLIC_API_URL` content can remain in JavaScript assets. The local
   Playwright command remains local and uses its own database fixtures.

4. If needed, open `https://dash.cloudflare.com`, choose **Sign up**, and use
   the GitHub sign-in option. Complete Cloudflare's email verification, then
   approve GitHub access only for `tylervsd/expo-fastapi-todo`. In the
   dashboard choose **Workers & Pages**, **Create application**, **Pages**, and
   **Connect to Git**. Select that repository and create the project. Restrict
   the integration to this repository. Create it now so Cloudflare assigns the
   production hostname before the API CORS candidate is made. Copy the exact
   `https://<project>.pages.dev` origin from the Pages overview into
   `PRODUCTION_ORIGIN`; do not invent it.

   Configure Pages as follows. Use separate production and preview environment
   variable sets, each with its own observed HTTPS Cloud Run origin. Do not add
   secrets to Pages.

   | Pages setting | Value |
   | --- | --- |
   | Root directory | Repository root |
   | Production branch | `main` |
   | Framework preset | None |
   | Build command | `pnpm install --frozen-lockfile && pnpm build:pages` |
   | Build output directory | `apps/mobile/dist` |
   | `NODE_VERSION` | `24.20.0` |
   | `PNPM_VERSION` | `11.25.0` |
   | `SKIP_DEPENDENCY_INSTALL` | `true` |
   | `EXPO_PUBLIC_API_URL` (production) | `$CLOUD_URL` |
   | `EXPO_PUBLIC_API_URL` (preview) | `$CLOUD_URL` |

   Keep preview deployments limited to trusted branches. Check the first build
   log for the pinned Node and pnpm versions. Because `main` may not contain
   `build:pages` yet, its initial deployment can fail or serve pre-Phase-17
   code. That is expected and is not Phase 17 acceptance. In the Pages
   dashboard, paste the actual HTTPS URL printed for `$CLOUD_URL`; Pages does
   not expand terminal variables.

5. Push the implementation branch to trigger its trusted Pages preview. In the
   Pages project, open **Deployments**, wait for the branch deployment to finish,
   and choose its branch alias. Copy that URL, not a hash preview URL, into
   `PREVIEW_ORIGIN`. Inspect the build log for `$CLOUD_URL` and use browser
   DevTools Network to confirm the exported app calls it. The alias is not
   trusted by the API yet.

   ```sh
   export BRANCH="$(git branch --show-current)"
   git push -u origin "$BRANCH"
   export PRODUCTION_ORIGIN='https://<observed-project>.pages.dev'
   export PREVIEW_ORIGIN='https://<observed-branch-alias>.pages.dev'
   ```

   A Pages branch alias is stable for the branch, while hash URLs identify a
   particular preview deployment. Never allow all `pages.dev` origins and do
   not substitute a look-alike or hash URL for the copied alias.

## API image and exact-origin CORS candidate

6. Build the API from `apps/api` for Cloud Run's platform, push a unique tag,
   and resolve its immutable digest before deployment. The digest, rather than
   the mutable tag, is the candidate identity. Derive the existing Artifact
   Registry path from the deployed service rather than assuming its repository
   name, then authorize Docker for that regional hostname.

   ```sh
   export CURRENT_IMAGE="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
       --format='value(spec.template.spec.containers[0].image)'
   )"
   export CLOUD_IMAGE="$(printf '%s' "$CURRENT_IMAGE" | sed -E 's/@sha256:[^@]+$//; s/:[^/]+$//')"
   printf '%s\n' "$CLOUD_IMAGE"
   gcloud auth configure-docker "$CLOUD_REGION-docker.pkg.dev"
   docker buildx build --platform linux/amd64 --load \
     --tag fullstack-api:"$PHASE17_SUFFIX" apps/api
   docker tag fullstack-api:"$PHASE17_SUFFIX" "$CLOUD_IMAGE:$PHASE17_SUFFIX"
   docker push "$CLOUD_IMAGE:$PHASE17_SUFFIX"
   export CLOUD_DIGEST="$(
     gcloud artifacts docker images describe "$CLOUD_IMAGE:$PHASE17_SUFFIX" \
       --project="$CLOUD_PROJECT" --format='value(image_summary.digest)'
   )"
   export CLOUD_IMAGE_REF="$CLOUD_IMAGE@$CLOUD_DIGEST"
   printf '%s\n' "$CLOUD_IMAGE_REF"
   ```

7. Do not use `--env-vars-file`: it replaces all normal environment variables
   and risks removing existing settings such as `OPENROUTER_MODEL`. Keep secret
   mappings and the Cloud SQL attachment unchanged by leaving their flags out of
   the service update. Generate the JSON list from the one observed production
   origin.

   ```sh
   export CORS_ORIGINS="$(python3 -c 'import json, os; print(json.dumps([os.environ["PRODUCTION_ORIGIN"]]))')"
   ```

8. Use the alternate-delimiter update command below to change only CORS. This
   avoids the comma parsing conflict with the JSON array and avoids replacing
   other normal variables. The candidate receives no stable traffic and a tag;
   use a unique suffix for every retry.

   ```sh
   gcloud run services update "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --image="$CLOUD_IMAGE_REF" \
     --update-env-vars="^|^CORS_ALLOWED_ORIGINS=$CORS_ORIGINS" \
     --revision-suffix="$PHASE17_SUFFIX" \
     --no-traffic --tag=web-v1

   export CANDIDATE_REVISION="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
       --format='value(status.latestCreatedRevisionName)'
   )"
   gcloud run services describe "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format='yaml(status.traffic)'
   ```

   Discover the candidate URL and record the previous stable revision before
   promotion. The tagged URL is needed because an inactive revision has no
   normal service traffic.

   ```sh
   export ROLLBACK_REVISION="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" --format=json |
       python3 -c 'import json, sys; print(next(item["revisionName"] for item in json.load(sys.stdin)["status"]["traffic"] if item.get("percent") == 100))'
   )"
   export CANDIDATE_URL="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" --format=json |
       python3 -c 'import json, sys; tag = "web-v1"; print(next(item["url"] for item in json.load(sys.stdin)["status"]["traffic"] if item.get("tag") == tag))'
   )"
   test -n "$CANDIDATE_REVISION" && test -n "$CANDIDATE_URL"
   curl --fail --show-error "$CANDIDATE_URL/health"
   curl --include --request OPTIONS "$CANDIDATE_URL/auth/login" \
     --header "Origin: $PRODUCTION_ORIGIN" \
     --header 'Access-Control-Request-Method: POST' \
     --header 'Access-Control-Request-Headers: Authorization, Content-Type'
   ```

   Verify a `200` preflight with the exact production
   `Access-Control-Allow-Origin`; its allowed methods must include `POST` and
   its allowed headers must include `Authorization` and `Content-Type`. `health`
   alone does not prove Cloud SQL-backed application behavior.

9. Promote only after the tagged candidate is healthy and its preflight is
   correct. Test the stable API URL after promotion; a candidate tag by itself
   does not change stable traffic.

   ```sh
   gcloud run services update-traffic "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --to-revisions="$CANDIDATE_REVISION=100"
   export CLOUD_URL="$(
     gcloud run services describe "$CLOUD_SERVICE" \
       --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
       --format='value(status.url)'
   )"
   curl --include --request OPTIONS "$CLOUD_URL/auth/login" \
     --header "Origin: $PRODUCTION_ORIGIN" \
     --header 'Access-Control-Request-Method: POST' \
     --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    ```

   Recheck the revision's Cloud SQL connection, secret references, and
   non-secret variables in the console. If any are absent, stop before browser
   acceptance and correct the deployment configuration; do not add secrets or
   connection flags speculatively.

## Preview trust exercise and browser acceptance

10. Prove that the unlisted preview is denied. Request a preflight with the
    actual preview alias and inspect both the command result and the browser.

    ```sh
    curl --include --request OPTIONS "$CLOUD_URL/auth/login" \
      --header "Origin: $PREVIEW_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    ```

   The denied preflight must be `400` and must not contain an allow-origin
   header for that alias.
    In a browser opened at the preview URL, try sign-up or sign-in and confirm
    DevTools reports blocked response access. A simple request may still have
    an HTTP status, because CORS controls browser access to its response; this
    is different from an API authentication or server failure.

11. Add only this copied branch alias, making a fresh revision, then promote it
    after its tagged preflight succeeds. Keep the production origin in the list.

    ```sh
    export CORS_ORIGINS="$(python3 -c 'import json, os; print(json.dumps([os.environ["PRODUCTION_ORIGIN"], os.environ["PREVIEW_ORIGIN"]]))')"
    export PREVIEW_SUFFIX="preview-$(date +%Y%m%d%H%M%S)"
    gcloud run services update "$CLOUD_SERVICE" \
      --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
      --image="$CLOUD_IMAGE_REF" \
      --update-env-vars="^|^CORS_ALLOWED_ORIGINS=$CORS_ORIGINS" \
      --revision-suffix="$PREVIEW_SUFFIX" --no-traffic --tag=preview-cors

    export PREVIEW_CANDIDATE_REVISION="$(
      gcloud run services describe "$CLOUD_SERVICE" \
        --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
        --format='value(status.latestCreatedRevisionName)'
    )"
    export PREVIEW_CANDIDATE_URL="$(
      gcloud run services describe "$CLOUD_SERVICE" \
        --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" --format=json |
        python3 -c 'import json, sys; tag = "preview-cors"; print(next(item["url"] for item in json.load(sys.stdin)["status"]["traffic"] if item.get("tag") == tag))'
    )"
    test -n "$PREVIEW_CANDIDATE_REVISION" && test -n "$PREVIEW_CANDIDATE_URL"
    curl --include --request OPTIONS "$PREVIEW_CANDIDATE_URL/auth/login" \
      --header "Origin: $PREVIEW_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    ```

    Stop here unless the tagged preflight is `200`, returns the exact preview
    `Access-Control-Allow-Origin`, permits `POST`, and allows `Authorization`
    and `Content-Type`. Then promote this revision and verify the stable URL.

    ```sh
    gcloud run services update-traffic "$CLOUD_SERVICE" \
      --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
      --to-revisions="$PREVIEW_CANDIDATE_REVISION=100"
    curl --include --request OPTIONS "$CLOUD_URL/auth/login" \
      --header "Origin: $PREVIEW_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    ```

   Retest in a fresh browser profile or context: the browser can cache a
   successful preflight. Sign in again after moving between preview and
   production because auth tokens are stored in per-origin local storage.

12. Run the preview journey using normal UI operations and disposable accounts,
    never E2E fixtures or test reset endpoints:

    - Sign up, sign in, create a clearly named todo, edit it, complete it, and
      reload while it still exists to confirm persistence. Sign out, sign in as
      a second account, and confirm that named todo is absent. Return to the
      first account and delete the todo only after the isolation check.
    - Start the guided workflow and a bounded live AI suggestion. Confirm the
      suggested action through the normal UI and observe AG-UI streaming in
      DevTools across the browser boundary. Exercise cancellation and
      refresh/resume using the app's existing semantics.

    Record provider/model cost settings and any unavailable live-AI prerequisite
    rather than inventing a result. This sandbox shares one Cloud Run API and
    Cloud SQL database between Pages production and preview, so use disposable
    data.

## Production deployment, hosting checks, and rollback

13. When preview evidence and required CI checks are ready, you may merge the
    implementation PR if you are authorized to do so, or ask the agent to do
    it. Confirm Pages builds the intended `main` commit, then repeat the
    preview journey on the exact production `pages.dev` origin.

14. Check the assigned production hostname, without adding a custom domain or
    changing DNS. Record the hostname, certificate result, HTTP redirect, and
    exact API CORS origin.

    ```sh
    curl -I "http://${PRODUCTION_ORIGIN#https://}"
    curl -I "$PRODUCTION_ORIGIN/"
    curl -I "$PRODUCTION_ORIGIN/phase17-refresh-check"
    ```

    In DevTools, confirm the root reloads, `/phase17-refresh-check` receives
    the app shell rather than a server 404, JavaScript and CSS responses use
    their real MIME types, and the production console has no new errors. Check
    the response headers for `X-Content-Type-Options`, `X-Frame-Options`,
    `Referrer-Policy`, `Permissions-Policy`, and the limited CSP. Inspect the
    preview response for `X-Robots-Tag: noindex` or the Pages preview noindex
    behavior. Use a fresh deployment and hard refresh to observe the intended
    asset version and avoid a stale-page error.

15. Perform the frontend rollback drill only after there are two successful
    production Pages deployments. Record each deployment ID and commit. A
    harmless guide-only commit may produce the second deployment if needed;
    obtain authorization before making or merging it. In Pages, roll production
    back to the first successful deployment, verify the selected deployment ID
    and application behavior, then restore the second. Do not invent visible
    app version labels for this drill.

    If Cloud Run also needs a rollback, use the separately recorded
    `ROLLBACK_REVISION` with `gcloud run services update-traffic`. That changes
    API traffic only. It neither rolls Pages back nor reverses migrations or
    other Cloud SQL data changes.

16. Remove the temporary preview alias after the exercise by returning CORS to
    the production origin alone in a fresh, tagged API revision. Test that the
    preview preflight is denied, the production preflight and browser flow
    remain successful, and remove disposable todos through the normal UI.

    ```sh
    export CORS_ORIGINS="$(python3 -c 'import json, os; print(json.dumps([os.environ["PRODUCTION_ORIGIN"]]))')"
    export CLEANUP_SUFFIX="cleanup-$(date +%Y%m%d%H%M%S)"
    gcloud run services update "$CLOUD_SERVICE" \
      --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
      --image="$CLOUD_IMAGE_REF" \
      --update-env-vars="^|^CORS_ALLOWED_ORIGINS=$CORS_ORIGINS" \
      --revision-suffix="$CLEANUP_SUFFIX" --no-traffic --tag=cleanup-cors

    export CLEANUP_CANDIDATE_REVISION="$(
      gcloud run services describe "$CLOUD_SERVICE" \
        --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
        --format='value(status.latestCreatedRevisionName)'
    )"
    export CLEANUP_CANDIDATE_URL="$(
      gcloud run services describe "$CLOUD_SERVICE" \
        --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" --format=json |
        python3 -c 'import json, sys; tag = "cleanup-cors"; print(next(item["url"] for item in json.load(sys.stdin)["status"]["traffic"] if item.get("tag") == tag))'
    )"
    test -n "$CLEANUP_CANDIDATE_REVISION" && test -n "$CLEANUP_CANDIDATE_URL"
    curl --include --request OPTIONS "$CLEANUP_CANDIDATE_URL/auth/login" \
      --header "Origin: $PRODUCTION_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    curl --include --request OPTIONS "$CLEANUP_CANDIDATE_URL/auth/login" \
      --header "Origin: $PREVIEW_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    ```

    Stop unless the production candidate preflight is `200` with the exact
    production allow-origin and the preview preflight is `400` without an
    allow-origin header. Then promote it, recheck the stable URL, and remove
    the temporary tags.

    ```sh
    gcloud run services update-traffic "$CLOUD_SERVICE" \
      --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
      --to-revisions="$CLEANUP_CANDIDATE_REVISION=100"
    curl --include --request OPTIONS "$CLOUD_URL/auth/login" \
      --header "Origin: $PRODUCTION_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    curl --include --request OPTIONS "$CLOUD_URL/auth/login" \
      --header "Origin: $PREVIEW_ORIGIN" \
      --header 'Access-Control-Request-Method: POST' \
      --header 'Access-Control-Request-Headers: Authorization, Content-Type'
    gcloud run services update-traffic "$CLOUD_SERVICE" \
      --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
      --remove-tags=web-v1,preview-cors,cleanup-cors
    ```

   In a fresh browser context, verify the preview is denied and production
   remains successful. The application has no account deletion endpoint; record
   that account-retention limitation instead of adding one for this walkthrough.

## Acceptance record

17. Fill this table only with observed, redacted evidence. Include date,
    URL/origin, commit, API image digest or revision, Pages deployment ID, and
    result for every completed row. All rows are pending until then.

| ID | Result | Required observed evidence |
| --- | --- | --- |
| A1 | Pending | Invalid/missing API target fails before export; valid target builds; output has intended public target and no server secrets. |
| A2 | Pending | Preview and production Pages builds use pinned tools, frozen lockfile, correct root/output, and separate API targets. |
| A3 | Pending | Local CORS passes; hosted allowlist excludes localhost and rejects unrelated, deceptive-suffix, and unlisted preview origins. |
| A4 | Pending | Browser denied preview, exact-alias grant, browser success, alias removal, and renewed denial. |
| A5 | Pending | Assigned production `pages.dev` hostname over HTTPS, valid certificate, HTTP redirect, and distinct preview/production deployments. |
| A6 | Pending | Root refresh, unmatched-path shell fallback, correct JS/CSS MIME types, and no console regression. |
| A7 | Pending | Required headers, preview noindex, and fresh-deployment cache behavior. |
| A8 | Pending | Hosted signup/login, todo CRUD, reload persistence, sign-out, and second-user isolation. |
| A9 | Pending | Hosted guided workflow and bounded AI/AG-UI stream, confirmation, cancellation, and refresh/resume. |
| A10 | Pending | Repository quality and existing local Playwright suite pass; native behavior remains unchanged. |
| A11 | Pending | Pages production rollback and restoration, each with observed deployment ID and commit. |
| A12 | Pending | Preview origin removal, test-data cleanup, final API/Pages state, shared-data note, costs, and remaining gaps. |

Record the assigned hostname, final image digest, API revision, Pages deployment
IDs, traffic, rollback observations, and cost settings with the table. Do not
mark Phase 17 complete or name Phase 18 as next until the learner reports the
required manual checks passed.

<!-- markdownlint-enable MD029 -->

## Troubleshooting

| Symptom | Check and recovery |
| --- | --- |
| Pages cannot find the output | Confirm root is the repository root, command is `pnpm install --frozen-lockfile && pnpm build:pages`, and output is `apps/mobile/dist`. |
| Wrong Node or pnpm in build log | Stop the deployment and set the documented `NODE_VERSION` and `PNPM_VERSION`; do not change repository pins to fit an image. |
| Browser bundle calls localhost or old API | Set the correct environment-specific `EXPO_PUBLIC_API_URL`, trigger a fresh build, and inspect Network. The value is baked in at export time. |
| API URL changed after Pages build | Rebuild the affected Pages environment; changing Cloud Run alone cannot rewrite an already exported bundle. |
| Preflight omits `Authorization` | Send the OPTIONS request with both requested headers, then check the exact CORS JSON and promoted revision; do not add frontend CORS headers. |
| Pages hostname or certificate is unavailable | Wait for the assigned `pages.dev` deployment to become active, verify it in Pages, and use its copied hostname. Do not substitute a custom domain. |
| Browser says CORS while curl has an API status | Inspect allow-origin and preflight headers. CORS blocks browser response access; an API error is a server/auth response and needs its own diagnosis. |
| Candidate tag URL is unavailable | Inspect `status.traffic`, use the tag URL, and keep the revision tagged. An inactive revision cannot be tested through the stable URL. |

## Sources

- [Expo web export and public assets](https://docs.expo.dev/guides/publishing-websites/)
- [Cloudflare Pages build image and version overrides](https://developers.cloudflare.com/pages/configuration/build-image/)
- [Cloudflare Pages preview deployments](https://developers.cloudflare.com/pages/configuration/preview-deployments/)
- [Cloudflare Pages serving, SPA fallback, and caching](https://developers.cloudflare.com/pages/configuration/serving-pages/)
- [Cloudflare Pages headers](https://developers.cloudflare.com/pages/configuration/headers/)
- [Cloudflare Pages rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/)
- [Cloud Run rollouts, revisions, and traffic](https://cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)
- [gcloud list/dictionary flag escaping](https://cloud.google.com/sdk/gcloud/reference/topic/escaping)
