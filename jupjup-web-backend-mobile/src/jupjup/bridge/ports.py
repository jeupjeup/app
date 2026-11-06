"""Connection-only interface to the core content store."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy import Connection

from jupjup.domain.models import ContentBundle
from jupjup.ingest.youtube_metadata import MetadataClassification
from jupjup.save.service import CoreCreateOutcome


class CoreRejected(Exception):
    pass


class CorePort(Protocol):
    def create_or_dedupe(
        self, conn: Connection, user_id: str, url: str, memo: str, now: datetime
    ) -> CoreCreateOutcome: ...
    def delete(self, conn: Connection, user_id: str, content_id: str) -> bool: ...
    def bundles(self, conn: Connection, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]: ...
    def metadata(self, conn: Connection, bundle: ContentBundle) -> MetadataClassification | None: ...
