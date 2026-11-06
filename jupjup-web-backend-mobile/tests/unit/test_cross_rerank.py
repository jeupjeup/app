"""크로스 인코더 리랭커: 창, 실행기, 녹화·재생, 게이트 v3, v2 폴백 (설계 7절 INV-R1~R9)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jupjup import container as container_module
from jupjup.config import (
    CrossCalibrationSettings,
    CrossRelevanceSettings,
    RerankModelSettings,
    SearchSettings,
    Settings,
)
from jupjup.domain.errors import RerankCacheMiss, RerankerError, RerankerUnavailable
from jupjup.eval.ab import (
    EXPECTED_FIXED_REGRESSION_COUNT,
    ABComparison,
    DeltaCI,
    FixedRegressionResult,
    LatencyReport,
    _fixed_regression_results,
    decide_reranker,
    reranker_test_confirmed,
)
from jupjup.index.document import IndexDocument
from jupjup.providers.rerank import MockReranker, RecordedReranker, RecordingReranker
from jupjup.providers.rerank_bge import BgeCrossEncoderReranker
from jupjup.search.cross_rerank import (
    CrossRerankStage,
    RerankWindow,
    SingleFlightExecutor,
    build_rerank_query,
    build_rerank_text,
    calibrate_cross,
)
from jupjup.search.filters import SearchFilters
from jupjup.search.gate import RelevanceGate
from jupjup.search.service import SearchRequest
from jupjup.search.types import CandidateEvidence
from jupjup.storage.seed import load_seed_file
from tests.conftest import DATA, KST, NOW, ROOT, make_container

ENABLED = RerankModelSettings(enabled=True)
# 설계 4.6절 시작값. 게이트 규칙 자체를 검사하려고 튜닝 전 floor를 명시한다.
START = CrossRelevanceSettings(
    version="relevance-v3-cross.1",
    beta_semantic=0.55,
    beta_cross=1.80,
    calibration=CrossCalibrationSettings(),
    lexical_only_threshold=0.44,
    cross_floor_semantic=0.50,
    cross_floor_low_signal=0.60,
    cross_signal_floor=0.50,
    semantic_floor=0.45,
)


def _doc(**fields: str) -> IndexDocument:
    return IndexDocument(
        content_id="c1",
        user_id="u_a",
        platform="youtube",
        content_type="video",
        saved_at=datetime(2026, 9, 1, tzinfo=KST),
        original_status="available",
        fields={  # type: ignore[arg-type]
            "title": "", "tags_user": "", "tags_ai": "", "detail": "", "summary": "",
            "user_note": "", "body": "", "ocr": "", "author": "",
            **fields,
        },
        detail_core=fields.get("detail", ""),
        tags_display=["카페", "디저트"],
    )


def _evidence(**update: Any) -> CandidateEvidence:
    base: dict[str, Any] = {
        "content_id": "c1",
        "relevance": 0.6,
        "relevance_base": 0.6,
        "semantic": 0.7,
        "semantic_raw": 0.7,
        "original_lexical": 0.0,
        "canonical_lexical": 0.0,
        "phrase": 0.0,
        "purpose": 0.0,
        "corroboration": 0.0,
        "facet_cost": 0.0,
        "correction_contribution": 0.0,
        "signals": ("semantic", "cross"),
        "evidence_profile": "semantic-only",
        "model_id": "hashing-v1",
        "calibration_version": "x",
        "relevance_version": "relevance-v3-cross.1",
        "cross": 0.7,
        "rerank_scored": True,
        "relevance_profile": "v3-cross",
    }
    base.update(update)
    return CandidateEvidence.model_validate(base)


@pytest.fixture(scope="module")
def parse() -> Any:
    container = make_container()
    return lambda text: container.understander.parse(text, NOW)


# ------------------------------------------------------------------ INV-R4 텍스트 구성
def test_rerank_query_has_no_facet_spans(parse: Any) -> None:
    query = build_rerank_query(parse("지난달 인스타에서 본 성수동 카페 영상"))
    assert query is not None
    for facet in ("지난달", "인스타", "영상"):
        assert facet not in query
    assert "성수동" in query and "카페" in query
    reparsed = parse(query)
    assert reparsed.platforms == [] and reparsed.content_types == [] and reparsed.time_range is None


def test_rerank_text_excludes_platform_type_time_and_author() -> None:
    text = build_rerank_text(
        _doc(title="어니언 성수", summary="빵이 맛있다", author="작성자이름", ocr="OCR글자", body="본문"),
        max_chars=600,
    )
    assert "어니언 성수" in text.text and "빵이 맛있다" in text.text and "카페" in text.text
    for excluded in ("youtube", "video", "2026", "작성자이름", "OCR글자"):
        assert excluded not in text.text
    assert len(build_rerank_text(_doc(body="가" * 2000), max_chars=600).text) == 600
    assert text.text_hash == build_rerank_text(_doc(title="어니언 성수", summary="빵이 맛있다",
                                                    author="다른사람", body="본문"), 600).text_hash


# ------------------------------------------------------------------ 창 선택 (INV-R3)
def test_window_unions_global_and_plan_members_with_truncation() -> None:
    settings = RerankModelSettings(enabled=True, n_global=2, k_plan=1, n_max=3, pre_threshold=0.2)
    stage = CrossRerankStage(MockReranker(), settings, CrossCalibrationSettings())
    base = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.1, "e": 0.05}
    window = stage.select_window(base, {"strict": ["d"], "wide": ["e", "a"]})
    # 전역 상위 2개(a, b) + strict의 d + wide의 a(중복) → R_base 순
    assert window.content_ids == ["a", "b", "d"]
    assert window.reasons == {"a": "global", "b": "global", "d": "plan:strict"}
    assert not window.truncated
    narrow = CrossRerankStage(MockReranker(), settings.model_copy(update={"n_max": 2}), CrossCalibrationSettings())
    truncated = narrow.select_window(base, {"strict": ["d"], "wide": ["e"]})
    assert truncated.truncated and truncated.content_ids == ["a", "b"]


def test_window_ignores_limit(golden: Any) -> None:
    container = golden(cross_rerank={"enabled": True})
    windows = []
    for limit in (1, 2, 10, 50):
        result = container.search.search(
            SearchRequest(user_id="u_alice", query="성수동 카페", limit=limit, now=NOW, explain=True)
        )
        assert result.debug is not None
        windows.append(result.debug["rerank"]["window"])
    assert all(window == windows[0] for window in windows)


# ------------------------------------------------------------------ 실행기와 단계
def test_single_flight_reports_busy_and_timeout() -> None:
    executor = SingleFlightExecutor()
    gate = threading.Event()

    def slow() -> list[float]:
        gate.wait(2)
        return [1.0]

    assert executor.run(slow, 0.01) == ("timeout", None)
    assert executor.run(lambda: [1.0], 0.5) == ("busy", None)
    gate.set()
    for _ in range(100):
        status, value = executor.run(lambda: [2.0], 0.5)
        if status == "ok":
            break
        time.sleep(0.01)  # 끝난 추론의 완료 콜백이 busy를 풀 때까지
    assert (status, value) == ("ok", [2.0])


def test_stage_skip_reasons(parse: Any) -> None:
    parsed = parse("성수동 카페")
    window = RerankWindow(content_ids=["c1"])
    docs = {"c1": _doc(title="성수동 카페")}
    calibration = CrossCalibrationSettings()
    assert CrossRerankStage(None, ENABLED, calibration).score(parsed, window, docs).skip_reason == "disabled"
    off = RerankModelSettings(enabled=False)
    assert CrossRerankStage(MockReranker(), off, calibration).score(parsed, window, docs).skip_reason == "disabled"
    cpu_off = RerankModelSettings(enabled=True, enabled_on_cpu=False)
    outcome = CrossRerankStage(MockReranker(), cpu_off, calibration, device="cpu").score(parsed, window, docs)
    assert outcome.skip_reason == "cpu_disabled"
    preflight_cpu_off = CrossRerankStage(None, cpu_off, calibration, device="cpu_disabled").score(parsed, window, docs)
    assert preflight_cpu_off.skip_reason == "cpu_disabled"
    failing = MockReranker(fail_on={build_rerank_query(parsed) or ""})
    assert CrossRerankStage(failing, ENABLED, calibration).score(parsed, window, docs).skip_reason == "error"
    slow = RerankModelSettings(enabled=True, timeout_ms=5)
    outcome = CrossRerankStage(MockReranker(delay_ms=200), slow, calibration).score(parsed, window, docs)
    assert outcome.skip_reason == "timeout"
    scored = CrossRerankStage(MockReranker(), ENABLED, calibration).score(parsed, window, docs)
    assert scored.status == "scored" and 0.0 <= scored.scores["c1"] <= 1.0 and "c1" in scored.logits


def test_calibration_is_monotonic_piecewise_linear() -> None:
    settings = CrossCalibrationSettings(points=((0.0, 0.0), (0.5, 0.2), (1.0, 1.0)))
    assert calibrate_cross(0.25, settings) == pytest.approx(0.1)
    assert calibrate_cross(0.75, settings) == pytest.approx(0.6)
    values = [calibrate_cross(x / 20, settings) for x in range(21)]
    assert values == sorted(values)
    with pytest.raises(ValidationError):
        CrossCalibrationSettings(points=((0.0, 0.5), (1.0, 0.2)))


# ------------------------------------------------------------------ 녹화와 재생 (INV-R8)
def test_recording_has_no_raw_text_and_replay_misses_raise(tmp_path: Path) -> None:
    store = tmp_path / "rerank.jsonl"
    recorder = RecordingReranker(MockReranker(), store, max_length=384)
    live = recorder.score_logits("성수동 카페", ["성수동 카페 어니언", "기후 논문"])
    recorder.score_logits("성수동 카페", ["성수동 카페 어니언"])  # 중복 쌍은 다시 쓰지 않는다
    raw = store.read_text(encoding="utf-8")
    assert "성수동" not in raw and "어니언" not in raw
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 2
    assert set(rows[0]) == {
        "model_id",
        "revision",
        "pair_hash",
        "query_hash",
        "doc_hash",
        "max_length",
        "device",
        "dtype",
        "logit",
    }
    assert rows[0]["device"] == rows[0]["dtype"] == "unknown"

    replay = RecordedReranker(store, MockReranker.model_id, MockReranker.revision, 384)
    assert replay.score_logits("성수동 카페", ["성수동 카페 어니언", "기후 논문"]) == live
    with pytest.raises(RerankCacheMiss):
        replay.score_logits("성수동 카페", ["녹화 안 된 문서"])
    with pytest.raises(RerankCacheMiss):  # max_length가 바뀌면 키가 바뀐다
        RecordedReranker(store, MockReranker.model_id, MockReranker.revision, 256).score_logits(
            "성수동 카페", ["기후 논문"]
        )


def test_recorded_miss_is_not_swallowed_by_stage(tmp_path: Path, parse: Any) -> None:
    store = tmp_path / "empty.jsonl"
    store.write_text("", encoding="utf-8")
    stage = CrossRerankStage(RecordedReranker(store, "m", "r", 384), ENABLED, CrossCalibrationSettings())
    with pytest.raises(RerankCacheMiss):
        stage.score(parse("성수동 카페"), RerankWindow(content_ids=["c1"]), {"c1": _doc(title="카페")})


def test_recorded_replay_bypasses_wall_clock_executor(tmp_path: Path, parse: Any) -> None:
    store = tmp_path / "rerank.jsonl"
    query = build_rerank_query(parse("성수동 카페"))
    document = _doc(title="성수동 카페")
    assert query is not None
    text = build_rerank_text(document, ENABLED.max_doc_chars).text
    RecordingReranker(MockReranker(), store, ENABLED.max_length).score_logits(query, [text])
    replay = RecordedReranker(store, MockReranker.model_id, MockReranker.revision, ENABLED.max_length)

    class FailingExecutor:
        def run(self, *_: Any) -> Any:
            raise AssertionError("recorded replay must not use the wall-clock executor")

    stage = CrossRerankStage(replay, ENABLED, CrossCalibrationSettings(), executor=FailingExecutor())  # type: ignore[arg-type]
    outcome = stage.score(parse("성수동 카페"), RerankWindow(content_ids=["c1"]), {"c1": document})
    assert outcome.status == "scored"


# ------------------------------------------------------------------ 제공자
def test_bge_requires_revision_and_validates_output() -> None:
    with pytest.raises(RerankerUnavailable):
        BgeCrossEncoderReranker(RerankModelSettings(revision=""))

    class FakeModel:
        def __init__(self, output: Any) -> None:
            self.output = output

        def predict(self, sentences: list[list[str]], **kwargs: Any) -> Any:
            return self.output

    ok = BgeCrossEncoderReranker(RerankModelSettings(device="cpu"), model_factory=lambda *_: FakeModel([0.5, -1.0]))
    assert ok.score_logits("q", ["a", "b"]) == [0.5, -1.0]
    assert ok.score_logits("q", []) == []
    bad = BgeCrossEncoderReranker(RerankModelSettings(device="cpu"), model_factory=lambda *_: FakeModel([0.5]))
    with pytest.raises(Exception, match="출력"):
        bad.score_logits("q", ["a", "b"])


def test_default_install_never_imports_torch_for_mock_or_recorded() -> None:
    code = (
        "import sys\n"
        "from jupjup.config import Settings, SearchSettings\n"
        "from jupjup.container import build_container\n"
        "from jupjup.storage.db import create_db_engine\n"
        "for mode in ('mock', 'recorded'):\n"
        "    s = Settings(env='test', mode=mode, db_path=':memory:')\n"
        "    build_container(s, engine=create_db_engine(None))\n"
        "s = Settings(env='test', mode='mock', db_path=':memory:',\n"
        "             search=SearchSettings.model_validate({'cross_rerank': {'enabled': True}}))\n"
        "build_container(s, engine=create_db_engine(None))\n"
        "bad = [m for m in ('torch', 'sentence_transformers') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)


def test_live_cpu_disabled_skips_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        env="test",
        mode="live",
        search=SearchSettings(cross_rerank=RerankModelSettings(enabled=True, enabled_on_cpu=False)),
    )
    monkeypatch.setattr(container_module, "_rerank_extra_available", lambda: True)
    monkeypatch.setattr(container_module, "select_device", lambda _: "cpu")
    monkeypatch.setattr(
        container_module,
        "BgeCrossEncoderReranker",
        lambda *_: pytest.fail("cpu-disabled policy must run before model construction"),
    )
    assert container_module._model_reranker(settings) == (None, "cpu_disabled")


def test_live_warmup_error_falls_back_unless_required(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingProvider:
        device = "mps"

        def warm_up(self) -> None:
            raise RerankerError("warm-up failed")

    monkeypatch.setattr(container_module, "_rerank_extra_available", lambda: True)
    monkeypatch.setattr(container_module, "select_device", lambda _: "mps")
    monkeypatch.setattr(container_module, "BgeCrossEncoderReranker", lambda *_: FailingProvider())
    optional = Settings(
        env="test",
        mode="live",
        search=SearchSettings(cross_rerank=RerankModelSettings(enabled=True, required=False)),
    )
    with pytest.warns(RuntimeWarning, match="v2"):
        assert container_module._model_reranker(optional) == (None, "unavailable")
    required = optional.model_copy(
        update={
            "search": optional.search.model_copy(
                update={"cross_rerank": optional.search.cross_rerank.model_copy(update={"required": True})}
            )
        }
    )
    with pytest.raises(RerankerError, match="warm-up"):
        container_module._model_reranker(required)


def test_live_missing_extra_is_explicit_even_when_cpu_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_module, "_rerank_extra_available", lambda: False)
    optional = Settings(
        env="test",
        mode="live",
        search=SearchSettings(cross_rerank=RerankModelSettings(enabled=True, required=False, enabled_on_cpu=False)),
    )
    with pytest.warns(RuntimeWarning, match="extra"):
        assert container_module._model_reranker(optional) == (None, "unavailable")
    required = optional.model_copy(
        update={
            "search": optional.search.model_copy(
                update={"cross_rerank": optional.search.cross_rerank.model_copy(update={"required": True})}
            )
        }
    )
    with pytest.raises(RerankerUnavailable, match="extra"):
        container_module._model_reranker(required)


# ------------------------------------------------------------------ 설정 (INV-R6)
def test_v3_profile_thresholds_must_be_reachable() -> None:
    CrossRelevanceSettings()
    assert CrossRelevanceSettings().calibration.version.startswith("bge-reranker")
    with pytest.raises(ValidationError, match="lexical-only"):  # T35 탐색 중 실제로 걸린 조합
        CrossRelevanceSettings(beta_cross=0.15)
    with pytest.raises(ValidationError, match="semantic-only"):
        CrossRelevanceSettings(semantic_only_threshold=0.80)
    with pytest.raises(ValidationError, match="원형"):
        CrossRelevanceSettings(beta_original=0.5, beta_canonical=0.6)
    with pytest.raises(ValidationError):
        RerankModelSettings(n_global=40, n_max=32)


# ------------------------------------------------------------------ 게이트 v3 (INV-R9)
def test_gate_v3_uses_cross_floor_per_profile(parse: Any) -> None:
    gate = RelevanceGate(SearchSettings().gate, v3_settings=START)
    normal = parse("성수동 카페")
    assert gate.evaluate(normal, _evidence(cross=0.7)).accepted
    assert gate.evaluate(normal, _evidence(cross=0.4)).reason == "cross_floor"
    assert gate.evaluate(normal, _evidence(cross=0.7, semantic=0.3)).reason == "semantic_aux_floor"
    lexical = _evidence(
        signals=("lexical",), evidence_profile="lexical-only", semantic=0.1, original_lexical=1.0, cross=0.1
    )
    assert gate.evaluate(normal, lexical).reason == "cross_floor"
    assert gate.evaluate(normal, lexical.model_copy(update={"cross": 0.3})).accepted
    corroborated = _evidence(signals=("semantic", "lexical"), evidence_profile="corroborated", cross=0.04)
    assert gate.evaluate(normal, corroborated).reason == "cross_floor"
    low = parse("그거")
    assert low.query_signal_profile == "low-signal"
    assert gate.evaluate(low, _evidence(cross=0.55)).reason == "cross_floor"
    assert gate.evaluate(low, _evidence(cross=0.65)).accepted


def test_gate_v3_unscored_tail_requires_corroboration(parse: Any) -> None:
    gate = RelevanceGate(SearchSettings().gate, v3_settings=START)
    parsed = parse("성수동 카페")
    unscored = _evidence(cross=None, rerank_scored=False, signals=("semantic", "lexical"), relevance=0.6,
                         evidence_profile="corroborated")
    decision = gate.evaluate(parsed, unscored)
    assert decision.accepted and decision.reason == "accepted_unscored_tail"
    assert not gate.evaluate(parsed, unscored.model_copy(update={"relevance": 0.49})).accepted
    single = unscored.model_copy(update={"evidence_profile": "semantic-only", "signals": ("semantic",)})
    assert gate.evaluate(parsed, single).reason == "rerank_unscored"


def test_apply_cross_semantic_and_cross_alone_do_not_corroborate() -> None:
    container = make_container(search=SearchSettings(relevance_v3=START))
    scorer = container.search.relevance_scorer
    v2 = _evidence(relevance_profile="v2", cross=None, rerank_scored=False, signals=("semantic",),
                   relevance_version="relevance-v2")
    high = scorer.apply_cross(v2, 0.9, 2.2)
    assert high.evidence_profile == "semantic-only" and high.signals == ("semantic", "cross")
    assert high.relevance_profile == "v3-cross" and high.relevance_base == v2.relevance_base
    lexical = v2.model_copy(update={"signals": ("lexical",), "semantic": 0.1, "original_lexical": 1.0})
    assert scorer.apply_cross(lexical, 0.3).evidence_profile == "lexical-only"  # cross floor 미만은 신호 아님
    assert scorer.apply_cross(lexical, 0.8).evidence_profile == "corroborated"
    assert scorer.apply_cross(lexical, 0.8).relevance > scorer.apply_cross(lexical, 0.3).relevance


# ------------------------------------------------------------------ 서비스 통합 (INV-R1, R5, R7, R9)
@pytest.fixture(scope="module")
def golden() -> Any:
    cache: dict[str, Any] = {}

    def build(**overrides: Any) -> Any:
        key = json.dumps(overrides, sort_keys=True)
        if key not in cache:
            container = make_container(search=SearchSettings.model_validate(overrides))
            report = load_seed_file(DATA / "golden" / "seeds.jsonl", container.repo, container.indexer, strict=True)
            assert report.errors == []
            cache[key] = container
        return cache[key]

    return build


QUERIES = ("성수동 카페", "지난달 인스타 카페", "기후 위기 논문", "그거", "북극곰 다큐", "다리 운동 영상")


def _strip(result: Any) -> list[tuple[str, int]]:
    return [(item.content_id, item.rank) for item in result.results]


@pytest.mark.parametrize("query", QUERIES)
def test_scored_responses_use_one_scale(golden: Any, query: str) -> None:
    container = golden(cross_rerank={"enabled": True})
    result = container.search.search(SearchRequest(user_id="u_alice", query=query, limit=50, now=NOW, explain=True))
    assert result.rerank_status in {"scored", "skipped:empty_query"}
    profiles = {item.debug["evidence"]["relevance_profile"] for item in result.results if item.debug}
    assert len(profiles) <= 1
    if result.rerank_status == "scored" and result.results:
        assert profiles == {"v3-cross"}
        scored = [item.debug["evidence"]["rerank_scored"] for item in result.results if item.debug]
        assert scored == sorted(scored, reverse=True)  # 창 밖 문서는 창 안 문서 뒤 (INV-R9)


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize("fault", ["timeout", "error"])
def test_skipped_rerank_equals_v2(golden: Any, query: str, fault: str) -> None:
    v2 = golden()
    request = SearchRequest(user_id="u_alice", query=query, limit=50, now=NOW)
    expected = v2.search.search(request)
    faulty = golden(cross_rerank={"enabled": True, "timeout_ms": 1})
    stage = faulty.search.cross_stage
    assert stage is not None
    original = stage.reranker
    rerank_query = build_rerank_query(faulty.understander.parse(query, NOW)) or ""
    stage.reranker = MockReranker(delay_ms=50) if fault == "timeout" else MockReranker(fail_on={rerank_query})
    try:
        actual = faulty.search.search(request)
    finally:
        stage.reranker = original
        stage.executor = SingleFlightExecutor()
    assert _strip(actual) == _strip(expected)
    assert actual.applied_relaxations == expected.applied_relaxations
    if actual.rerank_status != "skipped:empty_query":
        assert actual.rerank_status == f"skipped:{fault}"
        assert f"reranker_skipped:{fault}" in actual.degraded_reasons


def test_cross_and_relevance_are_computed_once_per_request(golden: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-R1: 리랭크는 합집합 위에서 요청당 한 번 돌고, 모든 계획이 같은 evidence를 쓴다."""
    container = golden(cross_rerank={"enabled": True})
    scorer = container.search.relevance_scorer
    calls: list[str] = []
    original = scorer.apply_cross

    def counting(evidence: CandidateEvidence, *args: Any) -> CandidateEvidence:
        calls.append(evidence.content_id)
        return original(evidence, *args)

    monkeypatch.setattr(scorer, "apply_cross", counting)
    stage = container.search.cross_stage
    assert stage is not None
    score_calls: list[int] = []
    original_score = stage.score
    monkeypatch.setattr(stage, "score", lambda *a: score_calls.append(1) or original_score(*a))
    result = container.search.search(
        SearchRequest(user_id="u_alice", query="지난달 인스타에서 본 카페 영상", limit=50, now=NOW)
    )
    assert result.rerank_status == "scored"
    assert len(score_calls) == 1
    assert len(calls) == len(set(calls)) > 0


def _rerank_evidence(result: Any) -> dict[str, tuple[float, float]]:
    return {
        item.content_id: (item.debug["evidence"]["cross"], item.debug["evidence"]["relevance"])
        for item in result.results
        if item.debug and item.debug["evidence"]["rerank_scored"]
    }


def test_cross_and_relevance_ignore_now_for_documents_scored_twice(golden: Any) -> None:
    container = golden(cross_rerank={"enabled": True})
    first = container.search.search(
        SearchRequest(user_id="u_alice", query="지난주 카톡으로 받은 회의 장소", limit=50, now=NOW, explain=True)
    )
    second = container.search.search(
        SearchRequest(
            user_id="u_alice",
            query="지난주 카톡으로 받은 회의 장소",
            limit=50,
            now=NOW + timedelta(days=7),
            explain=True,
        )
    )
    left, right = _rerank_evidence(first), _rerank_evidence(second)
    common = left.keys() & right.keys()
    assert common
    assert all(left[content_id] == pytest.approx(right[content_id], abs=1e-6) for content_id in common)


def test_cross_and_relevance_ignore_request_locks_for_documents_scored_twice(golden: Any) -> None:
    container = golden(cross_rerank={"enabled": True})
    unlocked = container.search.search(
        SearchRequest(user_id="u_alice", query="성수동 카페", limit=50, now=NOW, explain=True)
    )
    locked = container.search.search(
        SearchRequest(
            user_id="u_alice",
            query="성수동 카페",
            filters=SearchFilters(platforms=["instagram"]),
            limit=50,
            now=NOW,
            explain=True,
        )
    )
    left, right = _rerank_evidence(unlocked), _rerank_evidence(locked)
    common = left.keys() & right.keys()
    assert common
    assert all(left[content_id] == pytest.approx(right[content_id], abs=1e-6) for content_id in common)


@pytest.mark.parametrize("reason", ["cpu_disabled", "empty_query"])
def test_policy_rerank_skips_are_not_degraded(golden: Any, reason: str, monkeypatch: pytest.MonkeyPatch) -> None:
    container = golden(cross_rerank={"enabled": True})
    stage = container.search.cross_stage
    assert stage is not None
    if reason == "cpu_disabled":
        monkeypatch.setattr(stage, "device", "cpu")
        monkeypatch.setattr(stage.settings, "enabled_on_cpu", False)
    else:
        monkeypatch.setattr("jupjup.search.cross_rerank.build_rerank_query", lambda _: None)
    result = container.search.search(SearchRequest(user_id="u_alice", query="성수동 카페", now=NOW))
    assert result.rerank_status == f"skipped:{reason}"
    assert not result.degraded
    assert f"reranker_skipped:{reason}" not in result.degraded_reasons


def test_disabled_rerank_leaves_responses_unchanged(golden: Any) -> None:
    v2 = golden()
    off = golden(cross_rerank={"enabled": False})
    for query in QUERIES:
        request = SearchRequest(user_id="u_alice", query=query, limit=50, now=NOW)
        left, right = v2.search.search(request), off.search.search(request)
        assert _strip(left) == _strip(right) and right.rerank_status is None


# ------------------------------------------------------------------ 채택 판정 (10.1절)
def _delta(metric: str, delta: float, ci_low: float) -> DeltaCI:
    return DeltaCI(metric=metric, delta=delta, ci_low=ci_low, ci_high=delta, wins=0, losses=0, ties=0,
                   sign_test_p=1.0)


def _comparison(**changes: tuple[float, float]) -> ABComparison:
    values = {"recall@10": (0.0, 0.0), "mrr@10": (0.0, 0.0), "ndcg@10": (0.0, 0.0), "success@1": (0.0, 0.0),
              "true_empty": (0.0, 0.0), "false_empty": (0.0, 0.0), **changes}
    return ABComparison(
        baseline="A0",
        candidate="A1",
        deltas=[_delta(metric.replace("_at_", "@"), *value) for metric, value in values.items()],
        candidate_gate_passed=True,
        candidate_absolute={
            "challenge_positive_recall@10": 0.95,
            "challenge_negative_true_empty": 1.0,
            "isolation_violations": 0.0,
            "filter_violations": 0.0,
        },
        candidate_denominators={"challenge_positive": 1, "challenge_negative": 1},
        category_deltas={"semantic": 0.0},
        fixed_regressions=[
            FixedRegressionResult(
                query_id="q_0167",
                query="다리 운동 영상",
                expected_top="c_alice_0040",
                actual_top="c_alice_0040",
                expected_relaxations=(),
                actual_relaxations=(),
                passed=True,
            )
        ],
    )


def _latency(**update: Any) -> LatencyReport:
    values: dict[str, Any] = {
        "device": "mps", "repeat": 3, "queries": 10, "rerank_p50_ms": 50, "rerank_p95_ms": 100,
        "rerank_max_ms": 120, "search_p50_ms": 100, "search_p95_ms": 200, "search_max_ms": 250,
        "rerank_budget_ms": 150, "search_budget_ms": 300, "skip_rate": 0.0, "rss_increase_mb": 900,
    }
    values.update(update)
    return LatencyReport.model_validate(values)


def test_decide_reranker_boundaries() -> None:
    adopt = decide_reranker(_comparison(**{"ndcg@10": (0.02, 0.001)}), _latency(), test_confirmed=True)
    assert adopt.verdict == "ADOPT", adopt.rules
    # 하락 허용치 경계: 정확히 −0.01은 통과, 그 아래는 실패
    edge = decide_reranker(
        _comparison(**{"ndcg@10": (0.03, 0.01), "mrr@10": (-0.01, -0.01)}),
        _latency(),
        test_confirmed=True,
    )
    assert edge.verdict == "ADOPT", edge.rules
    below = decide_reranker(_comparison(**{"ndcg@10": (0.03, 0.01), "mrr@10": (-0.01, -0.0101)}), _latency())
    assert below.verdict == "REJECT"
    no_gain = decide_reranker(_comparison(**{"ndcg@10": (0.02, 0.0)}), _latency())
    assert no_gain.verdict == "REJECT"
    seesaw = decide_reranker(_comparison(**{"true_empty": (0.1, 0.02)}), _latency(), test_confirmed=True)
    assert seesaw.verdict == "ADOPT"
    slow = decide_reranker(_comparison(**{"ndcg@10": (0.02, 0.001)}), _latency(rerank_p95_ms=151))
    assert slow.verdict == "REJECT"
    cpu_limited = decide_reranker(
        _comparison(**{"ndcg@10": (0.02, 0.001)}), _latency(cpu_enabled=False), test_confirmed=True
    )
    assert cpu_limited.verdict == "ADOPT_WITH_LIMITS"
    assert decide_reranker(_comparison(**{"ndcg@10": (0.02, 0.001)}), None).verdict == "REJECT"


def test_decide_reranker_fails_closed_for_missing_inputs() -> None:
    comparison = _comparison(**{"ndcg@10": (0.02, 0.001)})
    assert decide_reranker(comparison, _latency()).verdict == "REJECT"  # test confirmation absent
    comparison.candidate_absolute.pop("challenge_positive_recall@10")
    decision = decide_reranker(comparison, _latency(), test_confirmed=True)
    assert decision.verdict == "REJECT"
    assert next(rule for rule in decision.rules if rule.name == "1_absolute").passed is False
    comparison = _comparison(**{"ndcg@10": (0.02, 0.001)})
    comparison.deltas = [delta for delta in comparison.deltas if delta.metric != "false_empty"]
    assert decide_reranker(comparison, _latency(), test_confirmed=True).verdict == "REJECT"


def test_decide_reranker_reports_fixed_regression_failure() -> None:
    comparison = _comparison(**{"ndcg@10": (0.02, 0.001)})
    comparison.fixed_regressions[0].actual_top = "c_alice_0051"
    comparison.fixed_regressions[0].passed = False
    decision = decide_reranker(comparison, _latency(), test_confirmed=True)
    absolute = next(rule for rule in decision.rules if rule.name == "1_absolute")
    assert decision.verdict == "REJECT"
    assert not absolute.passed and "다리 운동 영상" in absolute.detail


def test_fixed_regressions_never_silently_skip_missing_cases() -> None:
    checks = _fixed_regression_results({}, {})
    assert len(checks) == EXPECTED_FIXED_REGRESSION_COUNT
    assert not any(check.passed for check in checks)


def test_zero_challenge_negative_denominator_is_explicitly_not_applicable() -> None:
    comparison = _comparison(**{"ndcg@10": (0.02, 0.001)})
    comparison.candidate_absolute.pop("challenge_negative_true_empty")
    comparison.candidate_denominators["challenge_negative"] = 0
    decision = decide_reranker(comparison, _latency(), test_confirmed=True)
    absolute = next(rule for rule in decision.rules if rule.name == "1_absolute")
    assert absolute.passed
    assert "challenge_negative_true_empty=n/a (denominator=0)" in absolute.detail


def test_test_confirmation_recomputes_rules_one_through_four() -> None:
    passing = _comparison(**{"ndcg@10": (0.02, 0.001)})
    assert reranker_test_confirmed(passing)
    passing.candidate_gate_passed = False
    assert not reranker_test_confirmed(passing)


def test_missing_rss_measurement_fails_operations_rule() -> None:
    decision = decide_reranker(
        _comparison(**{"ndcg@10": (0.02, 0.001)}),
        _latency(rss_increase_mb=None),
        test_confirmed=True,
    )
    operations = next(rule for rule in decision.rules if rule.name == "6_operations")
    assert not operations.passed
