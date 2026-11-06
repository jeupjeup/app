# Account-scoped data MVP — Codex-Primary

Base: PM `92d6364`. Role instructions: `CLAUDE.md`, `.claude/agents/codex-primary.md`.

## Result and schema

The existing core already stores `user_id` on contents, collections, jobs, analysis candidates,
URL fingerprints, idempotency keys and per-user index revisions. Existing repository/service
ownership predicates and per-user search indexes are reused, rather than rebuilding these tables.
The compatibility `/api` content store also already filters by its authenticated `api_users.id`.

One additive table connects these identities explicitly:

```sql
account_scopes (
  account_id TEXT PRIMARY KEY REFERENCES api_users(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL UNIQUE CHECK(user_id LIKE 'u_account_%')
)
```

`storage/account_migration.py` runs after the existing core, app API and OAuth migrations.
It uses a single `BEGIN IMMEDIATE` transaction, backfills only account mappings for existing
`api_users`, and installs two triggers. Account registration (password or OAuth) atomically creates
its scope. Account deletion removes its scoped collections, contents, idempotency keys and index
revisions; existing content foreign keys cascade to snapshots, analysis, jobs and membership data.

The scope remains `u_account_` + the account UUID without hyphens, preserving PM's already-issued
session identity and any content previously written through that session adapter. No content,
collection or job ownership is rewritten. Ordinary `u_frontend_dev`, `u_alice`, etc. demo/legacy
rows stay in their existing namespaces; there is no assignment to the first person who logs in.
The migration is idempotent. A database missing it is rejected when `auto_migrate=False`.
Existing migration checksums and seed files are untouched. Back up the SQLite database before
upgrading; do not downgrade after accepting account writes without restoring a compatible backup.

## API and security

- All `/v1` principals come from the opaque persisted Bearer session or the explicitly configured
  development adapter. Bearer authentication resolves the durable scope through `account_scopes`.
- A present but invalid, expired or revoked Authorization header returns 401 and cannot fall back
  to `X-User-Id`. Missing identity now returns 401 rather than the old `MISSING_USER` 400.
- Development headers cannot select any `u_account_` scope. They can read legacy/demo data and
  invoke read-only search/query parsing, but every mutation, including dev admin writes, needs
  a real session. Production still rejects `auth_backend=dev_header` at startup.
- Content list/search/detail/patch/delete/reanalysis, collections/membership, jobs, candidates and
  trace reads continue to use the same authenticated scope. Foreign resource IDs receive 404.
  Request validation may return 422 for malformed payloads independently of record existence.
- URL deduplication and idempotency are per scope: two accounts can save the same URL and key.
- `/api` compatibility records and `/v1` core records remain separate stores; this does not copy
  compatibility content into the ingest/search pipeline or implicitly import demo data.
- Existing OAuth secrets, cookies and exchange mechanics are unchanged. No secret files were read
  or added. The new schema stores account IDs only, not credentials or raw session tokens.

## Browser/session behavior

The transport reads the persisted session for each request and sends `Authorization: Bearer ...`.
Anonymous mutation requests no longer attach an implicit development identity; demo reads retain it.
Session storage survives reload. Same-tab session notifications and cross-tab storage notifications
switch archive, detail, collection, search and job query keys to the active account ID. Cached data
from a previous account is not rendered under the next account's queries.

The existing settings account control now performs logout: it attempts server revocation and clears
local storage even if the network request fails, then navigates to login. Only authentication copy
and wiring changed there. Archive UI structure, cards, layout and all CSS were left untouched.

## Webpages stuck in “분석 중”

Two concrete paths were found: `create_app` intentionally only submitted jobs, so running the API
without a separate worker left new jobs queued; the archive feed did not poll pending rows, so even
completed jobs could retain their initial presentation until a refetch.

`jupjup api serve` now defaults to `--with-worker`. An application lifespan starts the existing
lease-aware/retrying worker and signals it to stop on shutdown. It does not execute analysis inside
the HTTP request. The archive feed polls every two seconds while loaded rows contain pending work.
Terminal failures and confirmation waits keep their existing distinct states and UI.

Programmatic/ASGI `create_app` retains submit-only behavior by default (`embedded_worker=False`),
so existing separate-worker deployments and test harnesses stay valid. Start it with
`JUPJUP_EMBEDDED_WORKER=true` or explicitly configure `Settings(embedded_worker=True)` for a
single-process setup. For a separate worker:

```sh
uv run jupjup api serve --db var/jupjup.db --no-worker
uv run jupjup worker run --db var/jupjup.db
```

Both processes must use the same database, analyzer and model configuration. Missing model/runtime
configuration is surfaced through existing failed job handling; mock analysis remains explicitly
mock and is not substituted for unavailable real models.

## Verification

- Real-session integration test (`test_account_scoping.py`, no authentication override): two
  accounts, preserved demo content/collection, rejected anonymous/admin writes, Bearer precedence,
  account namespace spoof rejection, same-URL/key isolation, foreign content/search/patch/delete/
  reanalysis/collection/membership/job trace 404s, owned patch/delete, logout revocation, account
  deletion cascade, migration opt-out/idempotence and SQLite foreign-key integrity.
- A file-backed SQLite test starts the actual lifespan worker, fetches a webpage through offline
  HTTP transport, observes `queued` → `succeeded`/`ready`, and finds it only in its owner's search.
- Existing seed-based API tests now explicitly import `tests.legacy_api.create_app`, which injects
  their trusted test principals. This bypass is test-only. Real-session/OAuth/security tests use
  the actual application factory and dependency chain.
- Focused account/OAuth/migration tests: **50 passed**. Other focused API/search/save/worker/
  compatibility regressions: **149 passed**.
- Frontend `npm run check`: **59 tests passed**; typecheck passed; lint has only the eight existing
  Fast Refresh/effect warnings in unrelated archive files. Tests cover session reload, logout
  success/network failure, Bearer attachment and account cache switching.
- Frontend `npm run build`: passed. Backend `uv run mypy`: passed (130 source files).
  Backend `uv run ruff check src tests` and `git diff --check`: passed. CLI help confirms the
  worker default and explicit opt-out.
- Initial complete backend run: 1679 passed, 9 failed, 2 skipped, 5 deselected. Three failures were
  tests collected before their new 401/patch expectations were corrected; the focused reruns pass.
  The other six failures also reproduce unchanged in an isolated `git archive 92d6364` baseline:
  one stale empty-source error expectation (`INGEST_EXTRACT_FAILED` vs `SOURCE_TEXT_UNAVAILABLE`)
  and five golden-ingest seal/report failures (committed `764aaf...` vs computed `303826...`).
  Golden source data and seal files were deliberately not modified.
- Final complete regression run with those six independently confirmed baseline failures excluded:
  **1682 passed, 2 skipped, 11 deselected** (147.02 seconds). The 11 deselections comprise
  the six baseline failures and five existing optional model-test exclusions.

Baseline failures:

```text
tests/integration/test_ingest_record_replay.py::test_empty_fixture_becomes_a_failed_item_instead_of_stopping_the_run
tests/integration/test_ingest_record_replay.py::test_recorded_report_carries_golden_hash_and_compares_with_itself
tests/unit/test_ingest_golden_v2.py::test_test_seal_tracks_test_gold_but_not_review_status_or_dev
tests/unit/test_ingest_golden_v2.py::test_generator_reproduces_committed_files
tests/unit/test_ingest_golden_v2.py::test_validate_ingest_cli_exit_codes
tests/unit/test_ingest_golden_v2.py::test_l1_build_refuses_to_reseal_without_reason
```

## Limits and design deviations

This is an MVP reuse of the existing `user_id` schema, not a table-wide owner-column migration.
The original PRD's development-header write behavior is intentionally superseded by authenticated
sessions. Deployment must disable development authentication (`auth_backend=app_session`) to hide
legacy demo reads, and keep admin API exposure disabled outside development as before.

Real provider OAuth, external webpage availability and real local-model inference were not exercised
with live credentials/models. The webpage regression uses deterministic mock analysis and fake HTTP.
An ASGI deployment opting out of the embedded worker must supervise its separate worker; SQLite job
leases support restart recovery, but this is not a distributed queue or worker monitoring system.
Shutdown waits up to five seconds before leaving an in-flight worker to normal process shutdown and
lease recovery. Offline logout clears this browser's token but cannot guarantee remote revocation;
the server session otherwise expires under the existing policy. Bearer persistence remains in
localStorage, so existing XSS/browser-profile protections remain important.

No Reviewer feedback was supplied. Ready for PM/reviewer integration; no merge or deployment done.

## Changed files

- `frontend/src/features/archive/queries.ts`
- `frontend/src/pages/archive/SearchResultsPage.tsx`
- `frontend/src/pages/settings/SettingsPage.tsx`
- `frontend/src/shared/api/client.test.ts`
- `frontend/src/shared/api/client.ts`
- `frontend/src/shared/auth/scope.test.tsx`
- `frontend/src/shared/auth/session.test.ts`
- `frontend/src/shared/auth/session.ts`
- `specs/account_scoping_report.md`
- `src/jupjup/api/app.py`
- `src/jupjup/auth.py`
- `src/jupjup/cli.py`
- `src/jupjup/config.py`
- `src/jupjup/storage/account_migration.py`
- `src/jupjup/storage/db.py`
- `tests/integration/test_account_scoping.py`
- `tests/integration/test_api_ingest.py`
- `tests/integration/test_api_ingest_worker_split.py`
- `tests/integration/test_api_search.py`
- `tests/integration/test_instagram_metadata.py`
- `tests/integration/test_live_llm_save.py`
- `tests/integration/test_save_acceptance.py`
- `tests/integration/test_save_api.py`
- `tests/integration/test_youtube_metadata.py`
- `tests/legacy_api.py`
- `tests/unit/test_save_auth.py`
