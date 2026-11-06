"""T5: 골든셋 검증기 (설계서 3.1.5절)."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from jupjup.domain.errors import GoldenSetError
from jupjup.eval.schema import (
    CATEGORY_MINIMUMS,
    CATEGORY_SPLIT_MINIMUMS,
    GoldenSet,
    load_and_validate,
    load_golden,
    validate_golden,
)
from tests.conftest import DATA

G = DATA / "golden"


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    gs, errors = load_golden(G / "seeds.jsonl", G / "queries.jsonl", G / "lexicon_cases.jsonl")
    assert errors == []
    return gs


@pytest.fixture(scope="module")
def golden_with_challenge() -> GoldenSet:
    gs, errors = load_golden(
        G / "seeds.jsonl",
        G / "queries.jsonl",
        G / "lexicon_cases.jsonl",
        G / "challenge_queries.jsonl",
    )
    assert errors == []
    return gs


def test_committed_golden_passes(golden: GoldenSet) -> None:
    assert validate_golden(golden) == []
    assert len(golden.seeds) >= 200 and len(golden.queries) >= 180 and len(golden.lexicon_cases) >= 120


def test_category_minimums_met(golden: GoldenSet) -> None:
    from collections import Counter

    counts = Counter(c for q in golden.queries for c in q.categories)
    for cat, minimum in CATEGORY_MINIMUMS.items():
        assert counts[cat] >= minimum, cat
    for cat, split_minimums in CATEGORY_SPLIT_MINIMUMS.items():
        for split, minimum in split_minimums.items():
            assert sum(cat in q.categories and q.split == split for q in golden.queries) >= minimum


def test_split_roughly_60_40(golden: GoldenSet) -> None:
    dev = sum(q.split == "dev" for q in golden.queries)
    assert 0.55 <= dev / len(golden.queries) <= 0.65


def test_draft_marker_present(golden: GoldenSet) -> None:
    assert all(s.meta.get("authored_by") == "ai_draft_unreviewed" for s in golden.seeds)


def test_challenge_set_is_separate_and_awaits_human_review(golden_with_challenge: GoldenSet) -> None:
    challenges = [q for q in golden_with_challenge.queries if q.id in golden_with_challenge.challenge_query_ids]
    assert len(challenges) == 24
    assert {q.challenge_kind for q in challenges} == {
        "hard_negative",
        "synonym_mismatch",
        "typo_colloquial",
        "mixed_english",
    }
    assert all(q.review_status == "needs_human_review" for q in challenges)
    assert validate_golden(golden_with_challenge) == []


def test_group_split_rejects_template_or_entity_leak(golden_with_challenge: GoldenSet) -> None:
    gs = _mut(golden_with_challenge)
    source = next(q for q in gs.queries if q.template_id is not None)
    peer = next(q for q in gs.queries if q.template_id == source.template_id and q.id != source.id)
    peer.split = "test" if source.split == "dev" else "dev"
    assert any("group split 위반" in error for error in validate_golden(gs))


def _mut(gs: GoldenSet) -> GoldenSet:
    return GoldenSet(
        seeds=copy.deepcopy(gs.seeds), queries=copy.deepcopy(gs.queries), lexicon_cases=copy.deepcopy(gs.lexicon_cases)
    )


def test_detects_unknown_relevance_id(golden: GoldenSet) -> None:
    gs = _mut(golden)
    gs.queries[0].relevance["c_nope_9999"] = 3
    assert any("seeds에 없습니다" in e for e in validate_golden(gs))


def test_detects_cross_user_relevance(golden: GoldenSet) -> None:
    gs = _mut(golden)
    bob_id = next(s.id for s in gs.seeds if s.user_id == "u_bob")
    q = next(q for q in gs.queries if q.user_id == "u_alice" and q.relevance)
    q.relevance[bob_id] = 2
    assert any("user_id가 질의 사용자와 다릅니다" in e for e in validate_golden(gs))


def test_detects_duplicate_ids(golden: GoldenSet) -> None:
    gs = _mut(golden)
    gs.queries[1].id = gs.queries[0].id
    gs.seeds[1].id = gs.seeds[0].id
    errs = validate_golden(gs)
    assert any(e.startswith("queries: id 중복") for e in errs)
    assert any(e.startswith("seeds: id 중복") for e in errs)


def test_detects_future_seed(golden: GoldenSet) -> None:
    gs = _mut(golden)
    gs.seeds[0].saved_at = gs.queries[0].now + timedelta(days=1)
    assert any("미래" in e for e in validate_golden(gs))


def test_detects_category_shortfall(golden: GoldenSet) -> None:
    gs = _mut(golden)
    gs.queries = [q for q in gs.queries if "filter_conflict" not in q.categories]
    assert any("카테고리 filter_conflict" in e for e in validate_golden(gs))


def test_detects_filter_only_split_shortfall(golden: GoldenSet) -> None:
    gs = _mut(golden)
    gs.queries = [q for q in gs.queries if not ("filter_only" in q.categories and q.split == "test")]
    assert any("카테고리 filter_only/test" in e for e in validate_golden(gs))


def test_detects_negative_with_relevance(golden: GoldenSet) -> None:
    gs = _mut(golden)
    neg = next(q for q in gs.queries if "negative" in q.categories)
    neg.relevance = {gs.seeds[0].id: 3}
    assert any("negative 질의는" in e for e in validate_golden(gs))


def test_load_and_validate_raises_on_bad_file(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "q.jsonl"
    p.write_text('{"id": "q1"}\n', encoding="utf-8")
    with pytest.raises(GoldenSetError) as ei:
        load_and_validate(G / "seeds.jsonl", p, G / "lexicon_cases.jsonl")
    assert ei.value.details["errors"]
