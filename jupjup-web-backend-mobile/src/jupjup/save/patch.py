"""Atomic user layer updates, independent of AI persistence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update

from jupjup.api.errors import ApiError
from jupjup.domain.errors import NotFoundError
from jupjup.domain.models import merge_patch, normalize_tag_name, validate_detail_tags
from jupjup.save.dto import ContentPatch
from jupjup.storage import tables as T
from jupjup.storage.repositories import SqlContentRepository


def overlay_patch(old: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Compose merge patches while retaining explicit deletion tombstones."""
    result = dict(old)
    for key, value in patch.items():
        result[key] = (
            overlay_patch(result[key] if isinstance(result.get(key), dict) else {}, value)
            if isinstance(value, dict)
            else value
        )
    return result


def apply_user_patch(
    repo: SqlContentRepository, user_id: str, content_id: str, patch: ContentPatch, etag: str | None
) -> None:
    now = datetime.now(UTC).isoformat()
    with repo.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE contents SET revision=revision WHERE 0")
        row = (
            conn.execute(select(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id))
            .mappings()
            .first()
        )
        if row is None:
            raise NotFoundError("저장물을 찾을 수 없어요.")
        if row["status"] == "duplicate":
            raise ApiError(409, "INVALID_CONTENT_STATE", "중복 저장물입니다")
        if etag is not None and etag != f'"content:{content_id}:{row["revision"]}"':
            raise ApiError(409, "VERSION_CONFLICT", "저장물 버전이 변경되었습니다")
        changed = False
        values: dict[str, Any] = {}
        fields = patch.model_fields_set
        if "summary" in fields:
            current = (
                conn.execute(
                    select(T.summaries)
                    .where(T.summaries.c.content_id == content_id)
                    .order_by(T.summaries.c.version.desc())
                )
                .mappings()
                .all()
            )
            users = [s for s in current if s["source"] == "user"]
            ai = [s for s in current if s["source"] == "ai"]
            effective = (users or ai)[0]["text"] if users or ai else None
            if patch.summary is None:
                if users:
                    conn.execute(
                        delete(T.summaries).where(
                            T.summaries.c.content_id == content_id, T.summaries.c.source == "user"
                        )
                    )
                    changed = True
            elif patch.summary != effective:
                version = max((s["version"] for s in users), default=0) + 1
                conn.execute(
                    insert(T.summaries).values(
                        id=f"sum_{uuid.uuid4().hex}",
                        content_id=content_id,
                        version=version,
                        text=patch.summary,
                        source="user",
                        model="human",
                        created_at=now,
                    )
                )
                changed = True
        if "representative_tags" in fields:
            tags = (
                conn.execute(select(T.tags).where(T.tags.c.content_id == content_id).order_by(T.tags.c.position))
                .mappings()
                .all()
            )
            users = [t["name"] for t in tags if t["source"] == "user"]
            ai_names = [t["name"] for t in tags if t["source"] == "ai"]
            hidden = json.loads(row["hidden_tags"])
            names = list(dict.fromkeys(normalize_tag_name(t) for t in patch.representative_tags or []))
            if any(not t for t in names) or len(names) > 15:
                raise ApiError(422, "INVALID_PATCH", "유효 태그는 0~15개여야 합니다")
            effective_names = users + [t for t in ai_names if t not in hidden and t not in users]
            new_hidden = list(dict.fromkeys(hidden + [t for t in ai_names if t not in names]))
            if patch.representative_tags is None:
                names, new_hidden = [], []
                tag_changed = bool(users or hidden)
            else:
                tag_changed = names != effective_names
            if tag_changed:
                conn.execute(delete(T.tags).where(T.tags.c.content_id == content_id, T.tags.c.source == "user"))
                for position, name in enumerate(names):
                    conn.execute(
                        insert(T.tags).values(
                            content_id=content_id, name=name, source="user", position=position, created_at=now
                        )
                    )
                values["hidden_tags"] = json.dumps(new_hidden, ensure_ascii=False)
                changed = True
        if "detail_tags" in fields:
            detail = (
                conn.execute(select(T.detail_tags).where(T.detail_tags.c.content_id == content_id)).mappings().first()
            )
            ai_json = json.loads(detail["ai_json"]) if detail else {"schema_version": 1}
            old_patch = json.loads(detail["user_patch"]) if detail and detail["user_patch"] else None
            if patch.detail_tags is not None and "schema_version" in patch.detail_tags:
                raise ApiError(422, "INVALID_PATCH", "schema_version은 수정할 수 없습니다")
            new_patch = overlay_patch(old_patch or {}, patch.detail_tags) if patch.detail_tags is not None else None
            effective = merge_patch(ai_json, new_patch or {})
            validate_detail_tags(effective)
            if effective != merge_patch(ai_json, old_patch or {}) or (new_patch is None and old_patch is not None):
                detail_values = dict(
                    user_patch=json.dumps(new_patch, ensure_ascii=False) if new_patch is not None else None,
                    updated_at=now,
                )
                if detail:
                    conn.execute(
                        update(T.detail_tags).where(T.detail_tags.c.content_id == content_id).values(**detail_values)
                    )
                else:
                    conn.execute(
                        insert(T.detail_tags).values(
                            content_id=content_id, ai_json=json.dumps(ai_json), schema_version=1, **detail_values
                        )
                    )
                changed = True
        if "hidden" in fields:
            if patch.hidden is None:
                raise ApiError(422, "INVALID_PATCH", "hidden은 boolean이어야 합니다")
            if bool(row["is_hidden"]) != patch.hidden:
                values["is_hidden"] = int(patch.hidden)
                changed = True
        if changed:
            conn.execute(
                update(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                .values(revision=T.contents.c.revision + 1, updated_at=now, **values)
            )
