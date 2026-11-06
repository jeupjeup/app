"""Restore AI layers after a failed reanalysis, preserving concurrent user edits."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from jupjup.storage import tables as T


def capture_ai(conn: Connection, content_id: str) -> dict[str, Any]:
    detail = conn.execute(select(T.detail_tags).where(T.detail_tags.c.content_id == content_id)).mappings().first()
    embeddings = []
    for row in conn.execute(select(T.embeddings).where(T.embeddings.c.content_id == content_id)).mappings():
        value = dict(row)
        value["vector"] = base64.b64encode(value["vector"]).decode("ascii")
        embeddings.append(value)
    return dict(
        tags=[
            dict(row)
            for row in conn.execute(
                select(T.tags).where(T.tags.c.content_id == content_id, T.tags.c.source == "ai")
            ).mappings()
        ],
        detail=dict(detail) if detail else None,
        embeddings=embeddings,
    )


def restore_ai(conn: Connection, user_id: str, content_id: str, job_id: str, prior: dict[str, Any]) -> None:
    owned = conn.scalar(select(T.contents.c.id).where(T.contents.c.user_id == user_id, T.contents.c.id == content_id))
    if not owned:
        return
    runs = select(T.analysis_runs.c.id).where(
        T.analysis_runs.c.content_id == content_id, T.analysis_runs.c.job_id == job_id
    )
    conn.execute(
        delete(T.summaries).where(
            T.summaries.c.content_id == content_id,
            T.summaries.c.source == "ai",
            T.summaries.c.analysis_run_id.in_(runs),
        )
    )
    conn.execute(
        update(T.analysis_runs)
        .where(T.analysis_runs.c.content_id == content_id, T.analysis_runs.c.job_id == job_id)
        .values(accepted_at=None)
    )
    conn.execute(delete(T.tags).where(T.tags.c.content_id == content_id, T.tags.c.source == "ai"))
    for tag in prior["tags"]:
        conn.execute(insert(T.tags).values(**tag))
    detail = prior.get("detail")
    values = (
        {key: detail[key] for key in ("ai_json", "schema_version", "analysis_run_id")}
        if detail
        else dict(ai_json='{"schema_version":1}', schema_version=1, analysis_run_id=None)
    )
    conn.execute(update(T.detail_tags).where(T.detail_tags.c.content_id == content_id).values(**values))
    conn.execute(delete(T.embeddings).where(T.embeddings.c.content_id == content_id))
    for embedding in prior["embeddings"]:
        value = dict(embedding)
        value["vector"] = base64.b64decode(value["vector"])
        conn.execute(insert(T.embeddings).values(**value))
