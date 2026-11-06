"""커밋된 bge-m3 녹화본의 결정적 재생과 실제 제공자 기준선."""

from __future__ import annotations

import json

import pytest

from jupjup.container import AppContainer
from jupjup.eval.harness import EvalConfig, EvalHarness
from jupjup.search.service import SearchRequest
from tests.conftest import NOW, ROOT

pytestmark = pytest.mark.eval
BASELINE = ROOT / "data" / "baselines" / "recorded.json"


def test_recorded_dev_split_passes_live_like_gate() -> None:
    """T11 전에는 test aggregate를 소비하지 않고 recorded dev만 회귀 검증한다."""
    report = EvalHarness(EvalConfig(mode="recorded", split="dev", baseline_path=BASELINE)).run()
    assert report.gate.passed, report.gate.reasons


def test_recorded_replay_is_deterministic() -> None:
    config = EvalConfig(mode="recorded", split="dev")
    first = EvalHarness(config).run().deterministic_dict()
    second = EvalHarness(config).run().deterministic_dict()
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )


def test_inv13_recorded_cross_language_and_hard_negative() -> None:
    report = EvalHarness(EvalConfig(mode="recorded", split="dev")).run()
    by_id = {result.query_id: result for result in report.results}
    assert by_id["ch_0003"].ranked_ids[0] == "c_alice_0096"
    assert any(
        content_id in {"c_alice_0096", "c_alice_0104", "c_alice_0114"}
        for content_id in by_id["ch_0003"].ranked_ids[:3]
    )
    assert by_id["ch_0011"].ranked_ids == []
    assert by_id["ch_0012"].ranked_ids == []


@pytest.mark.parametrize(
    ("query", "top_id"),
    [
        ("coffee cardiovascular health paper", "c_alice_0112"),
        ("retrieval augmented generation survey paper", "c_alice_0100"),
    ],
)
def test_recorded_low_signal_cross_language_positive_is_reachable(
    recorded_golden_container: AppContainer,
    query: str,
    top_id: str,
) -> None:
    result = recorded_golden_container.search.search(
        SearchRequest(user_id="u_alice", query=query, now=NOW, limit=10)
    )
    assert result.understanding.query_signal_profile == "low-signal"
    assert result.results[0].content_id == top_id


@pytest.mark.parametrize(
    "query",
    [
        "북극곰 다큐",
        "미얀마 여행 일정",
        "보드게임 추천",
        "낚시 포인트 추천",
        "mars migration documentary 저장한 거",
    ],
)
def test_recorded_fixed_negatives_stay_empty(recorded_golden_container: AppContainer, query: str) -> None:
    result = recorded_golden_container.search.search(
        SearchRequest(user_id="u_alice", query=query, now=NOW, limit=50)
    )
    assert result.results == []
    assert result.applied_relaxations == []


def test_recorded_semantic_documentary_outranks_partial_lexical_match(
    recorded_golden_container: AppContainer,
) -> None:
    result = recorded_golden_container.search.search(
        SearchRequest(user_id="u_alice", query="환경 다큐", now=NOW, limit=10)
    )
    assert result.results[0].content_id == "c_alice_0047"


def test_recorded_strong_anchor_can_restore_a_related_lexical_tail(
    recorded_golden_container: AppContainer,
) -> None:
    result = recorded_golden_container.search.search(
        SearchRequest(user_id="u_alice", query="그 영화 예매했던 거", now=NOW, limit=10, explain=True)
    )
    tail = next(item for item in result.results if item.content_id == "c_alice_0053")
    assert tail.rank == 2
    assert tail.debug is not None
    assert tail.debug["gate"]["reason"] == "accepted_as_anchored_tail"


def test_anchored_tail_acceptance_is_monotonic_in_relevance(recorded_golden_container: AppContainer) -> None:
    result = recorded_golden_container.search.search(
        SearchRequest(user_id="u_alice", query="그 영화 예매했던 거", now=NOW, limit=50, explain=True)
    )
    tails = [
        item
        for item in result.results
        if item.debug is not None and item.debug["gate"]["reason"] == "accepted_as_anchored_tail"
    ]
    assert tails
    floor = recorded_golden_container.settings.search.gate.lexical_only_tail_threshold
    assert all(item.debug["evidence"]["relevance"] >= floor for item in tails if item.debug is not None)
    assert [item.debug["evidence"]["relevance"] for item in tails if item.debug is not None] == sorted(
        [item.debug["evidence"]["relevance"] for item in tails if item.debug is not None], reverse=True
    )


# ---------------------------------------------------------------- A1 (리랭커 녹화본 재생, 설계 9.3절)
@pytest.fixture(scope="module")
def recorded_a1_container() -> AppContainer:
    from jupjup.config import SearchSettings, Settings
    from jupjup.container import build_container
    from jupjup.storage.db import create_db_engine
    from jupjup.storage.seed import load_seed_file
    from tests.conftest import DATA

    search = SearchSettings.model_validate({"cross_rerank": {"enabled": True}})
    settings = Settings(env="test", mode="recorded", data_dir=DATA, db_path=":memory:", search=search)
    container = build_container(settings, engine=create_db_engine(None))
    report = load_seed_file(DATA / "golden" / "seeds.jsonl", container.repo, container.indexer, strict=True)
    assert report.errors == []
    return container


@pytest.mark.parametrize(
    "query",
    ["북극곰 다큐", "미얀마 여행 일정", "보드게임 추천", "낚시 포인트 추천", "mars migration documentary 저장한 거"],
)
def test_recorded_a1_fixed_negatives_stay_empty(recorded_a1_container: AppContainer, query: str) -> None:
    result = recorded_a1_container.search.search(SearchRequest(user_id="u_alice", query=query, now=NOW, limit=50))
    assert result.rerank_status == "scored"
    assert result.results == []


def test_recorded_a1_cross_language_positives(recorded_a1_container: AppContainer) -> None:
    ch_0003 = recorded_a1_container.search.search(
        SearchRequest(user_id="u_alice", query="assignment에 쓸 climate crisis paper", now=NOW, limit=10)
    )
    assert ch_0003.rerank_status == "scored"
    assert ch_0003.results[0].content_id == "c_alice_0096"
    ch_0001 = recorded_a1_container.search.search(
        SearchRequest(user_id="u_alice", query="IG에서 본 coffee shop dessert 그거", now=NOW, limit=10)
    )
    assert "c_alice_0001" in [item.content_id for item in ch_0001.results[:3]]


def test_recorded_a1_replay_is_deterministic() -> None:
    config = EvalConfig(mode="recorded", split="dev", search_overrides={"cross_rerank": {"enabled": True}})
    first = EvalHarness(config).run().deterministic_dict()
    second = EvalHarness(config).run().deterministic_dict()
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
