from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from jupjup.domain.errors import IdempotencyConflictError, IdempotencyInProgressError
from jupjup.storage import tables as T
from jupjup.storage.db import create_db_engine
from jupjup.storage.save_repositories import IdempotencyRepository, canonical_request_hash


def test_idempotency_replay_conflict_and_no_plaintext_key_or_source() -> None:
    engine = create_db_engine(None)
    repo = IdempotencyRepository(engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    body = {"source": {"kind": "text", "text": "private source"}, "user_note": "private note"}
    request_hash = canonical_request_hash({"path": {}, "body": body})
    reservation = repo.reserve("u_alice", "POST /v1/contents", "plain-secret-key", request_hash, now)
    assert reservation.replayed is False
    with pytest.raises(IdempotencyInProgressError):
        repo.reserve("u_alice", "POST /v1/contents", "plain-secret-key", request_hash, now)
    repo.complete(reservation, 202, {"content_id": "c_1", "job_id": "job_1"}, "c_1", "job_1")
    replay = repo.reserve("u_alice", "POST /v1/contents", "plain-secret-key", request_hash, now)
    assert replay.replayed is True
    assert replay.response_status == 202
    assert replay.response_json == {"content_id": "c_1", "job_id": "job_1"}
    with pytest.raises(IdempotencyConflictError):
        repo.reserve(
            "u_alice",
            "POST /v1/contents",
            "plain-secret-key",
            canonical_request_hash({"path": {}, "body": {"source": {"kind": "text", "text": "other"}}}),
            now,
        )
    with engine.connect() as connection:
        stored = connection.execute(select(T.idempotency_keys)).mappings().one()
    assert "plain-secret-key" not in str(dict(stored))
    assert "private source" not in str(dict(stored))
    assert "private note" not in str(dict(stored))


@pytest.mark.parametrize("key", ["", "contains\nnewline", "x" * 129, "한글"])
def test_invalid_idempotency_key_is_rejected(key: str) -> None:
    with pytest.raises(ValueError):
        IdempotencyRepository.validate_key(key)
