"""Durable SQLite ingest queue and its state machine."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, and_, func, insert, or_, select, update

from jupjup.domain.errors import JupjupError, LeaseLostError, LLMRefusalError, NotFoundError
from jupjup.ingest.fetch import SourceSpec
from jupjup.storage import tables as T

JobStatus = Literal[
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "needs_review",
    "awaiting_confirmation",
    "rejected",
    "deduplicated",
    "cancelled",
]
JobStage = Literal["fetch", "extract", "vision", "chunk", "analyze", "persist", "embed", "index"]
JobKind = Literal["ingest", "reanalyze"]

JOB_STATUSES: tuple[str, ...] = get_args(JobStatus)
JOB_STAGES: tuple[JobStage, ...] = get_args(JobStage)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "needs_review"})
ACTIVE_STATUSES = ("queued", "running", "retry_wait", "awaiting_confirmation")
# 재분석 잡 stage_data에 재분석 직전 콘텐츠 상태를 담는 키. 실패 시 이 값으로 되돌린다.
PRIOR_CONTENT_KEY = "prior_content"
_RESTORABLE_CONTENT_STATUSES = frozenset({"ready", "analysis_failed", "analysis_rejected"})
SAFE_ERROR_DETAIL_KEYS = frozenset(
    {
        "attempt",
        "attempts",
        "repair_attempts",
        "expected",
        "got",
        "key",
        "kind",
        "retryable",
        "status",
        "timeout_retries",
        "type",
    }
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _safe_error_detail(details: dict[str, Any]) -> dict[str, Any]:
    """Keep diagnostic metadata while excluding source text, paths, hashes, and provider payloads."""
    safe: dict[str, Any] = {}
    for key in SAFE_ERROR_DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, bool | int | float) or (isinstance(value, str) and len(value) <= 120):
            safe[key] = value
    return safe


class InvalidJobTransition(JupjupError):
    code = "INVALID_JOB_TRANSITION"


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    content_id: str
    user_id: str
    kind: JobKind
    status: JobStatus
    stage: JobStage
    automation_level: str = "auto"
    result_content_id: str | None = None
    candidate_id: str | None = None
    priority: int
    profile: str
    attempts: dict[JobStage, int] = Field(default_factory=dict)
    next_run_at: datetime | None = None
    lease_until: datetime | None = None
    leased_by: str | None = None
    lease_id: str | None = None
    last_error: dict[str, Any] | None = None
    source_spec: SourceSpec | None = None
    stage_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_validator("next_run_at", "lease_until", "created_at", "updated_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError("잡 시각은 timezone-aware여야 합니다")
        return value


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    job_id: str
    at: datetime
    stage: JobStage
    event: Literal["started", "succeeded", "retry", "failed"]
    detail: dict[str, Any] = Field(default_factory=dict)


class JobQueue:
    """SQLite queue with compare-and-set leasing.

    All timestamps are normalized to UTC before comparison so ISO text ordering is
    stable even when callers inject clocks from different timezones.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def enqueue(
        self,
        content_id: str,
        user_id: str,
        kind: JobKind,
        priority: int,
        profile: str = "default",
        *,
        source_spec: SourceSpec | None = None,
        initial_stage: JobStage = "fetch",
        now: datetime | None = None,
    ) -> str:
        with self.engine.begin() as conn:
            return self.enqueue_in_transaction(
                conn,
                content_id,
                user_id,
                kind,
                priority,
                profile,
                source_spec=source_spec,
                initial_stage=initial_stage,
                now=now,
            )

    def enqueue_in_transaction(
        self,
        conn: Connection,
        content_id: str,
        user_id: str,
        kind: JobKind,
        priority: int,
        profile: str = "default",
        *,
        source_spec: SourceSpec | None = None,
        initial_stage: JobStage = "fetch",
        now: datetime | None = None,
        stage_data: Mapping[str, Any] | None = None,
    ) -> str:
        at = now or datetime.now(UTC)
        job_id = f"job_{uuid.uuid4().hex}"
        active = conn.scalar(
            select(func.count())
            .select_from(T.ingest_jobs)
            .where(T.ingest_jobs.c.content_id == content_id, T.ingest_jobs.c.status.in_(ACTIVE_STATUSES))
        )
        if active:
            raise InvalidJobTransition("콘텐츠에 이미 활성 인제스트 잡이 있습니다", {"content_id": content_id})
        conn.execute(
            insert(T.ingest_jobs).values(
                id=job_id,
                user_id=user_id,
                content_id=content_id,
                kind=kind,
                status="queued",
                stage=initial_stage,
                priority=priority,
                profile=profile,
                attempts="{}",
                source_spec=None if source_spec is None else source_spec.model_dump_json(),
                stage_data=_json(dict(stage_data or {})),
                created_at=_iso(at),
                updated_at=_iso(at),
            )
        )
        return job_id

    def lease(self, worker_id: str, now: datetime, lease_s: int = 300) -> JobRecord | None:
        return self._lease(worker_id, now, lease_s, job_id=None)

    def lease_job(self, job_id: str, worker_id: str, now: datetime, lease_s: int = 300) -> JobRecord | None:
        return self._lease(worker_id, now, lease_s, job_id=job_id)

    def _lease(self, worker_id: str, now: datetime, lease_s: int, job_id: str | None) -> JobRecord | None:
        if lease_s <= 0:
            raise ValueError("lease_s는 양수여야 합니다")
        now_s = _iso(now)
        eligible = or_(
            T.ingest_jobs.c.status == "queued",
            and_(T.ingest_jobs.c.status == "retry_wait", T.ingest_jobs.c.next_run_at <= now_s),
            and_(T.ingest_jobs.c.status == "running", T.ingest_jobs.c.lease_until < now_s),
        )
        for _ in range(8):
            with self.engine.begin() as conn:
                query = (
                    select(T.ingest_jobs.c.id, T.ingest_jobs.c.status, T.ingest_jobs.c.lease_until)
                    .where(eligible)
                    .order_by(T.ingest_jobs.c.priority.desc(), T.ingest_jobs.c.created_at, T.ingest_jobs.c.id)
                    .limit(1)
                )
                if job_id is not None:
                    query = query.where(T.ingest_jobs.c.id == job_id)
                candidate = conn.execute(query).mappings().first()
                if candidate is None:
                    return None
                expected = T.ingest_jobs.c.status == candidate["status"]
                if candidate["status"] == "running":
                    expected = and_(expected, T.ingest_jobs.c.lease_until == candidate["lease_until"])
                lease_id = f"lease_{uuid.uuid4().hex}"
                claimed = conn.execute(
                    update(T.ingest_jobs)
                    .where(T.ingest_jobs.c.id == candidate["id"], expected, eligible)
                    .values(
                        status="running",
                        leased_by=worker_id,
                        lease_id=lease_id,
                        lease_until=_iso(now + timedelta(seconds=lease_s)),
                        next_run_at=None,
                        updated_at=now_s,
                    )
                )
                if claimed.rowcount == 1:
                    row = (
                        conn.execute(select(T.ingest_jobs).where(T.ingest_jobs.c.id == candidate["id"]))
                        .mappings()
                        .one()
                    )
                    return self._record(dict(row))
        return None

    def begin_stage(self, job_id: str, now: datetime, worker_id: str, lease_id: str, lease_s: int = 300) -> JobRecord:
        with self.engine.begin() as conn:
            row = self._locked_record(conn, job_id)
            attempts = dict(row.attempts)
            attempts[row.stage] = attempts.get(row.stage, 0) + 1
            result = conn.execute(
                update(T.ingest_jobs)
                .where(
                    T.ingest_jobs.c.id == job_id,
                    T.ingest_jobs.c.status == "running",
                    T.ingest_jobs.c.leased_by == worker_id,
                    T.ingest_jobs.c.lease_id == lease_id,
                )
                .values(
                    attempts=_json(attempts),
                    lease_until=_iso(now + timedelta(seconds=lease_s)),
                    updated_at=_iso(now),
                )
            )
            if result.rowcount != 1:
                raise LeaseLostError("잡 lease 소유권을 잃었습니다", {"job_id": job_id})
            self._event(conn, row, now, "started", {"attempt": attempts[row.stage], "worker_id": worker_id})
        return self.get(job_id)

    def renew_lease(self, job_id: str, worker_id: str, lease_id: str, now: datetime, lease_s: int = 300) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(T.ingest_jobs)
                .where(
                    T.ingest_jobs.c.id == job_id,
                    T.ingest_jobs.c.status == "running",
                    T.ingest_jobs.c.leased_by == worker_id,
                    T.ingest_jobs.c.lease_id == lease_id,
                )
                .values(lease_until=_iso(now + timedelta(seconds=lease_s)), updated_at=_iso(now))
            )
            if result.rowcount != 1:
                raise LeaseLostError("잡 lease를 갱신할 수 없습니다", {"job_id": job_id})

    def advance(self, job_id: str, next_stage: JobStage | None, now: datetime, *, lease_id: str) -> None:
        with self.engine.begin() as conn:
            row = self._locked_record(conn, job_id)
            if row.status != "running" or row.lease_id != lease_id:
                raise LeaseLostError("잡 lease 소유권을 잃었습니다", {"job_id": job_id})
            if next_stage is not None:
                current_index = JOB_STAGES.index(row.stage)
                if current_index + 1 >= len(JOB_STAGES) or JOB_STAGES[current_index + 1] != next_stage:
                    raise InvalidJobTransition(
                        "다음 단계 순서가 올바르지 않습니다", {"stage": row.stage, "next_stage": next_stage}
                    )
            values: dict[str, Any] = {"updated_at": _iso(now), "last_error": None}
            if next_stage is None:
                if row.result_content_id is not None:
                    values["stage_data"] = "{}"
                values.update(
                    status="succeeded",
                    completed_at=_iso(now),
                    lease_until=None,
                    leased_by=None,
                    lease_id=None,
                    next_run_at=None,
                )
            else:
                values["stage"] = next_stage
            result = conn.execute(
                update(T.ingest_jobs)
                .where(
                    T.ingest_jobs.c.id == job_id,
                    T.ingest_jobs.c.status == "running",
                    T.ingest_jobs.c.lease_id == lease_id,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise LeaseLostError("잡 lease 소유권을 잃었습니다", {"job_id": job_id})
            self._event(conn, row, now, "succeeded", {})

    def fail(
        self,
        job_id: str,
        err: JupjupError,
        now: datetime,
        retryable: bool,
        *,
        lease_id: str,
        next_run_at: datetime | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE ingest_jobs SET status=status WHERE 0")
            row = self._locked_record(conn, job_id)
            if isinstance(err, LLMRefusalError):
                status: JobStatus = "needs_review"
                event: Literal["retry", "failed"] = "failed"
            elif retryable:
                status = "retry_wait"
                event = "retry"
                next_run_at = next_run_at or now + timedelta(seconds=2)
            else:
                status = "failed"
                event = "failed"
            error: dict[str, Any] = {"code": err.code, "message": err.code, "stage": row.stage}
            safe_detail = _safe_error_detail(err.details)
            if err.code == "SOURCE_TEXT_UNAVAILABLE":
                from jupjup.ingest.youtube import SOURCE_REASON_MESSAGES

                reason = err.details.get("reason")
                if isinstance(reason, str) and reason in SOURCE_REASON_MESSAGES:
                    safe_detail["reason"] = reason
                    error["message"] = SOURCE_REASON_MESSAGES[reason]
            if safe_detail:
                error["details"] = safe_detail
            result = conn.execute(
                update(T.ingest_jobs)
                .where(
                    T.ingest_jobs.c.id == job_id,
                    T.ingest_jobs.c.status == "running",
                    T.ingest_jobs.c.lease_id == lease_id,
                )
                .values(
                    status=status,
                    next_run_at=None if next_run_at is None else _iso(next_run_at),
                    lease_until=None,
                    leased_by=None,
                    lease_id=None,
                    last_error=_json(error),
                    updated_at=_iso(now),
                )
            )
            if result.rowcount != 1:
                raise LeaseLostError("잡 lease 소유권을 잃었습니다", {"job_id": job_id})
            self._event(conn, row, now, event, error)
            if not retryable and row.result_content_id is not None:
                conn.execute(
                    update(T.ingest_jobs)
                    .where(T.ingest_jobs.c.id == row.id, T.ingest_jobs.c.user_id == row.user_id)
                    .values(stage_data="{}")
                )
            if status in ("failed", "needs_review"):
                content_values: dict[str, Any] = {"status": "analysis_failed"}
                if row.kind == "reanalyze":
                    content_values = self._reanalyze_restore_values(conn, row)
                    if "prior_ai" in row.stage_data:
                        from jupjup.save.recovery import restore_ai

                        restore_ai(conn, row.user_id, row.content_id, row.id, row.stage_data["prior_ai"])
                conn.execute(
                    update(T.contents)
                    .where(T.contents.c.id == row.content_id, T.contents.c.user_id == row.user_id)
                    .values(**content_values, updated_at=_iso(now))
                )

    @staticmethod
    def _reanalyze_restore_values(conn: Connection, row: JobRecord) -> dict[str, Any]:
        """재분석이 실패하면 재분석 직전 콘텐츠 상태로 되돌린다.

        이전에 ready였던 콘텐츠만 ready로 남는다. 한 번도 분석에 성공하지 못한 콘텐츠는
        analysis_failed 그대로다. stage_data에 이전 상태가 없는(이 규칙 전에 등록된) 잡은
        같은 콘텐츠에 성공한 다른 잡이 있을 때만 ready로 본다.
        """
        prior = row.stage_data.get(PRIOR_CONTENT_KEY)
        if isinstance(prior, dict) and prior.get("status") in _RESTORABLE_CONTENT_STATUSES:
            return {"status": prior["status"], "analysis_pending": 1 if prior.get("analysis_pending") else 0}
        succeeded_before = conn.scalar(
            select(func.count())
            .select_from(T.ingest_jobs)
            .where(
                T.ingest_jobs.c.content_id == row.content_id,
                T.ingest_jobs.c.status == "succeeded",
                T.ingest_jobs.c.id != row.id,
            )
        )
        if succeeded_before:
            return {"status": "ready", "analysis_pending": 0}
        return {"status": "analysis_failed"}

    def put_artifact(self, job_id: str, key: str, value: Any, now: datetime, *, lease_id: str) -> None:
        if not key:
            raise ValueError("artifact key가 필요합니다")
        with self.engine.begin() as conn:
            row = self._locked_record(conn, job_id)
            data = dict(row.stage_data)
            data[key] = value
            result = conn.execute(
                update(T.ingest_jobs)
                .where(
                    T.ingest_jobs.c.id == job_id,
                    T.ingest_jobs.c.status == "running",
                    T.ingest_jobs.c.lease_id == lease_id,
                )
                .values(stage_data=_json(data), updated_at=_iso(now))
            )
            if result.rowcount != 1:
                raise LeaseLostError("잡 lease 소유권을 잃었습니다", {"job_id": job_id})
            import hashlib

            payload = _json(value)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            exists = conn.scalar(
                select(T.ingest_trace_artifacts.c.id).where(
                    T.ingest_trace_artifacts.c.user_id == row.user_id,
                    T.ingest_trace_artifacts.c.job_id == job_id,
                    T.ingest_trace_artifacts.c.stage == row.stage,
                    T.ingest_trace_artifacts.c.attempt == row.attempts.get(row.stage, 0),
                    T.ingest_trace_artifacts.c.payload_hash == digest,
                )
            )
            if not exists:
                conn.execute(
                    insert(T.ingest_trace_artifacts).values(
                        id=f"trace_{uuid.uuid4().hex}",
                        user_id=row.user_id,
                        content_id=row.content_id,
                        job_id=job_id,
                        stage=row.stage,
                        attempt=row.attempts.get(row.stage, 0),
                        artifact_type={"analysis_input": "input", "analysis": "result", "validation": "validation"}.get(
                            key, "preprocessing"
                        ),
                        payload_json=payload,
                        payload_hash=digest,
                        sensitive=1,
                        created_at=_iso(now),
                    )
                )

    def artifact(self, user_id: str, job_id: str, key: str) -> Any:
        """Read durable stage artifacts after the job workspace has been cleared."""
        stage, artifact_type = {
            "raw": ("fetch", "preprocessing"),
            "youtube_metadata": ("extract", "preprocessing"),
            "youtube_salience": ("analyze", "preprocessing"),
            "vision": ("vision", "preprocessing"),
            "analysis_input": ("chunk", "input"),
            "validation": ("analyze", "validation"),
            "analysis": ("analyze", "result"),
        }[key]
        with self.engine.connect() as conn:
            payload = conn.scalar(
                select(T.ingest_trace_artifacts.c.payload_json)
                .where(
                    T.ingest_trace_artifacts.c.user_id == user_id,
                    T.ingest_trace_artifacts.c.job_id == job_id,
                    T.ingest_trace_artifacts.c.stage == stage,
                    T.ingest_trace_artifacts.c.artifact_type == artifact_type,
                )
                .order_by(T.ingest_trace_artifacts.c.attempt.desc(), T.ingest_trace_artifacts.c.created_at.desc())
                .limit(1)
            )
        return json.loads(payload) if payload is not None else None

    def get(self, job_id: str) -> JobRecord:
        with self.engine.connect() as conn:
            row = conn.execute(select(T.ingest_jobs).where(T.ingest_jobs.c.id == job_id)).mappings().first()
        if row is None:
            raise NotFoundError("인제스트 잡을 찾을 수 없습니다", {"job_id": job_id})
        return self._record(dict(row))

    def events(self, job_id: str) -> list[JobEvent]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(T.ingest_job_events)
                .where(T.ingest_job_events.c.job_id == job_id)
                .order_by(T.ingest_job_events.c.sequence)
            ).mappings()
            return [
                JobEvent(
                    id=row["id"],
                    job_id=row["job_id"],
                    at=cast(datetime, _dt(row["at"])),
                    stage=row["stage"],
                    event=row["event"],
                    detail=json.loads(row["detail"] or "{}"),
                )
                for row in rows
            ]

    def _locked_record(self, conn: Connection, job_id: str) -> JobRecord:
        row = conn.execute(select(T.ingest_jobs).where(T.ingest_jobs.c.id == job_id)).mappings().first()
        if row is None:
            raise NotFoundError("인제스트 잡을 찾을 수 없습니다", {"job_id": job_id})
        return self._record(dict(row))

    @staticmethod
    def _record(row: dict[str, Any]) -> JobRecord:
        source = None if row["source_spec"] is None else SourceSpec.model_validate_json(row["source_spec"])
        attempts = json.loads(row["attempts"] or "{}")
        return JobRecord(
            id=row["id"],
            content_id=row["content_id"],
            user_id=row["user_id"],
            kind=row["kind"],
            status=row["status"],
            stage=row["stage"],
            automation_level=row["automation_level"],
            result_content_id=row["result_content_id"],
            candidate_id=row["candidate_id"],
            priority=row["priority"],
            profile=row["profile"],
            attempts=attempts,
            next_run_at=_dt(row["next_run_at"]),
            lease_until=_dt(row["lease_until"]),
            leased_by=row["leased_by"],
            lease_id=row["lease_id"],
            last_error=None if row["last_error"] is None else json.loads(row["last_error"]),
            source_spec=source,
            stage_data=json.loads(row["stage_data"] or "{}"),
            created_at=cast(datetime, _dt(row["created_at"])),
            updated_at=cast(datetime, _dt(row["updated_at"])),
        )

    @staticmethod
    def _event(
        conn: Connection,
        row: JobRecord,
        at: datetime,
        event: Literal["started", "succeeded", "retry", "failed"],
        detail: dict[str, Any],
    ) -> None:
        detail = {"attempt": row.attempts.get(row.stage, 0), **detail}
        if event != "started":
            started = conn.scalar(
                select(T.ingest_job_events.c.at)
                .where(
                    T.ingest_job_events.c.job_id == row.id,
                    T.ingest_job_events.c.stage == row.stage,
                    T.ingest_job_events.c.event == "started",
                )
                .order_by(T.ingest_job_events.c.sequence.desc())
                .limit(1)
            )
            if started:
                detail["duration_ms"] = max(0.0, (at - datetime.fromisoformat(started)).total_seconds() * 1000)
        sequence = conn.scalar(
            select(func.coalesce(func.max(T.ingest_job_events.c.sequence), 0)).where(
                T.ingest_job_events.c.job_id == row.id
            )
        )
        conn.execute(
            insert(T.ingest_job_events).values(
                id=f"evt_{uuid.uuid4().hex}",
                job_id=row.id,
                at=_iso(at),
                sequence=int(sequence or 0) + 1,
                stage=row.stage,
                event=event,
                detail=_json(detail),
            )
        )
