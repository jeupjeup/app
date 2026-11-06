"""T25c: 자연문 인제스트 골든 v2, 템플릿 검사기, test 봉인, 사용자 표본 (design_local_analyzer.md 8.1절)."""

from __future__ import annotations

import filecmp
import importlib.util
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.config import REPO_ROOT
from jupjup.eval.ingest_golden_checks import (
    MAX_NGRAM_OVERLAP,
    SEAL_FILENAME,
    char_ngrams,
    check_ingest_templates,
    check_test_seal,
    compute_test_seal,
    ngram_overlap,
)
from jupjup.eval.ingest_harness import (
    INGEST_GOLDEN,
    INGEST_GOLDEN_V1,
    INGEST_V2_BASELINE,
    GoldenEntity,
    IngestEvalConfig,
    IngestEvalHarness,
    IngestGoldenSet,
    load_ingest_golden,
    validate_ingest_golden,
)

GROUP_SIZES = {"instagram": 15, "youtube": 15, "news": 15, "paper": 10, "kakaotalk": 10, "blog_web": 10, "image": 5}
DIFFICULT = {"long_text": 5, "ad_hashtag_heavy": 5, "mostly_english": 5, "number_date_dense": 5, "prompt_injection": 3}


def _load(golden_dir: Path = INGEST_GOLDEN) -> IngestGoldenSet:
    golden, errors = load_ingest_golden(golden_dir / "sources.jsonl", golden_dir / "annotations.jsonl")
    assert errors == []
    return golden


@pytest.fixture(scope="module")
def v2() -> IngestGoldenSet:
    return _load()


def test_v2_size_distribution_and_ai_draft_status(v2: IngestGoldenSet) -> None:
    assert validate_ingest_golden(v2, fixtures_root=INGEST_GOLDEN / "fixtures") == []
    assert len(v2.sources) == len(v2.annotations) == 80
    assert Counter(source.platform_group for source in v2.sources) == GROUP_SIZES
    assert Counter(case for source in v2.sources for case in source.difficult_cases) == DIFFICULT
    assert Counter(annotation.split for annotation in v2.annotations) == {"dev": 48, "test": 32}
    assert {annotation.review_status for annotation in v2.annotations} == {"ai_draft_unreviewed"}
    assert {annotation.annotator for annotation in v2.annotations} == {"ai"}
    assert all(source.source_id.startswith("ing2_") for source in v2.sources)
    # mock 재요청 배선이 dev·test 양쪽에서 돈다
    by_id = {annotation.source_id: annotation.split for annotation in v2.annotations}
    failures = Counter(by_id[source.source_id] for source in v2.sources if source.mock_failure)
    assert failures["dev"] >= 3 and failures["test"] >= 3


def test_v2_passes_template_checks_with_only_known_warnings(v2: IngestGoldenSet) -> None:
    report = check_ingest_templates(v2, INGEST_GOLDEN / "fixtures")
    assert report.errors == []
    # T25p에서 더한 경고(장소 level 누락, 긴 글 내부 반복)는 알려진 3건에만 남는다 (보고서 남은 문제)
    assert {w.split(":", 1)[0] for w in report.warnings} == {"ing2_0039", "ing2_0057", "ing2_0066"}
    assert all(overlap <= MAX_NGRAM_OVERLAP for overlap, _, _ in report.max_overlap.values())
    long_ids = {source.source_id for source in v2.sources if "long_text" in source.difficult_cases}
    assert all(report.text_lengths[source_id] > 40_000 for source_id in long_ids)


def test_v1_template_golden_is_rejected_by_template_checks() -> None:
    report = check_ingest_templates(_load(INGEST_GOLDEN_V1), INGEST_GOLDEN_V1 / "fixtures")
    assert any("8-gram 중복률" in error for error in report.errors)
    assert any("템플릿 금지 문구" in error for error in report.errors)


def test_ngram_overlap_detects_number_substitution_templates() -> None:
    first = char_ngrams("어니언 성수의 카페 핵심 정보 1 소개. 성수동 관련 디저트 자료 1 저장.")
    second = char_ngrams("어니언 성수의 카페 핵심 정보 2 소개. 성수동 관련 디저트 자료 2 저장.")
    natural = char_ngrams("망원동 새 카페가 문을 열었고 주말 이틀 동안 아메리카노를 싸게 판다.")
    assert ngram_overlap(first, second) > MAX_NGRAM_OVERLAP
    assert ngram_overlap(first, natural) <= MAX_NGRAM_OVERLAP


def _replace_text(golden: IngestGoldenSet, index: int, text: str) -> IngestGoldenSet:
    sources = [*golden.sources]
    source = sources[index]
    sources[index] = source.model_copy(update={"source": source.source.model_copy(update={"text": text})})
    return golden.model_copy(update={"sources": sources})


def _replace_gold(golden: IngestGoldenSet, index: int, **gold: object) -> IngestGoldenSet:
    annotations = [*golden.annotations]
    annotation = annotations[index]
    annotations[index] = annotation.model_copy(update={"gold": annotation.gold.model_copy(update=gold)})
    return golden.model_copy(update={"annotations": annotations})


def test_template_checker_flags_each_rule(v2: IngestGoldenSet) -> None:
    fixtures = INGEST_GOLDEN / "fixtures"
    first = v2.sources[0]
    assert first.source.text is not None
    banned = _replace_text(v2, 0, first.source.text + " 작성자가 직접 만든 평가용 원문입니다.")
    assert any("템플릿 금지 문구" in error for error in check_ingest_templates(banned, fixtures).errors)

    gold = v2.annotations[0].gold
    ungrounded = _replace_gold(v2, 0, entities=[*gold.entities, GoldenEntity(type="place", name="존재하지않는가게")])
    assert any("존재하지않는가게" in error for error in check_ingest_templates(ungrounded, fixtures).errors)

    claim_in_source = _replace_gold(v2, 0, forbidden_claims=["월요일"])
    assert any("forbidden_claim" in error for error in check_ingest_templates(claim_in_source, fixtures).errors)

    wrong_number = _replace_gold(v2, 0, key_facts=["오후 4시 무렵 갔을 때 35분가량 기다렸다", *gold.key_facts[1:]])
    assert any("숫자가 원문에 없습니다" in error for error in check_ingest_templates(wrong_number, fixtures).errors)

    copied = _replace_gold(v2, 0, key_facts=["참고로 월요일은 정기 휴무라 헛걸음하지 마세요", *gold.key_facts[1:]])
    assert any("부분 문자열" in warning for warning in check_ingest_templates(copied, fixtures).warnings)


def test_test_seal_tracks_test_gold_but_not_review_status_or_dev(tmp_path: Path, v2: IngestGoldenSet) -> None:
    assert check_test_seal(v2, INGEST_GOLDEN, required=True) == []
    digest, count = compute_test_seal(v2, INGEST_GOLDEN / "fixtures")
    assert count == 32
    assert (INGEST_GOLDEN / SEAL_FILENAME).read_text(encoding="utf-8").startswith(digest)

    test_index = next(index for index, item in enumerate(v2.annotations) if item.split == "test")
    dev_index = next(index for index, item in enumerate(v2.annotations) if item.split == "dev")
    reviewed = [*v2.annotations]
    reviewed[test_index] = reviewed[test_index].model_copy(
        update={"annotator": "human", "review_status": "human_reviewed"}
    )
    assert compute_test_seal(v2.model_copy(update={"annotations": reviewed}), INGEST_GOLDEN / "fixtures")[0] == digest
    dev_changed = _replace_gold(v2, dev_index, key_facts=["dev 쪽 수정"])
    assert compute_test_seal(dev_changed, INGEST_GOLDEN / "fixtures")[0] == digest
    test_changed = _replace_gold(v2, test_index, key_facts=["test 쪽 수정"])
    assert compute_test_seal(test_changed, INGEST_GOLDEN / "fixtures")[0] != digest
    assert any("봉인 불일치" in error for error in check_test_seal(test_changed, INGEST_GOLDEN, required=True))

    # fixture 바이트가 바뀌어도 봉인이 깨진다
    copy = tmp_path / "ingest"
    shutil.copytree(INGEST_GOLDEN, copy)
    test_ids = {item.source_id for item in v2.annotations if item.split == "test"}
    fixture = next(s.source.fixture for s in v2.sources if s.source_id in test_ids and s.source.fixture)
    assert fixture is not None
    (copy / "fixtures" / fixture).write_text("<html><body>바뀐 본문</body></html>", encoding="utf-8")
    assert any("봉인 불일치" in error for error in check_test_seal(_load(copy), copy, required=True))
    (copy / SEAL_FILENAME).unlink()
    assert any("없습니다" in error for error in check_test_seal(_load(copy), copy, required=True))


def _build_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "golden_ingest_v2" / "build.py"
    spec = importlib.util.spec_from_file_location("golden_ingest_v2_build", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def test_generator_reproduces_committed_files(tmp_path: Path) -> None:
    _build_module().write(tmp_path)
    produced = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file())
    assert produced
    for relative in produced:
        assert filecmp.cmp(tmp_path / relative, INGEST_GOLDEN / relative, shallow=False), relative


def test_user_sample_covers_groups_difficult_cases_and_both_splits(v2: IngestGoldenSet) -> None:
    rows = [
        json.loads(line)
        for line in (INGEST_GOLDEN / "sample_for_user.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert 20 <= len(rows) <= 30
    sources = {source.source_id: source for source in v2.sources}
    annotations = {annotation.source_id: annotation for annotation in v2.annotations}
    assert len({row["source_id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["source_id"] in sources
        assert row["gold"] == annotations[row["source_id"]].gold.model_dump(mode="json")
        assert row["user_verdict"] is None
    assert {row["platform_group"] for row in rows} == set(GROUP_SIZES)
    assert set(DIFFICULT) <= {case for row in rows for case in row["difficult_cases"]}
    assert {row["split"] for row in rows} == {"dev", "test"}


def test_default_golden_follows_mode() -> None:
    assert IngestEvalConfig().sources_path == INGEST_GOLDEN_V1 / "sources.jsonl"
    assert IngestEvalConfig(mode="recorded").sources_path == INGEST_GOLDEN / "sources.jsonl"
    assert IngestEvalConfig(mode="live").annotations_path == INGEST_GOLDEN / "annotations.jsonl"
    explicit = IngestEvalConfig(mode="recorded", sources_path=INGEST_GOLDEN_V1 / "sources.jsonl")
    assert explicit.sources_path == INGEST_GOLDEN_V1 / "sources.jsonl"


def test_validate_ingest_cli_exit_codes() -> None:
    runner = CliRunner()
    passed = runner.invoke(app, ["eval", "validate-ingest"])
    assert passed.exit_code == 0, passed.output
    assert "템플릿 검사·test 봉인 포함" in passed.output
    rejected = runner.invoke(app, ["eval", "validate-ingest", "--golden-dir", str(INGEST_GOLDEN_V1)])
    assert rejected.exit_code == 1
    legacy = runner.invoke(app, ["eval", "validate-ingest", "--golden-dir", str(INGEST_GOLDEN_V1), "--legacy"])
    assert legacy.exit_code == 0, legacy.output


@pytest.mark.eval
@pytest.mark.parametrize(("split", "expected"), [("dev", 48), ("test", 32)])
def test_v2_mock_gate_baseline_and_determinism(split: str, expected: int) -> None:
    config = IngestEvalConfig(
        split=split,  # type: ignore[arg-type]
        sources_path=INGEST_GOLDEN / "sources.jsonl",
        annotations_path=INGEST_GOLDEN / "annotations.jsonl",
        baseline_path=INGEST_V2_BASELINE,
    )
    first = IngestEvalHarness(config).run()
    second = IngestEvalHarness(config).run()
    assert first.gate.passed and first.gate.regression
    assert first.counts["sources"] == expected
    assert first.counts["retry_exercised"] > 0
    assert first.overall["injection_resistance"] == 1.0
    assert json.dumps(first.deterministic_dict(), ensure_ascii=False) == json.dumps(
        second.deterministic_dict(), ensure_ascii=False
    )


@pytest.mark.eval
def test_eval_ingest_cli_golden_option(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["eval", "ingest", "--mode", "mock", "--golden", "v2", "--split", "test", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "골든 v2 (data/golden/ingest)" in result.output
    config = json.loads((tmp_path / "eval_ingest_mock_test.json").read_text(encoding="utf-8"))["config"]
    assert config["sources_path"] == "data/golden/ingest/sources.jsonl"
    assert config["baseline_path"] == "data/baselines/ingest_v2.mock.json"
    bad = runner.invoke(app, ["eval", "ingest", "--golden", "v3", "--out", str(tmp_path)])
    assert bad.exit_code == 2


# --- T25p: T25c 검수 M1 (gold 자기모순), L1 (봉인), L3·L5 (검사기 경고) ----------------------------------------

KNOWN_LEVEL_WARNINGS = {
    # T25p에서 고치지 않은 건 (보고서 남은 문제). ing2_0039는 test라 봉인 원칙상, ing2_0057(dev)은 mock 리포트 바이트를
    # 바꾸지 않으려고 그대로 뒀다. 고치면 GOLD_REVISIONS에 이유를 남기고, test 건이면 다시 봉인한다.
    "ing2_0057: 장소 '부산'에 level이 없습니다",
    "ing2_0039: 장소 '경기 북부'에 level이 없습니다",
    "ing2_0039: 장소 '강원'에 level이 없습니다",
    "ing2_0039: 장소 '철원'에 level이 없습니다",
}


def test_m1_forbidden_claim_inside_own_gold_is_an_error(v2: IngestGoldenSet) -> None:
    """M1 재현: key_fact '입장료는 없다'와 forbidden_claim '입장료'가 같은 건에 있으면
    충실한 요약이 비충실 1.0이 된다."""
    index = next(i for i, a in enumerate(v2.annotations) if a.source_id == "ing2_0038")
    gold = v2.annotations[index].gold
    contradictory = _replace_gold(v2, index, forbidden_claims=["입장료", *gold.forbidden_claims])
    errors = check_ingest_templates(contradictory, INGEST_GOLDEN / "fixtures").errors
    assert any("ing2_0038" in e and "forbidden_claim '입장료'" in e and "key_facts" in e for e in errors), errors

    tag_clash = _replace_gold(v2, index, forbidden_claims=["빛축제"])
    assert any("representative_tags" in e for e in check_ingest_templates(tag_clash, INGEST_GOLDEN / "fixtures").errors)
    entity_clash = _replace_gold(v2, index, forbidden_claims=["누리천"])
    assert any("entities" in e for e in check_ingest_templates(entity_clash, INGEST_GOLDEN / "fixtures").errors)


def test_m1_one_character_forbidden_claim_is_an_error(v2: IngestGoldenSet) -> None:
    """M1 ③ 재현: forbidden_claim '굴'은 '얼굴'·'동굴'처럼 무관한 단어에도 걸린다."""
    index = next(i for i, a in enumerate(v2.annotations) if a.source_id == "ing2_0069")
    short = _replace_gold(v2, index, forbidden_claims=["굴"])
    errors = check_ingest_templates(short, INGEST_GOLDEN / "fixtures").errors
    assert any("ing2_0069" in e and "2자 이상" in e for e in errors), errors


def test_m1_fixed_records_and_reasons_are_logged() -> None:
    annotations = {
        json.loads(line)["source_id"]: json.loads(line)
        for line in (INGEST_GOLDEN / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert "입장료" not in annotations["ing2_0038"]["gold"]["forbidden_claims"]
    assert "입장료는 없다" in annotations["ing2_0038"]["gold"]["key_facts"]
    assert "굴" not in annotations["ing2_0069"]["gold"]["forbidden_claims"]
    manifest = json.loads((INGEST_GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    revisions = {row["source_id"]: row for row in manifest["gold_revisions"]}
    assert set(revisions) == {"ing2_0038", "ing2_0069"}
    assert all(row["split"] == "dev" and row["reason"] and row["change"] for row in revisions.values())
    assert manifest["seal_history"][0]["reason"]  # 처음 봉인 기록. test 건은 고치지 않아 봉인은 그대로다


def test_l3_l5_checker_warns_on_missing_location_level_and_repetitive_long_text(v2: IngestGoldenSet) -> None:
    report = check_ingest_templates(v2, INGEST_GOLDEN / "fixtures")
    long_warnings = {w for w in report.warnings if "고유 문장 비율" in w}
    assert {w.split(":", 1)[0] for w in long_warnings} == {"ing2_0066"}  # test 건, 보고서 남은 문제
    assert {w for w in report.warnings if "level" in w} == KNOWN_LEVEL_WARNINGS


def test_l1_build_refuses_to_reseal_without_reason(tmp_path: Path) -> None:
    build = _build_module()
    out = tmp_path / "ingest"
    shutil.copytree(INGEST_GOLDEN, out)
    build.write(out)  # 봉인이 같으면 그대로 쓴다
    (out / "test.sha256").write_text(
        "0" * 64 + "  test split 32 records (sources + fixtures + gold)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="--reseal"):
        build.write(out)
    build.write(out, reseal_reason="테스트: 봉인 다시 하기")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seal_history"][-1]["reason"] == "테스트: 봉인 다시 하기"
    assert (out / "test.sha256").read_text(encoding="utf-8") == (INGEST_GOLDEN / "test.sha256").read_text(
        encoding="utf-8"
    )
