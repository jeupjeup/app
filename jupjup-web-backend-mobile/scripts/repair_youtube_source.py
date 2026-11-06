"""Repair only the approved legacy item. Default dry-run; never recreate missing data.

Apply requires the dry-run state hash and a new backup file. Uses SQLite backup and
an immediate transaction, refuses active jobs or unexpected source/snapshot state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

TARGET = "c_cab996a8fd78407d8fbdc3e8948a5232"
USER = "u_frontend_dev"
URL = "https://www.youtube.com/watch?v=EbL67RhCGbY"
TABLES = (
    "contents",
    "snapshots",
    "summaries",
    "tags",
    "detail_tags",
    "ingest_jobs",
    "analysis_runs",
    "analysis_candidates",
    "embeddings",
    "ingest_trace_artifacts",
)


def state(conn):
    result = {}
    for table in TABLES:
        column = "id" if table == "contents" else "content_id"
        rows = conn.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY rowid", (TARGET,)).fetchall()
        result[table] = [dict(row) for row in rows]
    return result


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=lambda v: bytes(v).hex()).encode()).hexdigest()


def repair(db: Path, *, expected: str | None = None, backup: Path | None = None):
    if not db.is_file():
        raise ValueError("DB 파일이 없습니다")
    conn = sqlite3.connect(f"file:{db.resolve()}?mode={'rw' if expected else 'ro'}", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.create_function(
        "utc_instant",
        1,
        lambda value: datetime.fromisoformat(value).astimezone(UTC).isoformat(timespec="microseconds"),
        deterministic=True,
    )
    try:
        if expected:
            conn.execute("BEGIN IMMEDIATE")
        data = state(conn)
        if not data["contents"]:
            conn.rollback()
            return {"status": "skip_missing", "content_id": TARGET}
        content = data["contents"][0]
        if content["user_id"] != USER or content["source_url"] != URL:
            raise ValueError("대상 사용자/URL 불일치")
        if len(data["snapshots"]) != 1:
            raise ValueError("원문이 없거나 여러 버전입니다. 수동 검토 필요")
        snapshot = data["snapshots"][0]
        body = snapshot["text"] or ""
        if not all(marker in body for marker in ("저작권", "개인정보처리방침", "약관")) or len(body) > 1500:
            raise ValueError("알려진 잘못된 원문과 다릅니다")
        if any(
            j["status"] in ("queued", "running", "retry_wait", "awaiting_confirmation") for j in data["ingest_jobs"]
        ):
            raise ValueError("활성 작업이 있습니다. 동시 수정 금지")
        digest = fingerprint(data)
        if not expected:
            return {
                "status": "dry_run",
                "content_id": TARGET,
                "state_sha256": digest,
                "counts": {t: len(rows) for t, rows in data.items()},
                "preserves": "snapshots/user summaries/user tags/user_patch/source_spec",
            }
        if digest != expected:
            raise ValueError("dry-run 이후 대상이 변경되었습니다")
        if backup is None or backup.exists() or backup.resolve() == db.resolve():
            raise ValueError("새 backup 경로가 필요합니다")
        backup.parent.mkdir(parents=True, exist_ok=True)
        # Backup on a second read connection: the writer holds a reserved lock,
        # preventing writes while WAL readers can still copy the committed state.
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as reader, sqlite3.connect(backup) as dest:
            reader.backup(dest)
        for table in ("summaries", "tags"):
            conn.execute(f"DELETE FROM {table} WHERE content_id=? AND source='ai'", (TARGET,))
        conn.execute(
            "UPDATE detail_tags SET ai_json=?, analysis_run_id=NULL WHERE content_id=?",
            ('{"schema_version":1}', TARGET),
        )
        conn.execute("DELETE FROM embeddings WHERE content_id=?", (TARGET,))
        conn.execute("DELETE FROM analysis_candidates WHERE content_id=? AND user_id=?", (TARGET, USER))
        conn.execute("DELETE FROM analysis_runs WHERE content_id=?", (TARGET,))
        conn.execute(
            "DELETE FROM ingest_trace_artifacts WHERE content_id=? AND stage NOT IN ('fetch','extract')", (TARGET,)
        )
        now = datetime.now(UTC).isoformat()
        error = json.dumps(
            {
                "code": "SOURCE_TEXT_UNAVAILABLE",
                "message": "영상 본문 대신 메뉴·약관이 수집되었습니다. 자막이나 텍스트를 직접 저장해 주세요.",
                "details": {"retryable": False, "reason": "legacy_watch_snapshot"},
            }
        )
        conn.execute(
            "UPDATE ingest_jobs SET status='failed',stage='extract',last_error=?,stage_data='{}',"
            "candidate_id=NULL,completed_at=?,updated_at=? WHERE content_id=? AND user_id=?",
            (error, now, now, TARGET, USER),
        )
        conn.execute(
            "UPDATE contents SET status='analysis_failed',analysis_pending=0,revision=revision+1,"
            "updated_at=?,updated_at_instant=? WHERE id=? AND user_id=?",
            (now, now, TARGET, USER),
        )
        conn.commit()
        return {"status": "repaired", "content_id": TARGET, "backup": str(backup), "before_sha256": digest}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and (not args.expected_sha256 or not args.backup):
        parser.error("--apply requires --expected-sha256 and --backup")
    print(
        json.dumps(
            repair(args.db, expected=args.expected_sha256 if args.apply else None, backup=args.backup),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
