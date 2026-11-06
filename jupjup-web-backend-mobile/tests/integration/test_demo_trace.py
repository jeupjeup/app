"""검색 데모의 "검색 과정"(trace) 패널: 스키마, SearchService explain 결과와의 일치, 무회귀.

스냅숏 갱신: ``UPDATE_TRACE_SNAPSHOTS=1 uv run pytest tests/integration/test_demo_trace.py``
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jupjup.container import AppContainer
from jupjup.demo import create_demo_app
from jupjup.demo.app import DemoSearchTrace
from jupjup.domain.errors import JupjupError
from jupjup.search.service import SearchRequest
from jupjup.search.types import SearchResult
from tests.integration._search_digest import golden_queries, result_digest

NOW = "2026-10-15T12:00:00+09:00"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "search_trace"
TRACE_GROUPS = {"input_data", "preprocessing", "model_processing", "analysis", "evidence", "execution_log", "timing_ms"}
LEGACY_FIELDS = {
    "query",
    "understanding",
    "results",
    "browse",
    "applied_relaxations",
    "empty_state",
    "degraded",
    "degraded_reasons",
    "timing_ms",
}
REPRESENTATIVE = {
    "period_platform": "지난달 인스타에서 본 성수동 카페",
    "typo": "파스티 레시피",
    "empty_then_relaxed": "지난주 유튜브 파스타 레시피",
}
COMPONENT_TIMING_KEYS = {
    "temporal_parse": "query_understanding",
    "facet_extract": "query_understanding",
    "intent_classify": "query_understanding",
    "bm25f_retrieve": "candidate_retrieval",
    "vector_retrieve": "candidate_retrieval",
    "fusion": "fusion",
    "feature_rerank": "feature_rerank_gate",
    "relevance_gate": "feature_rerank_gate",
    "relaxation": "relaxation_selection",
    "cross_rerank": "cross_rerank",
}


def _post(container: AppContainer, query: str, user_id: str = "u_alice") -> dict[str, Any]:
    with TestClient(create_demo_app(container=container)) as client:
        response = client.post("/demo/search", json={"query": query, "user_id": user_id, "now": NOW})
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def _post_capturing(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch, query: str
) -> tuple[dict[str, Any], SearchResult]:
    """데모 엔드포인트가 실제로 받은 SearchResult를 함께 돌려준다."""
    captured: list[SearchResult] = []
    original = container.search.search

    def spy(req: SearchRequest) -> SearchResult:
        result = original(req)
        captured.append(result)
        return result

    monkeypatch.setattr(container.search, "search", spy)
    data = _post(container, query)
    monkeypatch.undo()
    assert len(captured) == 1 and captured[0].debug is not None
    return data, captured[0]


def _expected_log_status(raw: str) -> tuple[str, str | None]:
    head, separator, detail = raw.partition(":")
    if head == "scored":
        return "success", None
    if head in {"success", "skipped", "degraded", "failed"}:
        return head, detail if separator else None
    return "failed", raw


# ----------------------------------------------------------------- 스키마
def test_trace_schema_and_legacy_fields(golden_container: AppContainer) -> None:
    data = _post(golden_container, REPRESENTATIVE["period_platform"])
    assert set(data) >= LEGACY_FIELDS
    assert set(data["trace"]) == TRACE_GROUPS
    trace = DemoSearchTrace.model_validate(data["trace"])
    steps = [
        trace.preprocessing.normalization,
        trace.analysis.understanding,
        trace.evidence.filtering,
        trace.evidence.retrieval,
        trace.evidence.fusion,
        trace.evidence.reranking,
        trace.evidence.relaxation,
        trace.model_processing.cross_reranker,
        trace.analysis.final,
    ]
    assert [step.number for step in steps] == list(range(1, 10))
    assert all(step.title for step in steps)
    assert {"query_understanding", "filter_resolution", "candidate_retrieval", "fusion", "total"} <= set(
        trace.timing_ms
    )
    stages = [component.stage for component in trace.model_processing.components]
    assert stages == [
        "temporal_parse",
        "facet_extract",
        "intent_classify",
        "bm25f_retrieve",
        "vector_retrieve",
        "fusion",
        "feature_rerank",
        "relevance_gate",
        "relaxation",
        "cross_rerank",
    ]
    vector = next(c for c in trace.model_processing.components if c.stage == "vector_retrieve")
    assert vector.model == golden_container.embedder.model_id
    assert vector.dimension == golden_container.embedder.dim
    assert vector.mode == "query" and vector.provider_mode == golden_container.settings.mode
    # 크로스 리랭커는 기본 꺼짐으로 표시된다.
    assert trace.model_processing.cross_reranker.enabled is False
    assert trace.model_processing.cross_reranker.used is False
    assert trace.model_processing.cross_reranker.status == "skipped:disabled"
    cross = next(c for c in trace.model_processing.components if c.stage == "cross_rerank")
    assert cross.status == "skipped:disabled"


def test_page_has_trace_panel(golden_container: AppContainer) -> None:
    with TestClient(create_demo_app(container=golden_container)) as client:
        html = client.get("/").text
    assert 'id="trace"' in html and "검색 과정" in html
    assert "renderTrace(data)" in html and "TABLE_LIMIT = 10" in html
    assert "@media print" in html
    for group in ("입력", "전처리", "모델 처리", "분석 결과", "근거", "실행 로그"):
        assert f"'{group}'" in html
    assert "<link" not in html and "<script src=" not in html and "https://" not in html


# ----------------------------------------------------------------- 값 일치
@pytest.mark.parametrize("name", list(REPRESENTATIVE))
def test_trace_values_come_from_service_explain(
    golden_container: AppContainer, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    data, result = _post_capturing(golden_container, monkeypatch, REPRESENTATIVE[name])
    trace = data["trace"]
    assert result.debug is not None
    pipeline = result.debug["pipeline"]

    assert trace["timing_ms"] == pipeline["timing_ms"]
    assert trace["input_data"]["query"] == pipeline["input"]["query"] == REPRESENTATIVE[name]
    assert trace["input_data"]["user_id"] == pipeline["input"]["user_id"] == pipeline["user_id"] == "u_alice"
    assert datetime.fromisoformat(trace["input_data"]["now"]) == datetime.fromisoformat(pipeline["input"]["now"])

    pre = trace["preprocessing"]
    assert pre["normalization"]["original"] == result.understanding.original
    assert pre["normalization"]["normalized"] == result.understanding.normalized
    assert pre["normalization"]["corrections"] == [
        {
            "source": correction.from_,
            "corrected": correction.to,
            "kind": correction.kind,
            "confidence": correction.confidence,
            "evidence": list(correction.evidence),
        }
        for correction in result.understanding.corrections
    ]
    assert pre["correction_before"] == result.understanding.raw_keywords
    assert pre["correction_after"] == result.understanding.keywords
    assert pre["morph_tokens"] == pipeline["query_terms"]["morph"]
    assert pre["ngram_tokens"] == pipeline["query_terms"]["ngram"]

    evidence = trace["evidence"]
    assert evidence["filtering"]["isolated_user_id"] == "u_alice"
    assert evidence["filtering"]["resolved_filters"] == pipeline["filters"]
    for filtering_plan, raw in zip(evidence["filtering"]["plans"], pipeline["plans"], strict=True):
        assert filtering_plan == {
            "plan_id": raw["plan_id"],
            "selected": raw["selected"],
            "allowed_relaxations": raw["allowed_query_relaxations"],
            "hard_filter": raw["hard_filter"],
            "eligible_document_count": raw["eligible_document_count"],
        }
    for plan, raw in zip(evidence["retrieval"]["plans"], pipeline["plans"], strict=True):
        assert {key: plan[key] for key in ("plan_id", "selected")} == {
            "plan_id": raw["plan_id"],
            "selected": raw["selected"],
        }
        assert [retriever["name"] for retriever in plan["retrievers"]] == list(raw["retrievers"])
        for retriever in plan["retrievers"]:
            raw_retriever = raw["retrievers"][retriever["name"]]
            assert retriever["candidate_count"] == raw_retriever["candidate_count"]
            assert [
                {key: candidate[key] for key in ("content_id", "rank", "score", "matched_fields")}
                for candidate in retriever["candidates"]
            ] == [
                {key: candidate[key] for key in ("content_id", "rank", "score", "matched_fields")}
                for candidate in raw_retriever["candidates"]
            ]
    for plan, raw in zip(evidence["fusion"]["plans"], pipeline["plans"], strict=True):
        assert {key: plan[key] for key in ("plan_id", "selected")} == {
            "plan_id": raw["plan_id"],
            "selected": raw["selected"],
        }
        assert plan["candidate_count"] == len(raw["fused_candidates"])
        assert [
            {key: candidate[key] for key in ("content_id", "rrf_score", "ranks", "raw_scores")}
            for candidate in plan["candidates"]
        ] == [
            {key: candidate[key] for key in ("content_id", "rrf_score", "ranks", "raw_scores")}
            for candidate in raw["fused_candidates"]
        ]
    assert {key: evidence["fusion"][key] for key in ("method", "k", "weights")} == pipeline["fusion"]
    assert evidence["fusion"]["k"] == golden_container.settings.search.fusion.k
    rerank_keys = ("content_id", "final_score", "selected", "features", "gate")
    assert [
        {key: candidate[key] for key in rerank_keys} for candidate in evidence["reranking"]["candidates"]
    ] == [
        {key: candidate[key] for key in rerank_keys} for candidate in pipeline["scored_candidates"]
    ]
    reranking = evidence["reranking"]
    expected_passed = sum(candidate["gate"]["accepted"] for candidate in pipeline["scored_candidates"])
    assert reranking["candidate_count"] == len(pipeline["scored_candidates"])
    assert reranking["passed_count"] == expected_passed
    assert reranking["rejected_count"] == len(pipeline["scored_candidates"]) - expected_passed
    decision = result.debug["relaxation_decision"]
    assert evidence["relaxation"]["selected_plan_id"] == decision["selected_plan_id"]
    assert evidence["relaxation"]["attempted_plans"] == decision["attempted_plans"]
    assert evidence["relaxation"]["applied_relaxations"] == result.applied_relaxations

    final = trace["analysis"]["final"]
    assert [(r["content_id"], r["score"]) for r in final["results"]] == [
        (item.content_id, item.score) for item in result.results
    ]
    assert final["results"] == data["results"]
    assert trace["analysis"]["understanding"]["value"] == data["understanding"]
    assert trace["analysis"]["understanding"]["warnings"] == result.understanding.warnings
    components = trace["model_processing"]["components"]
    for component, raw in zip(components, pipeline["components"], strict=True):
        assert {key: component[key] for key in raw} == raw
        assert component["timing_key"] == COMPONENT_TIMING_KEYS[raw["stage"]]
    cross = trace["model_processing"]["cross_reranker"]
    cross_component = next(component for component in pipeline["components"] if component["stage"] == "cross_rerank")
    assert cross["configured"] == pipeline["cross_reranker"]["configured"]
    assert cross["enabled"] == pipeline["cross_reranker"]["enabled"]
    assert cross["status"] == (pipeline["cross_reranker"]["status"] or cross_component["status"])
    assert cross["used"] is (cross["status"] == "scored")

    log = trace["execution_log"]
    assert log["degraded"] == result.degraded and log["degraded_reasons"] == result.degraded_reasons
    assert log["entries"][0] == {
        "stage": "filter_resolution",
        "status": "success",
        "timing_key": "filter_resolution",
        "timing_ms": pipeline["timing_ms"]["filter_resolution"],
        "detail": None,
    }
    for entry, component in zip(log["entries"][1:-1], components, strict=True):
        expected_status, expected_detail = _expected_log_status(component["status"])
        timing_key = component["timing_key"]
        timing_ms = (
            result.timing_ms.get("cross_rerank")
            if timing_key == "cross_rerank"
            else pipeline["timing_ms"].get(timing_key)
        )
        assert entry == {
            "stage": component["stage"],
            "status": expected_status,
            "timing_key": timing_key,
            "timing_ms": timing_ms,
            "detail": expected_detail,
        }
    assert log["errors"] == []
    assert log["entries"][-1] == {
        "stage": "finalize",
        "status": "success",
        "timing_key": "finalize",
        "timing_ms": pipeline["timing_ms"]["finalize"],
        "detail": None,
    }


def test_browse_trace_marks_skipped_stages(golden_container: AppContainer) -> None:
    trace = _post(golden_container, "유튜브 영상")["trace"]
    statuses = {entry["stage"]: entry["status"] for entry in trace["execution_log"]["entries"]}
    assert statuses["bm25f_retrieve"] == "skipped" and statuses["relaxation"] == "skipped"
    assert trace["evidence"]["relaxation"]["reason"] == "not_run:filter_only_browse"
    assert trace["evidence"]["filtering"]["plans"][0]["plan_id"] == "browse"
    assert trace["analysis"]["final"]["result_count"] > 0


def test_trace_is_isolated_per_user(golden_container: AppContainer) -> None:
    trace = _post(golden_container, "성수동 카페", user_id="u_bob")["trace"]
    assert trace["evidence"]["filtering"]["isolated_user_id"] == "u_bob"
    ids = {
        candidate["content_id"]
        for plan in trace["evidence"]["retrieval"]["plans"]
        for retriever in plan["retrievers"]
        for candidate in retriever["candidates"]
    }
    ids |= {candidate["content_id"] for candidate in trace["evidence"]["reranking"]["candidates"]}
    assert ids and all(content_id.startswith("c_bob_") for content_id in ids)


# ----------------------------------------------------------------- 무회귀
@pytest.mark.parametrize("mode", ["mock", "recorded"])
def test_explain_false_results_byte_identical_to_baseline(request: pytest.FixtureRequest, mode: str) -> None:
    """trace 기준선과 동일하다 (원문 어절 보존으로 달라진 네 질의 해시는 갱신)."""
    container: AppContainer = request.getfixturevalue(
        "golden_container" if mode == "mock" else "recorded_golden_container"
    )
    baseline = json.loads((FIXTURES / "explain_false_baseline.json").read_text(encoding="utf-8"))[mode]
    rows = golden_queries()
    assert len(rows) == len(baseline)
    mismatched = [row["id"] for row in rows if result_digest(container, row) != baseline[row["id"]]]
    assert mismatched == []


def test_explain_true_does_not_change_ranking(golden_container: AppContainer) -> None:
    for row in golden_queries()[:60]:
        req = SearchRequest(user_id=row["user_id"], query=row["query"], now=datetime.fromisoformat(row["now"]))
        try:
            plain = golden_container.search.search(req)
        except JupjupError as exc:
            # 잘못된 질의는 두 경로가 같은 오류로 실패해야 한다.
            with pytest.raises(type(exc)):
                golden_container.search.search(req.model_copy(update={"explain": True}))
            continue
        explained = golden_container.search.search(req.model_copy(update={"explain": True}))
        exclude = {"query_id", "timing_ms", "debug"}
        assert explained.model_dump(mode="json", exclude=exclude | {"results"}) == plain.model_dump(
            mode="json", exclude=exclude | {"results"}
        )
        assert [item.model_dump(mode="json", exclude={"debug"}) for item in explained.results] == [
            item.model_dump(mode="json", exclude={"debug"}) for item in plain.results
        ]


# ----------------------------------------------------------------- 대표 질의 스냅숏
def _condense(trace: dict[str, Any]) -> dict[str, Any]:
    """실행마다 바뀌는 timing 값을 빼고 화면의 핵심 값만 남긴다 (표는 상위 10개)."""
    ev = trace["evidence"]
    return {
        "input": {k: trace["input_data"][k] for k in ("query", "user_id")},
        "preprocessing": {
            "normalized": trace["preprocessing"]["normalization"]["normalized"],
            "corrections": trace["preprocessing"]["normalization"]["corrections"],
            "correction_before": trace["preprocessing"]["correction_before"],
            "correction_after": trace["preprocessing"]["correction_after"],
            "morph_tokens": trace["preprocessing"]["morph_tokens"],
            "ngram_tokens": trace["preprocessing"]["ngram_tokens"],
        },
        "components": [
            {k: c[k] for k in ("stage", "component", "model", "mode", "dimension", "status")}
            for c in trace["model_processing"]["components"]
        ],
        "understanding": trace["analysis"]["understanding"]["value"],
        "filter_plans": [
            {k: p[k] for k in ("plan_id", "selected", "allowed_relaxations", "eligible_document_count")}
            for p in ev["filtering"]["plans"]
        ],
        "retrieval": {
            p["plan_id"]: {
                r["name"]: {
                    "count": r["candidate_count"],
                    "top": [[c["content_id"], c["rank"], round(c["score"], 6)] for c in r["candidates"][:10]],
                }
                for r in p["retrievers"]
            }
            for p in ev["retrieval"]["plans"]
            if p["selected"]
        },
        "fusion_top": {
            p["plan_id"]: [[c["content_id"], round(c["rrf_score"], 6), c["ranks"]] for c in p["candidates"][:10]]
            for p in ev["fusion"]["plans"]
            if p["selected"]
        },
        "rerank": {
            "passed": ev["reranking"]["passed_count"],
            "rejected": ev["reranking"]["rejected_count"],
            "top": [
                [c["content_id"], round(c["final_score"], 6), c["selected"], c["gate"]["accepted"], c["gate"]["reason"]]
                for c in ev["reranking"]["candidates"][:10]
            ],
        },
        "relaxation": {
            "selected_plan_id": ev["relaxation"]["selected_plan_id"],
            "applied": ev["relaxation"]["applied_relaxations"],
            "reason": ev["relaxation"]["reason"],
            "attempts": [
                [a["plan_id"], a["accepted"], a["reason"], a["eligible_count"]]
                for a in ev["relaxation"]["attempted_plans"]
            ],
        },
        "cross_reranker": {
            k: trace["model_processing"]["cross_reranker"][k] for k in ("configured", "enabled", "used", "status")
        },
        "final": [
            [r["rank"], r["content_id"], r["score"], r["relaxed"], [x["type"] for x in r["reasons"]]]
            for r in trace["analysis"]["final"]["results"]
        ],
        "log": [[e["stage"], e["status"], e["timing_key"]] for e in trace["execution_log"]["entries"]],
        "degraded_reasons": trace["execution_log"]["degraded_reasons"],
    }


@pytest.mark.parametrize("name", list(REPRESENTATIVE))
def test_representative_trace_snapshot(golden_container: AppContainer, name: str) -> None:
    condensed = _condense(_post(golden_container, REPRESENTATIVE[name])["trace"])
    path = FIXTURES / f"{name}.json"
    if os.environ.get("UPDATE_TRACE_SNAPSHOTS") == "1":
        path.write_text(json.dumps(condensed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert condensed == json.loads(path.read_text(encoding="utf-8"))


def test_representative_traces_show_expected_pipeline_behaviour(golden_container: AppContainer) -> None:
    period = _post(golden_container, REPRESENTATIVE["period_platform"])["trace"]
    understanding = period["analysis"]["understanding"]["value"]
    assert understanding["time_range"]["expression"] == "지난달"
    assert understanding["platforms"][0]["value"] == "instagram"
    assert understanding["platforms"][0]["strength"] == "hard"
    strict = period["evidence"]["filtering"]["plans"][0]
    assert strict["plan_id"] == "strict" and strict["selected"]
    assert strict["hard_filter"]["platforms"] == ["instagram"]

    typo = _post(golden_container, REPRESENTATIVE["typo"])["trace"]
    corrections = typo["preprocessing"]["normalization"]["corrections"]
    assert [(c["source"], c["corrected"], c["kind"]) for c in corrections] == [("파스티", "파스타", "spelling")]
    assert "파스타" in typo["preprocessing"]["morph_tokens"]

    relaxed = _post(golden_container, REPRESENTATIVE["empty_then_relaxed"])["trace"]
    attempts = {a["plan_id"]: a for a in relaxed["evidence"]["relaxation"]["attempted_plans"]}
    assert attempts["strict"]["accepted"] is False and attempts["strict"]["top_id"] is None
    assert relaxed["evidence"]["relaxation"]["applied_relaxations"] == ["time_filter_dropped"]
    assert relaxed["evidence"]["relaxation"]["reason"] == "accepted"
    assert all(r["relaxed"] for r in relaxed["analysis"]["final"]["results"])
