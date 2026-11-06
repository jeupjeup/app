"""Repair dry-run, guarded backup, and user/source preservation on isolated DB."""

import importlib.util
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jupjup.config import Settings
from jupjup.container import build_container
from jupjup.domain.models import Content, ContentBundle, DetailTags, Snapshot, Summary, Tag
from jupjup.storage.db import create_db_engine


def module():
    spec = importlib.util.spec_from_file_location(
        "repair_youtube_source", Path(__file__).parents[2] / "scripts/repair_youtube_source.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_repair_is_scoped_backed_up_and_preserves_user_content(container_factory, tmp_path):
    repair = module()
    db = tmp_path / "repair.db"
    container = build_container(Settings(env="test", mode="mock", db_path=str(db)), engine=create_db_engine(db))
    now = datetime.now(UTC)
    body = "정보보도자료저작권문의하기크리에이터광고개발자약관개인정보처리방침 Google LLC"
    bundle = ContentBundle(
        content=Content(
            id=repair.TARGET,
            user_id=repair.USER,
            source_url=repair.URL,
            platform="youtube",
            content_type="video",
            saved_at=now,
            status="ready",
            user_note="내 메모 보존",
        ),
        snapshot=Snapshot(
            id="bad-snapshot",
            content_id=repair.TARGET,
            captured_at=now,
            text=body,
            content_hash="bad-hash",
            raw_meta={"source": "http"},
        ),
        summaries=[
            Summary(
                id="ai-summary",
                content_id=repair.TARGET,
                version=1,
                text="잘못된 mock 요약",
                source="ai",
                model="mock-analyzer-v1",
                created_at=now,
            ),
            Summary(
                id="user-summary",
                content_id=repair.TARGET,
                version=1,
                text="내가 수정한 요약",
                source="user",
                created_at=now,
            ),
        ],
        tags=[Tag(name="잘못된태그", source="ai", created_at=now), Tag(name="내태그", source="user", created_at=now)],
        detail_tags=DetailTags(
            content_id=repair.TARGET,
            ai_json={"schema_version": 1, "topics": ["wrong"]},
            user_patch={"topics": ["내 주제"]},
        ),
    )
    container.repo.upsert(bundle)
    container.repo.upsert(
        ContentBundle(
            content=Content(id="unrelated", user_id=repair.USER, platform="local", content_type="message", saved_at=now)
        )
    )
    before = repair.repair(db)
    assert before["status"] == "dry_run"
    assert container.repo.get_bundle(repair.USER, repair.TARGET).content.status == "ready"
    with pytest.raises(ValueError, match="변경"):
        repair.repair(db, expected="wrong", backup=tmp_path / "wrong.db")
    backup = tmp_path / "backup.db"
    assert repair.repair(db, expected=before["state_sha256"], backup=backup)["status"] == "repaired"
    with sqlite3.connect(backup) as c:
        assert c.execute("select count(*) from summaries").fetchone()[0] == 2
    after = container.repo.get_bundle(repair.USER, repair.TARGET)
    assert after.content.status == "analysis_failed"
    assert after.content.user_note == "내 메모 보존"
    assert after.snapshot.text == body
    assert [s.text for s in after.summaries] == ["내가 수정한 요약"]
    assert [t.name for t in after.tags] == ["내태그"]
    assert after.detail_tags.user_patch == {"topics": ["내 주제"]}
    assert not after.detail_tags.ai_json.get("topics")
    assert container.repo.get_bundle(repair.USER, "unrelated").content.status == "ready"


def test_missing_target_skip(container_factory, tmp_path):
    db = tmp_path / "empty.db"
    build_container(Settings(env="test", mode="mock", db_path=str(db)), engine=create_db_engine(db))
    assert module().repair(db)["status"] == "skip_missing"
