"""``jupjup eval judge-sample|judge-calibrate``의 본체 (설계 design_local_analyzer.md 8.3절 κ 보정).

- judge-sample: 후보 프로필마다 dev split을 recorded(또는 배선 확인용 mock)로 돌려 요약을 모으고, 문장과 핵심 사실
  쌍을 seed 고정으로 고르게 뽑아 빈 라벨 파일을 만든다. **dev만** 쓴다 (8.2절 4번, test 봉인).
- judge-calibrate: 라벨 파일의 표본마다 판정기를 평가와 같은 요청으로 불러 κ를 내고 보정 파일을 쓴다.

원문은 저장소의 합성 골든이고 기기 밖으로 나가지 않는다. 네트워크를 쓰지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from jupjup.domain.errors import LLMCacheMiss
from jupjup.eval.ingest_harness import (
    INGEST_GOLDEN,
    IngestEvalConfig,
    IngestEvalHarness,
    golden_source_text,
    load_ingest_golden,
)
from jupjup.eval.ingest_runtime import (
    DEFAULT_LLM_RECORDINGS_DIR,
    DEFAULT_PROFILES_PATH,
    LiveLLMFactory,
    MissRecord,
    RunEstimate,
    build_eval_judges,
    estimate_run,
    miss_record,
    prepare_judge_setup,
    repo_relative,
)
from jupjup.eval.judge import KeyFactJudgment, SentenceJudgment
from jupjup.eval.judge_calibration import (
    DEFAULT_SEED,
    MIN_KEYFACTS,
    MIN_SENTENCES,
    JudgeCalibration,
    KeyFactLabelRow,
    SentenceLabelRow,
    SummarySample,
    calibrate,
    file_sha256,
    load_label_rows,
    sample_for_labeling,
)


class JudgeToolMiss(ValueError):
    """녹화 미스가 있어 표집·보정을 끝내지 못했다 (CLI 종료 2)."""

    def __init__(self, message: str, misses: Sequence[MissRecord]) -> None:
        super().__init__(message)
        self.misses = list(misses)


def estimate_calibration_run(
    labels_path: Path,
    judge: str,
    *,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    recordings_dir: Path = DEFAULT_LLM_RECORDINGS_DIR,
) -> RunEstimate:
    """라벨이 있는 고유 문장/핵심 사실 요청 수로 live 보정 시간을 추정한다."""
    rows = load_label_rows(labels_path)
    requests = {
        (row.kind, row.source_id, row.summary)
        for row in rows
        if row.label is not None
    }
    setup = prepare_judge_setup(profiles_path, judge, recordings_dir)
    return estimate_run(setup.spec, len(requests))


def collect_dev_summaries(
    profiles: Sequence[str],
    *,
    mode: Literal["mock", "recorded"] = "recorded",
    golden_dir: Path = INGEST_GOLDEN,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    recordings_dir: Path = DEFAULT_LLM_RECORDINGS_DIR,
) -> list[SummarySample]:
    """프로필마다 dev split 분석 결과를 모은다. 녹화 미스가 하나라도 있으면 ``JudgeToolMiss``."""
    if not profiles:
        raise ValueError("프로필을 하나 이상 주세요")
    golden, errors = load_ingest_golden(golden_dir / "sources.jsonl", golden_dir / "annotations.jsonl")
    if errors:
        raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
    facts = {annotation.source_id: list(annotation.gold.key_facts) for annotation in golden.annotations}
    samples: list[SummarySample] = []
    for profile in dict.fromkeys(profiles):
        config = IngestEvalConfig(
            mode=mode,
            profile=profile,
            split="dev",  # 판정기 보정용 라벨은 dev에서만 단다
            sources_path=golden_dir / "sources.jsonl",
            annotations_path=golden_dir / "annotations.jsonl",
            baseline_path=None,
            profiles_path=profiles_path,
            recordings_dir=recordings_dir,
        )
        harness = IngestEvalHarness(config)
        report = harness.run()
        if report.misses:
            raise JudgeToolMiss(f"프로필 {profile}의 녹화 미스 {len(report.misses)}건", report.misses)
        for source_id, (output, source_text) in sorted(harness.last_outputs.items()):
            if not output.summary.strip():
                continue
            samples.append(
                SummarySample(
                    profile=profile,
                    source_id=source_id,
                    summary=output.summary,
                    source_text=source_text,
                    key_facts=facts[source_id],
                )
            )
    return samples


def judge_sample(
    profiles: Sequence[str],
    *,
    mode: Literal["mock", "recorded"] = "recorded",
    n_sentences: int = MIN_SENTENCES,
    n_keyfacts: int = MIN_KEYFACTS,
    seed: int = DEFAULT_SEED,
    golden_dir: Path = INGEST_GOLDEN,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    recordings_dir: Path = DEFAULT_LLM_RECORDINGS_DIR,
) -> list[SentenceLabelRow | KeyFactLabelRow]:
    samples = collect_dev_summaries(
        profiles, mode=mode, golden_dir=golden_dir, profiles_path=profiles_path, recordings_dir=recordings_dir
    )
    return sample_for_labeling(samples, n_sentences=n_sentences, n_keyfacts=n_keyfacts, seed=seed)


def judge_calibrate(
    labels_path: Path,
    judge: str,
    *,
    mode: Literal["recorded", "live"] = "recorded",
    golden_dir: Path = INGEST_GOLDEN,
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    recordings_dir: Path = DEFAULT_LLM_RECORDINGS_DIR,
    live_llm_factory: LiveLLMFactory | None = None,
    record: bool = False,
) -> JudgeCalibration:
    rows = load_label_rows(labels_path)
    golden, errors = load_ingest_golden(golden_dir / "sources.jsonl", golden_dir / "annotations.jsonl")
    if errors:
        raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
    annotations = {annotation.source_id: annotation for annotation in golden.annotations}
    sources = {source.source_id: source for source in golden.sources}
    for row in rows:
        annotation = annotations.get(row.source_id)
        if annotation is None:
            raise ValueError(f"{row.sample_id}: 골든에 없는 source_id입니다")
        if annotation.split != "dev":
            raise ValueError(f"{row.sample_id}: 보정 라벨은 dev 건만 씁니다 ({row.source_id}는 {annotation.split})")
    setup = prepare_judge_setup(profiles_path, judge, recordings_dir)
    build_eval_judges(setup, mode=mode, live_llm_factory=live_llm_factory, record=record)
    assert setup.faithfulness is not None and setup.keyfact is not None
    faithfulness, keyfact = setup.faithfulness, setup.keyfact
    texts: dict[str, str] = {}
    misses: list[MissRecord] = []

    def source_text(source_id: str) -> str:
        if source_id not in texts:
            texts[source_id] = golden_source_text(golden_dir / "sources.jsonl", sources[source_id])
        return texts[source_id]

    def judge_sentences(source_id: str, text: str, sentences: Sequence[str]) -> list[SentenceJudgment]:
        try:
            return faithfulness.judge(text, sentences)
        except LLMCacheMiss as exc:
            misses.append(miss_record(source_id, exc))
            return [SentenceJudgment(sentence=sentence, verdict="judge_failed") for sentence in sentences]

    def judge_keyfacts(source_id: str, summary: str, facts: Sequence[str]) -> list[KeyFactJudgment]:
        try:
            return keyfact.judge(summary, facts)
        except LLMCacheMiss as exc:
            misses.append(miss_record(source_id, exc))
            return [KeyFactJudgment(fact=fact, verdict="judge_failed") for fact in facts]

    result = calibrate(
        rows,
        source_text=source_text,
        key_facts=lambda source_id: list(annotations[source_id].gold.key_facts),
        judge_sentences=judge_sentences,
        judge_keyfacts=judge_keyfacts,
        judge_profile=setup.profile.name,
        recording_model_id=setup.model_id,
        prompts=setup.prompt_sha256s(),
        labels_file=repo_relative(labels_path),
        labels_sha256=file_sha256(labels_path),
    )
    if misses:
        raise JudgeToolMiss(f"판정기 녹화 미스 {len(misses)}건", misses)
    return result
