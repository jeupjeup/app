# Mobile integration work report

## Implemented

The CLI permits an external bind only with both `--allow-external-bind` and
`app_session` authentication. External binds force the development admin API off
and print a LAN URL hint. The `/api` sub-application no longer redirects trailing
slashes. Added a frozen specification hash check, bind policy and routing tests,
a standard-library smoke script, and mobile connection instructions.

## Outstanding

Phase 12 is **not implemented**: mobile and core content remain separate. In
particular, mobile saves do not enter the core analysis or search pipeline, and
web saves are not backfilled into mobile state. A correct bridge needs a shared
transaction for core ingest and mobile linking, plus coordinated index removal,
trash/restore and backfill. The existing `ContentCommandService.submit` starts
its own transaction while the mobile endpoint already holds a SQLite writer
lock, so calling it directly would not provide rollback consistency and risks a
deadlock. No migration or partial bridge was added.

Phase 11 contract coverage is also incomplete: the full T2, T3, T6 and T7
matrices and live LAN smoke run remain to be completed. The smoke script checks
the basic flow, but does not validate responses against JSON Schema.

Production domain and HTTPS deployment remain infrastructure work.

## Verification

- `uv run --offline pytest tests/integration/test_mobile_connect.py tests/integration/test_app_api.py`: 64 passed.
- `uv run --offline ruff check src tests scripts/app_contract_smoke.py`: passed.
- `uv run --offline mypy`: passed, 130 source files.
- `uv run --offline ruff check .`: fails on 11 existing violations in `frontend/scripts/smoke_local_api.py`.
