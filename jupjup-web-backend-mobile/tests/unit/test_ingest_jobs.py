"""T22 SQLite queue transitions, leases, retry policy, and error classification."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from jupjup.domain.errors import (
    AnalysisSchemaError,
    FetchError,
    LeaseLostError,
    LLMProviderError,
    LLMRefusalError,
    UnsupportedSourceError,
)
from jupjup.domain.models import Content, ContentBundle
from jupjup.ingest.jobs import JOB_STAGES, InvalidJobTransition, JobQueue
from jupjup.ingest.worker import IngestWorker, RetryPolicy, is_retryable_error
from jupjup.storage.db import create_db_engine
from jupjup.storage.repositories import SqlContentRepository

NOW = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)


def queue_with_content() -> tuple[JobQueue, SqlContentRepository]:
    engine = create_db_engine(None)
    repo = SqlContentRepository(engine)
    repo.upsert(
        ContentBundle(
            content=Content(
                id="c_queue",
                user_id="u_queue",
                platform="local",
                content_type="message",
                saved_at=NOW,
                status="pending",
            )
        )
    )
    return JobQueue(engine), repo


def test_all_success_state_transitions_and_events() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    assert queue.get(job_id).status == "queued"

    job = queue.lease("w1", NOW)
    assert job is not None and job.status == "running" and job.stage == "fetch"
    for index, stage in enumerate(JOB_STAGES):
        leased = queue.get(job_id)
        assert leased.lease_id is not None
        current = queue.begin_stage(job_id, NOW + timedelta(seconds=index), "w1", leased.lease_id)
        assert current.stage == stage and current.attempts[stage] == 1
        following = JOB_STAGES[index + 1] if index + 1 < len(JOB_STAGES) else None
        queue.advance(
            job_id,
            following,
            NOW + timedelta(seconds=index, milliseconds=500),
            lease_id=leased.lease_id,
        )

    done = queue.get(job_id)
    assert done.status == "succeeded" and done.leased_by is None and done.lease_until is None
    expected_events = [value for _ in JOB_STAGES for value in ("started", "succeeded")]
    assert [event.event for event in queue.events(job_id)] == expected_events
    with pytest.raises(LeaseLostError):
        queue.advance(job_id, None, NOW, lease_id="expired")


def test_retry_failed_and_needs_review_transitions() -> None:
    queue, _ = queue_with_content()

    retry_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    assert queue.lease("w1", NOW) is not None
    retry = queue.get(retry_id)
    assert retry.lease_id is not None
    queue.begin_stage(retry_id, NOW, "w1", retry.lease_id)
    due = NOW + timedelta(seconds=7)
    queue.fail(retry_id, FetchError("temporary"), NOW, True, lease_id=retry.lease_id, next_run_at=due)
    assert queue.get(retry_id).status == "retry_wait"
    assert queue.lease("w2", due - timedelta(microseconds=1)) is None
    assert queue.lease("w2", due) is not None

    # Finish the retried job so it cannot win the next priority tie.
    retried = queue.get(retry_id)
    assert retried.lease_id is not None
    queue.fail(retry_id, UnsupportedSourceError("bad"), due, False, lease_id=retried.lease_id)
    failed_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    assert queue.lease("w1", due) is not None
    failed = queue.get(failed_id)
    assert failed.lease_id is not None
    queue.fail(failed_id, UnsupportedSourceError("bad"), due, False, lease_id=failed.lease_id)
    assert queue.get(failed_id).status == "failed"

    review_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    assert queue.lease("w1", due) is not None
    review = queue.get(review_id)
    assert review.lease_id is not None
    queue.fail(review_id, LLMRefusalError("no"), due, False, lease_id=review.lease_id)
    assert queue.get(review_id).status == "needs_review"


def test_expired_lease_is_recovered_at_same_stage() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, initial_stage="analyze", now=NOW)
    first = queue.lease("dead-worker", NOW, lease_s=5)
    assert first is not None
    assert queue.lease("other", NOW + timedelta(seconds=5)) is None
    recovered = queue.lease("other", NOW + timedelta(seconds=5, microseconds=1))
    assert recovered is not None
    assert recovered.id == job_id and recovered.stage == "analyze" and recovered.leased_by == "other"
    assert recovered.lease_id != first.lease_id


def test_stale_lease_cannot_advance_fail_or_write_artifacts() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    stale = queue.lease("same-worker", NOW, lease_s=5)
    assert stale is not None and stale.lease_id is not None
    current = queue.lease("same-worker", NOW + timedelta(seconds=6), lease_s=5)
    assert current is not None and current.lease_id is not None and current.lease_id != stale.lease_id

    with pytest.raises(LeaseLostError):
        queue.advance(job_id, "extract", NOW + timedelta(seconds=6), lease_id=stale.lease_id)
    with pytest.raises(LeaseLostError):
        queue.fail(
            job_id,
            FetchError("stale"),
            NOW + timedelta(seconds=6),
            True,
            lease_id=stale.lease_id,
        )
    with pytest.raises(LeaseLostError):
        queue.put_artifact(job_id, "raw", {"forbidden": True}, NOW, lease_id=stale.lease_id)

    unchanged = queue.get(job_id)
    assert unchanged.status == "running" and unchanged.stage == "fetch"
    assert unchanged.lease_id == current.lease_id and "raw" not in unchanged.stage_data


def test_same_worker_threads_keep_a_slow_stage_alive_with_heartbeat() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=datetime.now(UTC))
    calls = 0

    def slow(_: Any) -> None:
        nonlocal calls
        calls += 1
        time.sleep(1.3)

    stages = {stage: (slow if stage == "fetch" else lambda _job: None) for stage in JOB_STAGES}
    worker = IngestWorker(queue, stages, worker_id="shared", lease_s=1, concurrency=2)
    first = threading.Thread(target=worker.run_once)
    first.start()
    time.sleep(1.05)
    assert not worker.run_once()
    first.join(timeout=3)

    assert not first.is_alive()
    assert calls == 1
    assert queue.get(job_id).status == "succeeded"


def test_backoff_uses_injected_clock_and_is_deterministic() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    clock = [NOW]
    calls = {"fetch": 0}

    def fetch(_: Any) -> None:
        calls["fetch"] += 1
        if calls["fetch"] == 1:
            raise FetchError("temporary")

    stages = {stage: (fetch if stage == "fetch" else lambda _job: None) for stage in JOB_STAGES}
    policy = RetryPolicy(base_s=2, cap_s=300, jitter=0.2)
    worker = IngestWorker(queue, stages, lambda: clock[0], policy, worker_id="clocked")

    assert worker.run_once()
    waiting = queue.get(job_id)
    expected = policy.delay(job_id, "fetch", 1)
    assert waiting.status == "retry_wait"
    assert waiting.next_run_at == NOW + timedelta(seconds=expected)
    assert policy.delay(job_id, "fetch", 1) == expected
    assert not worker.run_once()

    clock[0] = waiting.next_run_at
    assert worker.run_once()
    assert queue.get(job_id).status == "succeeded"
    assert queue.get(job_id).attempts["fetch"] == 2


def test_retry_exhaustion_becomes_terminal_failure() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    clock = [NOW]

    def unavailable(_: Any) -> None:
        raise FetchError("still unavailable")

    policy = RetryPolicy(max_attempts={"fetch": 2}, jitter=0)
    worker = IngestWorker(queue, {"fetch": unavailable}, lambda: clock[0], policy, worker_id="retrying")
    assert worker.run_once()
    first = queue.get(job_id)
    assert first.status == "retry_wait" and first.next_run_at is not None
    clock[0] = first.next_run_at
    assert worker.run_once()
    failed = queue.get(job_id)
    assert failed.status == "failed" and failed.attempts["fetch"] == 2


def test_retryable_and_permanent_errors_are_distinct() -> None:
    assert is_retryable_error(FetchError("timeout"))
    assert not is_retryable_error(UnsupportedSourceError("bad source"))
    assert not is_retryable_error(AnalysisSchemaError("bad schema"))
    assert not is_retryable_error(LLMRefusalError("refused"))
    assert is_retryable_error(LLMProviderError("rate limited", {"status": 429}))
    assert is_retryable_error(LLMProviderError("server", {"status": 503}))
    assert not is_retryable_error(LLMProviderError("bad request", {"status": 400}))


def test_priority_new_ingest_before_reanalysis() -> None:
    queue, repo = queue_with_content()
    repo.upsert(
        ContentBundle(
            content=Content(
                id="c_queue_high",
                user_id="u_queue",
                platform="local",
                content_type="message",
                saved_at=NOW,
                status="pending",
            )
        )
    )
    low = queue.enqueue("c_queue", "u_queue", "reanalyze", 1, initial_stage="chunk", now=NOW)
    high = queue.enqueue("c_queue_high", "u_queue", "ingest", 10, now=NOW + timedelta(seconds=1))
    leased = queue.lease("w", NOW + timedelta(seconds=2))
    assert leased is not None and leased.id == high and leased.id != low


def test_only_one_active_job_is_allowed_per_content() -> None:
    queue, _ = queue_with_content()
    queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    with pytest.raises(InvalidJobTransition):
        queue.enqueue("c_queue", "u_queue", "reanalyze", 1, initial_stage="chunk", now=NOW)


def test_error_log_uses_allowlisted_details_and_deterministic_event_sequence() -> None:
    queue, _ = queue_with_content()
    job_id = queue.enqueue("c_queue", "u_queue", "ingest", 10, now=NOW)
    leased = queue.lease("w", NOW)
    assert leased is not None and leased.lease_id is not None
    queue.begin_stage(job_id, NOW, "w", leased.lease_id)
    queue.fail(
        job_id,
        LLMProviderError("원문 자체가 메시지에 들어감", {"raw": "절대 저장하면 안 되는 본문", "status": 503}),
        NOW,
        True,
        lease_id=leased.lease_id,
        next_run_at=NOW + timedelta(seconds=2),
    )

    record = queue.get(job_id)
    serialized = str(record.last_error)
    assert "절대 저장하면 안 되는 본문" not in serialized
    assert "원문 자체가 메시지에 들어감" not in serialized
    assert record.last_error == {
        "code": "LLM_UNAVAILABLE",
        "details": {"status": 503},
        "message": "LLM_UNAVAILABLE",
        "stage": "fetch",
    }
    assert [event.event for event in queue.events(job_id)] == ["started", "retry"]


def test_run_forever_survives_queue_error(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    queue, _ = queue_with_content()
    stop = threading.Event()
    calls = 0
    original = queue.lease

    def flaky(worker_id: str, now: datetime, lease_s: int = 300) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("lease", {}, RuntimeError("database is locked"))
        if calls >= 3:
            stop.set()
        return original(worker_id, now, lease_s)

    monkeypatch.setattr(queue, "lease", flaky)
    worker = IngestWorker(queue, {}, worker_id="survivor", concurrency=1)
    worker.run_forever(stop)

    assert calls >= 3
    assert any(record.message == "ingest worker task failed" for record in caplog.records)
