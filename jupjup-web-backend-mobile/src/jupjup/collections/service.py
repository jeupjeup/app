"""Collection commands never update contents or analysis/index inputs."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import Field, field_validator
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from jupjup.api.errors import ApiError
from jupjup.save.dto import StrictModel


class CollectionBody(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#DDB8E5", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name", mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        return unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value


class CollectionPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name", mode="before")
    @classmethod
    def normalize(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("이름은 비워둘 수 없어요.")
        return CollectionBody.normalize(value)

    @field_validator("color", mode="before")
    @classmethod
    def non_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("색상은 비워둘 수 없어요.")
        return value


class CollectionView(StrictModel):
    id: str
    name: str
    color: str
    created_at: str
    updated_at: str
    content_count: int


class CollectionPage(StrictModel):
    items: list[CollectionView]


def owned_collection(conn: Connection, user: str, collection: str) -> dict[str, Any]:
    row = (
        conn.execute(text("SELECT * FROM collections WHERE id=:id AND user_id=:u"), dict(id=collection, u=user))
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, "NOT_FOUND", "컬렉션을 찾을 수 없어요.")
    return dict(row)


def collection_ids(conn: Connection, user: str, content: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT collection_id FROM collection_contents WHERE user_id=:u "
                "AND content_id=:id ORDER BY collection_id"
            ),
            dict(u=user, id=content),
        ).scalars()
    )


class CollectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, user: str, collection: str | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    text("""SELECT c.id,c.name,c.color,c.created_at,c.updated_at,
                (SELECT count(*) FROM collection_contents m JOIN contents x ON x.id=m.content_id AND x.user_id=m.user_id
                 WHERE m.collection_id=c.id AND m.user_id=c.user_id AND x.is_hidden=0
                    AND x.status!='duplicate') content_count
                FROM collections c WHERE c.user_id=:u AND (:id IS NULL OR c.id=:id)
                ORDER BY c.created_at,c.id"""),
                    dict(u=user, id=collection),
                )
                .mappings()
                .all()
            )
        if collection is not None and not rows:
            raise ApiError(404, "NOT_FOUND", "컬렉션을 찾을 수 없어요.")
        return dict(rows[0]) if collection is not None else dict(items=[dict(r) for r in rows])

    def write(self, user: str, body: CollectionBody | CollectionPatch, collection: str | None = None) -> dict[str, Any]:
        identifier = collection or "col_" + uuid4().hex
        values = body.model_dump(exclude_unset=True)
        now = datetime.now(UTC).isoformat()
        try:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                if collection:
                    owned_collection(conn, user, collection)
                    if values:
                        if "name" in values:
                            values["name_key"] = unicodedata.normalize("NFC", values["name"].casefold())
                        values["updated_at"] = now
                        assignments = ",".join(f"{key}=:{key}" for key in values)
                        conn.execute(
                            text(f"UPDATE collections SET {assignments} WHERE id=:id AND user_id=:u"),
                            dict(values, id=identifier, u=user),
                        )
                else:
                    assert isinstance(body, CollectionBody)
                    conn.execute(
                        text("INSERT INTO collections VALUES (:id,:u,:name,:key,:color,:at,:at)"),
                        dict(
                            id=identifier,
                            u=user,
                            name=body.name,
                            key=unicodedata.normalize("NFC", body.name.casefold()),
                            color=body.color,
                            at=now,
                        ),
                    )
        except IntegrityError as exc:
            raise ApiError(409, "COLLECTION_NAME_CONFLICT", "같은 이름의 컬렉션이 있어요.") from exc
        return self.list(user, identifier)

    def delete(self, user: str, collection: str) -> None:
        with self.engine.begin() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            owned_collection(conn, user, collection)
            conn.execute(text("DELETE FROM collections WHERE id=:id AND user_id=:u"), dict(id=collection, u=user))

    def membership(self, user: str, collection: str, content: str, *, add: bool) -> None:
        with self.engine.begin() as conn:
            # A write lock keeps ownership checks and membership changes atomic with deletion.
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            owned_collection(conn, user, collection)
            if not conn.scalar(text("SELECT 1 FROM contents WHERE id=:id AND user_id=:u"), dict(id=content, u=user)):
                raise ApiError(404, "NOT_FOUND", "콘텐츠를 찾을 수 없어요.")
            sql = (
                "INSERT INTO collection_contents VALUES (:c,:id,:u) ON CONFLICT(collection_id,content_id) DO NOTHING"
                if add
                else "DELETE FROM collection_contents WHERE collection_id=:c AND content_id=:id AND user_id=:u"
            )
            conn.execute(text(sql), dict(c=collection, id=content, u=user))
