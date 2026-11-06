from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text

from jupjup.container import AppContainer
from jupjup.storage.db import run_migrations
from tests.integration.test_save_api import _client, _post


def _legacy_times(container: AppContainer, values: list[str], client) -> list[str]:
    ids = [
        _post(client, {"source": {"kind": "text", "text": f"시간 회귀 {i}"}}, key=f"time-{i}").json()["content_id"]
        for i in range(len(values))
    ]
    for cid in ids:
        job = client.get(f"/v1/contents/{cid}", headers={"X-User-Id": "u_alice"}).json()["analysis"]["latest_job_id"]
        client.app.state.ingest.run_inline(job)
    with container.repo.engine.begin() as conn:
        # Simulate a v27 schema, including removal of later collection objects.
        conn.exec_driver_sql("DROP TABLE collection_contents")
        conn.exec_driver_sql("DROP TABLE collections")
        conn.exec_driver_sql("DROP INDEX uq_contents_id_user")
        conn.execute(text("DELETE FROM schema_migrations WHERE version > 27"))
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS trg_contents_instants_insert")
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS trg_contents_instants_update")
        for cid, value in zip(ids, values, strict=True):
            conn.execute(
                text("UPDATE contents SET saved_at=:at, updated_at=:at WHERE id=:id"), {"at": value, "id": cid}
            )
    run_migrations(container.repo.engine)
    return ids


def test_review_reproduction_1_offset_saved_at_is_in_utc_window(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        ids = _legacy_times(container, ["2026-11-03T10:00:00+09:00"], client)
        for start, end in [
            ("2026-11-03T00:00:00Z", "2026-11-03T02:00:00Z"),
            ("2026-11-03T09:00:00+09:00", "2026-11-03T11:00:00+09:00"),
        ]:
            response = client.get(
                "/v1/contents", headers={"X-User-Id": "u_alice"}, params={"saved_from": start, "saved_to": end}
            )
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["items"]] == ids


def test_review_reproduction_2_mixed_offsets_sort_by_instant(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        ids = _legacy_times(container, ["2026-11-03T10:00:00+09:00", "2026-11-03T02:00:00+00:00"], client)
        response = client.get("/v1/contents", headers={"X-User-Id": "u_alice"}, params={"order": "desc", "limit": 1})
        assert response.status_code == 200
        assert response.json()["items"][0]["id"] == ids[1]


def test_mixed_offsets_microseconds_ties_and_full_cursor_walk(container_factory: Callable[..., AppContainer]) -> None:
    from datetime import datetime

    container = container_factory()
    times = [
        "2026-11-03T10:00:00+09:00",
        "2026-11-03T01:00:00.000000Z",
        "2026-11-02T20:00:00.000001-05:00",
        "2026-11-03T01:00:00.999999+00:00",
        "2026-11-03T02:00:00+00:00",
    ]
    with _client(container) as client:
        ids = _legacy_times(container, times[:-1], client)
        client.app.state.ingest.worker.clock = lambda: datetime.fromisoformat(times[-1])
        created = _post(client, {"source": {"kind": "text", "text": "새 UTC 저장물"}}, key="new-utc")
        assert created.status_code == 202
        ids.append(created.json()["content_id"])
        expected = sorted(ids, key=lambda cid: (datetime.fromisoformat(times[ids.index(cid)]), cid))
        for sort in ["saved_at", "updated_at"]:
            for order in ["asc", "desc"]:
                for limit in [1, 2]:
                    params = {"sort": sort, "order": order, "limit": limit}
                    found = []
                    for _ in range(len(ids) + 1):
                        response = client.get("/v1/contents", headers={"X-User-Id": "u_alice"}, params=params)
                        assert response.status_code == 200
                        page = response.json()
                        found.extend(item["id"] for item in page["items"])
                        if not page["has_more"]:
                            break
                        params["cursor"] = page["next_cursor"]
                    assert found == (expected if order == "asc" else list(reversed(expected)))
        for start, end in [
            ("2026-11-03T01:00:00Z", "2026-11-03T01:00:00.000001Z"),
            ("2026-11-03T10:00:00+09:00", "2026-11-03T10:00:00.000001+09:00"),
        ]:
            params = {"saved_from": start, "saved_to": end}
            listed = client.get("/v1/contents", headers={"X-User-Id": "u_alice"}, params=params).json()
            assert {item["id"] for item in listed["items"]} == set(ids[:2])
            # Browse search uses the existing engine's saved_at hard filter.
            searched = client.post(
                "/v1/search",
                headers={"X-User-Id": "u_alice"},
                json={"query": "유튜브", "filters": {**params, "platforms": ["local"]}},
            )
            assert searched.status_code == 200
            assert {item["content_id"] for item in searched.json()["results"]} == set(ids[:2])
