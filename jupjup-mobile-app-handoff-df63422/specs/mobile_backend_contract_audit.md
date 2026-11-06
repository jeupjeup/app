# Mobile ↔ Backend contract audit (Phase 10, read-only)

Author: Claude-Architect · Base: PM `8e822b9` · Machine-readable matrix: `specs/mobile_backend_contract_matrix.json`

## 0. 요약 (PM/사용자용)

- **The backend implements this spec.** `message (5).txt` is **byte-identical** to `specs/app_api_openapi.json` (sha256 `cd18e859669a7528…`). That file is the contract the `/api` layer was built and tested against (commit `37979ff`). All **24 operations** and **17 schemas** match exactly. The existing 100 integration tests pass, and they validate every success response against this file (`test_app_api.py`, `test_account_scoping.py`, `test_social_oauth.py`).
- **An app built against the spec can't reach the server from a real phone yet.** `jupjup api serve` refuses to bind to any non-loopback address. There is a safe workaround that needs no code change (§8.2), and Phase 11 fixes it properly.
- **The one dangerous problem is two separate content stores.** A URL saved through `/api/contents` gets no AI analysis, can't be found by `/v1/search`, and never appears on the web dashboard. The reverse holds too: web saves never show up in `/api/state`. Both sides use the same account and the same token. I confirmed this on a live server. Fixing it (Phase 12) needs a product decision first.
- Gap counts across 22 cross-cutting items: **exact 7 · adapter 4 · richer 4 · missing 4 · dangerous 3** (operations 24/24 exact, schemas 17/17 exact).

## 1. Scope and method

- Read the full input OpenAPI 3.1 (3559 lines). Then extracted every path, operation, parameter, request/response schema, security override, status code and `x-` annotation with a script.
- Read the implementation: `src/jupjup/app_api/{http,service,auth,validation,repository,errors,oauth}.py`, `src/jupjup/auth.py`, `src/jupjup/api/app.py`, `src/jupjup/save/routes.py`, the migrations (`app_api_migration.py`, `account_migration.py`), `cli.py api serve`, `config.Settings`, and the frontend API/session clients.
- Ran the existing tests (100 passed). Probed edge cases with TestClient: trailing slash, HEAD, Origin variants, empty bodies, lowercase `bearer`.
- Booted the real `create_app` on loopback with a temporary mock DB (`JUPJUP_AUTH_BACKEND=app_session`) and exercised `/api` and `/v1` with one token.
- No `src/` or `frontend/` changes. No secrets were read or printed: OAuth client IDs/secrets come only from env and were not inspected.

Classification legend:
- **exact** — behaviour matches the spec.
- **adapter** — compatible once a config value or thin mapping is in place.
- **richer** — the backend has a stronger replacement outside the contract.
- **missing** — not present.
- **dangerous** — a mismatch that breaks correctness or security.

## 2. Operation matrix (all under `/api`)

| # | Method Path | operationId | Auth | Spec 2xx | Impl 2xx | Class | Notes / richer `/v1` |
|---|---|---|---|---|---|---|---|
| 1 | GET /health | health | none | 200 | 200 | exact | Pings the DB. `/healthz` is richer (index readiness, 503 while starting). |
| 2 | POST /auth/register | register | none | 201 | 201 | exact | Email lowercased; scrypt + per-user salt; 409 `EMAIL_EXISTS`; rate-limited. |
| 3 | POST /auth/login | login | none | 200 | 200 | exact | Same 401 for unknown email and wrong password, with equal hashing cost. |
| 4 | POST /auth/logout | logout | bearer | 204 | 204 | exact | **Must send `Content-Type: application/json` and body `{}`.** |
| 5 | GET /state | getState | bearer | 200 | 200 | exact | Full snapshot including trash; `savedCount` excludes trash. Shows `api_contents` only (X12). |
| 6 | GET /me | getMe | bearer | 200 | 200 | exact | |
| 7 | PATCH /me | updateMe | bearer | 200 | 200 | exact | |
| 8 | DELETE /me | deleteMe | bearer | 204 | 204 | exact | Also deletes the account's core `/v1` data via the `account_scopes` trigger. |
| 9 | POST /me/password/verify | verifyPassword | bearer | 204 | 204 | exact | 5 failures → 24h 429 `PASSWORD_LOCKED`. |
| 10 | PATCH /me/password | changePassword | bearer | 204 | 204 | exact | Revokes the user's other sessions. |
| 11 | POST /contents | createContent | bearer | 201 | 201 | exact | Bookmark only (`ready`, `기타`, empty description/tags). `/v1/contents` is richer: 202 + AI job, url/text/image sources. |
| 12 | GET /contents | listContent | bearer | 200 | 200 | exact | Substring `q`. `/v1/search` is richer (semantic). |
| 13 | GET /contents/{id} | getContent | bearer | 200 | 200 | exact | Malformed ID and another user's ID both return 404. |
| 14 | PATCH /contents/{id} | updateContent | bearer | 200 | 200 | exact | `collection:null` clears the value; returns 409 on trashed items. |
| 15 | DELETE /contents/{id} | deleteContent | bearer | 204 | 204 | exact | Soft delete. `/v1` DELETE is a hard delete. |
| 16 | POST /contents/{id}/restore | restoreContent | bearer | 200 | 200 | exact | 409 on active-URL conflict. |
| 17 | POST /contents/{id}/view | viewContent | bearer | 204 | 204 | exact | |
| 18 | DELETE /trash | emptyTrash | bearer | 204 | 204 | exact | |
| 19 | GET /notices | listNotices | bearer | 200 | 200 | exact | In-app notices only (no push). |
| 20 | POST /notices/read | readAllNotices | bearer | 204 | 204 | exact | |
| 21 | POST /notices/{id}/read | readNotice | bearer | 204 | 204 | exact | |
| 22 | GET /search-history | getSearchHistory | bearer | 200 | 200 | exact | |
| 23 | POST /search-history | addSearchHistory | bearer | 200 | 200 | exact | Deduplicated, newest 10 kept. |
| 24 | DELETE /search-history | clearSearchHistory | bearer | 204 | 204 | exact | |

Error statuses: every code the implementation emits for an operation (400/401/403/404/409/413/415/429/500) belongs to that operation's spec `responses`. Rate limiting applies to `/auth/*` and `/me/password*`, which are exactly the operations that declare 429. **Nothing is missing.** The spec lists 24 operations; the earlier "25" count was a briefing error (documented in `app_api_backend_report.md`).

Schemas (User, Content, Notice, Session, State, Error, Register, Login, CreateContent, UpdateContent, VerifyPassword, ChangePassword, Nickname, SearchQuery, History, Notices, ContentList): **17/17 exact**. Length counts use code points (JSON Schema semantics); lone surrogates are rejected. Optional `collection/deletedAt/viewedAt` keys are omitted when null, as the spec says.

## 3. Cross-cutting findings (most severe first)

### Dangerous
- **X12 Dual content store (high).** `/api` operations read and write `api_contents`. `/v1` reads and writes the core `contents` table, which feeds analysis, indexing and search. I verified on a live server that the two never meet. A mobile app built against the spec would hold a library separate from the web dashboard for the same account, and none of its saves would get AI analysis or search.
- **X09 LAN binding (high).** `cli.py api_serve` exits with code 2 for any non-loopback `--host`, and its `--allow-external-bind` option is declared but never read. Bypassing the guard with raw uvicorn and the default `auth_backend=dev_header` would let anyone on the LAN read `/v1` data by sending `X-User-Id`.
- **X11 Trailing slash / HEAD (low).** `/api/health/` returns 307, and behind TLS termination the `Location` can come out as `http://`. HEAD returns 404. Neither is in the spec, but generated clients sometimes append a slash.

### Missing
- **X10 HTTPS production profile (high).** There is no TLS/reverse-proxy recipe. `env=prod` doesn't reject the default `cursor_secret`. Forwarded-IP trust isn't documented. iOS release builds require HTTPS.
- **X21 Contract tests (medium).** Status-set conformance on error paths, full-app mounting, CLI bind policy, a spec hash pin and a black-box device smoke test are all absent. Plan in §7.
- **X22 Native network policy (medium).** iOS ATS / local-network permission and Android cleartext rules; see §8.
- **X17 OAuth-only accounts (low).** Their random password makes the password endpoints useless: verify always fails and locks after 5 tries, and `User` has no flag the app could check.

### Adapter
- **X02 Base URL.** The spec says `http://localhost:3001/api`. The server's real default port is 8000 (8791 in the frontend README). The prefix `/api` matches exactly; only host and port change.
- **X03.** The web Vite proxy double prefix (`/api/api`) is irrelevant to mobile. Never point the app at port 5177.
- **X15 Collections.** The spec uses a fixed 6-value enum; `/v1` collections are user-defined.
- **X19.** The spec's `info.description` prose is stale (Node server, "no OAuth"). Behaviour is unaffected.

### Richer (keep; outside the contract)
- **X05.** The same bearer token authorizes `/v1`. `CompositeAuthenticator` maps the account to `u_account_<hex>`; verified live.
- **X13.** Real analysis lifecycle.
- **X14.** Semantic search.
- **X16.** Google/Naver OAuth. It's web-only (cookie + web callback), so it isn't usable natively, and the spec says unsupported anyway.

### Exact
Bearer auth, body rules, rate limiting, CORS/Origin, unsupported-feature absence, deletion cascade, and spec identity.
- **X06 body rules (an integration requirement).** POSTs that carry no data must still send `{}` with `Content-Type: application/json`.
- **X08 CORS.** Native apps send no `Origin`, so CORS doesn't affect them. WebView apps send origins such as `capacitor://localhost` or `null`, which get 403 unless listed in `CORS_ORIGINS`.

## 4. Which contract is canonical

1. **`specs/app_api_openapi.json` (= message (5)) is the canonical, frozen Mobile App Contract v1 for `/api`.** Don't change it in place. Its stale prose is documented here as errata.
2. **`/v1` stays canonical for AI save/analysis, search and user collections.** It is a separate, richer surface reachable with the same token. Nothing in OAuth, AI or search gets removed or rerouted.
3. **No new fields on `/api` DTOs.** The schemas allow extra properties, but strict decoders reject unknown keys (kotlinx.serialization without `ignoreUnknownKeys`, some Swift generators). Ship richer data through `/v1` or a future `/api/v2`.
4. **Long term (Phase 12), `/api` content becomes a view over the core store**, using the status values the spec already defines (`analyzing`, `failed`, `unavailable`). An app built on v1 then gets real analysis without a contract change.

## 5. Smallest backward-compatible implementation that lets the app connect

**Phase 11: `phase-11-mobile-connect`** (Codex-Primary, small, no contract change, no DB migration)

1. `cli.py api_serve`: allow a non-loopback `--host` only when `--allow-external-bind` is given **and** `Settings().auth_backend == "app_session"`. In every other case keep exit code 2 with a clear message.
   - When binding externally, print the LAN base URL hint: `http://<ip>:<port>/api`.
   - Recommend `JUPJUP_ADMIN_API_ENABLED=false` when binding externally. Better: force it off, since the admin routes only exist in dev.
2. `app_api/http.py`: create the sub-app with `redirect_slashes=False` so unknown or trailing-slash paths return the contract 404 instead of a 307.
3. Docs: an "Mobile app integration" section in `README.md` copying §8.
4. Contract tests from §7.
5. Optional: let `--port` default to 3001 when external bind is on? **Not recommended.** Keep 8000 and document it, to avoid surprising anyone.

Acceptance:
- Every existing test stays green.
- The new tests pass.
- `jupjup api serve --host 0.0.0.0 --allow-external-bind` with `JUPJUP_AUTH_BACKEND=app_session` starts.
- The same command with `dev_header` fails with exit code 2.
- A phone on the LAN completes the smoke flow (§7 T8).

## 6. Later phases

**Phase 12: `phase-12-app-content-bridge`** (needs the decision in §9 Q1; Architect writes the design first, then Codex-Primary)

The recommended design is "overlay link", chosen for the smallest blast radius:
- Additive migration: `api_contents.core_content_id TEXT NULL` (unique per user). Because this is a ledger v2 migration, the v1 checksum stays unchanged.
- `POST /api/contents`:
  - Keep the current insert and notice, plus the 201 response.
  - In the same flow, submit a core ingest (`ContentCommandService.submit`, `source.kind=url`, `user_note=memo`) and store the link.
  - The response returns `status:"analyzing"`, which is a legal enum value.
  - If the analyzer is unavailable, keep `ready`, as today.
- `content_dto` overlay when linked:
  - Status mapping: core `pending`/`awaiting_confirmation` → `analyzing`; `ready` → `ready`; `analysis_failed`/`analysis_rejected` → `failed`; original deleted → `unavailable`.
  - `description` = summary text and `tags` = representative tags. Both are strings, so the schemas stay valid.
  - `type` uses the user override if set, otherwise derives from `content_type` (video/short_video → 영상, image → 이미지, post/article/paper/message → 텍스트, webpage → 기타).
  - `title` = core title or host.
  - `collection`, `memo`, `viewedAt` and `deletedAt` stay app-owned in `api_contents`.
- Trash:
  - `/api` delete sets core `is_hidden=1` and saves the previous value; restore puts it back.
  - The 30-day purge and `emptyTrash` call `indexer.remove_content`.
  - A `/v1` hard delete of a linked item marks the `/api` row `unavailable` rather than orphaning it.
- Backfill: web-created URL contents get `api_contents` rows on demand in `getState`/`listContent`. Text/image contents have no URL, so they stay `/v1`-only (§9 Q2).
- IDs: `/api` keeps its own UUIDs, so the core `c_<hex>` IDs never leak. No ID adapter is needed.
- Tests: an `/api` save becomes visible in `/v1/contents` and `/v1/search` and vice versa, and every `/api` response still validates against the frozen spec.

**Phase 13: `phase-13-https-deploy`**
- Reverse proxy with TLS (Caddy or nginx) → uvicorn on 127.0.0.1. The proxy must run on the same host, because uvicorn only trusts forwarded headers from 127.0.0.1.
- `env=prod` + `app_session` + required non-default `cursor_secret` (add a validator).
- `CORS_ORIGINS` limited to the real web origin. HSTS at the proxy. DB backups.
- An HTTPS smoke test.

**Later:**
- Native OAuth: PKCE + Universal/App Links, plus an `/api/v2` or `/v1` account-capabilities endpoint (fixes X16 and X17).
- Push notifications.

## 7. Automated contract tests (Phase 11 deliverable)

Add these to `tests/integration/test_app_api_contract.py`. Use only existing dependencies (pytest, jsonschema, httpx/TestClient).

| ID | Test | Asserts |
|---|---|---|
| T1 | `test_spec_is_frozen` | sha256(`specs/app_api_openapi.json`) == `cd18e859669a7528…` (full hash in the matrix JSON). Changing it requires a deliberate update. |
| T2 | `test_error_statuses_subset_of_spec[op]` | For each of the 24 operations, run a table of negative probes: no token → 401, bad Origin → 403, wrong content type → 415, 17 KB body → 413, `{}`/invalid → 400, foreign id → 404, duplicate → 409, 31st auth request → 429. Every observed status must be in that operation's `responses` keys, and every body must validate against `Error`. |
| T3 | `test_full_app_mount_contract` | Build `jupjup.api.create_app` with test Settings (`app_session`) instead of a bare sub-app. Run register → createContent → state through `/api/...` and validate against the spec. Confirm that `X-User-Id` on `/v1` returns 401 and the bearer token works on `/v1/contents`. |
| T4 | `test_cli_external_bind_policy` | Typer CliRunner with `uvicorn.run` monkeypatched: 0.0.0.0 + dev_header → exit 2; 0.0.0.0 without the flag → exit 2; 0.0.0.0 + flag + app_session → `uvicorn.run(host="0.0.0.0")`. |
| T5 | `test_no_slash_redirect_and_unknown_routes` | `/api/health/` and HEAD return the contract 404 envelope, never a 3xx. |
| T6 | `test_native_and_webview_origins` | No Origin → OK. `capacitor://localhost` → 403 by default and allowed once configured. Preflight with Authorization/Content-Type → 204 with ACAO. |
| T7 | `test_bodyless_posts_require_empty_object` | For logout, restore, view and notices-read: `{}` → success; empty body → 400 `INVALID_JSON`; no content type → 415. Locks in the documented client rule. |
| T8 | `scripts/app_contract_smoke.py --base-url URL` (stdlib only, not part of pytest) | Black-box run against a live server from a laptop or CI: health → register (random `+smoke` email) → login → createContent → getState validated against the spec → deleteMe. Prints pass/fail and **never prints the token**. Run it against the LAN IP to simulate a device. |

## 8. App integration instructions

### 8.1 Client rules
- **Base URL** = `<scheme>://<host>:<port>/api`. Every spec path is relative to it (`GET {base}/health`).
- **Auth:** call `POST {base}/auth/login` or `POST {base}/auth/register` → keep `token` and `expiresAt`. Send `Authorization: Bearer <token>` on every other call. Store the token in iOS Keychain / Android Keystore (EncryptedSharedPreferences), never in plain storage or logs. On any 401, clear the token and route to login. Re-login after `expiresAt` (30 days); there is no refresh endpoint.
- **Bodies:** every POST/PATCH sends `Content-Type: application/json`. POSTs with no data send `{}`. Keep bodies ≤16 KB.
- **Errors:** branch on `error.code`, not `message`, since the message is always a generic string.
- **Sync model:** call `GET /state` on launch, on return to foreground, on pull-to-refresh and after every write. Do search, filter and sort locally as the spec intends.
- **Decoding:** treat `collection`, `deletedAt` and `viewedAt` as optional. Allow unknown keys (`ignoreUnknownKeys = true`) as a future-proofing default.
- Don't call `/api/auth/oauth/*` from the app: that flow is web-only.

### 8.2 Local / LAN development (real device)
1. Find the Mac's LAN IP: `ipconfig getifaddr en0` (e.g. `192.168.0.12`). Phone and Mac must share the Wi-Fi network, and AP/client isolation must be off. Allow Python in the macOS firewall prompt.
2. **Now (no code change, verified on loopback):**
   ```
   JUPJUP_ENV=dev JUPJUP_AUTH_BACKEND=app_session JUPJUP_ADMIN_API_ENABLED=false \
   JUPJUP_DB_PATH="$PWD/var/mobile-dev.db" \
   uv run uvicorn jupjup.api:create_app --factory --host 0.0.0.0 --port 8000
   ```
   `app_session` turns off the `X-User-Id` dev header, so `/v1` is not exposed anonymously. Never LAN-bind with the default `dev_header`.
   **After Phase 11:** `JUPJUP_AUTH_BACKEND=app_session uv run jupjup api serve --host 0.0.0.0 --port 8000 --allow-external-bind`.
3. App base URLs:
   - Real device: `http://192.168.0.12:8000/api`
   - Android emulator: `http://10.0.2.2:8000/api`
   - iOS simulator: `http://127.0.0.1:8000/api`
4. Plain HTTP on device, debug builds only:
   - **iOS:** `NSAppTransportSecurity > NSAllowsLocalNetworking = YES` (plus an `NSExceptionDomains` entry for the IP if needed). Add `NSLocalNetworkUsageDescription` and accept the iOS local-network prompt.
   - **Android:** `res/xml/network_security_config.xml` with `cleartextTrafficPermitted="true"` scoped to the dev IP, in the debug source set only.
5. CORS: native fetch (RN/Flutter/Swift/Kotlin) sends no Origin, so no config is needed. For a WebView/Capacitor/Expo-web build, set `CORS_ORIGINS="capacitor://localhost,http://localhost"` (or whatever exact origin it sends). `Origin: null` is always rejected.
6. Verify: `curl http://192.168.0.12:8000/api/health` → `{"status":"ok"}`. Then run the T8 smoke script (Phase 11).
7. Rate limit: 30 auth/password requests per minute per IP. A whole team behind one Wi-Fi NAT shares that budget during testing.

### 8.3 Production
- HTTPS only: `https://api.<domain>/api`, with TLS terminated at Caddy/nginx on the same host, proxying to `127.0.0.1:8000`.
- Settings: `JUPJUP_ENV=prod`, `JUPJUP_AUTH_BACKEND=app_session` (prod refuses `dev_header`), a strong `JUPJUP_CURSOR_SECRET`, and `CORS_ORIGINS` set to the web origin only. Keep secrets in the environment or a secret manager, never in the app bundle or git.
- Release builds keep ATS and cleartext defaults (HTTPS required). Certificate pinning is optional.
- Expect `status: "ready"` and empty `description`/`tags` until Phase 12 ships. After Phase 12, handle `analyzing` by re-fetching `/state` (poll every 3–5 s while any item is `analyzing`, or on foreground).

## 9. Blockers and open questions

**Blockers**
- **B1 (code, Phase 11):** the CLI LAN-bind guard blocks real devices on the documented path. The interim workaround in §8.2 unblocks testing today.
- **B2 (product decision → Phase 12):** the dual content store.
- **B3 (infrastructure → Phase 13):** no production HTTPS host or domain yet; iOS release builds need it.

**Open questions for the PM/user**
- **Q1.** Should a URL saved from the mobile app be AI-analyzed, searchable and shown on the web dashboard? Recommendation: **yes**, via the Phase 12 overlay link.
- **Q2.** Web-only text/image saves have no URL, but the spec's `Content.url` is required. Should they stay out of the mobile `/state` (recommended), or should the contract get a v2?
- **Q3.** Target app stack (React Native/Expo, Flutter, native, Capacitor)? This decides whether `CORS_ORIGINS` matters.
- **Q4.** Should the mobile app eventually support Google/Naver login? If so, schedule native OAuth (PKCE + app links) as its own phase.
- **Q5.** Where should production run (domain, host)?

## 10. Handoff to Codex-Primary (Phase 11)

- **Scope:** `src/jupjup/cli.py` (api_serve bind policy), `src/jupjup/app_api/http.py` (`redirect_slashes=False` only), the new `tests/integration/test_app_api_contract.py` (T1–T7), the new `scripts/app_contract_smoke.py` (T8), and a README section.
- **Don't touch:** `specs/app_api_openapi.json`, `/v1` routes, OAuth, AI/search, `frontend/`, migrations.
- **Report:** write `specs/phase11_mobile_connect_report.md` and run `uv run --offline pytest`, `ruff` and `mypy`.
