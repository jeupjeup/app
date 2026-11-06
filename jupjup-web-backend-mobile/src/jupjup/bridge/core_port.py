"""Adapter for connection-only core commands."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import Connection

from jupjup.bridge.ports import CoreRejected
from jupjup.domain.errors import ContentValidationError
from jupjup.domain.models import ContentBundle
from jupjup.ingest.youtube_metadata import MetadataClassification
from jupjup.save.dto import CreateContent, UrlSource
from jupjup.save.service import ContentCommandService, CoreCreateOutcome
from jupjup.storage.repositories import SqlContentRepository


class SaveCorePort:
    def __init__(self, commands: ContentCommandService, repo: SqlContentRepository) -> None:
        self.commands, self.repo = commands, repo

    def create_or_dedupe(self, conn: Connection, user_id: str, url: str, memo: str, now: datetime) -> CoreCreateOutcome:
        try:
            body = CreateContent(source=UrlSource(kind="url", url=url), user_note=memo or None)
        except (ValidationError, ContentValidationError) as exc:
            raise CoreRejected("core_rejected_url") from exc
        return self.commands.create_in_transaction(conn, user_id, body, now)

    def delete(self, conn: Connection, user_id: str, content_id: str) -> bool:
        return self.repo.delete_in_transaction(conn, user_id, content_id)

    def bundles(self, conn: Connection, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]:
        return self.repo.bundles_in(conn, user_id, ids)

    def metadata(self, conn: Connection, bundle: ContentBundle) -> MetadataClassification | None:
        return self.repo.metadata_in(conn, bundle)
