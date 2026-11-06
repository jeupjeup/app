"""완화 정책 v2 불변식 INV-01~INV-16."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from jupjup.config import GateSettings, SearchSettings
from jupjup.container import AppContainer
from jupjup.query.temporal import SEOUL
from jupjup.search.filters import FilterResolver, SearchFilters
from jupjup.search.gate import RelevanceGate
from jupjup.search.service import SearchRequest
from jupjup.search.types import CandidateEvidence, EvidenceSignal, RelaxationName
from tests.conftest import NOW


def _evidence(
    content_id: str,
    relevance: float,
    *,
    cost: float = 0.0,
    semantic: float = 0.7,
    original: float = 0.5,
    canonical: float = 0.0,
    correction: float = 0.0,
    profile: str = "corroborated",
    violations: tuple[RelaxationName, ...] = (),
    signals: tuple[EvidenceSignal, ...] | None = None,
) -> CandidateEvidence:
    default_signals: dict[str, tuple[EvidenceSignal, ...]] = {
        "corroborated": ("semantic", "lexical"),
        "semantic-only": ("semantic",),
        "lexical-only": ("canonical",) if original == 0.0 and canonical > 0.0 else ("lexical",),
    }
    return CandidateEvidence(
        content_id=content_id,
        relevance=relevance,
        semantic=semantic,
        semantic_raw=semantic,
        original_lexical=original,
        canonical_lexical=canonical,
        phrase=0.0,
        purpose=0.0,
        corroboration=1.0 if profile == "corroborated" else 0.0,
        signals=default_signals[profile] if signals is None else signals,
        evidence_profile=profile,  # type: ignore[arg-type]
        query_facet_violations=violations,
        facet_cost=cost,
        correction_contribution=correction,
        model_id="hashing-v1",
        calibration_version="test",
        relevance_version="test",
    )


def test_inv01_request_locks_are_in_every_plan_and_final_results(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("지난달 인스타 카페", NOW)
    requested = SearchFilters(
        platforms=["youtube"],
        content_types=["video"],
        saved_from=datetime(2020, 1, 1, tzinfo=SEOUL),
        saved_to=datetime(2027, 1, 1, tzinfo=SEOUL),
    )
    resolved = FilterResolver().resolve(parsed, requested)
    policy = golden_container.search.relaxation
    assert policy is not None
    plans = policy.plans(resolved, parsed)
    for plan in plans:
        hard = plan.filters.to_hard_filter(golden_container.lexicon)
        assert hard.platforms == {"youtube"}
        assert hard.content_types == {"video", "short_video"}
        assert hard.saved_from == requested.saved_from and hard.saved_to == requested.saved_to

    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="카페", filters=requested, now=NOW, limit=50)
    )
    assert all(
        item.platform == "youtube" and item.content_type in {"video", "short_video"}
        for item in result.results
    )


def test_inv02_inv14_relevance_is_context_independent(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("성수동 카페", NOW)
    resolved = FilterResolver().resolve(parsed, None)
    scorer = golden_container.search.relevance_scorer
    index = golden_container.registry.get("u_alice")
    first = scorer.score(parsed, "c_alice_0001", index, 0.61, resolved)
    second = scorer.score(parsed, "c_alice_0001", index, 0.61, resolved.model_copy(deep=True))
    assert first.relevance == pytest.approx(second.relevance, abs=1e-6)
    assert first.model_dump() == second.model_dump()


def test_inv03_to_inv06_single_adoption_boundary(golden_container: AppContainer) -> None:
    service = golden_container.search
    incumbent = _evidence("same", 0.70)
    assert not service.should_adopt(incumbent, _evidence("same", 1.0), 0.0)
    assert not service.should_adopt(incumbent, _evidence("tie", 0.75), 0.0)
    assert not service.should_adopt(
        incumbent,
        _evidence("weak", 0.86, cost=0.12, violations=("platform_filter_dropped",)),
        0.0,
    )
    assert service.should_adopt(
        incumbent,
        _evidence("strong", 0.90, cost=0.10, violations=("content_type_filter_dropped",)),
        0.0,
    )


def test_inv07_inv08_immutable_atomic_plans(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("경주 맛집 카톡 논문", NOW)
    resolved = FilterResolver().resolve(parsed, None)
    policy = golden_container.search.relaxation
    assert policy is not None
    plans = {plan.plan_id: plan for plan in policy.plans(resolved, parsed)}
    assert {
        "strict",
        "platform_filter_dropped",
        "content_type_filter_dropped",
        "platform_filter_dropped+content_type_filter_dropped",
    } <= plans.keys()
    platform_hard = plans["platform_filter_dropped"].filters.to_hard_filter(golden_container.lexicon)
    type_hard = plans["content_type_filter_dropped"].filters.to_hard_filter(golden_container.lexicon)
    assert platform_hard.platforms is None and platform_hard.content_types == {"paper"}
    assert type_hard.platforms == {"kakaotalk"} and type_hard.content_types is None


def test_inv09_inv12_rejected_attempts_leave_empty(golden_container: AppContainer) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="mars migration documentary 저장한 거", now=NOW, explain=True)
    )
    assert result.results == []
    assert result.applied_relaxations == []
    assert result.debug is not None
    attempts = result.debug["relaxation_decision"]["attempted_plans"]
    strict = next(attempt for attempt in attempts if attempt["plan_id"] == "strict")
    assert strict["candidate_count"] > 0
    assert strict["eligible_count"] == 0
    assert strict["reason"] == "all_candidates_rejected"
    assert strict["gate_rejections"]
    assert {rejection["reason"] for rejection in strict["gate_rejections"]} & {
        "semantic_floor",
        "no_evidence",
        "below_threshold",
    }


def test_inv10_original_survives_canonicalization(golden_container: AppContainer) -> None:
    vocabulary = golden_container.registry.get("u_alice").morph.vocabulary()
    parsed = golden_container.understander.parse("다리 운동 영상", NOW, vocabulary)
    assert "다리" in parsed.original_terms
    assert parsed.keywords[:2] == ["다리", "하체"]
    assert parsed.semantic_text_original == "다리 운동 영상"
    assert all(correction.to != "자리" for correction in parsed.corrections)


def test_inv11_correction_only_cannot_pass(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("기휴변화", NOW)
    evidence = _evidence(
        "corrected",
        0.90,
        semantic=0.2,
        original=0.0,
        canonical=1.0,
        correction=1.0,
        profile="lexical-only",
    )
    decision = RelevanceGate(GateSettings()).evaluate(parsed, evidence)
    assert not decision.accepted and decision.reason == "correction_only"


def test_inv12_semantic_only_floor_is_absolute(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("unknown language", NOW)
    evidence = _evidence(
        "semantic",
        0.99,
        semantic=0.59,
        original=0.0,
        profile="semantic-only",
    )
    decision = RelevanceGate(GateSettings()).evaluate(parsed, evidence)
    assert not decision.accepted and decision.reason == "semantic_floor"


def test_lexical_only_partial_match_must_clear_its_absolute_threshold(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("북극곰 다큐", NOW)
    evidence = _evidence(
        "partial",
        0.57,
        semantic=0.5,
        original=0.5,
        profile="lexical-only",
    ).model_copy(update={"key_coverage": 0.5})
    decision = RelevanceGate(GateSettings()).evaluate(parsed, evidence)
    assert not decision.accepted and decision.reason == "below_threshold"


def test_inv15_relaxed_flag_equals_actual_facets(golden_container: AppContainer) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="경주 맛집 카톡 논문", now=NOW, limit=10)
    )
    assert result.applied_relaxations == ["platform_filter_dropped", "content_type_filter_dropped"]
    assert all(item.relaxed == bool(item.relaxed_facets) for item in result.results)
    assert result.results[0].relaxed_facets == result.applied_relaxations


def test_inv16_time_cost_is_mutually_exclusive(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("지난주 카톡으로 받은 회의 장소", NOW)
    resolved = FilterResolver().resolve(parsed, None)
    evidence = golden_container.search.relevance_scorer.score(
        parsed,
        "c_alice_0136",
        golden_container.registry.get("u_alice"),
        0.8,
        resolved,
    )
    assert evidence.query_facet_violations == ("time_window_expanded",)
    assert evidence.facet_cost == pytest.approx(SearchSettings().relaxation.time_expanded_cost)


def test_v2_settings_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchSettings.model_validate({"gate": {"tail_ratio": 0.5}})


def test_all_gate_profile_thresholds_are_reachable() -> None:
    settings = SearchSettings()
    assert settings.gate.low_signal_threshold < 0.5
    with pytest.raises(ValidationError, match="도달할 수 없는 게이트 문턱"):
        SearchSettings.model_validate({"gate": {"low_signal_threshold": 0.99}})
    with pytest.raises(ValidationError, match="tail 문턱"):
        SearchSettings.model_validate(
            {"gate": {"lexical_only_threshold": 0.5, "lexical_only_tail_threshold": 0.6}}
        )


def _score(golden_container: AppContainer, query: str, content_id: str, semantic_raw: float) -> CandidateEvidence:
    index = golden_container.registry.get("u_alice")
    parsed = golden_container.understander.parse(query, NOW, index.morph.vocabulary())
    resolved = FilterResolver().resolve(parsed, None)
    return golden_container.search.relevance_scorer.score(parsed, content_id, index, semantic_raw, resolved)


def test_key_coverage_counts_each_query_word_once(golden_container: AppContainer) -> None:
    # 트랜치코트 → 트랜치/트랜치코트/코트 하위어가 분모를 늘리지 않는다. 코디 한 어절 일치는 절반이다.
    evidence = _score(golden_container, "트랜치코트 코디", "c_alice_0011", 0.0)
    assert evidence.original_lexical == pytest.approx(0.25)
    assert evidence.key_coverage == pytest.approx(0.5)
    assert "lexical" in evidence.signals


def test_phrase_ngrams_do_not_double_count_a_single_word_match(golden_container: AppContainer) -> None:
    # 세 어절 중 `수제` 하나만 일치하면 같은 단어의 n-gram이 더해져도 어휘 증거 floor를 넘지 못한다.
    evidence = _score(golden_container, "수제 맥주 양조법", "c_alice_0014", 0.0)
    assert evidence.key_coverage == pytest.approx(1 / 3)
    assert evidence.phrase > 0.0
    assert evidence.lexical_support < SearchSettings().relevance.lexical_evidence_floor
    assert evidence.signals == ()
    decision = golden_container.search.gate.evaluate(
        golden_container.understander.parse("수제 맥주 양조법", NOW), evidence
    )
    assert not decision.accepted and decision.reason == "no_evidence"


def test_specific_documentary_term_remains_in_original_lexical(golden_container: AppContainer) -> None:
    relevant = _score(golden_container, "환경 다큐", "c_alice_0047", 0.0)
    unrelated = _score(golden_container, "환경 다큐", "c_alice_0113", 0.0)
    # df=1인 `다큐`를 범용어로 지우지 않는다. 각 문서가 한 원형 용어만 맞히므로 필드 신뢰도만 차이 난다.
    assert relevant.original_lexical == pytest.approx(0.5)
    assert unrelated.original_lexical == pytest.approx(0.3)


@pytest.mark.parametrize("query", ["수제 맥주 양조법", "바둑 정석 공부", "낚시 포인트 추천"])
def test_single_partial_word_match_queries_are_empty(golden_container: AppContainer, query: str) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query=query, now=NOW))
    assert result.results == []
    assert result.applied_relaxations == []


def test_curated_synonym_is_full_concept_evidence(golden_container: AppContainer) -> None:
    # 사전 동의어(confidence 1.0)는 같은 개념의 증거다. R에서는 βo > βc로 원형 우선을 유지한다.
    evidence = _score(golden_container, "지구온난화 연구", "c_alice_0104", 0.0)
    assert evidence.original_lexical == 0.0 and evidence.canonical_lexical > 0.0
    assert evidence.key_coverage == pytest.approx(0.5)
    assert evidence.signals == ("canonical",)
    assert evidence.correction_contribution == 0.0  # 동의어는 교정 단독 거부 대상이 아니다


def test_typo_with_independent_semantic_signal_is_not_correction_only(golden_container: AppContainer) -> None:
    # q_0038 회귀: 교정 일치 + 잡음 floor 이상의 독립 의미 신호는 통과, 교정 단독 후보는 계속 거부된다.
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="기휴변화 논문", now=NOW))
    assert result.results
    assert result.results[0].content_id == "c_alice_0096"
    for item in result.results:
        evidence = _score(golden_container, "기휴변화 논문", item.content_id, 0.0)
        assert evidence.correction_contribution > 0.0
    lone = _evidence("lone", 0.90, semantic=0.0, original=0.0, canonical=1.0, correction=1.0, profile="lexical-only")
    decision = RelevanceGate(GateSettings()).evaluate(golden_container.understander.parse("기휴변화", NOW), lone)
    assert not decision.accepted and decision.reason == "correction_only"


def test_semantic_only_acceptance_is_bound_by_floor_not_saturated_r(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("unknown language", NOW)
    gate = RelevanceGate(GateSettings(), model_id="bge-m3")
    above = _evidence("above", 0.47, semantic=0.65, original=0.0, profile="semantic-only")
    below = _evidence("below", 0.99, semantic=0.59, original=0.0, profile="semantic-only")
    assert gate.evaluate(parsed, above).accepted
    decision = gate.evaluate(parsed, below)
    assert not decision.accepted and decision.reason == "semantic_floor"


def test_soft_platform_is_a_ranking_preference_not_a_relaxation(golden_container: AppContainer) -> None:
    # 조사 없는 "유툽"은 soft facet이다. 필터·완화 기록 없이 불일치 문서의 효용만 낮춘다.
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="유툽 레시피", now=NOW))
    assert result.applied_relaxations == []
    assert all(not item.relaxed for item in result.results)
    assert [item.platform for item in result.results[:5]] == ["youtube"] * 5
    youtube = _score(golden_container, "유툽 레시피", "c_alice_0068", 0.5)
    local = _score(golden_container, "유툽 레시피", "c_alice_0123", 0.5)
    assert youtube.soft_facet_cost == 0.0 and local.soft_facet_cost > 0.0
    assert local.query_facet_violations == ()
    assert youtube.relevance == pytest.approx(local.relevance, abs=0.05)
