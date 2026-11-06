"""Contract operations; all writes use the caller's single SQLite transaction."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import Connection, text
from starlette.datastructures import QueryParams

from jupjup.app_api import auth
from jupjup.app_api import repository as repo
from jupjup.app_api import validation as v
from jupjup.app_api.errors import ContractError

if TYPE_CHECKING:
    from jupjup.bridge.service import AccountScope, ContentBridge


def execute(
    conn: Connection,
    operation: str,
    body: dict[str, Any],
    now: datetime,
    user: dict[str, Any] | None,
    token_hash: str,
    item_id: str,
    query: QueryParams,
    bridge: ContentBridge | None = None,
) -> Any:
    if operation == "health":
        conn.exec_driver_sql("SELECT 1")
        return {"status": "ok"}
    if operation == "register":
        return auth.register(conn, body, now)
    if operation == "login":
        return auth.login(conn, body, now)
    assert user is not None
    uid = user["id"]
    params = dict(user=uid, id=item_id, now=auth.instant(now))
    scope = (
        bridge.scope(conn, uid)
        if bridge
        and operation
        in (
            "getState",
            "createContent",
            "listContent",
            "getContent",
            "updateContent",
            "deleteContent",
            "restoreContent",
            "viewContent",
            "emptyTrash",
        )
        else None
    )
    if operation == "logout":
        conn.execute(text("DELETE FROM api_sessions WHERE token_hash=:token"), dict(token=token_hash))
    elif operation == "getMe":
        return auth.user_dto(user)
    elif operation == "updateMe":
        user["nickname"] = v.string(body, "nickname", 25)
        conn.execute(text("UPDATE api_users SET nickname=:nickname WHERE id=:id"), user)
        return auth.user_dto(user)
    elif operation == "deleteMe":
        conn.execute(text("DELETE FROM api_users WHERE id=:user"), params)
    elif operation in ("verifyPassword", "changePassword"):
        new = v.password(body, "newPassword") if operation == "changePassword" else None
        auth.verify_password(conn, user, body, now)
        if new is not None:
            conn.execute(
                text("UPDATE api_users SET password_hash=:password_hash,password_salt=:password_salt WHERE id=:id"),
                dict(id=uid, **auth.credentials(new)),
            )
            conn.execute(
                text("DELETE FROM api_sessions WHERE user_id=:user AND token_hash<>:token"),
                dict(user=uid, token=token_hash),
            )
    elif operation == "getState":
        if bridge and scope:
            bridge.sync(conn, scope, now)
            rows = [
                dict(r)
                for r in conn.execute(
                    text("SELECT * FROM api_contents WHERE user_id=:user ORDER BY saved_at DESC,rowid DESC"),
                    {"user": uid},
                ).mappings()
            ]
            items = bridge.project(conn, scope, rows)
        else:
            items = repo.contents(conn, uid)
        return dict(
            user=auth.user_dto(user),
            contents=items,
            notices=repo.notices(conn, uid),
            searchHistory=repo.history(conn, uid),
            savedCount=sum("deletedAt" not in item for item in items),
        )
    elif operation == "createContent":
        url, host = v.normalize_url(body)
        memo = v.string(body, "memo", 70, 0) if "memo" in body else ""
        if conn.execute(
            text("SELECT 1 FROM api_contents WHERE user_id=:user AND url=:url AND deleted_at IS NULL"),
            dict(user=uid, url=url),
        ).first():
            raise ContractError(409, "DUPLICATE_CONTENT")
        if bridge and scope:
            bridge.assert_allowed(conn, scope, url)
        cid = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO api_contents (id,user_id,url,title,memo,source,saved_at) "
                "VALUES (:id,:user,:url,:title,:memo,:source,:now)"
            ),
            dict(id=cid, user=uid, url=url, title=host, memo=memo, source=host, now=params["now"]),
        )
        conn.execute(
            text(
                "INSERT INTO api_notices (id,user_id,title,description,date) "
                "VALUES (:id,:user,:title,:description,:now)"
            ),
            dict(id=str(uuid4()), user=uid, title="정보를 저장했어요", description=host, now=params["now"]),
        )
        row = repo.owned(conn, "api_contents", uid, cid)
        if bridge and scope:
            bridge.link_new(conn, scope, row, now)
            return bridge.project(conn, scope, [row])[0]
        return repo.content_dto(row)
    elif operation == "listContent":
        if bridge and scope:
            bridge.sync(conn, scope, now)
        return list_contents(conn, uid, query, bridge, scope)
    elif operation in ("getContent", "updateContent", "deleteContent", "restoreContent", "viewContent"):
        return content_operation(conn, operation, body, uid, params, bridge, scope, now)
    elif operation == "emptyTrash":
        if bridge:
            bridge.purge(conn, "a.user_id=:user AND a.deleted_at IS NOT NULL", params)
        else:
            conn.execute(text("DELETE FROM api_contents WHERE user_id=:user AND deleted_at IS NOT NULL"), params)
    elif operation == "listNotices":
        return {"items": repo.notices(conn, uid)}
    elif operation in ("readNotice", "readAllNotices"):
        if operation == "readNotice":
            repo.owned(conn, "api_notices", uid, item_id)
        suffix = " AND id=:id" if operation == "readNotice" else ""
        conn.execute(text("UPDATE api_notices SET read=1 WHERE user_id=:user" + suffix), params)
    elif operation in ("getSearchHistory", "addSearchHistory", "clearSearchHistory"):
        if operation == "clearSearchHistory":
            conn.execute(text("DELETE FROM api_search_history WHERE user_id=:user"), params)
            return None
        if operation == "addSearchHistory":
            term = v.string(body, "query", 200)
            conn.execute(
                text("DELETE FROM api_search_history WHERE user_id=:user AND query=:query"), dict(user=uid, query=term)
            )
            conn.execute(
                text("INSERT INTO api_search_history (user_id,query) VALUES (:user,:query)"), dict(user=uid, query=term)
            )
            conn.execute(
                text(
                    "DELETE FROM api_search_history WHERE user_id=:user AND sequence NOT IN "
                    "(SELECT sequence FROM api_search_history WHERE user_id=:user "
                    "ORDER BY sequence DESC LIMIT 10)"
                ),
                params,
            )
        return {"items": repo.history(conn, uid)}
    else:
        raise AssertionError(operation)
    return None


def content_operation(
    conn: Connection,
    operation: str,
    body: dict[str, Any],
    uid: str,
    params: dict[str, Any],
    bridge: ContentBridge | None = None,
    scope: AccountScope | None = None,
    now: datetime | None = None,
) -> Any:
    row = repo.owned(conn, "api_contents", uid, params["id"])
    if operation in ("updateContent", "viewContent") and row["deleted_at"] is not None:
        raise ContractError(409, "CONTENT_DELETED")
    if operation == "updateContent":
        values: dict[str, Any] = {}
        for key, maximum, minimum in (("title", 200, 1), ("memo", 70, 0)):
            if key in body:
                values[key] = v.string(body, key, maximum, minimum)
        if "type" in body:
            if body["type"] not in v.TYPES:
                v.invalid()
            values["type"] = body["type"]
        if "collection" in body:
            if body["collection"] is not None and body["collection"] not in v.COLLECTIONS:
                v.invalid()
            values["collection"] = body["collection"]
        if values:
            assignments = ",".join(f"{key}=:{key}" for key in values)
            conn.execute(
                text(f"UPDATE api_contents SET {assignments} WHERE user_id=:user AND id=:id"), dict(**params, **values)
            )
        if bridge and scope:
            shared: dict[str, Any] = {key: values[key] for key in ("title", "memo") if key in values}
            if shared:
                assignments = ",".join(f"{'user_note' if key == 'memo' else key}=:{key}" for key in shared)
                conn.execute(
                    text(
                        f"UPDATE contents SET {assignments},revision=revision+1,updated_at=:now "
                        "WHERE user_id=:core_user AND id IN (SELECT core_content_id FROM app_content_links "
                        "WHERE api_content_id=:id AND account_id=:user AND state='linked')"
                    ),
                    {**params, **shared, "core_user": scope.core_user_id},
                )
        if bridge and scope and ("title" in values or "type" in values):
            conn.execute(
                text(
                    "UPDATE app_content_links SET title_locked=MAX(title_locked,:title), "
                    "type_locked=MAX(type_locked,:type) WHERE api_content_id=:id AND account_id=:user"
                ),
                {**params, "title": int("title" in values), "type": int("type" in values)},
            )
    elif operation == "deleteContent":
        conn.execute(
            text("UPDATE api_contents SET deleted_at=COALESCE(deleted_at,:now) WHERE user_id=:user AND id=:id"), params
        )
        if bridge and scope and now:
            bridge.after_trash(conn, scope, params["id"], now)
        return None
    elif operation == "restoreContent":
        if conn.execute(
            text("SELECT 1 FROM api_contents WHERE user_id=:user AND url=:url AND deleted_at IS NULL AND id<>:id"),
            dict(**params, url=row["url"]),
        ).first():
            raise ContractError(409, "DUPLICATE_CONTENT")
        if bridge and scope:
            bridge.assert_allowed(conn, scope, row["url"], params["id"])
        conn.execute(text("UPDATE api_contents SET deleted_at=NULL WHERE user_id=:user AND id=:id"), params)
        if bridge and scope and now:
            bridge.after_restore(conn, scope, params["id"], now)
    elif operation == "viewContent":
        conn.execute(text("UPDATE api_contents SET viewed_at=:now WHERE user_id=:user AND id=:id"), params)
        return None
    row = repo.owned(conn, "api_contents", uid, params["id"])
    return bridge.project(conn, scope, [row])[0] if bridge and scope else repo.content_dto(row)


def list_contents(
    conn: Connection,
    uid: str,
    query: QueryParams,
    bridge: ContentBridge | None = None,
    scope: AccountScope | None = None,
) -> dict[str, Any]:
    for key, choices in (
        ("type", v.TYPES),
        ("collection", v.COLLECTIONS),
        ("deleted", ("false", "true", "all")),
        ("sort", ("newest", "oldest", "recent")),
    ):
        if key in query and query[key] not in choices:
            v.invalid()
    if bridge and scope:
        rows = [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM api_contents WHERE user_id=:user ORDER BY saved_at DESC,rowid DESC"), {"user": uid}
            ).mappings()
        ]
        items = bridge.project(conn, scope, rows)
    else:
        items = repo.contents(conn, uid)
    deleted = query.get("deleted", "false")
    term = query.get("q", "").strip().lower()
    items = [
        item
        for item in items
        if (deleted == "all" or ("deletedAt" in item) == (deleted == "true"))
        and ("type" not in query or item["type"] == query["type"])
        and ("collection" not in query or item.get("collection") == query["collection"])
        and (not term or term in " ".join([item["title"], item["memo"], item["description"], *item["tags"]]).lower())
    ]
    sort = query.get("sort", "newest")
    if sort == "oldest":
        items.reverse()
    elif sort == "recent":
        items.sort(key=lambda item: item.get("viewedAt", ""), reverse=True)
    return {"items": items, "total": len(items)}
