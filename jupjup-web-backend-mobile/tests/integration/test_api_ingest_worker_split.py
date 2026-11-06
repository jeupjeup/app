"""T23 loop 1 M2: API 서버와 별도 워커 프로세스가 같은 DB를 쓸 때도 검색이 최신 상태를 본다.

워커 쪽은 같은 파일 DB에 연결한 별도 컨테이너(엔진, 메모리 인덱스, 레지스트리가 모두 따로)다.
API 쪽 메모리 인덱스와 아무것도 공유하지 않으므로 다른 프로세스와 같은 조건이다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from jupjup.config import Settings
from jupjup.container import AppContainer, build_container, build_ingest_service
from jupjup.domain.errors import LLMRefusalError
from jupjup.ingest.analyzer import AnalysisRunMeta
from jupjup.ingest.fetch import FetcherRouter, InlineTextFetcher
from jupjup.ingest.jobs import JobQueue
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.worker import IngestStageRunners, IngestWorker
from jupjup.providers.vision import OcrOnlyUnderstander
from jupjup.storage import tables as T
from tests.conftest import DATA
from tests.legacy_api import create_app

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
ALICE = {"X-User-Id": "u_alice"}


def _container(db_path: Path) -> AppContainer:
    settings = Settings(env="dev", mode="mock", data_dir=DATA, db_path=db_path, ingest_fixtures_dir=FIXTURES)
    return build_container(settings)


@pytest.fixture
def split(tmp_path: Path) -> Iterator[tuple[TestClient, AppContainer, AppContainer]]:
    db_path = tmp_path / "split.db"
    api_container = _container(db_path)
    worker_container = _container(db_path)
    assert api_container.registry is not worker_container.registry
    with TestClient(create_app(container=api_container), raise_server_exceptions=False) as client:
        yield client, api_container, worker_container


def _search(client: TestClient, query: str) -> list[str]:
    response = client.post("/v1/search", headers=ALICE, json={"query": query})
    assert response.status_code == 200, response.text
    return [item["content_id"] for item in response.json()["results"]]


def _drain(worker_container: AppContainer) -> None:
    worker = build_ingest_service(worker_container, worker_id="split-worker").worker
    while worker.run_once():
        pass


def _submit(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/v1/admin/ingest", headers=ALICE, json=body)
    assert response.status_code == 202, response.text
    data: dict[str, Any] = response.json()
    return data


def test_api_submit_then_separate_worker_then_same_api_search_finds_content(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, _, worker_container = split
    submitted = _submit(client, {"source": {"kind": "text", "text": "은하수조약돌 표본 관찰 기록입니다. 보관법 메모."}})
    assert _search(client, "은하수조약돌") == []  # 아직 아무 단계도 돌지 않았다

    _drain(worker_container)

    status = client.get(f"/v1/admin/ingest/jobs/{submitted['job_id']}", headers=ALICE).json()
    assert status["status"] == "succeeded"
    assert _search(client, "은하수조약돌") == [submitted["content_id"]]
    result = client.post("/v1/search", headers=ALICE, json={"query": "은하수조약돌"}).json()["results"][0]
    assert result["summary"]  # 완전 인덱스(I8)의 요약까지 보인다


def test_html_fixture_processed_by_separate_worker_is_searchable(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, api_container, worker_container = split
    source = {"kind": "url", "url": "https://example.com/article", "fixture": "html/article.html"}
    submitted = _submit(client, {"source": source, "title": "독립 서점 소식"})
    _drain(worker_container)
    assert client.get(f"/v1/admin/ingest/jobs/{submitted['job_id']}", headers=ALICE).json()["status"] == "succeeded"

    bundle = api_container.repo.get_bundle("u_alice", submitted["content_id"])
    assert bundle.content.title == "독립 서점 소식"
    assert submitted["content_id"] in _search(client, "독립 서점")


def test_content_deleted_by_another_process_disappears_from_search(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, _, worker_container = split
    submitted = _submit(client, {"source": {"kind": "text", "text": "은하수조약돌 삭제 확인용 기록입니다."}})
    _drain(worker_container)
    assert _search(client, "은하수조약돌") == [submitted["content_id"]]

    worker_container.repo.delete("u_alice", submitted["content_id"])
    assert _search(client, "은하수조약돌") == []


def test_unchanged_store_does_not_rebuild_the_index(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, api_container, worker_container = split
    _submit(client, {"source": {"kind": "text", "text": "은하수조약돌 재구축 횟수 확인 기록입니다."}})
    _drain(worker_container)
    _search(client, "은하수조약돌")
    before = api_container.registry.get("u_alice")
    _search(client, "은하수조약돌")
    _search(client, "관찰")
    assert api_container.registry.get("u_alice") is before


def test_in_place_content_edit_with_same_updated_at_is_reloaded(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, api_container, worker_container = split
    submitted = _submit(client, {"source": {"kind": "text", "text": "은하수조약돌 원문입니다."}})
    _drain(worker_container)
    assert _search(client, "은하수조약돌") == [submitted["content_id"]]

    with worker_container.engine.begin() as conn:
        conn.execute(
            update(T.contents).where(T.contents.c.id == submitted["content_id"]).values(title="태양나침반 제자리 수정")
        )

    assert _search(client, "태양나침반") == [submitted["content_id"]]
    assert api_container.repo.get_bundle("u_alice", submitted["content_id"]).content.title == "태양나침반 제자리 수정"


class RefusingAnalyzer:
    profile_name = "refusing"

    def analyze(self, inp: object) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        raise LLMRefusalError("refused", {"attempts": 1})


def test_separate_worker_refusal_keeps_reduced_i2_content_searchable(
    split: tuple[TestClient, AppContainer, AppContainer],
) -> None:
    client, _, worker_container = split
    submitted = _submit(client, {"source": {"kind": "text", "text": "청동해시계 희귀 표본 기록입니다."}})
    queue = JobQueue(worker_container.engine)
    stages = IngestStageRunners(
        queue,
        worker_container.repo,
        worker_container.indexer,
        FetcherRouter([InlineTextFetcher()]),
        RefusingAnalyzer(),
        OcrOnlyUnderstander(),
    )
    worker = IngestWorker(queue, stages.mapping(), worker_id="refusing-worker")
    while worker.run_once():
        pass

    status = client.get(f"/v1/admin/ingest/jobs/{submitted['job_id']}", headers=ALICE).json()
    assert status["status"] == "needs_review"
    assert _search(client, "청동해시계") == [submitted["content_id"]]
