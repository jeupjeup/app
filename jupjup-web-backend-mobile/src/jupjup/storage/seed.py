"""시드 적재 `load_seed_file` (설계서 5.8.7절, FR-6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError

from jupjup.domain.errors import ContentValidationError
from jupjup.domain.models import ContentBundle, SeedRecord
from jupjup.storage.repositories import ContentRepository

if TYPE_CHECKING:
    from jupjup.index.service import IndexingService


class SeedLineError(BaseModel):
    line: int
    id: str | None = None
    code: str
    message: str


class SeedLoadReport(BaseModel):
    path: str
    total_lines: int = 0
    loaded: int = 0
    indexed: int = 0
    embedding_pending: int = 0
    rolled_back: bool = False
    users: dict[str, int] = Field(default_factory=dict)
    errors: list[SeedLineError] = Field(default_factory=list)


def parse_seed_lines(lines: list[str]) -> tuple[list[ContentBundle], list[SeedLineError]]:
    bundles: list[ContentBundle] = []
    errors: list[SeedLineError] = []
    seen: set[str] = set()
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        rid: str | None = None
        try:
            obj = json.loads(line)
            rid = obj.get("id") if isinstance(obj, dict) else None
            bundle = SeedRecord.model_validate(obj).to_bundle()
        except json.JSONDecodeError as exc:
            errors.append(SeedLineError(line=lineno, code="INVALID_JSON", message=str(exc)))
            continue
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(x) for x in first.get("loc", ()))
            errors.append(SeedLineError(line=lineno, id=rid, code="INVALID_CONTENT", message=f"{loc}: {first['msg']}"))
            continue
        except ContentValidationError as exc:
            errors.append(SeedLineError(line=lineno, id=rid, code=exc.code, message=exc.message))
            continue
        if bundle.content.id in seen:
            errors.append(
                SeedLineError(line=lineno, id=rid, code="DUPLICATE_ID", message="파일 안에서 id가 중복됩니다")
            )
            continue
        seen.add(bundle.content.id)
        bundles.append(bundle)
    return bundles, errors


def load_seed_file(
    path: Path,
    repo: ContentRepository,
    indexer: IndexingService | None,
    *,
    replace_user: bool = False,
    strict: bool = False,
) -> SeedLoadReport:
    """줄 단위 검증. 잘못된 줄은 errors에 남기고 나머지를 적재한다. strict=True면 하나라도 틀리면 아무것도 넣지 않는다.

    DB 쓰기는 한 트랜잭션이라 중간에 실패해도 부분 적재가 남지 않는다. replace_user=True면 파일에 나온 사용자의
    기존 저장물을 먼저 지운다 (멱등 재적재).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    report = SeedLoadReport(path=str(path), total_lines=sum(1 for x in lines if x.strip()))
    bundles, errors = parse_seed_lines(lines)
    report.errors = errors
    if strict and errors:
        report.rolled_back = True
        return report
    users = sorted({b.content.user_id for b in bundles})
    repo.upsert_many(bundles, replace_users=users if replace_user else ())
    report.loaded = len(bundles)
    for b in bundles:
        report.users[b.content.user_id] = report.users.get(b.content.user_id, 0) + 1
    if indexer is not None:
        if replace_user:
            for uid in users:
                indexer.reindex_all(uid)
            report.indexed = len(bundles)
        else:
            for b in bundles:
                res = indexer.index_content(b.content.user_id, b.content.id)
                report.indexed += 1
                report.embedding_pending += int(res.embedding_pending)
    return report
