"""Offline public save pipeline: fake HTTP, scripted LLM, in-memory SQLite."""

import copy
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jupjup.container import build_ingest_service
from jupjup.ingest.fetch import FetcherRouter, HttpResponse, HttpSourceFetcher
from jupjup.ingest.instagram import InstagramMetadataFetcher
from jupjup.ingest.validation import AnalysisValidator
from tests.legacy_api import create_app
from tests.unit.test_llm_analyzer import VALID, ScriptedLLM, analyzer_for, ok

H = {"X-User-Id": "u_alice", "Idempotency-Key": "instagram-save"}


@pytest.mark.parametrize("kind,fixture,level", [
    ("p", "post", "auto"), ("reel", "reel", "auto"), ("reels", "reel", "confirm"),
    ("p", "title_only", "auto"),
])
def test_scripted_llm_save_safe_and_searchable(container_factory, kind, fixture, level):
    c = container_factory()
    poisoned = copy.deepcopy(VALID)
    poisoned.update(summary="실제 영상과 음성을 분석해 파리의 미슐랭 식당을 확인했습니다.",
                    representative_tags=["파리", "미슐랭", "가짜"], title_suggestion="가짜제목")
    poisoned["detail_tags"].update(category="howto_recipe", keywords=["가짜"],
                                   locations=[{"name": "파리", "level": "city"}],
                                   entities=[{"name": "가짜", "type": "person"}], attributes=["가짜"])
    llm = ScriptedLLM(responder=lambda _: ok(poisoned))
    service = build_ingest_service(c, analyzer=analyzer_for(llm, AnalysisValidator(c.lexicon)))
    html = ('<title>제주 여행 바다</title>' if fixture == "title_only"
            else Path(f"tests/fixtures/instagram/{fixture}.html").read_text())
    requests = []

    def transport(url, timeout):
        requests.append(url)
        return HttpResponse(200, {"content-type": "text/html; charset=utf-8"}, html.encode())

    stage = service.worker.stages["fetch"].__self__
    stage.fetcher = FetcherRouter([
        InstagramMetadataFetcher(HttpSourceFetcher(resolver=lambda _: ["93.184.216.34"], transport=transport))
    ])
    with TestClient(create_app(container=c, ingest=service)) as client:
        response = client.post("/v1/contents", headers=H, json={
            "source": {"kind": "url", "url": f"https://instagram.com/{kind}/abc/?igsh=secret"},
            "platform_hint": "web", "content_type_hint": "webpage", "automation_level": level,
        })
        assert response.status_code == 202, response.text
        ids = response.json()
        service.run_inline(ids["job_id"])
        cid = ids["content_id"]
        if level == "confirm":
            detail = client.get(f"/v1/contents/{cid}", headers=H).json()
            candidate = detail["analysis"]["candidate"]
            approved = client.post(f"/v1/contents/{cid}:review", headers=H,
                                   json={"candidate_id": candidate["id"], "decision": "approve"})
            assert approved.status_code == 202
            service.run_inline(ids["job_id"])
        job = service.status("u_alice", ids["job_id"])
        assert job.status == "succeeded", job.last_error
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert detail["platform"] == "instagram"
        assert detail["content_type"] == ("post" if kind == "p" else "short_video")
        assert "기준 기록" in detail["summary"]["ai"]
        assert "가짜" not in str(detail) and "미슐랭" not in str(detail) and "파리" not in str(detail)
        assert detail["detail_tags"]["ai"]["category"] == "other"
        assert "BOILERPLATE" not in str(detail)
        bundle = c.repo.get_bundle("u_alice", cid)
        assert bundle.snapshot.raw_meta["source_scope"] == "instagram_metadata"
        # Tags are verbatim metadata words, modulo the shared lexicon canonicalization (e.g. 성수 -> 성수동).
        validator = AnalysisValidator(c.lexicon)
        grounded = {validator._normalize_tag(word) for word in re.findall(r"\w+", bundle.snapshot.text)}
        assert all(tag in bundle.snapshot.text or tag in grounded for tag in detail["representative_tags"]["ai"])
        assert not any(tag.endswith(("에서", "와")) for tag in detail["representative_tags"]["ai"])
        inp = service.queue.artifact("u_alice", ids["job_id"], "analysis_input")
        assert inp["source_scope"] == "instagram_metadata"
        assert "BOILERPLATE" not in inp["text"]
        assert len(llm.calls) == 1
        assert "음성은 보지 않았다" in llm.calls[0].system
        assert client.get("/v1/contents", headers=H).status_code == 200
        query = "성수 카페" if fixture == "post" else "제주 여행"
        search = client.post("/v1/search", headers=H, json={"query": query})
        assert search.status_code == 200
        assert cid in [row["content_id"] for row in search.json()["results"]]
        assert len(requests) == 1 and "secret" not in requests[0]


def test_default_router_claims_instagram_before_generic(container_factory):
    from jupjup.ingest.fetch import SourceSpec

    service = build_ingest_service(container_factory())
    router = service.worker.stages["fetch"].__self__.fetcher
    spec = SourceSpec(kind="url", url="https://instagram.com/p/abc/")
    matching = [fetcher for fetcher in router._fetchers if fetcher.supports(spec)]
    assert isinstance(matching[0], InstagramMetadataFetcher)
