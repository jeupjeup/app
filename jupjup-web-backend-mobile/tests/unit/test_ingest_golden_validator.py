from __future__ import annotations

from collections import Counter

import pytest

from jupjup.eval.ingest_harness import (
    INGEST_GOLDEN_V1,
    IngestGoldenSet,
    load_ingest_golden,
    validate_ingest_golden,
)


def test_ingest_golden_v1_draft_has_required_size_split_and_review_status() -> None:
    golden, errors = load_ingest_golden(INGEST_GOLDEN_V1 / "sources.jsonl", INGEST_GOLDEN_V1 / "annotations.jsonl")
    errors += validate_ingest_golden(golden, fixtures_root=INGEST_GOLDEN_V1 / "fixtures")
    assert errors == []
    assert len(golden.sources) == len(golden.annotations) == 80
    assert Counter(annotation.split for annotation in golden.annotations) == {"dev": 48, "test": 32}
    assert {annotation.review_status for annotation in golden.annotations} == {"ai_draft_unreviewed"}
    assert {annotation.annotator for annotation in golden.annotations} == {"ai"}


def test_long_fixtures_are_over_40k_characters() -> None:
    fixtures = sorted((INGEST_GOLDEN_V1 / "fixtures" / "html").glob("long_*.html"))
    assert len(fixtures) == 5
    assert all(len(path.read_text(encoding="utf-8")) > 40_000 for path in fixtures)


def _golden() -> IngestGoldenSet:
    golden, errors = load_ingest_golden(INGEST_GOLDEN_V1 / "sources.jsonl", INGEST_GOLDEN_V1 / "annotations.jsonl")
    assert errors == []
    return golden


@pytest.mark.parametrize(
    "fixture",
    ["../../../../etc/passwd", "/etc/passwd", "html/../html/long_01.html"],
)
def test_validator_rejects_fixture_path_escape(fixture: str) -> None:
    golden = _golden()
    index = next(index for index, source in enumerate(golden.sources) if source.source.fixture is not None)
    source = golden.sources[index]
    changed = source.model_copy(update={"source": source.source.model_copy(update={"fixture": fixture})})
    sources = [*golden.sources]
    sources[index] = changed
    errors = validate_ingest_golden(golden.model_copy(update={"sources": sources}))
    assert any("안전하지 않은 fixture 경로" in error for error in errors)


def test_validator_rejects_duplicates_and_split_drift() -> None:
    golden = _golden()
    duplicate_errors = validate_ingest_golden(
        golden.model_copy(update={"sources": [*golden.sources, golden.sources[0]]})
    )
    assert any("source_id 중복" in error for error in duplicate_errors)

    annotation = golden.annotations[0].model_copy(update={"split": "test"})
    split_errors = validate_ingest_golden(
        golden.model_copy(update={"annotations": [annotation, *golden.annotations[1:]]})
    )
    assert any("split은 고정 60/40" in error for error in split_errors)


def test_validator_rejects_blank_text_key_fact_and_invalid_review_pair() -> None:
    golden = _golden()
    source = golden.sources[0]
    blank_source = source.model_copy(update={"source": source.source.model_copy(update={"text": "   "})})
    annotation = golden.annotations[0]
    blank_fact = annotation.model_copy(update={"gold": annotation.gold.model_copy(update={"key_facts": [""]})})
    bad_review = golden.annotations[1].model_copy(update={"review_status": "human_reviewed", "annotator": "ai"})
    errors = validate_ingest_golden(
        golden.model_copy(
            update={
                "sources": [blank_source, *golden.sources[1:]],
                "annotations": [blank_fact, bad_review, *golden.annotations[2:]],
            }
        )
    )
    assert any("text 원본이 비어" in error for error in errors)
    assert any("key_facts에는 빈 문자열" in error for error in errors)
    assert any("annotator는 human" in error for error in errors)


def test_validator_rejects_platform_group_mismatch() -> None:
    golden = _golden()
    source = golden.sources[0].model_copy(update={"platform": "youtube"})
    errors = validate_ingest_golden(golden.model_copy(update={"sources": [source, *golden.sources[1:]]}))
    assert any("platform_group instagram" in error for error in errors)


def test_difficult_case_gold_targets_the_labeled_capability() -> None:
    golden = _golden()
    annotations = {annotation.source_id: annotation for annotation in golden.annotations}
    number_cases = [source for source in golden.sources if "number_date_dense" in source.difficult_cases]
    english_cases = [source for source in golden.sources if "mostly_english" in source.difficult_cases]
    ad_cases = [source for source in golden.sources if "ad_hashtag_heavy" in source.difficult_cases]
    assert all(
        any(char.isdigit() for fact in annotations[source.source_id].gold.key_facts for char in fact)
        for source in number_cases
    )
    assert all(
        "Orca Retrieval Lab" in " ".join(annotations[source.source_id].gold.key_facts) for source in english_cases
    )
    assert all(
        any("증정" in claim or "할인" in claim for claim in annotations[source.source_id].gold.forbidden_claims)
        for source in ad_cases
    )
    assert len({tuple(annotation.gold.forbidden_claims) for annotation in golden.annotations}) > 1
    assert (
        sum(
            "prompt_injection" in source.difficult_cases and annotations[source.source_id].split == "test"
            for source in golden.sources
        )
        >= 2
    )
