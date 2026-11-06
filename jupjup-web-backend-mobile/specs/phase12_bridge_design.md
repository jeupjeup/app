# Phase 12: App ↔ Core Content Bridge (design)

Author: Claude-Architect · Base: PM `eaa60e2` (Phase 11, safe) · Status: **design only, no `src/` changes**
Inputs: `specs/mobile_backend_contract_audit.md` (§6 Phase 12, §9 Q1), `specs/mobile_app_bridge_report.md`, plus the code it cites.
Product decision: **Q1 = yes.** A URL saved from the mobile app is AI-analyzed, searchable through `/v1/search`, and shown on the web dashboard. Web URL saves show up in the app's `/api/state`.

---

## 0. 요약 (PM/사용자용)

- **Why the last attempt failed.** The `/api` handler opens a SQLite write transaction (`BEGIN IMMEDIATE` under `api.state.lock`). `ContentCommandService.submit` then opens a *second* connection and asks for the writer lock too. On a file DB that connection waits for the first, which is waiting for it. After the 5 s busy timeout it fails with `database is locked`. On the `:memory:` `StaticPool` DB it is worse: both "connections" share one DBAPI connection, so the inner `engine.begin()` either raises "cannot start a transaction within a transaction" or, when its context exits, **rolls back the outer `/api` transaction without any error**.
- **What this design changes.** Both stores are tables in **the same SQLite file under one writer lock**. So the bridge never needs to coordinate two databases. Every bridge write goes into the `/api` request's own transaction, through new `*_in_transaction(conn, …)` core functions. The app row, the link row, the core `contents` row and the `ingest_jobs` row all commit together or all roll back.
- **Where the outbox is.** `ingest_jobs` already is a durable, leased, retried outbox for the only slow external step: fetch → LLM analysis → embed → index. The bridge writes its job row in the same transaction as the app row. That is the transactional-outbox pattern without adding a second queue. Anything derived (the in-memory search index, web→app backfill, re-linking orphans, legacy adoption) is **post-commit and idempotent**: it is reconciled lazily on read and can be checked and repaired with `jupjup bridge audit [--repair]`.
- **No contract change.** `specs/app_api_openapi.json` stays byte-identical (T1 hash test). App rows only gain *values* the spec already allows: `status ∈ {analyzing, failed, unavailable}`, non-empty `description` and `tags`.
- **Integrated worker:** **don't extend it.** The existing ingest worker processes bridge jobs unchanged, and the bridge has no background work that correctness depends on (§9).
- **Implementation size:** about 1 migration, 1 new package (`jupjup/bridge`), small refactors in `save/service.py`, `storage/repositories.py`, `app_api/{http,service,repository}.py` and `api/app.py`, plus about 45 tests. It fits one Codex-Primary loop.

---

## 1. Goals and non-goals

### Goals
- G1. `POST /api/contents` creates a core URL content and an analysis job **atomically** with the app row. It returns `201` with `status:"analyzing"`, or the status of the existing core content when the URL deduplicates.
- G2. `/api` content DTOs are a read-time projection of the linked core content: status, description = effective summary, tags = effective representative tags, title and type. App-owned fields are overlaid on top.
- G3. Web (`/v1`) URL contents appear in `/api/state` and `/api/contents` (backfill).
- G4. Trash, restore, purge (`emptyTrash` and the 30-day sweep), `/v1` hard delete and `DELETE /api/me` keep both sides consistent, with no orphans and no surprise deletions.
- G5. Duplicate-URL behavior is deterministic and documented on both surfaces.
- G6. Strict account scoping: an account's bridge only ever touches `contents.user_id = account_scopes.user_id` for that account.
- G7. The `/v1` in-memory search index converges to SQLite after every bridge write.
- G8. Zero deadlocks: no code path opens a second connection while the `/api` transaction is open.

### Non-goals
- No change to `specs/app_api_openapi.json`, no new DTO fields, no `/api/v2`.
- Text and image saves made on the web stay `/v1`-only: they have no URL, so they can't satisfy `Content.url` (audit Q2, recommended default).
- Memo is not synced continuously to `user_note`; it is copied once, when the core content is created. Collections are not synced (the app uses a fixed 6-value enum; the web has user collections).
- No "analysis finished" notices or push.
- No mobile review/approve flow for `automation_level=confirm`. Bridge saves always use `auto`.
- No new background thread and no worker changes.

---

## 2. Decision record: single local transaction + `ingest_jobs` outbox (chosen) vs. bridge saga/outbox

| | **A. Chosen: in-transaction core enqueue** | B. Bridge outbox table + dispatcher (saga) |
|---|---|---|
| Atomicity of app row ↔ core row ↔ job | One SQLite commit. Never partial. | Eventual. Needs `pending` link states visible to clients. |
| Purge or trash before dispatch | Impossible: the dispatch already happened in the same transaction. | Needs compensation (delete the core row created after the user purged), ordered per key. |
| Liveness dependency | None for linking. Analysis depends on the ingest worker, which exists today. | A dispatcher must run (inline, a sweep or a thread), and the app shows `analyzing` with no core row behind it if it doesn't. |
| Idempotency | No request key needed: the transaction either commits once or not at all. Core URL-fingerprint dedupe still applies. | Deterministic Idempotency-Key, which expires after 24 h, plus fingerprint fallback. |
| Deadlock risk | Removed by construction (G8 rule plus a test). | Removed, because dispatch runs post-commit. |
| Code churn in core | Extract `create_in_transaction` and `delete_in_transaction`; `/v1` behavior is byte-for-byte unchanged. | None in core, but a new queue, retry policy and dead-letter handling. |
| Works if `/api` and core later move to separate DBs | No (that would need B). | Yes. |

**Why A:** the "two stores" share one SQLite file and one writer lock, so a saga would *add* failure windows that a single commit doesn't have. The only external, slow, retryable step (fetch/LLM) already goes through `ingest_jobs`, which is durable, leased, retried, written transactionally and visible as the core `status`. That is exactly the role of a transactional outbox.

**Post-commit idempotent reconciliation** is still part of the design, for the things that are *derived*:
1. In-memory search index: the existing `index_revisions` triggers plus `refresh_if_stale` (§8).
2. Web→app backfill, orphan re-link and legacy-row adoption: `ContentBridge.sync`, run lazily in `getState` and `listContent` inside a savepoint (§6.6).
3. Audit and repair of every invariant: `jupjup bridge audit [--repair]` (§6.9).

**If the stores are ever split** into separate DBs, swap `CorePort` for an outbox-backed implementation. The `ContentBridge` interface (§5) is shaped so that swap stays local.

---

## 3. Data model and migration

### 3.1 New migration `src/jupjup/storage/app_bridge_migration.py`

- Use its **own ledger** table, `app_bridge_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)`, with version 1 and checksum = sha256 of the file bytes, the same pattern as `oauth_migration.py`.
- **Do not** edit `app_api_migration.py`, `account_migration.py`, `migration*.py` or `oauth_migration.py`. Their checksums are sha256 of their own source files, so any edit bricks existing DBs. `app_api_migration` also rejects any ledger other than `[(1, chk)]`, so a "v2 row in `app_api_migrations`" is **not** an option.
- Wire it into `storage/db.py:create_db_engine` **after** `run_account_migrations`, because it depends on `api_users`, `api_contents`, `contents` and `account_scopes`. Run it before `_create_index_revision_triggers`; the order between the two doesn't matter.
- The ledger check accepts exactly `[(1, _CHECKSUM)]`. A future v2 must be written as a new file with its own constant (document this in the module docstring).
- `auto_migrate=False` with the table missing → `MigrationError("database requires app bridge migration")`.
- Run everything in a `BEGIN IMMEDIATE` transaction. Afterwards `PRAGMA foreign_key_check` must be empty, or raise.
- **Additive DDL only. No data rewrite.** Existing `api_contents` rows get no link row ("unlinked legacy rows") and are adopted lazily (§6.6).

```sql
CREATE TABLE app_content_links (
    api_content_id  TEXT PRIMARY KEY REFERENCES api_contents(id) ON DELETE CASCADE,
    account_id      TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
    core_user_id    TEXT NOT NULL CHECK (core_user_id LIKE 'u_account_%'),
    core_content_id TEXT,                 -- no FK: core deletes are handled by trigger (orphan/remove)
    core_url_fp     TEXT,                 -- sha256(core-normalized URL); NULL when the core rejects the URL
    url_version     TEXT NOT NULL,        -- URL_NORMALIZATION_VERSION used for core_url_fp
    origin          TEXT NOT NULL CHECK (origin IN ('app','core')),
    state           TEXT NOT NULL CHECK (state IN ('linked','rejected','orphaned')),
    reject_code     TEXT CHECK (reject_code IS NULL OR reject_code IN ('core_rejected_url','duplicate_active')),
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),   -- mirrors api_contents.deleted_at IS NULL
    hid_core        INTEGER NOT NULL DEFAULT 0 CHECK (hid_core IN (0,1)), -- the bridge set contents.is_hidden=1
    title_locked    INTEGER NOT NULL DEFAULT 0 CHECK (title_locked IN (0,1)),
    type_locked     INTEGER NOT NULL DEFAULT 0 CHECK (type_locked IN (0,1)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CHECK ((state = 'linked') = (core_content_id IS NOT NULL)),
    CHECK ((state = 'rejected') = (reject_code IS NOT NULL))
);
CREATE UNIQUE INDEX uq_app_link_active_core ON app_content_links(core_user_id, core_content_id)
    WHERE active = 1 AND state = 'linked';
CREATE UNIQUE INDEX uq_app_link_active_fp ON app_content_links(account_id, core_url_fp)
    WHERE active = 1 AND core_url_fp IS NOT NULL;
CREATE INDEX ix_app_link_core ON app_content_links(core_user_id, core_content_id);
CREATE INDEX ix_app_link_account ON app_content_links(account_id, state, active);

-- Keep `active` in lockstep with app trash state, whatever code path changes deleted_at.
CREATE TRIGGER trg_app_link_active AFTER UPDATE OF deleted_at ON api_contents
BEGIN
    UPDATE app_content_links SET active = (NEW.deleted_at IS NULL) WHERE api_content_id = NEW.id;
END;

-- /v1 hard delete, admin delete, duplicate cascade, account cascade: never leave a dangling link.
CREATE TRIGGER trg_app_bridge_core_deleted AFTER DELETE ON contents
BEGIN
    DELETE FROM api_contents WHERE id IN (
        SELECT api_content_id FROM app_content_links
        WHERE core_user_id = OLD.user_id AND core_content_id = OLD.id AND origin = 'core');
    UPDATE app_content_links SET state = 'orphaned', core_content_id = NULL, hid_core = 0
        WHERE core_user_id = OLD.user_id AND core_content_id = OLD.id;
END;

-- Any unhide (web PATCH hidden=false, bridge restore, release on re-save) ends the bridge's claim.
CREATE TRIGGER trg_app_bridge_core_unhidden AFTER UPDATE OF is_hidden ON contents
WHEN OLD.is_hidden = 1 AND NEW.is_hidden = 0
BEGIN
    UPDATE app_content_links SET hid_core = 0
        WHERE core_user_id = NEW.user_id AND core_content_id = NEW.id AND hid_core = 1;
END;
```

Notes:
- `url_version` lets `sync` retry `core_rejected_url` links after `URL_NORMALIZATION_VERSION` changes (for example, a broader Instagram rule).
- `account_id` cascades from `api_users`. `DELETE /api/me` removes app rows (→ links) and `account_scopes` (→ the existing trigger deletes core rows → the bridge trigger becomes a no-op). Everything happens in one transaction.
- The trigger behavior inside FK cascades is SQLite default (`recursive_triggers` off). FK actions still fire these triggers. Test B37 covers it.

### 3.2 Field ownership (app ↔ core projection)

| `/api` field | Source when linked | Notes |
|---|---|---|
| `id` | app (`api_contents.id`, UUID) | Core `c_<hex>` IDs never leak. |
| `url` | app | For `origin=app` it is the app-normalized string the client sent. For backfilled rows it is the core `source_url`. |
| `title` | app if `title_locked`, else core `title`, else accepted YouTube metadata title, else app `title` (host) | A `PATCH` with `title` sets `title_locked=1`. |
| `memo` | app | Copied to core `user_note` **only** when the bridge creates a new core content. |
| `type` | app if `type_locked`, else derived from core `content_type` | `video`/`short_video`→`영상`; `image`→`이미지`; `post`/`article`/`paper`/`message`→`텍스트`; `webpage`→`기타`. |
| `collection` | app | |
| `source` | app (host) | |
| `description` | core effective summary text, or `""` | Use the same visibility rules as `/v1/contents/{id}` (`save.query.visible_analysis`). |
| `tags` | core effective representative tags, or `[]` | Same rules. Never includes hidden AI tags. |
| `savedAt` | app | Equals the core `saved_at` for `origin=app`, because both are written from the same `now`. |
| `status` | projected (§3.3) | |
| `deletedAt`, `viewedAt` | app | |

Unlinked or legacy rows and `duplicate_active` rejects are projected as today: `status:"ready"`, `description:""`, `tags:[]`.

### 3.3 Status projection

Resolve `c` = the linked core content. If `c.status == 'duplicate'`, follow `duplicate_of_content_id` one hop (same `user_id`); if the canonical row is missing, the result is `unavailable`. Then apply the first matching rule:

| Condition | `/api` status |
|---|---|
| link `state='orphaned'` | `unavailable` |
| link `state='rejected'`, `reject_code='core_rejected_url'` | `failed` |
| link `state='rejected'`, `reject_code='duplicate_active'` / no link | `ready` (bookmark only) |
| `c.original_status == 'deleted'` | `unavailable` |
| `c.status ∈ {pending, awaiting_confirmation}` | `analyzing` |
| `c.status == 'ready'` | `ready` |
| `c.status ∈ {analysis_failed, analysis_rejected}` | `failed` |

Description and tags come from the resolved canonical content.

---

## 4. Invariants (all must hold after every commit; `bridge audit` checks them)

- **I1 (single active link per core content):** for each `(core_user_id, core_content_id)` there is at most one link with `active=1 AND state='linked'`. Enforced by `uq_app_link_active_core`.
- **I2 (single active link per URL identity):** for each `(account_id, core_url_fp)` there is at most one link with `active=1`. Enforced by `uq_app_link_active_fp`.
- **I3 (scope):** `link.core_user_id = account_scopes.user_id WHERE account_id = link.account_id`, and if `state='linked'`, then `contents(id=core_content_id).user_id = core_user_id`.
- **I4 (no dangling):** `state='linked'` ⇒ the core row exists (enforced by the trigger). `state='orphaned'` ⇒ `core_content_id IS NULL`.
- **I5 (active mirror):** `link.active = (api_contents.deleted_at IS NULL)` (enforced by the trigger).
- **I6 (bridge hide claim):** `hid_core=1` ⇒ `active=0 ∧ state='linked' ∧ contents.is_hidden=1`, and no *active* link references that core content.
- **I7 (no unexplained hidden content):** a core content hidden by the bridge always has exactly one link with `hid_core=1`. When an active link attaches to a core content that a trashed link hid, the bridge unhides it first (the trigger clears `hid_core`).
- **I8 (purge safety):** the bridge hard-deletes a core content only if (a) a purged link had `hid_core=1` for it, (b) after the purge no link references it, and (c) `contents.is_hidden=1` at purge time. A web unhide anywhere in between cancels the deletion, because the trigger clears `hid_core`.
- **I9 (backfill completeness, eventually):** after `sync(scope)` with no limit hit, every core content with `source_kind='url'`, `status<>'duplicate'` and `is_hidden=0` for that user has exactly one link.
- **I10 (no nested connection):** while an `/api` request transaction is open, no code checks out another pooled connection or calls `engine.connect()`/`engine.begin()`. All bridge and core-port functions take `conn`.
- **I11 (contract):** every `/api` response validates against the frozen `specs/app_api_openapi.json`, and its sha256 is unchanged.
- **I12 (index convergence):** after `refresh_if_stale(user)`, the user's registry documents equal `{contents for user | is_hidden=0 ∧ status≠'duplicate'}`.

---

## 5. Modules and interfaces

```
src/jupjup/bridge/
  __init__.py        # re-exports ContentBridge, AccountScope
  ports.py           # CorePort protocol + CoreCreateOutcome
  core_port.py       # SaveCorePort: CorePort over ContentCommandService + SqlContentRepository
  links.py           # conn-only SQL for app_content_links (no engine access)
  projection.py      # status/type maps, build DTOs (pure apart from conn reads)
  service.py         # ContentBridge orchestration called by app_api.service
  audit.py           # audit(conn) / repair(conn) for I1–I12
src/jupjup/storage/app_bridge_migration.py
src/jupjup/storage/bridge_sql.py      # release_bridge_hide(conn, user_id, content_id): used by the core dedupe branch
```

### 5.1 Core refactors (behavior-preserving for `/v1`)

`src/jupjup/save/service.py`
```python
@dataclass(frozen=True)
class CoreCreateOutcome:
    content_id: str
    job_id: str | None          # None when deduplicated
    deduplicated: bool
    status: str                 # contents.status after the call

class ContentCommandService:
    def create_in_transaction(
        self, conn: Connection, user_id: str, body: CreateContent, now: datetime
    ) -> CoreCreateOutcome:
        """Exactly the current submit() body between the idempotency lookup and the
        idempotency insert, for CreateContent only: fingerprint dedupe, platform and
        content_type inference, create_in_transaction, enqueue_in_transaction, fingerprint
        insert, job automation_level/result_content_id update. On dedupe it calls
        bridge_sql.release_bridge_hide(conn, user_id, existing). It never opens a connection."""
```
- `submit()` keeps its idempotency logic and its exact response shapes (including `warnings=["user_note_not_applied"]` and `duplicate_reason`). It calls `create_in_transaction` for `CreateContent`. The reanalyze branch is unchanged.
- **Requirement:** all existing `/v1` tests (`test_save_api.py`, `test_save_acceptance.py`, `test_api_ingest*.py`, `test_account_scoping.py`) pass unmodified.

`src/jupjup/storage/bridge_sql.py`
```python
def release_bridge_hide(conn: Connection, user_id: str, content_id: str) -> bool:
    """If the content is hidden *and* an app link holds hid_core=1 for it, set is_hidden=0,
    revision+1, updated_at=now. The trigger clears hid_core. A no-op for pure-web data
    (no link rows). Returns whether it unhid."""
```

`src/jupjup/storage/repositories.py`
```python
def delete_in_transaction(self, conn: Connection, user_id: str, content_id: str) -> bool:
    """Cancel active jobs + DELETE contents row (cascades). Returns False if absent; never raises NotFound."""
def delete(self, user_id, content_id) -> None   # now: begin() + delete_in_transaction; raises NotFound as before
def bundles_in(self, conn: Connection, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]
def metadata_in(self, conn: Connection, bundle: ContentBundle) -> MetadataClassification | None
def metadata_for(self, bundle) -> ...           # now: connect() + metadata_in
```

`src/jupjup/save/query.py`: rename `_visible_analysis` → `visible_analysis` (keep a private alias for one release) so the projection can import it.

### 5.2 Ports

`bridge/ports.py`
```python
class CorePort(Protocol):
    def create_or_dedupe(self, conn: Connection, user_id: str, url: str, memo: str, now: datetime) -> CoreCreateOutcome
        # raises CoreRejected(code) for ContentValidationError/ApiError(4xx) raised before any write
    def delete(self, conn: Connection, user_id: str, content_id: str) -> bool
    def bundles(self, conn: Connection, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]
    def metadata(self, conn: Connection, bundle: ContentBundle) -> MetadataClassification | None

class CoreRejected(Exception):
    code: Literal["core_rejected_url"]
```
`bridge/core_port.py: SaveCorePort(commands: ContentCommandService, repo: SqlContentRepository)` builds `CreateContent(source=UrlSource(kind="url", url=url), user_note=memo or None, automation_level="auto")`. Constructing the DTO is pure and happens before any write, so a pydantic `ValidationError` or `ContentValidationError` maps to `CoreRejected` with nothing written.

### 5.3 `ContentBridge` (`bridge/service.py`)

```python
@dataclass(frozen=True)
class AccountScope:
    account_id: str
    core_user_id: str

class ContentBridge:
    def __init__(self, core: CorePort, *, sync_limit: int = 500, adopt_limit: int = 50,
                 purge_batch: int = 200) -> None

    def scope(self, conn: Connection, account_id: str) -> AccountScope
        # SELECT user_id FROM account_scopes WHERE account_id=?; missing → ContractError(500,"INTERNAL_ERROR")

    def core_identity(self, url: str) -> tuple[str | None, str | None]
        # (core_normalized_url, fp) via save.dedupe.normalize_source_url/fingerprint; (None, None) if rejected. Pure.

    def assert_create_allowed(self, conn, scope, url: str) -> None
        # 409 DUPLICATE_CONTENT if an active link has the same fp (I2). The app-url check stays in service.py.

    def link_new(self, conn, scope, api_row: Mapping[str, Any], now: datetime) -> None
        # In SAVEPOINT bridge_link: core_identity → None ⇒ link rejected/core_rejected_url (fp NULL).
        # else core.create_or_dedupe(...) → attach(...). CoreRejected ⇒ ROLLBACK TO savepoint, link rejected.
        # Any other exception propagates ⇒ whole request rolls back (atomic 500).

    def attach(self, conn, scope, api_content_id: str, core_content_id: str, fp: str, origin: str, now) -> None
        # I7: unhide core content if it is hidden (bridge- or web-hidden: an explicit save wins),
        # then insert/update the link as linked. Insert/update order keeps I1/I2 enforced by indexes.

    def note_update(self, conn, scope, api_content_id: str, fields: set[str]) -> None
        # title in fields → title_locked=1; type in fields → type_locked=1 (only if a link exists)

    def after_trash(self, conn, scope, api_content_id: str, now) -> None
        # linked ∧ contents.is_hidden=0 ⇒ is_hidden=1, revision+1, updated_at; hid_core=1. Idempotent.

    def before_restore(self, conn, scope, api_row) -> None
        # 409 DUPLICATE_CONTENT if another active link has the same fp (I2).

    def after_restore(self, conn, scope, api_content_id: str, now) -> None
        # linked ∧ hid_core=1 ⇒ is_hidden=0 (trigger clears hid_core).
        # orphaned ⇒ try relink by fp. No link (legacy) ⇒ adopt (same as link_new with origin='app').

    def purge(self, conn, api_content_ids: Sequence[str]) -> int
        # Multi-account, set-based, I8. Returns the number of core contents hard-deleted.

    def sync(self, conn, scope, now) -> SyncResult
        # SAVEPOINT bridge_sync; on any Exception: ROLLBACK TO + log warning (no content values) + return partial.
        # Steps, in order: (1) retry rejected links whose url_version != current, (2) relink orphaned
        # links by fp, (3) adopt unlinked *active* app rows (≤ adopt_limit), (4) backfill web URL contents (≤ sync_limit).

    def project(self, conn, scope, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]
        # Batch: links for the rows, bundles for the linked ids + duplicate canonicals, then the DTOs from §3.2/§3.3.
```

`SyncResult(adopted: int, backfilled: int, relinked: int, retried: int, truncated: bool)`.

### 5.4 Changes in `app_api`

`app_api/http.py`
- `create_api(engine, *, origins=None, bridge: ContentBridge | None = None)`, with `api.state.bridge = bridge`. `bridge=None` keeps today's behavior exactly, so the existing `test_app_api.py` and `test_mobile_connect.py` stay green.
- `maintain()`: when the bridge is set, `SELECT id FROM api_contents WHERE deleted_at<=:cutoff LIMIT :purge_batch` → `bridge.purge(conn, ids)` → `DELETE ... WHERE id IN ids`. Otherwise keep the current single `DELETE`.
- Pass `api.state.bridge` into `service.execute(...)` as a new keyword-only `bridge=` argument.

`app_api/service.py` (all calls use the handler's `conn`)

| Operation | Bridge hook (only when `bridge` is set) |
|---|---|
| `createContent` | After the existing app-url duplicate check: `bridge.assert_create_allowed`. After the inserts: `bridge.link_new`. Return `bridge.project(...)[0]`. |
| `getState`, `listContent` | `bridge.sync(conn, scope, now)` before reading, then `repo.contents(conn, uid, project=…)`. |
| `getContent`, `updateContent`, `restoreContent` return | Project the single row. |
| `updateContent` | `bridge.note_update(conn, scope, id, set(values))`. |
| `deleteContent` | `bridge.after_trash` after the UPDATE. |
| `restoreContent` | `bridge.before_restore` (409), the UPDATE, then `bridge.after_restore`. |
| `emptyTrash` | Select the trashed ids, `bridge.purge(conn, ids)`, then the existing DELETE. |
| `deleteMe` | Nothing: the cascades and triggers handle it (B37). |

`app_api/repository.py`: `contents(conn, user_id, *, project: Callable[[list[dict]], list[dict]] | None = None)`. The default projection is today's `content_dto`.

### 5.5 Wiring (`api/app.py`, `config.py`, `cli.py`)
- `Settings.app_bridge_enabled: bool = True` (`JUPJUP_APP_BRIDGE_ENABLED`).
- In `create_app`, build `public_ingest` **before** `app.mount("/api", …)`. Move the `profile` computation out of `save_router` into `container.analyzer_profile_name(settings)` and reuse it in both places. If the bridge is enabled, use `bridge = ContentBridge(SaveCorePort(ContentCommandService(public_ingest, profile), active.repo))`, otherwise `None`. Then `app.mount("/api", create_api(active.engine, bridge=bridge))`. `save_router` receives the same `ContentCommandService` instance.
- `cli.py`: `jupjup bridge audit [--db PATH] [--repair] [--account ID]`. It prints violation counts per invariant, never URLs or content text, and exits 1 if any violation remains.

---

## 6. Flows

### 6.1 Create (`POST /api/contents`)
```
handler: lock + BEGIN IMMEDIATE (conn)
  authenticate → uid
  url, host = validation.normalize_url(body)           # unchanged; 400 on invalid
  app-url active duplicate? → 409 DUPLICATE_CONTENT     # unchanged
  scope = bridge.scope(conn, uid)
  bridge.assert_create_allowed(conn, scope, url)        # fp duplicate → 409 (new, spec-legal)
  INSERT api_contents, INSERT api_notices               # unchanged
  bridge.link_new(conn, scope, row, now)
     SAVEPOINT bridge_link
       core_url, fp = core_identity(url)   (None → rejected link, RELEASE)
       outcome = core.create_or_dedupe(conn, scope.core_user_id, core_url, memo, now)
           ├─ new:   INSERT contents(status=pending) + ingest_jobs(queued) + content_fingerprints
           └─ dedupe: existing id; release_bridge_hide
       attach(...)  → unhide if hidden; INSERT link(linked, origin=app, fp)
     RELEASE bridge_link            | CoreRejected → ROLLBACK TO bridge_link; INSERT link(rejected)
  dto = bridge.project(conn, scope, [row])[0]          # status analyzing | deduped status
COMMIT  → 201 dto
post-commit: the ingest worker leases the job; worker index stage publishes to the registry
```
Unexpected exceptions anywhere → ROLLBACK of everything → `500 INTERNAL_ERROR`. No app row, no core row, no job.

### 6.2 Update
App fields as today. Setting `title`/`type` locks them. Core data is never written from `/api` PATCH.

### 6.3 Trash / restore
- Trash: `deleted_at=COALESCE(...)` → trigger `active=0` → `after_trash`: hide core only if it is visible, and claim with `hid_core=1`. If the core content is already hidden by the web, there is no claim, so a purge won't delete it.
- Restore: 409 if there is an app-url or fp active duplicate. `deleted_at=NULL` → trigger `active=1` → `after_restore`: unhide only if the bridge still holds the claim (`hid_core=1`). If the web unhid it meanwhile, the trigger already cleared the claim, so this is a no-op.

### 6.4 Purge (`emptyTrash`, 30-day sweep)
```
L = links of ids where state='linked' AND hid_core=1          -- candidate core ids
DELETE api_contents WHERE id IN ids                            -- links cascade
for (user, cid) in distinct L:
   if NOT EXISTS(link where core_user_id=user AND core_content_id=cid)
      AND contents(cid).is_hidden=1:
        core.delete(conn, user, cid)    -- cancels active jobs, deletes rows, triggers bump index_revisions
```
Everything is in the request or `maintain` transaction. Rows with no link, rejected or orphaned only delete the app row.

### 6.5 `/v1` hard delete (web)
`DELETE /v1/contents/{id}` → `indexer.remove_content` → `repo.delete` → trigger:
- `origin='core'` app rows (web-originated, backfilled) are deleted. The web owns them, and leaving them behind would leave junk in the app.
- `origin='app'` rows become `orphaned` → `unavailable`. The app keeps the user's memo and collection, and the user can trash it from the app.
- No route code changes.

### 6.6 Sync (lazy reconciliation inside `getState`/`listContent`)
1. **Retry:** rejected `core_rejected_url` links with `url_version != URL_NORMALIZATION_VERSION` and active → rerun `link_new` logic (update in place).
2. **Relink orphans:** active `orphaned` links with `core_url_fp` → find a live core content via `content_fingerprints(user, normalized_url, version, fp)` that has no active link → `attach`.
3. **Adopt legacy:** active app rows with no link (≤ `adopt_limit`, oldest first) → same as `link_new`. If its fp is already claimed by another active link → link `rejected/duplicate_active` (bookmark-only, I2 kept).
4. **Backfill:** core contents for `core_user_id` with `source_kind='url'`, `status<>'duplicate'`, `is_hidden=0` and no link (anti-join on `ix_app_link_core`), up to `sync_limit`, oldest `saved_at` first. For each:
   - compute `fp` from `normalized_url` (fallback: `normalize_source_url(source_url)`; skip if it fails);
   - if an active app row (unlinked) has the same app `url` or fp → link it (`origin='app'`);
   - otherwise INSERT `api_contents(id=uuid4, url=source_url, title=title or host, memo='', type=derived, source=host, saved_at=instant(core saved_at))` plus a link (`origin='core'`, `linked`). No notice.
   - If `source_url` would collide with `uq_api_active_url` (an app row with the same URL string that belongs to a different fp, which is practically impossible), skip it and report it in the audit.
5. `truncated=True` when a limit was hit. The next read continues, and `bridge audit --repair` drains everything.

The savepoint guarantees sync failure never breaks `getState`. Repeating sync is a no-op: every step checks before writing, so it's idempotent.

### 6.7 Web save of a URL the app already has
- `/v1/contents` → fingerprint dedupe → `200 deduplicated` with the same core content. The app row stays as the single link.
- If the app had trashed it (bridge-hidden) → `release_bridge_hide` unhides it, and the trigger clears the claim. The web save becomes visible and a later app purge removes only the app row; the next sync backfills it again as `origin='core'`.

### 6.8 Duplicate URL matrix (normative; tests B10–B17)

| Situation | `/api` result | Core effect |
|---|---|---|
| App create, same app-normalized URL active in app | 409 `DUPLICATE_CONTENT` | none |
| App create, a URL variant with the same core fp (`utm_*`, `youtu.be`↔`watch?v=`, default port) active in app | 409 `DUPLICATE_CONTENT` **(new)** | none |
| App create, URL already saved on web, not yet backfilled | 201, links to the existing core content; status = core projection | no new job; `user_note` untouched; unhidden if hidden |
| App create, same URL only in app trash | 201 new row; links to the same core content and unhides it (I7). The old trashed link keeps `hid_core=0`. | none |
| App create, the core rejects the URL (e.g. non-public Instagram, longer than 2048 chars) | 201, `status:"failed"`, description and tags empty | none |
| Restore while an fp-equal row is active | 409 `DUPLICATE_CONTENT` | none |
| Two accounts save the same URL | Both 201 | two separate core contents (per-user fingerprints) |

### 6.9 Audit and repair (`bridge/audit.py`)
`audit(conn, account_id=None) -> dict[str, int]` counts violations of I1–I9 and I3 scope, plus "unbackfilled web URL contents" and "unadopted legacy rows". `repair(conn, bridge, now)` runs `sync` for every account without limits (in chunks, one transaction per account) and fixes I5 and I6 drift (drift is only possible from manual SQL). It is safe to run while serving, because each account repair is one short `BEGIN IMMEDIATE`.

---

## 7. Concurrency and the deadlock rule (G8 / I10)

- **Rule:** everything reachable from `app_api.service.execute` and `maintain` uses only the passed `conn`. Forbidden inside it: `engine.connect()`, `engine.begin()`, `repo.get_bundle(s)`, `repo.metadata_for`, `repo.delete`, `indexer.*`, `ingest.submit`, `ContentCommandService.submit`.
- **Why it matters for `StaticPool`:** an inner `with engine.connect()` on the shared DBAPI connection issues a ROLLBACK on exit, which silently discards the outer `/api` writes. Test B40 pins this.
- Cross-process and cross-thread writers (`/v1` routes, the ingest worker, the CLI) serialize on the SQLite writer lock as today. The `/api` transaction never waits on anything inside its own process while holding the lock, so a wait cycle is impossible. The bridge adds only a few milliseconds of SQL to the `/api` transaction.
- Same-URL races between `/api` create and `/v1` submit: whichever commits first creates the core row, and the other dedupes (B18).

## 8. Index consistency (G7 / I12)
- Every bridge mutation of `contents` (insert, `is_hidden` update, delete) fires the existing `trg_contents_index_revision_*` triggers in the same transaction.
- `/v1/search` calls `refresh_if_stale(user)` under `state_lock` before searching, which reloads the user's registry from SQLite. Hidden or deleted content drops out, and restored content comes back with its stored embeddings.
- New content becomes searchable when the worker's index stage runs, exactly like `/v1` saves.
- Embeddings are removed by the FK cascade on core delete.
- `/api` code never touches the registry directly: one convergence path, already tested.

## 9. Integrated worker: do not extend
- Bridge jobs are ordinary `ingest_jobs` rows (`kind='ingest'`, profile = the configured analyzer profile). `jupjup api serve` (default `--with-worker`) and `jupjup worker run` process them unchanged.
- Status flows back by read-time projection, so nothing needs to be pushed to `api_contents`.
- The only time-based bridge action, the 30-day purge, already lives in `maintain`. Backfill is lazy-on-read. Repair is a CLI.
- Adding a reconciler thread would create a second writer with its own failure modes for no gain. Revisit only if the stores are split (§2) or push notices are added.

## 10. Errors and the contract
- All `/api` errors stay within each operation's spec `responses`: 409 for the new fp-duplicate on `createContent`/`restoreContent` (both already declare 409), and 500 `INTERNAL_ERROR` for unexpected failures (atomic rollback).
- `CoreRejected` never surfaces as an error; it becomes `status:"failed"`.
- Logging never includes URLs, memos, titles or tokens: only operation, link state and exception type.

---

## 11. Test matrix

New files: `tests/integration/test_app_bridge.py` (B), `tests/unit/test_app_bridge_projection.py` (P), `tests/unit/test_app_bridge_migration.py` (M). Fixture: `create_app(Settings(env="test", auth_backend="app_session", db_path=tmp_path/…))` with a fixed `api.state.clock` and the mock analyzer. Jobs are run deterministically via `app.state.ingest.worker.run_once()`. Every `/api` 2xx body is validated with jsonschema against the frozen spec. Run each B test on **file-backed** DBs; B40 also runs on `:memory:`.

| ID | Test | Asserts |
|---|---|---|
| M1 | fresh DB migrates | tables, indexes and 3 triggers exist; ledger `[(1, chk)]`; FK check empty |
| M2 | existing Phase 11 DB with app rows | migration additive; old ledgers and checksums untouched; no links created |
| M3 | rerun / tampered checksum / `auto_migrate=False` | idempotent / `MigrationError` / `MigrationError` |
| P1 | status map table (§3.3) incl. the duplicate canonical hop and `original_status=deleted` | exact enum values |
| P2 | type map for all 8 `ContentType`s; `type_locked` / `title_locked` overrides | |
| P3 | description/tags follow `visible_analysis` (user summary wins, hidden AI tags excluded, legacy-watch rule) | parity with `/v1/contents/{id}` effective fields |
| B01 | `POST /api/contents` → 201 `analyzing`; core content + queued job exist in the same commit; memo → `user_note` | |
| B02 | after `worker.run_once()` until idle: `/api/state` item `ready` with non-empty description/tags | Q1 analysis |
| B03 | the same item is found by `/v1/search` with the same bearer token, and listed by `/v1/contents` | Q1 search + web |
| B04 | web save (`/v1/contents`) → appears in `/api/state` with `origin=core`, correct title/type/savedAt format | backfill |
| B05 | backfill excludes text/image, hidden and `duplicate` core contents | Q2 default |
| B06 | sync is idempotent: two `getState` calls → no extra rows or links | |
| B07 | `sync_limit` truncation continues on the next read; `audit --repair` drains it | |
| B08 | legacy app row (inserted before migration) adopted on `getState`, a job enqueued | |
| B09 | analyzer job fails → `failed`; `awaiting_confirmation` → `analyzing` | |
| B10 | app-url duplicate → 409 | |
| B11 | fp-variant duplicate (`?utm_source=x`, `youtu.be` vs `watch?v=`) → 409 | new behavior |
| B12 | app create of a URL already on the web → 201, deduped link, no new job, `user_note` unchanged | |
| B13 | app create of a URL that is only in app trash → new row, core unhidden, old link `hid_core=0` | I7 |
| B14 | core-rejected URL → 201 `failed`, no core rows (savepoint) | |
| B15 | restore with fp conflict → 409; restore with no conflict → 200 and core unhidden | |
| B16 | two accounts, same URL → two core contents, no cross-visibility in `/api` or `/v1` | scoping |
| B17 | web re-save of an app-trashed URL → `200 deduplicated`, core visible, claim released; app purge keeps core | I8 |
| B18 | concurrent `/api` create + `/v1` submit for the same URL (2 threads, file DB) → one core content, both 2xx, < 6 s | race + no deadlock |
| B19 | trash → `/v1/contents` (default) hides it; `/v1/search` no longer returns it | index I12 |
| B20 | restore → visible and searchable again | |
| B21 | `emptyTrash` → core row, jobs, embeddings and fingerprints gone; `/v1/contents/{id}` 404 | purge |
| B22 | 30-day `maintain` purge (advance the clock) → same as B21 | |
| B23 | trash, then web `PATCH hidden=false`, then purge → app row gone, core kept and visible | I8 |
| B24 | web-hidden content, app trash → no claim; purge keeps core | I8 |
| B25 | `/v1` DELETE of an `origin=app` item → `/api` status `unavailable`, memo kept | orphan |
| B26 | `/v1` DELETE of an `origin=core` item → gone from `/api/state` | |
| B27 | orphan then web re-save of the same URL → relinked on next `getState` | |
| B28 | `PATCH /api/contents/{id}` title/type → locked; later core title change not shown; memo/collection never touch core | ownership |
| B29 | `listContent?q=` matches projected AI tags/description | |
| B30 | `getContent` of a foreign or malformed id → 404 (unchanged) | |
| B31 | trash during a running job → job continues; content stays hidden; indexed as removed | |
| B32 | purge during an active job → job cancelled, no worker crash, no orphan rows | |
| B33 | duplicate status (content-hash dupe by worker) → projection uses the canonical analysis | |
| B34 | atomicity: monkeypatch `enqueue_in_transaction` to raise `SQLAlchemyError` after the content insert → 500; no app row, notice, core row or job | partial-failure guard |
| B35 | `CoreRejected` path leaves no fingerprint or contents row | savepoint |
| B36 | sync failure (monkeypatch backfill to raise) → `getState` still 200 with the pre-sync state; warning logged without URLs | |
| B37 | `DELETE /api/me` → app rows, links, core contents, jobs, fingerprints and index revisions all gone | cascade |
| B38 | bridge disabled (`JUPJUP_APP_BRIDGE_ENABLED=false`) → exact legacy behavior | flag |
| B39 | `bridge audit` on a healthy DB → all zeros, exit 0; after manual SQL corruption → nonzero, `--repair` fixes I5/I6/I9 | |
| B40 | **no nested connection:** count pool checkouts during each `/api` operation via `event.listen(engine, "checkout")` → exactly the handler's connection (+ `maintain`); on `:memory:` StaticPool, create+trash+purge persist (no silent rollback) | I10 |
| B41 | every `/api` response in B01–B40 validates against the spec; `test_spec_is_frozen` still passes | I11 |
| R1 | all existing suites unchanged: `test_app_api.py`, `test_mobile_connect.py`, `test_save_api.py`, `test_save_acceptance.py`, `test_api_ingest*.py`, `test_account_scoping.py`, `test_collections.py`, `test_social_oauth.py` | no regressions |
| R2 | perf: `getState` with 500 linked analyzed items < 1.5 s on the mock DB (CI-safe budget; skip marker if slow runner) | |

---

## 12. Task order and dependency tree

```
T1 migration (app_bridge_migration + db.py wiring) ── M1–M3
 └─ T2 core refactors (create_in_transaction, delete_in_transaction, bundles_in/metadata_in,
 │     visible_analysis rename, bridge_sql.release_bridge_hide) ── R1 must stay green
 │   └─ T3 bridge package: ports/core_port → links → projection (P1–P3) → service
 │       └─ T4 app_api integration (http.create_api bridge param, maintain purge, service hooks,
 │       │     repository projection hook) ── B01, B10–B15, B19–B22, B34–B35, B40
 │       │   └─ T5 wiring (api/app.py reorder, Settings flag, analyzer_profile_name) ── B02–B09, B16–B18, B23–B33, B36–B38
 │       │       └─ T6 audit + CLI ── B39
 │       └─ T7 perf + contract sweep ── R2, B41
 └─ T8 report specs/phase12_bridge_report.md
```
Single Codex-Primary worktree (`phase-12-app-content-bridge`). No parallel `src/` workers.

## 13. Acceptance criteria (Reviewer scoring)
1. Q1 end-to-end proven by B01–B04 on a file DB with the real `create_app`.
2. B34, B35 and B40 pass: no partial writes, no nested connections, no silent StaticPool rollback.
3. All tests in §11 pass. `uv run --offline pytest`, `ruff check src tests` and `mypy` are clean (the known `frontend/scripts` ruff noise excluded).
4. `specs/app_api_openapi.json` is byte-identical, and `git diff --stat` shows no change to it, to any historical migration file or to `frontend/`.
5. No `/v1` behavior change except `release_bridge_hide` (which is a no-op without links), proven by R1.
6. Logs and the CLI audit never print URLs, memos, titles or tokens.

## 14. Risks
- **`submit` refactor regression:** mitigated by extracting the code verbatim, keeping R1 green and diffing response JSON in existing tests.
- **Projection cost** on very large libraries: `bundles_in` loads snapshot text. The R2 budget guards it. If it fails, add `SqlContentRepository.projection_rows_in(conn, user_id, ids)` that loads only summaries, tags, detail run id and snapshot `raw_meta`, and keep P3 parity tests.
- **Backfill inside GET** holds the writer lock longer on the first big sync. It is bounded by `sync_limit=500`; run `bridge audit --repair` once after deploy.
- **Behavior change:** URL variants now 409 on `/api` (B11). This is spec-legal; mention it in release notes for the app team.

## 15. Open questions (defaults chosen; PM can override before implementation)
- **OQ1 (default: yes):** `/v1` hard delete removes `origin=core` app rows but leaves `origin=app` rows as `unavailable`. The alternative is to delete both.
- **OQ2 (default: unhide):** an explicit app save of a URL the web has *hidden* unhides it on the web.
- **OQ3 (default: no):** add an "분석이 끝났어요" notice when a bridged item becomes `ready`?
- **OQ4 (default: stays /v1-only, audit Q2):** text and image web saves in the app.

---

## 16. Handoff to Codex-Primary (Phase 12 implementation)

- **Worktree:** `phase-12-app-content-bridge` (base PM after this spec is merged).
- **Read first:** this file, `.claude/agents/codex-primary.md`, `specs/mobile_backend_contract_audit.md` §6 and §8.
- **Scope (edit):** `src/jupjup/bridge/**` (new), `src/jupjup/storage/{app_bridge_migration,bridge_sql}.py` (new), `src/jupjup/storage/{db,repositories}.py`, `src/jupjup/save/{service,query,routes}.py`, `src/jupjup/app_api/{http,service,repository}.py`, `src/jupjup/api/app.py`, `src/jupjup/container.py` (`analyzer_profile_name`), `src/jupjup/config.py` (flag), `src/jupjup/cli.py` (`bridge audit`), the new tests in §11, and a README note (URL-variant 409, `bridge audit --repair` after deploy).
- **Don't touch:** `specs/app_api_openapi.json`, any existing migration file, OAuth, search ranking, the ingest worker and stages, `frontend/`.
- **Hard rules:** I10 (no `engine.connect()`/`begin()` under the `/api` transaction); savepoints via raw `SAVEPOINT`/`RELEASE`/`ROLLBACK TO` on the handler `conn`; `bridge=None` keeps legacy behavior bit-for-bit.
- **Report:** `specs/phase12_bridge_report.md` with the test counts per §11 ID group, the pytest/ruff/mypy output and any deviations from this design (with reasons).
