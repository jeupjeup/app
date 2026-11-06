"""Repositories for idempotency, deduplication, candidates, and trace artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from jupjup.domain.errors import IdempotencyConflictError, IdempotencyInProgressError
from jupjup.storage import tables as T


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def canonical_request_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class IdempotencyReservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    operation: str
    key_hash: str
    request_hash: str
    replayed: bool = False
    response_status: int | None = None
    response_json: dict[str, Any] | None = None


class IdempotencyRepository:
    def __init__(self, engine: Engine, ttl: timedelta = timedelta(hours=24)) -> None:
        self.engine = engine
        self.ttl = ttl

    @staticmethod
    def validate_key(key: str) -> str:
        if not 1 <= len(key) <= 128 or any(ord(character) < 0x20 or ord(character) > 0x7E for character in key):
            raise ValueError("Idempotency-Key는 printable ASCII 1~128자여야 합니다")
        return key

    def reserve(
        self,
        user_id: str,
        operation: str,
        key: str,
        request_hash: str,
        now: datetime | None = None,
    ) -> IdempotencyReservation:
        self.validate_key(key)
        at = (now or datetime.now(UTC)).astimezone(UTC)
        key_hash = hashlib.sha256(key.encode("ascii")).hexdigest()
        values = {
            "user_id": user_id,
            "operation": operation,
            "key_hash": key_hash,
            "request_hash": request_hash,
            "state": "in_progress",
            "created_at": at.isoformat(),
            "expires_at": (at + self.ttl).isoformat(),
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    delete(T.idempotency_keys).where(
                        T.idempotency_keys.c.user_id == user_id,
                        T.idempotency_keys.c.operation == operation,
                        T.idempotency_keys.c.key_hash == key_hash,
                        T.idempotency_keys.c.expires_at <= at.isoformat(),
                    )
                )
                connection.execute(insert(T.idempotency_keys).values(**values))
            return IdempotencyReservation(
                user_id=user_id, operation=operation, key_hash=key_hash, request_hash=request_hash
            )
        except IntegrityError:
            pass
        with self.engine.connect() as connection:
            row = connection.execute(
                select(T.idempotency_keys).where(
                    T.idempotency_keys.c.user_id == user_id,
                    T.idempotency_keys.c.operation == operation,
                    T.idempotency_keys.c.key_hash == key_hash,
                )
            ).mappings().one()
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError("같은 Idempotency-Key에 다른 요청을 보낼 수 없습니다")
        if row["state"] != "completed":
            raise IdempotencyInProgressError("동일한 요청을 처리하고 있습니다", {"retry_after": 1})
        return IdempotencyReservation(
            user_id=user_id,
            operation=operation,
            key_hash=key_hash,
            request_hash=request_hash,
            replayed=True,
            response_status=row["response_status"],
            response_json=json.loads(row["response_json"]),
        )

    def complete(
        self,
        reservation: IdempotencyReservation,
        status: int,
        response: dict[str, Any],
        resource_id: str | None,
        job_id: str | None,
    ) -> None:
        safe_response = canonical_json(response)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(T.idempotency_keys)
                .where(
                    T.idempotency_keys.c.user_id == reservation.user_id,
                    T.idempotency_keys.c.operation == reservation.operation,
                    T.idempotency_keys.c.key_hash == reservation.key_hash,
                    T.idempotency_keys.c.request_hash == reservation.request_hash,
                    T.idempotency_keys.c.state == "in_progress",
                )
                .values(
                    state="completed",
                    response_status=status,
                    response_json=safe_response,
                    resource_id=resource_id,
                    job_id=job_id,
                )
            )
            if result.rowcount != 1:
                raise IdempotencyConflictError("멱등 요청 상태가 변경되었습니다")


class FingerprintRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(
        self, user_id: str, kind: str, version: str, value: str, content_id: str, now: datetime
    ) -> tuple[bool, str]:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest() if kind == "normalized_url" else value
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(T.content_fingerprints).values(
                        user_id=user_id,
                        kind=kind,
                        version=version,
                        fingerprint=digest,
                        content_id=content_id,
                        created_at=now.astimezone(UTC).isoformat(),
                    )
                )
            return True, content_id
        except IntegrityError:
            with self.engine.connect() as connection:
                canonical = connection.scalar(
                    select(T.content_fingerprints.c.content_id).where(
                        T.content_fingerprints.c.user_id == user_id,
                        T.content_fingerprints.c.kind == kind,
                        T.content_fingerprints.c.version == version,
                        T.content_fingerprints.c.fingerprint == digest,
                    )
                )
            assert canonical is not None
            return False, canonical
