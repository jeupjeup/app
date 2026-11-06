"""Selection is extractive; music credits remain primary only for music content."""

import json
from pathlib import Path

import pytest

from jupjup.domain.errors import AnalysisSchemaError, LLMProviderError
from jupjup.ingest.validation import AnalysisValidator
from jupjup.ingest.youtube_metadata import YoutubeMetadata
from jupjup.ingest.youtube_metadata_repair import repair_metadata_output
from jupjup.ingest.youtube_salience import filter_metadata, source_blocks
from tests.unit.test_llm_analyzer import ScriptedLLM, analyzer_for, ok

CASE_PATH = Path(__file__).resolve().parents[1] / "fixtures/youtube/salience_case.json"


def gaming_metadata():
    value = json.loads(CASE_PATH.read_text())
    return YoutubeMetadata.model_validate({k: v for k, v in value.items() if k not in {"provenance", "url"}})


def selected(metadata, ids):
    return {
        f"block_{b.id}": ("primary_topic" if b.id in ids else "background_music_credit")
        for b in source_blocks(metadata)
    }


def test_gaming_selection_has_exact_offsets_and_excludes_credits(lexicon):
    metadata = gaming_metadata()
    llm = ScriptedLLM(script=[ok(selected(metadata, [0, 3]))])
    result = filter_metadata(metadata, analyzer_for(llm, AnalysisValidator(lexicon)))
    assert "발로란트" in result.primary_text() and "김된모" in result.primary_text()
    assert "NCS" not in result.primary_text()
    assert any("NCS" in b.text for b in result.auxiliary)
    assert result.basis == "title_description"
    assert result.meta.attempts == 1 and len(llm.calls) == 1
    for block in result.primary + result.auxiliary:
        assert getattr(metadata, block.field)[block.start : block.end] == block.text
    assert len(result.primary) + len(result.auxiliary) == len(source_blocks(metadata))


def test_music_selection_keeps_ncs_as_primary(lexicon):
    metadata = gaming_metadata().model_copy(
        update={
            "title": "Lost Sky - Dreams pt. II [NCS Release]",
            "description": "Lost Sky - Dreams pt. II\nMusic provided by NoCopyrightSounds.\n",
        }
    )
    result = filter_metadata(
        metadata,
        analyzer_for(
            ScriptedLLM(script=[ok(selected(metadata, [0, 1, 2]))]),
            AnalysisValidator(lexicon),
        ),
    )
    assert "NCS" in result.primary_text() and "Lost Sky" in result.primary_text()
    assert not result.auxiliary


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"block_999": True},
        {"block_0": "true"},
        {"block_0": 1},
        {"primary_ids": [0, 0]},
        {"primary_ids": [0], "invented": "사실"},
        "broken json",
    ],
)
def test_invalid_selection_fails_without_fallback(lexicon, value):
    llm = ScriptedLLM(script=[ok(value)])
    with pytest.raises(AnalysisSchemaError):
        filter_metadata(gaming_metadata(), analyzer_for(llm, AnalysisValidator(lexicon)))
    assert len(llm.calls) == 1


def test_provider_failure_propagates(lexicon):
    llm = ScriptedLLM(script=[LLMProviderError("local failure")])
    with pytest.raises(LLMProviderError):
        filter_metadata(gaming_metadata(), analyzer_for(llm, AnalysisValidator(lexicon)))
    assert len(llm.calls) == 1


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
def test_incomplete_selection_fails(lexicon, reason):
    raw = ok(selected(gaming_metadata(), [0])).model_copy(update={"stop_reason": reason})
    with pytest.raises(AnalysisSchemaError):
        filter_metadata(gaming_metadata(), analyzer_for(ScriptedLLM(script=[raw]), AnalysisValidator(lexicon)))


def test_title_only_and_long_unicode_offsets(lexicon):
    metadata = gaming_metadata().model_copy(update={"description": ""})
    result = filter_metadata(
        metadata,
        analyzer_for(
            ScriptedLLM(script=[ok(selected(metadata, [0]))]),
            AnalysisValidator(lexicon),
        ),
    )
    assert result.basis == "title_only" and len(result.primary) == 1
    metadata = metadata.model_copy(update={"description": "가" * 1100 + "\r\n\n#게임\n"})
    for block in source_blocks(metadata):
        assert getattr(metadata, block.field)[block.start : block.end] == block.text


def test_all_auxiliary_is_failure(lexicon):
    metadata = gaming_metadata()
    llm = ScriptedLLM(script=[ok(selected(metadata, []))])
    with pytest.raises(AnalysisSchemaError, match="핵심 주제 근거"):
        filter_metadata(metadata, analyzer_for(llm, AnalysisValidator(lexicon)))


def test_excessive_blocks_fail_without_silent_truncation(lexicon):
    metadata = gaming_metadata().model_copy(update={"description": "주제\n" * 256})
    llm = ScriptedLLM()
    with pytest.raises(AnalysisSchemaError, match="상한"):
        filter_metadata(metadata, analyzer_for(llm, AnalysisValidator(lexicon)))
    assert not llm.calls


def test_scoped_generation_keeps_validator_and_metadata_only_instruction(lexicon):
    from jupjup.ingest.chunking import AnalysisInput
    from tests.unit.test_llm_analyzer import SOURCE, VALID

    llm = ScriptedLLM(script=[ok(VALID)])
    analyzer = analyzer_for(llm, AnalysisValidator(lexicon))
    generated, meta = analyzer.analyze_youtube_metadata(AnalysisInput(mode="single", text=SOURCE))
    assert generated.summary == VALID["summary"]
    assert "제목·설명 기준" in llm.calls[0].system
    assert "culture_media" in llm.calls[0].system
    assert meta.prompt_version.endswith("youtube_metadata_scope_v1")
    with pytest.raises(ValueError):
        analyzer.analyze_youtube_metadata(AnalysisInput(mode="map_reduce", chunks=[]))


def test_short_metadata_tag_retry_names_hashtag_sources_without_weakening_validation(lexicon):
    import copy

    from jupjup.ingest.chunking import AnalysisInput
    from tests.unit.test_llm_analyzer import SOURCE, VALID, ScriptedLLM, analyzer_for, ok

    short_source = f"{SOURCE} #발로란트 #김된모 #레디언트"
    insufficient = copy.deepcopy(VALID)
    insufficient["representative_tags"] = ["발로란트", "김된모"]
    llm = ScriptedLLM(script=[ok(insufficient), ok(VALID)])
    analyzer = analyzer_for(llm, AnalysisValidator(lexicon))
    generated, meta = analyzer.analyze_youtube_metadata(AnalysisInput(mode="single", text=short_source))
    assert len(llm.calls) == 1
    assert generated.representative_tags[:3] == ["발로란트", "김된모", "레디언트"]
    assert meta.attempts == 1


def test_metadata_retry_rejects_invented_tag_and_howto_category(lexicon):
    import copy

    from jupjup.ingest.chunking import AnalysisInput
    from tests.unit.test_llm_analyzer import VALID, ScriptedLLM, analyzer_for, ok

    source = "모든 레디언트는 결국 저를 통합니다\n#발로란트 #김된모"
    wrong = copy.deepcopy(VALID)
    wrong["summary"] = "제목·설명 기준으로 발로란트 영상입니다. 해시태그에는 김된모가 있습니다."
    wrong["evidence"] = [{"claim": "주제", "source_span": "#발로란트 #김된모"}]
    wrong["representative_tags"] = ["발로란티브", "김된모", "레디언트"]
    wrong["detail_tags"]["category"] = "howto_recipe"
    correct = copy.deepcopy(wrong)
    correct["representative_tags"] = ["발로란트", "김된모", "레디언트"]
    correct["detail_tags"]["category"] = "culture_media"
    llm = ScriptedLLM(script=[ok(wrong), ok(correct)])
    analyzer = analyzer_for(llm, AnalysisValidator(lexicon))

    generated, meta = analyzer.analyze_youtube_metadata(AnalysisInput(mode="single", text=source))

    assert len(llm.calls) == 1
    assert generated.representative_tags == correct["representative_tags"]
    assert generated.detail_tags["category"] == "culture_media"
    assert meta.attempts == 1


def test_metadata_repair_recovers_grounded_hashtags_and_title_tokens():
    source = "제목: 모든 레디언트는 결국 저를 통합니다\n설명: #발로란트 #김된모"
    value = {
        "representative_tags": ["발로란트트랙", "ncs공개곡", "음악소개"],
        "detail_tags": {"category": "howto_recipe", "schema_version": 1},
    }

    repaired = repair_metadata_output(value, source)

    assert repaired["representative_tags"] == ["발로란트", "김된모", "레디언트"]
    assert repaired["detail_tags"]["category"] == "culture_media"


def test_metadata_repair_safely_grounded_title_and_hashtag_only_output():
    source = "제목: 모든 레디언트는 결국 저를 통합니다\n설명: #발로란트 #김된모"
    value = {
        "summary": "발로란티브 게임의 인기 캐릭터 김된모를 소개하는 영상입니다.",
        "representative_tags": ["발로란트트랙", "ncs공개곡", "음악소개"],
        "detail_tags": {
            "schema_version": 1,
            "category": "culture_media",
            "topics": ["발로란티브 게임", "인기 캐릭터"],
            "keywords": ["발로란티브", "공부자료"],
            "entities": [{"type": "person", "name": "김된모"}, {"type": "work", "name": "발로란티브"}],
            "purpose": ["과제", "공부자료"],
            "save_intent": {"labels": ["과제", "공부자료"], "confidence": 0.9, "inferred": True},
        },
        "save_intent": {"labels": ["과제", "공부자료"], "confidence": 0.9, "rationale": "공부할 내용이다."},
    }

    repaired = repair_metadata_output(value, source)

    assert repaired["summary"] == (
        "제목·설명 기준으로, 이 영상은 발로란트 관련 콘텐츠입니다. "
        "제목은 '모든 레디언트는 결국 저를 통합니다'이며 설명에는 #발로란트, #김된모가 표시되어 있습니다."
    )
    assert repaired["representative_tags"] == ["발로란트", "김된모", "레디언트"]
    detail = repaired["detail_tags"]
    assert detail["topics"] == ["발로란트"]
    assert detail["keywords"] == ["발로란트", "김된모", "레디언트"]
    assert detail["entities"] == [{"type": "person", "name": "김된모"}]
    assert detail["purpose"] == ["정보보관"]
    assert detail["save_intent"]["labels"] == ["정보보관"]
    assert repaired["save_intent"]["labels"] == ["정보보관"]


def test_metadata_repair_removes_poisoned_optional_detail_fields_on_focused_path():
    source = "제목: 오늘의 한 장면\n설명: #발로란티"
    value = {
        "detail_tags": {
            "schema_version": 1,
            "category": "culture_media",
            "topics": ["wrong"],
            "keywords": ["wrong"],
            "entities": [{"type": "other", "name": "발로란티"}],
            "locations": [{"name": "서울"}],
            "purpose": ["wrong"],
            "save_intent": {"labels": ["wrong"], "confidence": 0.9, "inferred": True},
            "attributes": ["academic"],
            "time_mentions": ["#발로란티"],
        }
    }

    repaired = repair_metadata_output(value, source)

    assert set(repaired["detail_tags"]) == {
        "schema_version", "category", "topics", "keywords", "entities", "locations", "purpose", "save_intent"
    }
    assert repaired["detail_tags"]["entities"] == [{"type": "other", "name": "발로란티"}]
    assert repaired["detail_tags"]["locations"] == []


def test_metadata_repair_does_not_rewrite_music_metadata_without_hashtags():
    source = "제목: Lost Sky - Dreams pt. II [NCS Release]"
    value = {
        "summary": "원래 요약",
        "representative_tags": ["Lost Sky", "Dreams", "Dreams pt. II"],
        "detail_tags": {"keywords": ["원래 키워드"]},
        "save_intent": {"labels": ["공부자료"]},
    }
    repaired = repair_metadata_output(value, source)
    assert repaired["summary"] == value["summary"]
    assert repaired["detail_tags"] == value["detail_tags"]
    assert repaired["save_intent"] == value["save_intent"]


def test_metadata_repair_prefers_exact_llm_tags_after_hashtags_and_preserves_music():
    source = "제목: Lost Sky - Dreams pt. II (feat. Sara Skinner) [NCS Release]"
    value = {
        "representative_tags": ["Lost Sky", "Dreams", "Sara Skinner"],
        "detail_tags": {"category": "howto_recipe", "schema_version": 1},
    }

    repaired = repair_metadata_output(value, source)

    assert repaired["representative_tags"] == value["representative_tags"]
    assert repaired["detail_tags"]["category"] == "culture_media"

    ncs_title = "제목: Lost Sky - Dreams pt. II [NCS Release]"
    ncs_value = {
        "representative_tags": ["Lost Sky", "Dreams", "Dreams pt. II"],
        "detail_tags": {"category": "howto_recipe", "schema_version": 1},
    }
    ncs_repaired = repair_metadata_output(ncs_value, ncs_title)
    assert ncs_repaired["representative_tags"] == ncs_value["representative_tags"]
    assert ncs_repaired["detail_tags"]["category"] == "culture_media"


def test_metadata_repair_leaves_unclear_howto_and_insufficient_tags_unchanged():
    source = "제목: 새 제품 소개\n설명: 자세한 정보"
    value = {
        "representative_tags": ["제품", "소개", "정보"],
        "detail_tags": {"category": "howto_recipe", "schema_version": 1},
    }

    repaired = repair_metadata_output(value, source)

    assert repaired == value

    weak_title = "제목: 모든 저를 통합니다\n설명: 내용"
    weak_value = {
        "representative_tags": ["모든", "저를", "통합니다"],
        "detail_tags": {"category": "howto_recipe", "schema_version": 1},
    }
    assert repair_metadata_output(weak_value, weak_title) == weak_value
