"""T12: FilterResolver, fuse_rrf, SearchService v0 (요청 필터 우선, degraded 경로)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

import numpy as np
import pytest

from jupjup.container import AppContainer
from jupjup.domain.errors import EmbeddingProviderError, InvalidFilterError, InvalidQueryError, InvalidUserError
from jupjup.domain.models import SeedRecord, SeedSnapshot, SeedTag
from jupjup.index.document import HardFilter
from jupjup.search.filters import FilterResolver, SearchFilters
from jupjup.search.fusion import fuse_combsum, fuse_rrf
from jupjup.search.service import SearchRequest
from jupjup.search.types import RetrievalHit
from tests.conftest import KST, NOW


@pytest.mark.parametrize(("term", "context"), [("발로란트", "공략"), ("텍스쳐", "소스")])
@pytest.mark.parametrize("field", ["tags", "text"])
def test_standalone_proper_noun_finds_exact_saved_tags_and_text(
    container_factory: Callable[..., AppContainer], term: str, context: str, field: str
) -> None:
    c = container_factory()
    bundle = SeedRecord(
        id="c_proper_noun",
        user_id="u_test",
        platform="web",
        content_type="article",
        saved_at=NOW,
        tags=[SeedTag(name=term, source="user"), SeedTag(name=context, source="user")] if field == "tags" else [],
        snapshot=SeedSnapshot(text=f"{term} {context}") if field == "text" else None,
    ).to_bundle()
    c.repo.upsert_many([bundle])
    c.indexer.index_bundle(bundle)
    index = c.registry.get("u_test")
    parsed = c.understander.parse(term, NOW, index.morph.vocabulary())
    assert parsed.query_signal_profile == "normal"
    # Context makes Kiwi retain the document's full noun; the isolated query loses its suffix.
    assert term not in parsed.raw_keywords
    assert term in index.morph.doc_terms(bundle.content.id)
    hits = index.morph.search(c.search.morph_terms(parsed), HardFilter(), 10)
    assert [hit.content_id for hit in hits] == [bundle.content.id]
    assert term in {word for words in hits[0].matched_fields.values() for word in words}
    evidence = c.search.relevance_scorer.score(
        parsed, bundle.content.id, index, 0.0, FilterResolver().resolve(parsed, None)
    )
    assert evidence.key_coverage == pytest.approx(1.0 if field == "tags" else 0.6)
    assert "lexical" in evidence.signals
    result = c.search.search(SearchRequest(user_id="u_test", query=term, now=NOW))
    assert [item.content_id for item in result.results] == [bundle.content.id]


def H(cid: str, rank: int, score: float = 1.0) -> RetrievalHit:
    return RetrievalHit(content_id=cid, rank=rank, score=score)


def test_rrf_hand() -> None:
    lists = {"morph": [H("a", 1), H("b", 2)], "ngram": [H("b", 1), H("c", 2)], "vector": [H("c", 1), H("a", 3)]}
    w = {"morph": 1.0, "ngram": 0.6, "vector": 1.0}
    fused = {f.content_id: f for f in fuse_rrf(lists, w, k=60)}
    assert fused["a"].rrf_score == pytest.approx(1 / 61 + 1 / 63)
    assert fused["b"].rrf_score == pytest.approx(1 / 62 + 0.6 / 61)
    assert fused["c"].rrf_score == pytest.approx(0.6 / 62 + 1 / 61)
    assert fused["a"].ranks == {"morph": 1, "vector": 3}
    order = [f.content_id for f in fuse_rrf(lists, w, k=60)]
    assert order == sorted(fused, key=lambda x: -fused[x].rrf_score)


def test_rrf_ties_and_top_n() -> None:
    lists = {"morph": [H("z", 1)], "ngram": [H("y", 1)]}
    out = fuse_rrf(lists, {"morph": 1.0, "ngram": 1.0}, k=60, top_n=1)
    assert [f.content_id for f in out] == ["y"]  # 동점이면 id 오름차순


def test_combsum() -> None:
    lists = {"morph": [H("a", 1, 10.0), H("b", 2, 5.0), H("c", 3, 0.0)], "vector": [H("c", 1, 0.9)]}
    out = {f.content_id: f.rrf_score for f in fuse_combsum(lists, {"morph": 1.0, "vector": 1.0})}
    assert out == pytest.approx({"a": 1.0, "b": 0.5, "c": 1.0})


def test_request_filter_overrides_query(golden_container: AppContainer) -> None:
    c = golden_container
    parsed = c.understander.parse("지난달 인스타에서 본 성수동 카페", NOW)
    rf = FilterResolver().resolve(parsed, SearchFilters(platforms=["youtube"]))
    assert rf.platforms is not None and rf.platforms.value == ["youtube"] and rf.platforms.locked
    assert rf.platforms.origin == "request" and "platforms" in rf.overridden
    assert rf.saved_window is not None and rf.saved_window.origin == "query" and not rf.saved_window.locked
    hf = rf.to_hard_filter(c.lexicon)
    assert hf.platforms == {"youtube"}


def test_request_window_overrides(golden_container: AppContainer) -> None:
    c = golden_container
    parsed = c.understander.parse("지난달 저장한 카페", NOW)
    req = SearchFilters(saved_from=datetime(2025, 1, 1, tzinfo=KST), saved_to=datetime(2026, 1, 1, tzinfo=KST))
    rf = FilterResolver().resolve(parsed, req)
    assert rf.saved_window is not None and rf.saved_window.locked and "saved_range" in rf.overridden
    assert rf.saved_window.start == datetime(2025, 1, 1, tzinfo=KST)


def test_video_matches_short_video(golden_container: AppContainer) -> None:
    parsed = golden_container.understander.parse("하체 운동 영상", NOW)
    hf = FilterResolver().resolve(parsed, None).to_hard_filter(golden_container.lexicon)
    assert hf.content_types == {"video", "short_video"}


def test_invalid_filters() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SearchFilters(platforms=["tiktok"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        SearchFilters(platforms=["youtube"] * 11)
    with pytest.raises(ValidationError):
        SearchFilters(saved_from=datetime(2026, 1, 1))  # naive


def test_saved_from_after_to_rejected(golden_container: AppContainer) -> None:
    req = SearchRequest(
        user_id="u_alice",
        query="카페",
        now=NOW,
        filters=SearchFilters(saved_from=datetime(2026, 2, 1, tzinfo=KST), saved_to=datetime(2026, 1, 1, tzinfo=KST)),
    )
    with pytest.raises(InvalidFilterError):
        golden_container.search.search(req)


def test_search_basic_and_isolation(golden_container: AppContainer) -> None:
    s = golden_container.search
    for user in ("u_alice", "u_bob", "u_carol"):
        res = s.search(SearchRequest(user_id=user, query="성수동 카페", now=NOW, limit=20))
        assert res.results
        assert all(r.content_id.startswith(f"c_{user[2:]}_") for r in res.results)


def test_search_s1_top(golden_container: AppContainer) -> None:
    res = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="지난달 인스타에서 본 성수동 카페", now=NOW)
    )
    assert res.results[0].content_id == "c_alice_0001"
    assert all(r.platform == "instagram" for r in res.results)
    assert res.understanding.time_range is not None


@pytest.mark.parametrize("limit", [1, 2, 10, 50])
def test_s7_prefers_stronger_expanded_period_result(golden_container: AppContainer, limit: int) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="지난주 카톡으로 받은 회의 장소", now=NOW, limit=limit)
    )
    assert result.results[0].content_id == "c_alice_0136"
    assert result.results[0].rank == 1
    assert result.applied_relaxations == ["time_window_expanded"]
    assert result.results[0].relaxed is True
    assert all(item.relaxed for item in result.results)
    assert all("time_filter_dropped" not in item.relaxed_facets for item in result.results)
    assert any(reason.type == "time_near" for reason in result.results[0].match_reasons)


def test_near_time_strong_match_beats_weak_strict_incumbent(golden_container: AppContainer) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="지지난주 성수 카페 약속", now=NOW, explain=True)
    )
    assert result.results[0].content_id == "c_alice_0140"
    assert result.applied_relaxations == ["time_window_expanded"]
    assert result.debug is not None
    decision = result.debug["relaxation_decision"]
    assert decision["selected_plan_id"] == "time_window_expanded"
    assert all(set(item.relaxed_facets) <= {"time_window_expanded"} for item in result.results)


@pytest.mark.parametrize("limit", [1, 2, 10, 50])
def test_relaxation_preserves_original_blog_facet(golden_container: AppContainer, limit: int) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="레스토랑 추천 블로그", now=NOW, limit=limit)
    )
    assert result.results[0].content_id == "c_alice_0153"
    assert result.results[0].rank == 1
    assert result.applied_relaxations == []
    assert all(item.platform == "blog" and not item.relaxed for item in result.results)
    assert all(item.content_id != "c_alice_0145" for item in result.results[:1])


@pytest.mark.parametrize("limit", [1, 2, 10, 50])
def test_same_top_does_not_record_content_type_relaxation(golden_container: AppContainer, limit: int) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="다리 운동 영상", now=NOW, limit=limit)
    )
    assert result.results[0].content_id == "c_alice_0040"
    assert result.results[0].rank == 1
    assert result.applied_relaxations == []
    assert all(not item.relaxed for item in result.results)


@pytest.mark.parametrize("limit", [1, 2, 10, 50])
@pytest.mark.parametrize(
    ("query", "top_id", "relaxations"),
    [
        ("경주 맛집 인스타", "c_alice_0153", ["platform_filter_dropped"]),
        ("하체 운동 유튜브", "c_alice_0040", ["platform_filter_dropped"]),
        (
            "경주 맛집 카톡 논문",
            "c_alice_0153",
            ["platform_filter_dropped", "content_type_filter_dropped"],
        ),
    ],
)
def test_relaxation_v2_fixed_facet_regressions(
    golden_container: AppContainer,
    limit: int,
    query: str,
    top_id: str,
    relaxations: list[str],
) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query=query, now=NOW, limit=limit))
    assert result.results[0].content_id == top_id
    assert result.applied_relaxations == relaxations
    assert result.results[0].relaxed_facets == relaxations


@pytest.mark.parametrize("limit", [1, 2, 10, 50])
def test_relaxation_v2_hard_negative_stays_empty(golden_container: AppContainer, limit: int) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="mars migration documentary 저장한 거", now=NOW, limit=limit)
    )
    assert result.results == []
    assert result.applied_relaxations == []


@pytest.mark.parametrize("query", ["북극곰 다큐", "미얀마 여행 일정", "보드게임 추천", "낚시 포인트 추천"])
def test_weak_generic_lexical_overlap_stays_empty(golden_container: AppContainer, query: str) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query=query, now=NOW, limit=50, explain=True)
    )
    assert result.results == []
    assert result.applied_relaxations == []
    assert result.debug is not None


def test_margin_result_uses_near_period_reason(golden_container: AppContainer) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="지난주 카톡 회식 장소", now=NOW))
    near = next(reason for reason in result.results[0].match_reasons if reason.type == "time_near")
    assert near.detail == "기간 근접 (지난주)"
    assert all(reason.detail != "지난주 저장" for reason in result.results[0].match_reasons)


def test_mixed_english_coffee_shop_returns_relevant_instagram(golden_container: AppContainer) -> None:
    result = golden_container.search.search(
        SearchRequest(user_id="u_alice", query="IG에서 본 coffee shop 디저트", now=NOW)
    )
    assert result.understanding.keywords == ["카페", "디저트"]
    assert result.results
    assert all(item.platform == "instagram" for item in result.results)
    assert "c_alice_0001" in [item.content_id for item in result.results[:3]]


def test_filter_only_browse_returns_latest_matching_page(golden_container: AppContainer) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="유튜브", now=NOW, limit=7))
    assert result.browse is True
    assert result.understanding.intent == "browse" and result.understanding.filter_only
    assert len(result.results) == 7
    assert all(item.platform == "youtube" for item in result.results)
    assert [item.saved_at for item in result.results] == sorted(
        (item.saved_at for item in result.results), reverse=True
    )
    assert all(item.match_reasons[0].type == "browse" for item in result.results)
    assert result.applied_relaxations == [] and result.empty_state is None


def test_filter_only_platform_and_type_browse_all_types(golden_container: AppContainer) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="유튜브 영상", now=NOW, limit=50))
    assert result.browse is True
    assert len(result.results) == 30
    assert all(item.platform == "youtube" and item.content_type in {"video", "short_video"} for item in result.results)


def test_filter_only_browse_uses_exact_query_period(golden_container: AppContainer) -> None:
    result = golden_container.search.search(SearchRequest(user_id="u_alice", query="지난달 인스타", now=NOW, limit=50))
    assert result.browse is True
    assert len(result.results) == 4
    assert all(
        item.platform == "instagram"
        and datetime(2026, 9, 1, tzinfo=KST) <= item.saved_at < datetime(2026, 10, 1, tzinfo=KST)
        for item in result.results
    )


def test_filter_only_browse_request_filter_wins_and_isolates(golden_container: AppContainer) -> None:
    result = golden_container.search.search(
        SearchRequest(
            user_id="u_bob",
            query="유튜브",
            filters=SearchFilters(platforms=["instagram"]),
            now=NOW,
            limit=50,
        )
    )
    assert result.browse is True
    assert result.overridden_by_request == ["platforms"]
    assert result.results
    assert all(item.platform == "instagram" and item.content_id.startswith("c_bob_") for item in result.results)


def test_request_filter_respected_in_results(golden_container: AppContainer) -> None:
    res = golden_container.search.search(
        SearchRequest(
            user_id="u_alice", query="인스타에서 본 성수동 카페", now=NOW, filters=SearchFilters(platforms=["youtube"])
        )
    )
    assert all(r.platform == "youtube" for r in res.results)
    assert res.overridden_by_request == ["platforms"]


def test_deleted_original_flag(golden_container: AppContainer) -> None:
    res = golden_container.search.search(SearchRequest(user_id="u_alice", query="로우커피 핸드드립 원두", now=NOW))
    top = res.results[0]
    assert top.title.startswith("성수동 로우커피") and top.original_available is False


def test_explain_debug(golden_container: AppContainer) -> None:
    res = golden_container.search.search(SearchRequest(user_id="u_alice", query="파스타 레시피", now=NOW, explain=True))
    assert res.results[0].debug is not None and "ranks" in res.results[0].debug
    res2 = golden_container.search.search(SearchRequest(user_id="u_alice", query="파스타 레시피", now=NOW))
    assert res2.results[0].debug is None


def test_inv02_inv14_service_relevance_ignores_limit_now_and_request_lock(
    golden_container: AppContainer,
) -> None:
    requests = [
        SearchRequest(user_id="u_alice", query="성수동 카페", now=NOW, limit=10, explain=True),
        SearchRequest(
            user_id="u_alice",
            query="성수동 카페",
            now=datetime(2025, 1, 1, tzinfo=KST),
            limit=50,
            explain=True,
        ),
        SearchRequest(
            user_id="u_alice",
            query="성수동 카페",
            now=NOW,
            limit=10,
            filters=SearchFilters(platforms=["instagram"]),
            explain=True,
        ),
    ]
    scores = []
    for request in requests:
        result = golden_container.search.search(request)
        item = next(item for item in result.results if item.content_id == "c_alice_0001")
        assert item.debug is not None
        scores.append(item.debug["evidence"]["relevance"])
    assert scores == pytest.approx([scores[0]] * len(scores), abs=1e-6)


class Boom:
    model_id = "hashing-v1"
    dim = 384

    def embed(self, texts: Sequence[str], kind: str) -> np.ndarray:
        raise EmbeddingProviderError("down")


def test_degraded_when_embedder_fails(golden_container: AppContainer) -> None:
    s = golden_container.search
    original = s.embedder
    s.embedder = Boom()  # type: ignore[assignment]
    try:
        res = s.search(SearchRequest(user_id="u_alice", query="토마토 파스타", now=NOW))
    finally:
        s.embedder = original
    assert res.degraded and res.degraded_reasons == ["embedding_unavailable"]
    assert res.results and res.results[0].content_id == "c_alice_0041"


def test_input_validation(golden_container: AppContainer) -> None:
    s = golden_container.search
    with pytest.raises(InvalidUserError):
        s.search(SearchRequest(user_id="alice", query="카페", now=NOW))
    with pytest.raises(InvalidFilterError):
        s.search(SearchRequest(user_id="u_alice", query="카페", now=NOW, limit=0))
    with pytest.raises(InvalidFilterError):
        s.search(SearchRequest(user_id="u_alice", query="카페", now=NOW, limit=51))
    with pytest.raises(InvalidQueryError):
        s.search(SearchRequest(user_id="u_alice", query="   ", now=NOW))


def test_unknown_user_gets_empty(golden_container: AppContainer) -> None:
    res = golden_container.search.search(SearchRequest(user_id="u_nobody", query="성수동 카페", now=NOW))
    assert res.results == [] and res.empty_state is not None
    assert res.empty_state.message == "다른 표현으로 다시 찾아볼까요?"


def test_noun_not_corrected_to_verb_stem(golden_container: AppContainer) -> None:
    p = golden_container.search.parse_only("골프 레슨 영상", NOW, "u_alice")
    assert all(c.to != "고르" for c in p.corrections)
