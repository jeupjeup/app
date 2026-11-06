"""`jupjup seed load --analyze` (설계서 5.10.8절): 시드의 스냅샷만 넣고 분석은 인제스트 파이프라인이 만든다."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import delete

from jupjup.domain.errors import JupjupError
from jupjup.domain.models import ContentBundle, DetailTags
from jupjup.index.service import IndexingService
from jupjup.ingest.jobs import JobStatus
from jupjup.ingest.service import IngestService
from jupjup.storage import tables as T
from jupjup.storage.seed import SeedLineError, parse_seed_lines

SEED_PRIORITY = 10  # 신규 저장과 같은 우선순위 (5.10.3절)


class SeedAnalyzeReport(BaseModel):
    path: str
    total_lines: int = 0
    loaded: int = 0
    queued: int = 0
    rolled_back: bool = False
    inline: bool = True
    users: dict[str, int] = Field(default_factory=dict)
    statuses: dict[str, int] = Field(default_factory=dict)
    job_ids: list[str] = Field(default_factory=list)
    errors: list[SeedLineError] = Field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return not self.errors and (not self.inline or self.statuses.get("succeeded", 0) == self.queued)


def snapshot_only(bundle: ContentBundle) -> ContentBundle:
    """사람이 쓴 AI 분석(요약·AI 태그·AI 세부 태그)을 빼고 사용자 입력과 스냅샷만 남긴다."""
    detail = None
    if bundle.detail_tags is not None and bundle.detail_tags.user_patch is not None:
        detail = DetailTags(content_id=bundle.content.id, user_patch=bundle.detail_tags.user_patch)
    return bundle.model_copy(
        update={
            "content": bundle.content.model_copy(update={"status": "pending", "analysis_pending": True}),
            "summaries": [summary for summary in bundle.summaries if summary.source == "user"],
            "tags": [tag for tag in bundle.tags if tag.source == "user"],
            "detail_tags": detail,
        }
    )


def load_seed_file_for_analysis(
    path: Path,
    service: IngestService,
    indexer: IndexingService,
    *,
    replace_user: bool = False,
    strict: bool = False,
    inline: bool = True,
) -> SeedAnalyzeReport:
    """콘텐츠 저장과 잡 등록은 한 트랜잭션이다. 하나라도 등록하지 못하면 아무것도 넣지 않는다.

    잡은 스냅샷이 이미 있으므로 `chunk` 단계부터 시작한다 (fetch/extract/vision 생략).
    `inline=True`면 같은 프로세스에서 바로 실행하고, False면 `jupjup worker run`에 맡긴다.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    report = SeedAnalyzeReport(path=str(path), total_lines=sum(1 for x in lines if x.strip()), inline=inline)
    parsed, errors = parse_seed_lines(lines)
    line_of = _line_numbers(lines)
    bundles: list[ContentBundle] = []
    for bundle in parsed:
        snapshot = bundle.snapshot
        if snapshot is None or not (snapshot.text.strip() or (snapshot.ocr_text or "").strip()):
            errors.append(
                SeedLineError(
                    line=line_of.get(bundle.content.id, 0),
                    id=bundle.content.id,
                    code="MISSING_SNAPSHOT",
                    message="--analyze에는 스냅샷 본문이 필요합니다",
                )
            )
            continue
        bundles.append(snapshot_only(bundle))
    errors.sort(key=lambda error: error.line)
    report.errors = errors
    if strict and errors:
        report.rolled_back = True
        return report

    users = sorted({bundle.content.user_id for bundle in bundles})
    now = service.worker.clock()
    job_ids: list[str] = []
    try:
        with service.repo.engine.begin() as conn:
            if replace_user:
                for uid in users:
                    conn.execute(delete(T.contents).where(T.contents.c.user_id == uid))
            for bundle in bundles:
                service.repo.upsert_in_transaction(conn, bundle)
                job_ids.append(
                    service.queue.enqueue_in_transaction(
                        conn,
                        bundle.content.id,
                        bundle.content.user_id,
                        "ingest",
                        SEED_PRIORITY,
                        initial_stage="chunk",
                        now=now,
                    )
                )
    except JupjupError as exc:
        content_id = exc.details.get("content_id") or exc.details.get("id")
        report.errors.append(
            SeedLineError(
                line=line_of.get(str(content_id), 0),
                id=None if content_id is None else str(content_id),
                code=exc.code,
                message=exc.message,
            )
        )
        report.rolled_back = True
        return report

    report.loaded = len(bundles)
    report.queued = len(job_ids)
    report.job_ids = job_ids
    for bundle in bundles:
        report.users[bundle.content.user_id] = report.users.get(bundle.content.user_id, 0) + 1

    # 분석 전에도 스냅샷 축약 인덱스로 검색되게 한다 (I2와 같은 동작).
    if replace_user:
        for uid in users:
            indexer.reindex_all(uid)
    else:
        for bundle in bundles:
            indexer.index_reduced(bundle.content.user_id, bundle.content.id)

    if inline:
        for job_id in job_ids:
            status: JobStatus = service.run_inline(job_id).status
            report.statuses[status] = report.statuses.get(status, 0) + 1
    else:
        report.statuses["queued"] = len(job_ids)
    return report


def _line_numbers(lines: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for lineno, line in enumerate(lines, 1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("id"), str):
            out.setdefault(obj["id"], lineno)
    return out
