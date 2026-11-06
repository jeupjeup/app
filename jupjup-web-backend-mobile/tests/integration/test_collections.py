from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from jupjup.container import AppContainer
from tests.integration.test_save_api import _client, _post

H = {"X-User-Id": "u_alice"}
B = {"X-User-Id": "u_bob"}


def test_collections_ownership_membership_and_preservation(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        cid = _post(
            client, {"source": {"kind": "text", "text": "원문을 보존하는 컬렉션 테스트"}, "automation_level": "confirm"}
        ).json()["content_id"]
        other = _post(client, {"source": {"kind": "text", "text": "다른 사용자 원문"}}, user="u_bob").json()[
            "content_id"
        ]
        # Exercise pending confirmation with explicit user overrides and original/job records.
        job = client.get(f"/v1/contents/{cid}", headers=H).json()["analysis"]["latest_job_id"]
        client.app.state.ingest.run_inline(job)
        current = client.get(f"/v1/contents/{cid}", headers=H)
        patched = client.patch(
            f"/v1/contents/{cid}",
            headers=dict(H, **{"If-Match": current.headers["etag"]}),
            json={"summary": "사용자 요약", "representative_tags": ["내 태그"]},
        )
        assert patched.status_code == 200
        original = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert original["status"] == "awaiting_confirmation"
        assert original["analysis"]["candidate"] is not None
        preserved_tables = [
            "contents",
            "snapshots",
            "summaries",
            "tags",
            "detail_tags",
            "ingest_jobs",
            "analysis_runs",
            "analysis_candidates",
            "index_revisions",
        ]
        with container.repo.engine.connect() as conn:
            preserved = {t: conn.exec_driver_sql(f'SELECT * FROM "{t}"').all() for t in preserved_tables}
        first = client.post("/v1/collections", headers=H, json={"name": "  Café  "})
        assert first.status_code == 201
        col = first.json()["id"]
        assert first.json()["name"] == "Café"
        assert client.post("/v1/collections", headers=H, json={"name": "CAFE\u0301"}).status_code == 409
        assert client.post("/v1/collections", headers=B, json={"name": "Café"}).status_code == 201
        for body in [{"name": "  "}, {"name": "a" * 81}, {"name": "ok", "color": "url(x)"}]:
            assert client.post("/v1/collections", headers=H, json=body).status_code == 422
        for method in ["get", "patch", "delete"]:
            kwargs = {"json": {"name": "steal"}} if method == "patch" else {}
            hidden = getattr(client, method)(f"/v1/collections/{col}", headers=B, **kwargs)
            missing = getattr(client, method)("/v1/collections/missing", headers=B, **kwargs)
            assert hidden.status_code == missing.status_code == 404
            assert hidden.json() == missing.json()
        second = client.post("/v1/collections", headers=H, json={"name": "second"}).json()["id"]
        assert client.patch(f"/v1/collections/{second}", headers=H, json={"name": "CAFÉ"}).status_code == 409
        assert client.patch(f"/v1/collections/{second}", headers=H, json={"name": None}).status_code == 422
        assert (
            client.patch(f"/v1/collections/{second}", headers=H, json={"name": "renamed"}).json()["name"] == "renamed"
        )
        for c in [col, second]:
            for _ in range(2):
                assert client.put(f"/v1/collections/{c}/contents/{cid}", headers=H).status_code == 204
        assert client.put(f"/v1/collections/{col}/contents/{other}", headers=H).status_code == 404
        assert client.delete(f"/v1/collections/{col}/contents/{cid}", headers=B).status_code == 404
        assert client.get("/v1/contents", headers=B, params={"collection_id": col}).status_code == 404
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert set(detail.pop("collection_ids")) == {col, second}
        original.pop("collection_ids")
        assert detail == original
        assert client.get(f"/v1/collections/{col}", headers=H).json()["content_count"] == 1
        for _ in range(2):
            assert client.delete(f"/v1/collections/{second}/contents/{cid}", headers=H).status_code == 204
        assert client.delete(f"/v1/collections/{col}", headers=H).status_code == 204
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert detail.pop("collection_ids") == []
        assert detail == original
        with container.repo.engine.connect() as conn:
            for table, rows in preserved.items():
                assert conn.exec_driver_sql(f'SELECT * FROM "{table}"').all() == rows
            assert conn.scalar(text("SELECT count(*) FROM collection_contents")) == 0
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_collection_pagination_counts_and_database_constraints(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        cols = [client.post("/v1/collections", headers=H, json={"name": n}).json()["id"] for n in ["one", "two"]]
        ids = [
            _post(client, {"source": {"kind": "text", "text": f"원문 번호 {i}"}}, key=f"k{i}").json()["content_id"]
            for i in range(5)
        ]
        for cid in ids:
            assert client.put(f"/v1/collections/{cols[0]}/contents/{cid}", headers=H).status_code == 204
        with container.repo.engine.begin() as conn:
            conn.execute(text("UPDATE contents SET is_hidden=1 WHERE id=:id"), {"id": ids[0]})
            conn.execute(text("UPDATE contents SET status='duplicate' WHERE id=:id"), {"id": ids[1]})
        assert client.get(f"/v1/collections/{cols[0]}", headers=H).json()["content_count"] == 3
        page = client.get("/v1/contents", headers=H, params={"collection_id": cols[0], "limit": 2}).json()
        assert len(page["items"]) == 2 and page["has_more"]
        # A pre-collection default cursor scope remains valid when no collection is selected.
        from jupjup.save.cursor import cursor_scope, decode_cursor
        from jupjup.save.query import ContentListQuery

        default_page = client.get("/v1/contents", headers=H, params={"limit": 2}).json()
        old_filters = ContentListQuery().model_dump(mode="json", exclude={"cursor", "limit", "collection_id"})
        decode_cursor(
            default_page["next_cursor"], cursor_scope("u_alice", old_filters), container.settings.cursor_secret
        )
        contract = client.get("/openapi.json").json()["components"]["schemas"]
        assert "collection_ids" in contract["ContentListItem"]["properties"]
        assert "collection_ids" in contract["ContentDetail"]["properties"]
        params = {"collection_id": cols[0], "limit": 2, "cursor": page["next_cursor"]}
        last = client.get("/v1/contents", headers=H, params=params).json()
        assert len(last["items"]) == 1 and not last["has_more"]
        assert len({r["id"] for r in page["items"] + last["items"]}) == 3
        for change in [{"collection_id": cols[1]}, {"order": "asc"}, {"collection_id": None}]:
            assert (
                client.get(
                    "/v1/contents", headers=H, params={k: v for k, v in dict(params, **change).items() if v is not None}
                ).status_code
                == 422
            )
        foreign = client.post("/v1/collections", headers=B, json={"name": "foreign"}).json()["id"]
        with pytest.raises(IntegrityError), container.repo.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO collection_contents VALUES (:c,:id,:u)"), dict(c=foreign, id=ids[2], u="u_alice")
            )
        with pytest.raises(IntegrityError), container.repo.engine.begin() as conn:
            conn.execute(text("UPDATE contents SET user_id=:u WHERE id=:id"), dict(u="u_bob", id=ids[2]))
        assert client.delete(f"/v1/contents/{ids[2]}", headers=H).status_code == 204
        assert client.get(f"/v1/collections/{cols[0]}", headers=H).json()["content_count"] == 2
