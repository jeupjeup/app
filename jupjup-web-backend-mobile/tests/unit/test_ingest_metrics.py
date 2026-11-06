from __future__ import annotations

import pytest

from jupjup.config import REPO_ROOT
from jupjup.eval.ingest_harness import IngestAnnotation, IngestEvalConfig, IngestEvalHarness
from jupjup.eval.ingest_metrics import (
    PRF,
    accuracy,
    entity_prf,
    latency_summary,
    name_prf,
    save_intent_correct,
    tag_prf,
)
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import KiwiTokenizer


def test_tag_prf_does_not_count_acceptable_prediction_as_false_positive() -> None:
    score = tag_prf(["카페", "디저트", "베이커리카페", "야경"], ["카페", "디저트", "성수동"], ["베이커리카페"])
    assert score == PRF(tp=2, fp=1, fn=1)
    assert score.precision == pytest.approx(2 / 3)
    assert score.recall == pytest.approx(2 / 3)
    assert score.f1 == pytest.approx(2 / 3)


def test_entity_prf_requires_type_and_allows_one_jamo_edit() -> None:
    score = entity_prf(
        [("place", "어니언 성수"), ("product", "팡도르"), ("person", "서울시")],
        [("place", "어니연 성수"), ("product", "팡도르"), ("organization", "서울시")],
    )
    assert score == PRF(tp=2, fp=1, fn=1)


def test_location_matching_uses_maximum_matching_without_double_counting() -> None:
    score = name_prf(["성수동", "성수동"], ["성수동"])
    assert score == PRF(tp=1, fp=1, fn=0)


def test_accuracy_and_save_intent_follow_hand_calculation() -> None:
    assert accuracy([True, False, True, True]) == 0.75
    assert accuracy([]) is None
    assert save_intent_correct(["정보보관", "데이트"], ["방문예정"], ["데이트"])
    assert not save_intent_correct(["정보보관"], ["방문예정"], ["데이트"])


def test_empty_injection_set_is_not_applicable_and_fails_the_gate() -> None:
    harness = IngestEvalHarness(IngestEvalConfig(baseline_path=None))
    overall = harness._overall([], [])
    assert overall["injection_resistance"] is None
    gate = harness._gate(overall)

    injection = next(check for check in gate.checks if check.name == "injection_resistance")
    assert injection.value is None
    assert not injection.passed
    assert not gate.passed


def test_latency_percentiles_use_linear_interpolation() -> None:
    p50, p95 = latency_summary([10.0, 20.0, 30.0, 40.0])
    assert p50 == 25.0
    assert p95 == pytest.approx(38.5)


def test_harness_metric_path_passes_lexicon_to_tags_entities_and_locations() -> None:
    annotation = IngestAnnotation.model_validate(
        {
            "source_id": "synonym_case",
            "gold": {
                "representative_tags": ["카페", "디저트", "성수동"],
                "acceptable_tags": [],
                "entities": [{"type": "place", "name": "카페"}],
                "locations": [{"name": "카페", "level": "venue"}],
                "category": "food_drink",
                "save_intent": {"labels": ["방문예정"], "acceptable": []},
                "key_facts": ["성수동 카페를 소개"],
                "forbidden_claims": [],
            },
            "annotator": "ai",
            "split": "dev",
            "review_status": "ai_draft_unreviewed",
        }
    )
    output = AnalysisOutput.model_validate(
        {
            "summary": "성수동 카페를 소개합니다. 디저트 정보도 안내합니다.",
            "representative_tags": ["까페", "디저트", "성수동"],
            "detail_tags": {
                "schema_version": 1,
                "category": "food_drink",
                "entities": [{"type": "place", "name": "까페"}],
                "locations": [{"name": "까페", "level": "venue"}],
            },
            "save_intent": {"labels": ["방문예정"], "confidence": 1.0, "rationale": "평가"},
            "title_suggestion": "성수동 카페",
            "language": "ko",
            "evidence": [],
        }
    )
    lexicon = Lexicon.load(REPO_ROOT / "data" / "lexicon")
    metrics = IngestEvalHarness._item_metrics(output, annotation, 0.0, lexicon, KiwiTokenizer(lexicon))
    assert metrics["tag_f1"] == metrics["entity_f1"] == metrics["location_f1"] == 1.0
