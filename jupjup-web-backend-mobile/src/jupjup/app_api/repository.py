"""Tenant-scoped reads and exact public DTOs."""

from typing import Any

from sqlalchemy import Connection, text

from jupjup.app_api.errors import ContractError


def owned(conn: Connection, table: str, user_id: str, item_id: str) -> dict[str, Any]:
    assert table in ("api_contents", "api_notices")
    row = (
        conn.execute(text(f"SELECT * FROM {table} WHERE id=:id AND user_id=:user"), dict(id=item_id, user=user_id))
        .mappings()
        .first()
    )
    if row is None:
        raise ContractError(404, "NOT_FOUND")
    return dict(row)


def content_dto(row: dict[str, Any]) -> dict[str, Any]:
    dto = {key: row[key] for key in ("id", "title", "url", "memo", "type", "source")}
    dto.update(description="", tags=[], savedAt=row["saved_at"], status="ready")
    for source, target in (("collection", "collection"), ("deleted_at", "deletedAt"), ("viewed_at", "viewedAt")):
        if row[source] is not None:
            dto[target] = row[source]
    return dto


def contents(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    return [
        content_dto(dict(row))
        for row in conn.execute(
            text("SELECT * FROM api_contents WHERE user_id=:user ORDER BY saved_at DESC,rowid DESC"), dict(user=user_id)
        ).mappings()
    ]


def notices(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "date": row["date"],
            "read": bool(row["read"]),
        }
        for row in conn.execute(
            text("SELECT * FROM api_notices WHERE user_id=:user ORDER BY date DESC,rowid DESC"), dict(user=user_id)
        ).mappings()
    ]


def history(conn: Connection, user_id: str) -> list[str]:
    return list(
        conn.execute(
            text("SELECT query FROM api_search_history WHERE user_id=:user ORDER BY sequence DESC LIMIT 10"),
            dict(user=user_id),
        ).scalars()
    )
