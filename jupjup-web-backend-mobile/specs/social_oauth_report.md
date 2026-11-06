# Google / Naver social OAuth implementation

Base: PM commit `37979ff`. Implementation is additive; unrelated archive frontend files were not modified. No real database, credentials, provider consoles, external network, or push was used. Dependency installation used existing offline caches. Provider HTTP is replaced by fakes in tests; live provider login has not been exercised.

## Environment and local registration

OAuth configuration comes only from server process environment:

| Variable | Meaning |
| --- | --- |
| `GOOGLE_OAUTH_CLIENT_ID` | Google web application OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google server-side client secret |
| `NAVER_OAUTH_CLIENT_ID` | Naver application client ID |
| `NAVER_OAUTH_CLIENT_SECRET` | Naver server-side client secret |
| `OAUTH_PUBLIC_ORIGIN` | External SPA origin; defaults to `http://127.0.0.1:5177` |
| `OAUTH_FRONTEND_CALLBACK_URL` | Must equal the public origin plus `/auth/callback`; defaults to that URL |

Do not put provider credentials in frontend `VITE_*` variables, tracked files, URLs, logs, or this report. Missing provider credentials produce `503 OAUTH_NOT_CONFIGURED` from start.

Register these exact **provider redirect URIs**, including both `/api` segments:

- Google: `http://127.0.0.1:5177/api/api/auth/oauth/google/callback`
- Naver: `http://127.0.0.1:5177/api/api/auth/oauth/naver/callback`

The SPA callback is `http://127.0.0.1:5177/auth/callback`; it is a different endpoint and must not replace the provider redirect URI. The existing Vite proxy removes the first `/api`, forwarding to the backend on port 8791; the backend mounts the compatibility application at the remaining `/api`. Frontend `VITE_API_BASE_URL` remains `/api`. Use `127.0.0.1` consistently rather than mixing it with `localhost` (cookies and registered redirect matching depend on this).

## Public endpoint contract

Paths below are backend paths, including the existing mounted `/api`. Public local browser paths prepend another `/api` via the Vite proxy.

| Method / path | Route name | Contract |
| --- | --- | --- |
| GET `/api/auth/oauth/{provider}/start` | `oauthStart` | Provider is exactly `google` or `naver`. Optional `return_path` is exactly `/dashboard` (default) or `/onboarding`. Responds 302 to the official authorization endpoint and sets a browser-binding cookie. Unknown provider: 404; invalid return path: 400. |
| GET `/api/auth/oauth/{provider}/callback` | `oauthCallback` | Accepts provider `state` and `code`, or provider error. Validates and atomically consumes browser-bound state before provider HTTP. Responds 303 to configured SPA callback with either one-time `code` or a fixed `error` identifier. Never includes app/provider bearer tokens or upstream descriptions. |
| POST `/api/auth/oauth/exchange` | `oauthExchange` | JSON body with string `code`; requires the original browser cookie. Responds 200 with `{session, returnPath, isNewUser}`. Invalid, expired, reused, or wrong-browser code: 400 `OAUTH_EXCHANGE_INVALID`. |

`session` is the existing Session contract: `token`, `expiresAt`, and `user` containing `id`, `email`, `nickname`, `notificationsEnabled`. The app token is opaque, valid for 30 days, and stored hashed in `api_sessions`. It is returned only in the exchange JSON body. Existing password registration/login/logout contracts remain unchanged.

Callback failures use fixed identifiers: `OAUTH_STATE_INVALID`, `OAUTH_DENIED`, `OAUTH_CODE_INVALID`, `OAUTH_PROVIDER_FAILED`, `OAUTH_PROFILE_INVALID`, `OAUTH_EMAIL_REQUIRED`, `OAUTH_EMAIL_UNVERIFIED`, `OAUTH_EMAIL_COLLISION`, and provider/configuration errors. The frontend presents a generic accessible retry message, scrubs the URL with replacement navigation, and never displays upstream error text.

## Provider protocol and security

- Google authorization: `https://accounts.google.com/o/oauth2/v2/auth`; token: `https://oauth2.googleapis.com/token`; userinfo: `https://openidconnect.googleapis.com/v1/userinfo`. Scopes: `openid profile email`. Uses S256 PKCE and a server-held verifier. Identity comes from authenticated userinfo `sub`; returned ID tokens are not used as identity assertions.
- Naver authorization: `https://nid.naver.com/oauth2.0/authorize`; token: `https://nid.naver.com/oauth2.0/token`; profile: `https://openapi.naver.com/v1/nid/me`. Token request includes the original state. The documented Naver flow does not expose PKCE parameters, so only Google uses PKCE. Identity comes from successful (`resultcode=00`) profile `response.id`.
- Token requests are form-encoded POSTs; userinfo requests send the provider access token in the Authorization header. Provider transport uses TLS verification, an 8-second timeout, a 64-KiB response limit, and rejects redirects. Provider tokens and bodies are not persisted or logged.
- State expires after five minutes. Only its SHA-256 hash is stored; it is bound to provider, a hashed browser cookie, PKCE verifier, and allowlisted return path. Atomic DELETE/RETURNING makes it single-use across callbacks, including denial and provider failures.
- The browser cookie is host-only, HttpOnly, SameSite=Lax, has a ten-minute lifetime, and is Secure for HTTPS origins. It is deleted on callback error or successful exchange. A new start replaces the cookie; parallel login attempts in the same browser should be restarted if superseded.
- Exchange codes expire after 60 seconds, are stored hashed, bind to the same cookie and account, and are consumed atomically with session issuance. Callback redirects contain only this exchange code; no session is issued before exchange.
- Exact return-path equality rejects query strings, trailing slashes, encoded alternatives, absolute URLs, and protocol-relative URLs. The SPA callback is fixed to the configured external origin's `/auth/callback`, preventing callback configuration from becoming an arbitrary redirect.
- Responses are `Cache-Control: no-store`; OAuth redirects and frontend exchange requests use `no-referrer`. The SPA document sets a no-referrer policy. The installed Uvicorn access-log filter removes query strings. OAuth exception handling suppresses sensitive tracebacks and upstream payloads.

## Identity and `/v1` policy

The durable key is `(provider, subject)`. Existing identities log into the same account even if profile email changes or is subsequently absent. Profile email never changes the durable association.

For a new identity, require a valid provider-asserted email; Google additionally requires boolean `email_verified=true`. Naver email is not treated as a verified account-linking assertion. Missing/invalid email rejects registration. Emails are normalized to lowercase and checked for collision across existing accounts.

**No automatic email linking is permitted**, including for verified Google email. A matching password account, another provider, or a different subject returns `OAUTH_EMAIL_COLLISION`; no identity or session is attached to that account. An authenticated explicit linking workflow would be a separate feature. New accounts receive a random unknowable password hash and enter onboarding; providers never supply a usable local password.

The composite `/v1` authenticator validates the existing app session and maps account UUID to `u_account_` plus its lowercase UUID hex. This mapping is stable, deterministic, and matches `USER_ID_RE`. Any Authorization header, including empty, malformed, expired, revoked, or invalid Bearer authorization, fails closed with 401 and never falls back to `X-User-Id`. Development headers are accepted only without Authorization, in dev/test with `auth_backend=dev_header`. Production uses `JUPJUP_ENV=prod` and `JUPJUP_AUTH_BACKEND=app_session`; the existing production rejection of `dev_header` remains.

## Storage and frontend

`storage/oauth_migration.py` adds `oauth_identities`, `oauth_states`, and `oauth_exchange_codes` plus an independent checksum ledger `oauth_migrations`. Existing app API and historical migration files/checksums remain unchanged. Foreign keys cascade account deletion to identities/exchange codes. Expired states/exchanges are purged at subsequent starts; expiry is enforced on every consumption. Production still defaults to migration checks only; apply the additive migration through the deployment's controlled migration process before serving the updated application. No deployed database was accessed here.

Google and Naver buttons redirect through `env.apiBaseUrl + /api/auth/oauth/{provider}/start`; these are the only login options. Loading/error states are accessible. `shared/auth/session.ts` validates and stores the app Session in browser localStorage, clears invalid/expired stored sessions, and shares only in-flight exchange requests to tolerate React StrictMode. The callback replaces navigation to scrub query parameters, then stores the session and replaces navigation to onboarding for new users or the exact returned allowlisted destination. The API client sends Bearer authorization when a valid session exists and omits development identity; no automatic fallback retry follows Bearer failure.

## Production provider setup

Serve the SPA and its `/api` reverse proxy on one external HTTPS origin. Set `OAUTH_PUBLIC_ORIGIN` to that origin and `OAUTH_FRONTEND_CALLBACK_URL` to its `/auth/callback`. Preserve the documented proxy mapping: public `/api/api/auth/oauth/{provider}/callback` reaches backend `/api/auth/oauth/{provider}/callback`. Register the exact resulting HTTPS callback URLs with each provider. Configure SPA history fallback for `/auth/callback` and forward cookies/Set-Cookie without rewriting them to another host. Do not derive public URLs from untrusted Host or forwarded headers.

For Google, create a **Web application** OAuth client, configure the consent screen, register exact authorized redirect URIs, and configure test users while the app is in testing. Publish/verify the consent configuration as required for the application's audience and requested scopes. JavaScript client credentials or a client-side implicit flow are not used.

For Naver, enable Naver Login on the application, configure the service URL and exact callback URL, and configure profile email consent/access in the developer console. Nickname is optional and has a fallback. A user may omit consent/profile email; the application rejects a new identity with a fixed error rather than inventing an email or merging accounts. Complete Naver's review/production access process for the intended audience.

Ensure ingress/CDN/APM/frontend access logs also omit OAuth queries, request/response bodies, cookies and Authorization headers. The application filter cannot control external infrastructure logging. Keep secrets server-side in deployment environment/secret injection and restrict production development access.

Official provider references (listed for deployment verification; no network lookup or console changes were performed during this task):

- Google web-server OAuth: https://developers.google.com/identity/protocols/oauth2/web-server
- Google OpenID Connect/userinfo: https://developers.google.com/identity/openid-connect/openid-connect
- Naver Login API reference: https://developers.naver.com/docs/login/api/api.md
- Naver Login developer guide: https://developers.naver.com/docs/login/devguide/devguide.md

## Validation

All backend tests use in-memory SQLite and injected/fake provider HTTP, with no real provider calls.

- `tests/integration/test_social_oauth.py`: Google/Naver contracts and endpoint names, state/cookie/provider binding, S256 verifier, expiry, denial/errors, missing/invalid/unverified email, durable subject replay, provider isolation and email collisions (including password accounts), single-use and concurrent exchange, no provider secrets/raw codes/tokens in storage/redirects, fixed provider errors, access-log redaction, configuration/CORS, production cookies, Bearer UUID mapping/expiry/no fallback, and `/v1` social session/search/logout smoke.
- `AuthPage.test.tsx`: only Google/Naver login options, no Kakao login text/button, loading/error announcements and signup destination.
- `AuthCallbackPage.test.tsx`: one exchange under StrictMode, session storage, URL/history replacement, onboarding/dashboard routing, invalid callbacks, failure and pending accessibility.
- `session.test.ts` and `client.test.ts`: session validation/expiry/storage, exact start URL, cookie-bearing exchange contract, response/return-path validation, Bearer attachment and development fallback rules.

Final focused run:

| Command | Outcome |
| --- | --- |
| `.venv/bin/pytest tests/integration/test_social_oauth.py tests/integration/test_app_api.py tests/unit/test_save_auth.py tests/integration/test_api_search.py tests/integration/test_save_api.py` | 140 passed; one existing Starlette/httpx deprecation warning |
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy` | Passed, 129 source files |
| `cd frontend && npm run typecheck` | Passed |
| `cd frontend && npm run test` | 56 passed, 12 files |
| `cd frontend && npx --offline oxlint src/pages/auth src/shared/auth src/shared/api/client.ts src/shared/api/client.test.ts` | Passed without warnings |
| `git diff --check` | Passed |

The final callback lint warning was removed by using an AbortController to cancel the effect subscription without reassigning an effect-local flag. Earlier full frontend lint reported unrelated archive warnings; those files were left unchanged. There are no lint warnings in the touched frontend scope.
