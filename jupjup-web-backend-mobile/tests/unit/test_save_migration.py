from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, select

from jupjup.domain.models import Content, ContentBundle, DetailTags, Summary, Tag
from jupjup.ingest.analyzer import AnalysisRunMeta
from jupjup.ingest.jobs import JobQueue
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.storage import tables as T
from jupjup.storage.db import create_db_engine
from jupjup.storage.repositories import SqlContentRepository


def _pre_t27_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE contents (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, source_url TEXT,
          platform TEXT NOT NULL, content_type TEXT NOT NULL, title TEXT,
          author TEXT, published_at TEXT, saved_at TEXT NOT NULL,
          original_status TEXT NOT NULL DEFAULT 'unknown', user_note TEXT,
          hidden_tags TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'ready',
          analysis_pending INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO contents VALUES (
          'c_old', 'u_alice', 'https://Example.com/a?utm_source=x', 'web', 'webpage',
          'old', NULL, NULL, '2026-01-01T00:00:00+00:00', 'unknown', NULL, '[]',
          'ready', 0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        """
    )
    connection.commit()
    connection.close()


def test_migration_from_pre_t27_db_preserves_rows_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    _pre_t27_database(path)

    engine = create_db_engine(path)
    columns = {column["name"] for column in inspect(engine).get_columns("contents")}
    assert {
        "source_kind",
        "normalized_url",
        "automation_level",
        "is_hidden",
        "revision",
        "duplicate_of_content_id",
    } <= columns
    assert {"ix_contents_user_hidden_saved", "ix_contents_user_updated", "ix_contents_user_status"} <= {
        index["name"] for index in inspect(engine).get_indexes("contents")
    }
    assert {
        "schema_migrations",
        "idempotency_keys",
        "content_fingerprints",
        "analysis_candidates",
        "ingest_trace_artifacts",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        row = connection.execute(select(T.contents).where(T.contents.c.id == "c_old")).mappings().one()
        assert row["source_kind"] == "url"
        assert row["normalized_url"] == "https://example.com/a"
        assert row["automation_level"] == "auto"
        assert row["revision"] == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        versions = connection.execute(select(T.schema_migrations.c.version)).all()

    engine.dispose()
    rerun = create_db_engine(path)
    with rerun.connect() as connection:
        assert connection.scalar(select(T.contents.c.id).where(T.contents.c.id == "c_old")) == "c_old"
        assert connection.execute(select(T.schema_migrations.c.version)).all() == versions


def test_persist_ai_analysis_preserves_user_layers() -> None:
    engine = create_db_engine(None)
    repo = SqlContentRepository(engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    repo.upsert(
        ContentBundle(
            content=Content(
                id="c_layers",
                user_id="u_alice",
                platform="local",
                content_type="message",
                saved_at=now,
                hidden_tags=["숨김"],
                user_note="keep",
            ),
            summaries=[
                Summary(
                    id="sum_user",
                    content_id="c_layers",
                    version=1,
                    text="사용자 요약",
                    source="user",
                    created_at=now,
                )
            ],
            tags=[Tag(name="사용자", source="user"), Tag(name="이전AI", source="ai")],
            detail_tags=DetailTags(
                content_id="c_layers",
                ai_json={"schema_version": 1, "topics": ["이전"]},
                user_patch={"topics": ["사용자"]},
            ),
        )
    )
    output = AnalysisOutput.model_validate(
        {
            "summary": "새로운 AI 분석 요약이며 충분한 길이를 갖춘 문장입니다.",
            "representative_tags": ["새AI", "숨김", "분석"],
            "detail_tags": {"schema_version": 1, "topics": ["새AI"]},
            "save_intent": {"labels": [], "confidence": 0.0, "rationale": ""},
            "title_suggestion": None,
            "language": "ko",
            "evidence": [],
        }
    )
    meta = AnalysisRunMeta.model_validate(
        {
            "model": "mock",
            "prompt_version": "v1",
            "attempts": 1,
            "first_pass_ok": True,
            "partial": False,
            "repairs": [],
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": 0,
            "latency_ms": 1,
        }
    )
    job_id = JobQueue(engine).enqueue("c_layers", "u_alice", "reanalyze", 1, initial_stage="chunk", now=now)

    repo.persist_ai_analysis(
        "u_alice",
        "c_layers",
        run_id="run_new",
        job_id=job_id,
        profile="mock",
        output=output,
        meta=meta,
        analysis_input={"mode": "single", "coverage": "full"},
        accepted_at=now,
    )

    saved = repo.get_bundle("u_alice", "c_layers")
    assert saved.summary is not None and saved.summary.text == "사용자 요약"
    assert [tag.name for tag in saved.tags if tag.source == "user"] == ["사용자"]
    assert saved.content.hidden_tags == ["숨김"]
    assert saved.content.user_note == "keep"
    assert saved.detail_tags is not None
    assert saved.detail_tags.user_patch == {"topics": ["사용자"]}
    assert saved.detail_tags.ai_json["topics"] == ["새AI"]
    with engine.connect() as connection:
        output_json = connection.scalar(select(T.analysis_runs.c.output_json).where(T.analysis_runs.c.id == "run_new"))
    assert json.loads(output_json)["summary"].startswith("새로운 AI 분석")


def test_migration_backup_fingerprint_and_manual_policy(tmp_path: Path) -> None:
    import pytest

    from jupjup.storage.migration import MigrationError

    path = tmp_path / "old.db"
    _pre_t27_database(path)
    before = path.read_bytes()
    with pytest.raises(MigrationError):
        create_db_engine(path, auto_migrate=False)
    assert path.read_bytes() == before
    engine = create_db_engine(path)
    backups = sorted(tmp_path.glob("old.db.*.bak"))
    assert len(backups) == 2  # pre-v27 and pre-v29
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT id,source_url FROM contents").fetchall() == [
            ("c_old", "https://Example.com/a?utm_source=x")
        ]
        assert "source_kind" not in {r[1] for r in backup.execute("PRAGMA table_info(contents)")}
    with engine.connect() as conn:
        assert conn.scalar(select(T.content_fingerprints.c.content_id)) == "c_old"


def test_migration_failure_rolls_back_ddl_and_checksum_tampering_is_rejected(tmp_path: Path) -> None:
    import pytest
    from sqlalchemy import create_engine, event

    from jupjup.storage.migration import MigrationError, run_migrations

    path = tmp_path / "rollback.db"
    _pre_t27_database(path)
    engine = create_engine(f"sqlite:///{path}")

    def fail_record(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO schema_migrations"):
            raise RuntimeError("injected migration failure")

    event.listen(engine, "before_cursor_execute", fail_record)
    with pytest.raises(RuntimeError, match="injected"):
        run_migrations(engine)
    assert "source_kind" not in {column["name"] for column in inspect(engine).get_columns("contents")}
    assert "schema_migrations" not in inspect(engine).get_table_names()
    event.remove(engine, "before_cursor_execute", fail_record)
    run_migrations(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE schema_migrations SET checksum='tampered'")
    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(engine)
