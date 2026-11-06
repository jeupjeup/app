"""App/core coordination on the caller's SQLite connection."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import Connection, text

from jupjup.app_api import repository as repo
from jupjup.app_api.auth import instant
from jupjup.app_api.errors import ContractError
from jupjup.bridge.ports import CorePort, CoreRejected
from jupjup.domain.errors import ContentValidationError
from jupjup.save.dedupe import URL_NORMALIZATION_VERSION, fingerprint, normalize_source_url
from jupjup.save.query import visible_analysis


@dataclass(frozen=True)
class AccountScope:
    account_id: str
    core_user_id: str


class ContentBridge:
    def __init__(self, core: CorePort, *, sync_limit: int = 500, adopt_limit: int = 50, purge_batch: int = 200):
        self.core, self.sync_limit, self.adopt_limit, self.purge_batch = core, sync_limit, adopt_limit, purge_batch

    def scope(self, conn: Connection, account_id: str) -> AccountScope:
        user = conn.scalar(text("SELECT user_id FROM account_scopes WHERE account_id=:id"), {"id": account_id})
        if not user:
            raise ContractError(500, "INTERNAL_ERROR")
        return AccountScope(account_id, user)

    def identity(self, url: str) -> tuple[str | None, str | None]:
        try:
            normalized = normalize_source_url(url)
            return normalized, fingerprint(normalized)
        except ContentValidationError:
            return None, None

    def assert_allowed(self, conn: Connection, scope: AccountScope, url: str, exclude: str = "") -> None:
        _, fp = self.identity(url)
        if (
            fp
            and conn.execute(
                text(
                    "SELECT 1 FROM app_content_links WHERE account_id=:account AND core_url_fp=:fp "
                    "AND active=1 AND api_content_id<>:id"
                ),
                {"account": scope.account_id, "fp": fp, "id": exclude},
            ).first()
        ):
            raise ContractError(409, "DUPLICATE_CONTENT")

    def link_new(self, conn: Connection, scope: AccountScope, row: dict[str, Any], now: datetime) -> None:
        url, fp = self.identity(row["url"])
        params = {
            "id": row["id"],
            "account": scope.account_id,
            "user": scope.core_user_id,
            "fp": fp,
            "version": URL_NORMALIZATION_VERSION,
            "now": instant(now),
            "active": int(row["deleted_at"] is None),
        }
        conn.exec_driver_sql("SAVEPOINT bridge_link")
        try:
            if url is None:
                raise CoreRejected("core_rejected_url")
            outcome = self.core.create_or_dedupe(conn, scope.core_user_id, url, row["memo"], now)
            params["cid"] = outcome.content_id
            conn.execute(
                text(
                    "UPDATE contents SET is_hidden=0,revision=revision+1,updated_at=:now "
                    "WHERE user_id=:user AND id=:cid AND is_hidden=1"
                ),
                params,
            )
            conn.execute(
                text("""INSERT INTO app_content_links (api_content_id,account_id,core_user_id,core_content_id,
                core_url_fp,url_version,origin,state,active,created_at,updated_at)
                VALUES (:id,:account,:user,:cid,:fp,:version,'app','linked',:active,:now,:now)"""),
                params,
            )
            conn.exec_driver_sql("RELEASE SAVEPOINT bridge_link")
        except CoreRejected:
            conn.exec_driver_sql("ROLLBACK TO SAVEPOINT bridge_link")
            conn.exec_driver_sql("RELEASE SAVEPOINT bridge_link")
            conn.execute(
                text("""INSERT INTO app_content_links (api_content_id,account_id,core_user_id,core_url_fp,
                url_version,origin,state,reject_code,active,created_at,updated_at)
                VALUES (:id,:account,:user,NULL,:version,'app','rejected','core_rejected_url',:active,:now,:now)"""),
                params,
            )

    def project(self, conn: Connection, scope: AccountScope, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        links = {
            r["api_content_id"]: dict(r)
            for r in conn.execute(
                text("SELECT * FROM app_content_links WHERE account_id=:account"), {"account": scope.account_id}
            ).mappings()
        }
        ids = [link["core_content_id"] for link in links.values() if link["core_content_id"]]
        bundles = self.core.bundles(conn, scope.core_user_id, ids)
        duplicate_ids = [
            b.content.duplicate_of_content_id
            for b in bundles.values()
            if b.content.status == "duplicate" and b.content.duplicate_of_content_id
        ]
        bundles.update(self.core.bundles(conn, scope.core_user_id, duplicate_ids))
        result = []
        for row in rows:
            dto = repo.content_dto(row)
            link = links.get(row["id"])
            if link:
                if link["state"] == "orphaned":
                    dto["status"] = "unavailable"
                elif link["state"] == "rejected" and link["reject_code"] == "core_rejected_url":
                    dto["status"] = "failed"
                elif link["state"] == "linked":
                    bundle = bundles.get(link["core_content_id"])
                    if bundle and bundle.content.status == "duplicate":
                        bundle = bundles.get(bundle.content.duplicate_of_content_id or "")
                    if bundle is None:
                        dto["status"] = "unavailable"
                    else:
                        c = bundle.content
                        dto["status"] = (
                            "unavailable"
                            if c.original_status == "deleted"
                            else {
                                "pending": "analyzing",
                                "awaiting_confirmation": "analyzing",
                                "ready": "ready",
                                "analysis_failed": "failed",
                                "analysis_rejected": "failed",
                            }.get(c.status, "unavailable")
                        )
                        metadata = self.core.metadata(conn, bundle)
                        _, summary, tags = visible_analysis(bundle, metadata is not None)
                        dto["description"] = summary.text if summary else ""
                        dto["tags"] = tags
                        if not link["title_locked"]:
                            dto["title"] = c.title or (metadata.metadata.title if metadata else None) or row["title"]
                        if not link["type_locked"]:
                            dto["type"] = {
                                "video": "영상",
                                "short_video": "영상",
                                "image": "이미지",
                                "post": "텍스트",
                                "article": "텍스트",
                                "paper": "텍스트",
                                "message": "텍스트",
                            }.get(c.content_type, "기타")
            result.append(dto)
        return result

    def after_trash(self, conn: Connection, scope: AccountScope, item_id: str, now: datetime) -> None:
        p = {"user": scope.core_user_id, "id": item_id, "now": instant(now)}
        link = conn.execute(
            text(
                "SELECT core_content_id FROM app_content_links WHERE api_content_id=:id AND core_user_id=:user AND state='linked'"  # noqa: E501
            ),
            p,
        ).first()
        if link:
            p["cid"] = link[0]
            changed = conn.execute(
                text(
                    "UPDATE contents SET is_hidden=1,revision=revision+1,updated_at=:now WHERE id=:cid AND user_id=:user AND is_hidden=0"  # noqa: E501
                ),
                p,
            )
            if changed.rowcount:
                conn.execute(text("UPDATE app_content_links SET hid_core=1 WHERE api_content_id=:id"), p)

    def after_restore(self, conn: Connection, scope: AccountScope, item_id: str, now: datetime) -> None:
        p = {"user": scope.core_user_id, "id": item_id, "now": instant(now)}
        conn.execute(
            text("""UPDATE contents SET is_hidden=0,revision=revision+1,updated_at=:now
            WHERE user_id=:user AND is_hidden=1 AND id IN (SELECT core_content_id FROM app_content_links
            WHERE api_content_id=:id AND core_user_id=:user AND hid_core=1)"""),
            p,
        )
        link = conn.execute(
            text("SELECT state FROM app_content_links WHERE api_content_id=:id AND account_id=:account"),
            {"id": item_id, "account": scope.account_id},
        ).first()
        if link is None:
            row = repo.owned(conn, "api_contents", scope.account_id, item_id)
            self.link_new(conn, scope, row, now)
        elif link.state == "orphaned":
            self.sync(conn, scope, now)

    def purge(self, conn: Connection, condition: str, params: dict[str, Any]) -> None:
        links = conn.execute(
            text(
                """SELECT DISTINCT l.core_user_id,l.core_content_id FROM app_content_links l
            JOIN api_contents a ON a.id=l.api_content_id WHERE l.hid_core=1 AND l.state='linked' AND """
                + condition
            ),
            params,
        ).all()
        conn.execute(
            text("DELETE FROM api_contents WHERE id IN (SELECT a.id FROM api_contents a WHERE " + condition + ")"),
            params,
        )
        for user, cid in links:
            if conn.execute(
                text(
                    "SELECT 1 FROM contents WHERE user_id=:user AND id=:cid AND is_hidden=1 AND NOT EXISTS (SELECT 1 FROM app_content_links WHERE core_user_id=:user AND core_content_id=:cid)"  # noqa: E501
                ),
                {"user": user, "cid": cid},
            ).first():
                self.core.delete(conn, user, cid)

    def sync(self, conn: Connection, scope: AccountScope, now: datetime) -> None:
        conn.exec_driver_sql("SAVEPOINT bridge_sync")
        try:
            self._sync(conn, scope, now)
            conn.exec_driver_sql("RELEASE SAVEPOINT bridge_sync")
        except Exception as exc:
            conn.exec_driver_sql("ROLLBACK TO SAVEPOINT bridge_sync")
            conn.exec_driver_sql("RELEASE SAVEPOINT bridge_sync")
            logging.getLogger(__name__).warning("bridge sync failed: %s", type(exc).__name__)

    def _sync(self, conn: Connection, scope: AccountScope, now: datetime) -> None:
        p: dict[str, Any] = {
            "account": scope.account_id,
            "user": scope.core_user_id,
            "version": URL_NORMALIZATION_VERSION,
        }
        retry = (
            conn.execute(
                text("""SELECT a.* FROM api_contents a JOIN app_content_links l ON l.api_content_id=a.id
            WHERE l.account_id=:account AND l.active=1 AND l.state='rejected'
            AND l.reject_code='core_rejected_url' AND l.url_version<>:version"""),
                p,
            )
            .mappings()
            .all()
        )
        for row in retry:
            conn.execute(text("DELETE FROM app_content_links WHERE api_content_id=:id"), {"id": row["id"]})
            self.link_new(conn, scope, dict(row), now)
        orphans = conn.execute(
            text("""SELECT l.api_content_id, f.content_id FROM app_content_links l
            JOIN content_fingerprints f ON f.user_id=l.core_user_id AND f.kind='normalized_url'
                AND f.version=l.url_version AND f.fingerprint=l.core_url_fp
            WHERE l.account_id=:account AND l.active=1 AND l.state='orphaned'
            AND NOT EXISTS (SELECT 1 FROM app_content_links x WHERE x.core_user_id=l.core_user_id
                AND x.core_content_id=f.content_id AND x.active=1 AND x.state='linked')"""),
            p,
        ).all()
        for item_id, cid in orphans:
            conn.execute(
                text(
                    "UPDATE contents SET is_hidden=0,revision=revision+1,updated_at=:now "
                    "WHERE id=:cid AND user_id=:user AND is_hidden=1"
                ),
                {"cid": cid, "user": scope.core_user_id, "now": instant(now)},
            )
            conn.execute(
                text("""UPDATE app_content_links SET state='linked',core_content_id=:cid,updated_at=:now
                WHERE api_content_id=:id"""),
                {"cid": cid, "id": item_id, "now": instant(now)},
            )
        p = {"account": scope.account_id, "user": scope.core_user_id, "limit": self.adopt_limit}
        rows = (
            conn.execute(
                text("""SELECT a.* FROM api_contents a LEFT JOIN app_content_links l ON l.api_content_id=a.id
            WHERE a.user_id=:account AND a.deleted_at IS NULL AND l.api_content_id IS NULL ORDER BY a.saved_at LIMIT :limit"""),  # noqa: E501
                p,
            )
            .mappings()
            .all()
        )
        for row in rows:
            try:
                self.assert_allowed(conn, scope, row["url"])
            except ContractError:
                conn.execute(
                    text("""INSERT INTO app_content_links (api_content_id,account_id,core_user_id,
                    url_version,origin,state,reject_code,
                    created_at,updated_at)
                    VALUES (:id,:account,:user,:version,'app','rejected','duplicate_active',:now,:now)"""),
                    {**p, "id": row["id"], "version": URL_NORMALIZATION_VERSION, "now": instant(now)},
                )
            else:
                self.link_new(conn, scope, dict(row), now)
        p["limit"] = self.sync_limit
        rows = (
            conn.execute(
                text("""SELECT c.* FROM contents c WHERE c.user_id=:user AND c.source_kind='url'
            AND c.status<>'duplicate' AND c.is_hidden=0 AND NOT EXISTS (SELECT 1 FROM app_content_links l
            WHERE l.core_user_id=c.user_id AND l.core_content_id=c.id) ORDER BY c.saved_at LIMIT :limit"""),
                p,
            )
            .mappings()
            .all()
        )
        for row in rows:
            url = row["source_url"]
            normalized, fp = self.identity(url)
            if (
                normalized is None
                or conn.execute(
                    text("SELECT 1 FROM api_contents WHERE user_id=:account AND url=:url AND deleted_at IS NULL"),
                    {**p, "url": url},
                ).first()
            ):
                continue
            if conn.execute(
                text("SELECT 1 FROM app_content_links WHERE account_id=:account AND core_url_fp=:fp AND active=1"),
                {**p, "fp": fp},
            ).first():
                continue
            item_id, host = str(uuid4()), urlsplit(url).hostname or ""
            values = {
                **p,
                "id": item_id,
                "url": url,
                "host": host,
                "title": row["title"] or host,
                "saved": instant(datetime.fromisoformat(row["saved_at"])),
                "cid": row["id"],
                "fp": fp,
                "version": URL_NORMALIZATION_VERSION,
                "now": instant(now),
            }
            conn.execute(
                text(
                    "INSERT INTO api_contents(id,user_id,url,title,memo,source,saved_at) VALUES (:id,:account,:url,:title,'',:host,:saved)"  # noqa: E501
                ),
                values,
            )
            conn.execute(
                text("""INSERT INTO app_content_links(api_content_id,account_id,core_user_id,
                core_content_id,core_url_fp,url_version,origin,state,created_at,updated_at)
                VALUES (:id,:account,:user,:cid,:fp,:version,'core','linked',:now,:now)"""),
                values,
            )
