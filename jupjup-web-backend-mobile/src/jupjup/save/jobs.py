"""Owned review decisions and truthful event-derived job views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from jupjup.api.errors import ApiError
from jupjup.domain.errors import NotFoundError
from jupjup.ingest.jobs import JOB_STAGES
from jupjup.ingest.service import IngestService
from jupjup.save.dto import ReviewRequest
from jupjup.storage import tables as T


def review(ingest: IngestService, user_id: str, content_id: str, request: ReviewRequest) -> tuple[int, dict[str, Any]]:
    now = ingest.worker.clock().isoformat()
    with ingest.repo.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE analysis_candidates SET status=status WHERE 0")
        candidate = (
            conn.execute(
                select(T.analysis_candidates).where(
                    T.analysis_candidates.c.id == request.candidate_id,
                    T.analysis_candidates.c.user_id == user_id,
                    T.analysis_candidates.c.content_id == content_id,
                )
            )
            .mappings()
            .first()
        )
        if candidate is None:
            raise NotFoundError("후보를 찾을 수 없어요.")
        desired = "approved" if request.decision == "approve" else "rejected"
        if candidate["status"] not in ("pending", desired):
            raise ApiError(409, "REVIEW_CONFLICT", "후보 결정이 충돌합니다")
        if candidate["status"] == "pending":
            job = (
                conn.execute(
                    select(T.ingest_jobs).where(
                        T.ingest_jobs.c.id == candidate["job_id"], T.ingest_jobs.c.user_id == user_id
                    )
                )
                .mappings()
                .one()
            )
            if job["status"] != "awaiting_confirmation":
                raise ApiError(409, "REVIEW_CONFLICT", "대기 중인 후보가 아닙니다")
            conn.execute(
                update(T.analysis_candidates)
                .where(
                    T.analysis_candidates.c.id == request.candidate_id,
                    T.analysis_candidates.c.user_id == user_id,
                    T.analysis_candidates.c.status == "pending",
                )
                .values(status=desired, decided_at=now, decision_revision=T.analysis_candidates.c.decision_revision + 1)
            )
            conn.execute(
                update(T.ingest_jobs)
                .where(T.ingest_jobs.c.id == candidate["job_id"], T.ingest_jobs.c.user_id == user_id)
                .values(
                    status="queued" if desired == "approved" else "rejected",
                    stage="persist",
                    updated_at=now,
                    stage_data=job["stage_data"] if desired == "approved" else "{}",
                )
            )
            status = "pending" if desired == "approved" else "analysis_rejected"
            conn.execute(
                update(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                .values(status=status, updated_at=now, revision=T.contents.c.revision + 1)
            )
    return (202 if desired == "approved" else 200), dict(
        content_id=content_id,
        job_id=candidate["job_id"],
        candidate_id=candidate["id"],
        decision=request.decision,
        status="queued" if desired == "approved" else "rejected",
    )


def job_detail(ingest: IngestService, user_id: str, job_id: str, trace: str) -> dict[str, Any]:
    job = ingest.status(user_id, job_id)
    events = ingest.queue.events(job_id)
    steps = []
    for stage in JOB_STAGES:
        matches = [event for event in events if event.stage == stage]
        starts = [event for event in matches if event.event == "started"]
        ends = [event for event in matches if event.event in ("succeeded", "failed", "retry")]
        start = starts[0].at if starts else None
        end = ends[-1].at if ends else None
        status = "pending"
        if matches:
            status = {"started": "running", "succeeded": "succeeded", "failed": "failed", "retry": "retry_wait"}[
                matches[-1].event
            ]
        if status == "running":
            end = None
        if stage == "vision" and (job.source_spec is None or job.source_spec.kind != "image"):
            status = "skipped"
        steps.append(
            dict(
                stage=stage,
                status=status,
                attempts=job.attempts.get(stage, 0),
                started_at=start,
                finished_at=end,
                duration_ms=(end - start).total_seconds() * 1000 if start and end else None,
                error=job.last_error if job.last_error and job.last_error.get("stage") == stage else None,
            )
        )
    steps.insert(
        5,
        dict(
            stage="confirm",
            status="skipped"
            if job.automation_level == "auto"
            else (
                "waiting" if job.status == "awaiting_confirmation" else "succeeded" if job.candidate_id else "pending"
            ),
            attempts=0,
            started_at=None,
            finished_at=None,
            duration_ms=None,
            error=None,
        ),
    )
    analysis = job.stage_data.get("analysis") or ingest.queue.artifact(user_id, job_id, "analysis") or {}
    inp = job.stage_data.get("analysis_input") or ingest.queue.artifact(user_id, job_id, "analysis_input") or {}
    snapshot = ingest.repo.get_bundle(user_id, job.content_id).snapshot
    payload: dict[str, Any] = dict(
        id=job.id,
        content_id=job.content_id,
        result_content_id=job.result_content_id or job.content_id,
        kind=job.kind,
        automation_level=job.automation_level,
        status=job.status,
        current_stage="confirm" if job.status == "awaiting_confirmation" else job.stage,
        attempts=job.attempts,
        created_at=job.created_at,
        updated_at=job.updated_at,
        next_run_at=job.next_run_at,
        error=(
            {**job.last_error, "retryable": job.status == "retry_wait", "attempt": job.attempts.get(job.stage, 0)}
            if job.last_error
            else None
        ),
        steps=steps,
        candidate=None,
    )
    if job.candidate_id:
        with ingest.repo.engine.connect() as conn:
            candidate = (
                conn.execute(
                    select(T.analysis_candidates).where(
                        T.analysis_candidates.c.id == job.candidate_id,
                        T.analysis_candidates.c.user_id == user_id,
                    )
                )
                .mappings()
                .first()
            )
        if candidate:
            payload["candidate"] = dict(id=candidate["id"], status=candidate["status"])
            start = datetime.fromisoformat(candidate["created_at"])
            end = datetime.fromisoformat(candidate["decided_at"]) if candidate["decided_at"] else None
            steps[5].update(
                started_at=start,
                finished_at=end,
                duration_ms=(end - start).total_seconds() * 1000 if end else None,
                status="waiting" if candidate["status"] == "pending" else candidate["status"],
            )
    if trace != "none":
        payload["trace"] = dict(
            input=(
                {
                    **inp,
                    "source_kind": ingest.repo.get_bundle(user_id, job.content_id).content.source_kind,
                    "snapshot_id": snapshot.id if snapshot else None,
                    "content_hash": snapshot.content_hash if snapshot else None,
                }
                if trace == "full"
                else dict(
                    snapshot_id=snapshot.id if snapshot else None,
                    content_hash=snapshot.content_hash if snapshot else None,
                )
            ),
            preprocessing={
                **{key: inp[key] for key in ("mode", "coverage", "preprocessing") if key in inp},
                **(
                    {
                        "truncated": snapshot.truncated,
                        "text_chars": len(snapshot.text),
                        "ocr_chars": len(snapshot.ocr_text or ""),
                    }
                    if snapshot
                    else {}
                ),
            },
            validation=ingest.queue.artifact(user_id, job_id, "validation") or {},
            model_processing=dict(profile=job.profile, **analysis.get("meta", {})),
            result=analysis.get("output", {}) if trace == "full" else {},
            evidence=analysis.get("output", {}).get("evidence", []) if trace == "full" else [],
            execution_log=[event.model_dump(mode="json") for event in events],
        )
    return payload
