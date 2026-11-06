# Phase 12 bridge MVP report

The app and core URL stores now share the app request's SQLite transaction. App saves enqueue core ingestion and create a link in that transaction; core validation rejection is isolated by a raw savepoint. Linked app responses project core status and analysis. The bridge also handles fingerprint conflicts, trash, restore, purge, and lazy adoption/backfill. `JUPJUP_APP_BRIDGE_ENABLED=false` disables the runtime bridge. The independent additive migration preserves the existing migration files and ledgers.

Verification:

- `uv run --offline pytest tests/integration/test_app_bridge.py tests/unit/test_app_bridge_migration.py tests/integration/test_app_api.py tests/integration/test_mobile_connect.py -q`: 71 passed. The bridge tests cover a successful enqueue, unexpected enqueue failure rolling back app/core/job/notice writes, rejection after core writes rolling back the savepoint, and connection checkout counts on file and in-memory databases; they also exercise duplicate, trash, purge and basic backfill behavior.
- `uv run --offline ruff check src tests`: passed.
- `uv run --offline mypy`: passed, 136 source files.
- Frozen OpenAPI SHA-256: `cd18e859669a75280dd8d130150a96a2a0966855911d3b175fbaabaea651194d` (unchanged).
- A focused regression run had one unrelated existing failure: `test_dev_header_rejects_external_bind_even_with_override` expects a different CLI message. The full suite was interrupted at the user's request; the interrupted run had also reported two ingest golden/seal failures.

This is an MVP, not the complete design acceptance: the audit/repair CLI and the full M1–M3, P1–P3, B01–B41, R1–R2 matrix are not implemented or verified. In particular, worker-to-search end-to-end, projection parity, concurrency races, performance, all reconciliation edge cases, and existing-link behavior after disabling the flag still need dedicated coverage. The reconciliation implementation does not expose truncation information or provide the prescribed audit repair drain. Do not treat this report as evidence that all Phase 12 invariants have been proven.
