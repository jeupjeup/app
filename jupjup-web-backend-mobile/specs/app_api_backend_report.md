# App API backend contract report

## Source and scope

Implemented against base PM commit `ef36395` in the existing Python/FastAPI/SQLite application. Read the entire supplied `/Users/minjun/Downloads/message (5).txt` (3559 lines) before editing. `specs/app_api_openapi.json` is a byte-for-byte copy of that input, retained as the authoritative contract and used directly by response-schema tests.

The request says **25 operations**, but the supplied OpenAPI `paths` contains **24 operations** (17 distinct paths). All 24 supplied operations are implemented. There is no specified 25th operation to implement; no additional product behavior was invented. This is the only unavoidable discrepancy with the requested operation count.

Only backend source, tests, and specs changed. Existing `/v1` authentication, ingest jobs, AI analysis/worker behavior, search, manual collections, and frontend files remain unchanged. No real database was opened, external network request made, service started, or push performed. Dependency/test commands used `uv run --offline`; databases used by the new tests are in-memory SQLite.

## Integration and persistence

`api/app.py` mounts an isolated FastAPI sub-application at `/api`. Its transport and errors cannot replace `/v1` validation, authentication, or response handlers. The compatibility application deliberately has no generated documentation route: the supplied OpenAPI artifact above is authoritative.

`storage/db.py` runs `storage/app_api_migration.py` on the **same SQLAlchemy SQLite engine** after the existing migration chain. Additive tables:

- `api_users`: UUID, unique normalized email, nickname, optional notification preference, consent timestamp, salted password hash, shared password-verification/change failure counter and lock deadline.
- `api_sessions`: SHA-256 token digest, account FK, expiration timestamp.
- `api_contents`: account-scoped bookmarks, editable fields, saved/deleted/viewed timestamps, unique partial index on `(user_id,url)` for active entries.
- `api_notices`: account-scoped persistent in-app notices.
- `api_search_history`: account-scoped distinct query strings with monotonic recency sequence.
- `api_rate_limits`: durable peer-IP counters and minute-window start.
- `app_api_migrations`: checksummed compatibility schema migration ledger.

The separate **ledger namespace**, not a separate database, preserves the immutable v27–v29 source checksums and the existing v29 version validator/CLI behavior. The existing main schema version remains 29; the compatibility extension version is 1. Migration uses `BEGIN IMMEDIATE`, verifies its checksum and foreign keys, is idempotent, and respects `auto_migrate=False`. Account-related FKs cascade. Migration and request transactions use SQLite serialization; a process-local lock additionally protects the existing in-memory `StaticPool` connection. No legacy rows are imported into invented email identities.

Modules separate transport/rate/CORS (`http.py`), credentials/sessions (`auth.py`), field/URL validation (`validation.py`), account-scoped DTO/read mapping (`repository.py`), and operations (`service.py`).

## Operation mapping

All paths below are prefixed with `/api`. Bodyless successes have zero response bytes.

| Method and path | operationId | Success | Behavior / DTO |
| --- | --- | --- | --- |
| GET /health | health | 200 | Real DB check; `{status:"ok"}`; public |
| POST /auth/register | register | 201 | Required consent, normalized email, salted credentials and 30-day Session in one transaction; public |
| POST /auth/login | login | 200 | Credentials → new Session; public |
| POST /auth/logout | logout | 204 | Delete only the current bearer session |
| GET /state | getState | 200 | User, all owned contents including trash, notices, history, active savedCount |
| GET /me | getMe | 200 | User |
| PATCH /me | updateMe | 200 | Nickname update → User |
| DELETE /me | deleteMe | 204 | Account and associated data/session cascade |
| POST /me/password/verify | verifyPassword | 204 | Verify current password; durable shared failure/lock semantics |
| PATCH /me/password | changePassword | 204 | Verify current password, hash new password; revoke all other sessions |
| POST /contents | createContent | 201 | Normalize URL, reject active duplicate, persist bookmark and notice atomically → Content |
| GET /contents | listContent | 200 | Full ContentList; q/collection/type/deleted/sort filters |
| GET /contents/{id} | getContent | 200 | Owned Content, including trash |
| PATCH /contents/{id} | updateContent | 200 | Only supplied title/memo/type/collection fields; null clears collection; trash → 409 |
| DELETE /contents/{id} | deleteContent | 204 | Soft delete; preserve first deletion timestamp |
| POST /contents/{id}/restore | restoreContent | 200 | Clear deletedAt, enforce active-URL uniqueness → Content |
| POST /contents/{id}/view | viewContent | 204 | Record viewedAt; trash → 409 |
| DELETE /trash | emptyTrash | 204 | Permanently delete only this account's trash |
| GET /notices | listNotices | 200 | Owned Notices |
| POST /notices/read | readAllNotices | 204 | Mark only owned notices read |
| POST /notices/{id}/read | readNotice | 204 | Mark one owned notice read |
| GET /search-history | getSearchHistory | 200 | History, newest first |
| POST /search-history | addSearchHistory | 200 | Deduplicate, promote query, retain newest 10 → History |
| DELETE /search-history | clearSearchHistory | 204 | Clear only owned history |

## Security, validation and fidelity

- Session tokens are 32 cryptographically random bytes encoded as 64 lowercase hex characters. Only their SHA-256 digests are persisted. Sessions expire at issuance plus 30 days, with an exclusive expiration boundary; logout and account deletion revoke access immediately.
- Passwords use scrypt (`N=16384, r=8, p=1, dklen=64`) with an independent random 16-byte salt per credential write. Comparison is constant-time. Unknown email login performs the same expensive derivation and returns the same `INVALID_CREDENTIALS` envelope as a wrong password.
- Verification/change share an account-level counter across sessions. First four failures return 401; the fifth persists a 24-hour deadline and returns 429 `PASSWORD_LOCKED`. Correct verification resets the counter. Expired locks start a fresh failure count. Login neither consults nor resets this counter. Password changes retain only the requesting session.
- Auth/password paths share a durable per-peer-IP fixed 60-second window capped at 30 requests; request 31 returns 429 `RATE_LIMITED`. Different IPs have separate limits. Malformed requests count. Forwarded headers cannot select a different limiter key inside this application. Deployment proxies must be configured with trusted peer handling at the ASGI server layer.
- POST/PATCH require `application/json` (case-insensitive media type, parameters permitted), a UTF-8 JSON object, and at most 16,384 raw body bytes. Streaming bodies receive the same cap. Empty/malformed/invalid UTF-8/nonfinite JSON returns `INVALID_JSON`; valid nonobject JSON and invalid fields return `VALIDATION_ERROR`. Unsupported media returns 415; oversized JSON returns 413.
- Strict string/boolean checks prevent coercion. Text field lengths, enums, consent=true, optional defaults, nullable collection, and the exact registration/new-password alphabet and pattern follow the schemas. Text values retain their supplied whitespace; lengths are checked without silently truncating input. Extra properties are ignored, consistent with the schemas allowing additional properties. Current/login passwords retain all characters and use the distinct 1–128 limit.
- HTTP(S) URLs are parsed locally; no fetch occurs. Normalize scheme/host case, IDNA hostnames, IPv6, default ports, empty path, dot segments and Unicode path/query encoding; remove fragments. Reject credentials, invalid ports/hosts, malformed escapes, controls, whitespace and backslashes. Persist the normalized URL as the duplicate key. Title/source use the normalized hostname (without a nondefault port); optional port remains in the stored URL.
- CORS uses exact comma-separated `CORS_ORIGINS`. Unset means no cross-origin callers are allowed; same-origin/native callers without Origin remain permitted. Allowed origins receive matching headers on successes/errors and preflight; disallowed origins get 403 `ORIGIN_FORBIDDEN`. Allowed request headers are Authorization and Content-Type; methods are GET/POST/PATCH/DELETE/OPTIONS. Responses use `Cache-Control: no-store`.
- Resource lookup always constrains both ID and authenticated user ID. Invalid, missing, and another account's IDs return identical 404 `NOT_FOUND` envelopes. Development `X-User-Id` does not authenticate `/api`.
- Active URL uniqueness is enforced by SQLite as well as explicit duplicate checks, including restoration. Deleted copies may coexist with a newly saved active bookmark. Concurrent duplicate creates yield one content and one notice.
- Before API request dispatch, purge contents deleted at least 30 days ago and expired sessions. Repeat deletion never extends retention. State includes unexpired trash but savedCount excludes it. Notices remain historical records when a content is purged.
- Content creation always returns type=기타, status=ready, description="", tags=[]; no image/pendingSync fields, claimed AI results, metadata lookup, recommendation, push, or upload/download behavior is synthesized. `collection`, `deletedAt`, and `viewedAt` are omitted when unset. Dates use UTC ISO 8601 with milliseconds. Notices use the supplied “정보를 저장했어요” title and URL hostname description.
- Errors use exactly `{error:{code,message}}`, with the contract's generic Korean message. Internal exception details stay out of responses. Writes roll back on failure, including content insertion when notice insertion fails. Password failure increments intentionally commit despite the failed authentication response.

The document does not specify a CORS default, window algorithm, tie-breaking order, or normalization algorithm beyond its stated URL constraints. The concrete choices above make these deterministic. Newest content/notices use insertion order for equal timestamps; oldest reverses saved order; recent places viewed items first and falls back to newest saved order. Keyword matching is case-insensitive substring matching over title/memo/description/tags, with no AI search. No functional operation from the supplied contract was omitted.

## Validation results

- New tests cover every contract operation and validate successful DTOs against the original OpenAPI JSON, plus auth/hash/session expiry/revocation, persistent password locks, user isolation and identical 404s, lifecycle/duplicates/restoration/trash/purge boundaries, notices/history/state, field/query/body/URL validation, streaming size limits, CORS, persistent per-IP rate limits, notice rollback, concurrent duplicate writes, migration checksums, and a combined `/api` + existing `/v1` smoke test.
- Focused command: `uv run --offline pytest tests/integration/test_app_api.py tests/integration/test_api_search.py tests/integration/test_api_ingest.py tests/integration/test_api_ingest_worker_split.py tests/integration/test_save_api.py tests/unit/test_save_migration.py tests/unit/test_instant_migration.py tests/unit/test_collections_migration.py`.
- `uv run --offline ruff check src tests` and `uv run --offline mypy` cover backend/tests and the entire Python package respectively.
- `ruff check .` additionally finds 11 pre-existing issues in `frontend/scripts/smoke_local_api.py`. That file was not modified because frontend changes are explicitly out of scope. The backend/tests lint scope passes.
- Final focused run: **153 passed** (61 new compatibility tests plus 92 existing regressions); one existing Starlette/httpx deprecation warning. Backend/tests ruff passes. Full-package mypy passes for **126 source files**. `git diff --check` and staged diff checks pass; original contract copy matches byte-for-byte.
