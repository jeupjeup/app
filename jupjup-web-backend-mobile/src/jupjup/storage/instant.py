"""Lossless, lexically sortable UTC representation for indexed content instants."""

from datetime import UTC, datetime

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def utc_instant(value: str) -> str:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("content timestamps must include a timezone")
    return instant.astimezone(UTC).isoformat(timespec="microseconds")


class InstantText(TypeDecorator[str]):
    """Normalize SQLAlchemy comparison-key writes and bound filter/cursor parameters."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else utc_instant(value)
