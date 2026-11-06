"""판정기 κ 보정 도구 (설계 design_local_analyzer.md 8.3절 κ 보정, 8.4절, 13절 Q-LA3·Q-LA10).

- ``sample_for_labeling``: dev 요약 문장(≥100)과 핵심 사실 쌍(≥60)을 후보 프로필에서 고르게, seed 고정으로 뽑는다.
- ``cohen_kappa``: Cohen's κ. 3분류와 이진(문장: unsupported 대 나머지, 핵심 사실: covered 대 나머지)을 낸다.
- ``calibrate``: 사람 라벨과 판정기 판정을 맞대어 ``JudgeCalibration``을 만든다. **이진 κ ≥ 0.7**이 통과 기준이다.
- ``calibration_status``: 하네스가 판정기 결과를 합격 판단에 써도 되는지 고른다. 보정 파일의 판정기 프로필,
  ``recording_model_id``, 프롬프트 sha256이 지금 설정과 모두 같아야 한다 (프롬프트를 바꾸면 다시 잰다).

라벨 파일은 dev 합성 골든에서만 만든다 (8.2절 4번). 이 모듈은 네트워크와 llama_cpp를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from jupjup.eval.judge import (
    JUDGE_FAILED,
    KeyFactJudgment,
    SentenceJudgment,
    bm25_top_sentences,
    split_sentences,
)

KAPPA_THRESHOLD = 0.7
MIN_SENTENCES = 100
MIN_KEYFACTS = 60
DEFAULT_SEED = 20261102
EXCERPT_SENTENCES = 5
SENTENCE_LABELS: tuple[str, ...] = ("supported", "partially", "unsupported")
KEYFACT_LABELS: tuple[str, ...] = ("covered", "partial", "missing")
CALIBRATION_FORMAT: Literal[1] = 1


def cohen_kappa(left: Sequence[str], right: Sequence[str], categories: Sequence[str] | None = None) -> float | None:
    """Cohen's κ = (p_o − p_e) / (1 − p_e). 길이가 다르면 ``ValueError``. 비었거나 p_e = 1이면 ``None``(정의 안 됨)."""
    if len(left) != len(right):
        raise ValueError("두 라벨 열의 길이가 같아야 합니다")
    n = len(left)
    if n == 0:
        return None
    labels = list(categories) if categories is not None else sorted(set(left) | set(right))
    unknown = (set(left) | set(right)) - set(labels)
    if unknown:
        raise ValueError(f"범주 밖 라벨이 있습니다: {sorted(unknown)}")
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / n
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum(left_counts[label] * right_counts[label] for label in labels) / (n * n)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def binarize(labels: Sequence[str], positive: str) -> list[str]:
    return [positive if label == positive else "other" for label in labels]


# --- 라벨 파일 -----------------------------------------------------------------------------------------------------


class SentenceLabelRow(BaseModel):
    """요약 문장 1개. 사람이 ``label``을 채운다. ``summary``는 판정기를 평가 때와 같은 요청으로 다시 부르려고 둔다."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sentence"] = "sentence"
    sample_id: str
    source_id: str
    profile: str
    sentence_index: int = Field(ge=0)
    sentence: str
    summary: str
    source_excerpt: str
    label: Literal["supported", "partially", "unsupported"] | None = None
    annotator: str | None = None  # "human" 이외(예: "ai_consensus")면 보정 리포트에 "사람 판정 아님"을 표시
    note: str = ""


class KeyFactLabelRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["keyfact"] = "keyfact"
    sample_id: str
    source_id: str
    profile: str
    fact_index: int = Field(ge=0)
    fact: str
    summary: str
    label: Literal["covered", "partial", "missing"] | None = None
    annotator: str | None = None
    note: str = ""


LabelRow = Annotated[SentenceLabelRow | KeyFactLabelRow, Field(discriminator="kind")]
_ROW_ADAPTER: TypeAdapter[SentenceLabelRow | KeyFactLabelRow] = TypeAdapter(LabelRow)


def load_label_rows(path: Path) -> list[SentenceLabelRow | KeyFactLabelRow]:
    rows: list[SentenceLabelRow | KeyFactLabelRow] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"라벨 파일을 읽지 못했습니다: {path}: {exc}") from exc
    seen: set[str] = set()
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = _ROW_ADAPTER.validate_json(line)
        except ValidationError as exc:
            raise ValueError(f"라벨 파일 {path.name} {number}번째 줄 형식 오류: {exc.errors()[0]['msg']}") from exc
        if row.sample_id in seen:
            raise ValueError(f"라벨 파일 {path.name}에 sample_id가 중복됩니다: {row.sample_id}")
        seen.add(row.sample_id)
        rows.append(row)
    return rows


def dump_label_rows(rows: Sequence[SentenceLabelRow | KeyFactLabelRow]) -> str:
    return "".join(
        json.dumps(row.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
    )


def labels_written(path: Path) -> bool:
    """이미 사람 라벨이 하나라도 있는 파일인가 (judge-sample이 덮어쓰지 않도록)."""
    if not path.exists():
        return False
    return any(row.label is not None for row in load_label_rows(path))


# --- 표집 ----------------------------------------------------------------------------------------------------------


class SummarySample(BaseModel):
    """후보 프로필 1개의 dev 건 1개 분석 결과 (표집 입력)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str
    source_id: str
    summary: str
    source_text: str
    key_facts: list[str]


def source_excerpt(sentence: str, source_text: str, k: int = EXCERPT_SENTENCES) -> str:
    """라벨 도구용 원문 발췌: BM25 상위 k개 원문 문장 (원문 순서, 문장 번호 포함)."""
    sentences = split_sentences(source_text)
    picked = bm25_top_sentences(sentence, sentences, k)
    return "\n".join(f"[s{index}] {' '.join(sentences[index].split())}" for index in picked)


def _round_robin[T](pools: dict[str, list[T]], limit: int) -> list[T]:
    """프로필별로 섞어 둔 목록에서 번갈아 하나씩 꺼낸다 (프로필 이름 순서, 고르게)."""
    picked: list[T] = []
    queues = {name: list(items) for name, items in sorted(pools.items())}
    while len(picked) < limit and any(queues.values()):
        for name in sorted(queues):
            if queues[name] and len(picked) < limit:
                picked.append(queues[name].pop(0))
    return picked


def sample_for_labeling(
    samples: Sequence[SummarySample],
    *,
    n_sentences: int = MIN_SENTENCES,
    n_keyfacts: int = MIN_KEYFACTS,
    seed: int = DEFAULT_SEED,
) -> list[SentenceLabelRow | KeyFactLabelRow]:
    """문장·핵심 사실 쌍을 프로필마다 seed로 섞어 번갈아 뽑는다. 결과는 (종류, 프로필, source_id, 번호) 순으로 정렬."""
    sentence_pools: dict[str, list[SentenceLabelRow]] = {}
    keyfact_pools: dict[str, list[KeyFactLabelRow]] = {}
    for sample in sorted(samples, key=lambda item: (item.profile, item.source_id)):
        for index, sentence in enumerate(split_sentences(sample.summary)):
            sentence_pools.setdefault(sample.profile, []).append(
                SentenceLabelRow(
                    sample_id=f"s:{sample.profile}:{sample.source_id}:{index}",
                    source_id=sample.source_id,
                    profile=sample.profile,
                    sentence_index=index,
                    sentence=sentence,
                    summary=sample.summary,
                    source_excerpt=source_excerpt(sentence, sample.source_text),
                )
            )
        for index, fact in enumerate(sample.key_facts):
            keyfact_pools.setdefault(sample.profile, []).append(
                KeyFactLabelRow(
                    sample_id=f"k:{sample.profile}:{sample.source_id}:{index}",
                    source_id=sample.source_id,
                    profile=sample.profile,
                    fact_index=index,
                    fact=fact,
                    summary=sample.summary,
                )
            )
    for profile, pool in sorted(sentence_pools.items()):
        random.Random(f"{seed}:sentence:{profile}").shuffle(pool)
    for profile, kpool in sorted(keyfact_pools.items()):
        random.Random(f"{seed}:keyfact:{profile}").shuffle(kpool)
    sentences = sorted(
        _round_robin(sentence_pools, n_sentences),
        key=lambda row: (row.profile, row.source_id, row.sentence_index),
    )
    keyfacts = sorted(
        _round_robin(keyfact_pools, n_keyfacts),
        key=lambda row: (row.profile, row.source_id, row.fact_index),
    )
    return [*sentences, *keyfacts]


# --- 보정 ----------------------------------------------------------------------------------------------------------


class AgreementStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: Literal["faithfulness", "keyfact"]
    labeled: int
    unlabeled: int
    compared: int
    judge_failed: int
    min_items: int
    kappa_3class: float | None
    kappa_binary: float | None
    binary_positive: str
    threshold: float = KAPPA_THRESHOLD
    confusion: dict[str, dict[str, int]]  # 사람 라벨 → 판정기 판정 → 건수
    non_human_labels: int = 0
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class JudgeCalibration(BaseModel):
    """``jupjup eval judge-calibrate`` 결과. 하네스가 이 파일로 판정기 사용 여부를 정한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal[1] = CALIBRATION_FORMAT
    judge_profile: str
    recording_model_id: str
    prompts: dict[str, str]
    labels_file: str
    labels_sha256: str
    faithfulness: AgreementStats
    keyfact: AgreementStats
    human_labels: bool  # False면 Q-LA3 준-사람 라벨. PRD 의미의 보정으로 주장하지 않는다


def agreement(
    task: Literal["faithfulness", "keyfact"],
    human: Sequence[str | None],
    judged: Sequence[str],
    *,
    annotators: Sequence[str | None] = (),
) -> AgreementStats:
    """사람 라벨이 있고 판정기가 실패하지 않은 쌍만 비교한다. 판정기 실패는 따로 세고 κ에서 뺀다."""
    if len(human) != len(judged):
        raise ValueError("사람 라벨과 판정 수가 다릅니다")
    categories = SENTENCE_LABELS if task == "faithfulness" else KEYFACT_LABELS
    positive = "unsupported" if task == "faithfulness" else "covered"
    min_items = MIN_SENTENCES if task == "faithfulness" else MIN_KEYFACTS
    pairs = [(h, j) for h, j in zip(human, judged, strict=True) if h is not None and j != JUDGE_FAILED]
    failed = sum(h is not None and j == JUDGE_FAILED for h, j in zip(human, judged, strict=True))
    labeled = sum(h is not None for h in human)
    left = [h for h, _ in pairs]
    right = [j for _, j in pairs]
    kappa3 = cohen_kappa(left, right, categories)
    kappa2 = cohen_kappa(binarize(left, positive), binarize(right, positive), (positive, "other"))
    confusion = {h: {j: 0 for j in categories} for h in categories}
    for h, j in pairs:
        confusion[h][j] += 1
    non_human = sum(
        1 for h, annotator in zip(human, annotators, strict=False) if h is not None and annotator not in (None, "human")
    )
    reasons: list[str] = []
    if len(pairs) < min_items:
        reasons.append(f"비교한 쌍 {len(pairs)}개 < 최소 {min_items}개")
    if kappa2 is None:
        reasons.append("이진 κ를 정의할 수 없음 (한 범주만 있음)")
    elif kappa2 < KAPPA_THRESHOLD:
        reasons.append(f"이진 κ {kappa2:.4f} < {KAPPA_THRESHOLD}")
    return AgreementStats(
        task=task,
        labeled=labeled,
        unlabeled=len(human) - labeled,
        compared=len(pairs),
        judge_failed=failed,
        min_items=min_items,
        kappa_3class=None if kappa3 is None else round(kappa3, 6),
        kappa_binary=None if kappa2 is None else round(kappa2, 6),
        binary_positive=positive,
        confusion=confusion,
        non_human_labels=non_human,
        passed=not reasons,
        reasons=reasons,
    )


SentenceJudgeFn = Callable[[str, str, Sequence[str]], list[SentenceJudgment]]  # (source_id, source, sentences)
KeyFactJudgeFn = Callable[[str, str, Sequence[str]], list[KeyFactJudgment]]  # (source_id, summary, facts)


def calibrate(
    rows: Sequence[SentenceLabelRow | KeyFactLabelRow],
    *,
    source_text: Callable[[str], str],
    key_facts: Callable[[str], list[str]],
    judge_sentences: SentenceJudgeFn,
    judge_keyfacts: KeyFactJudgeFn,
    judge_profile: str,
    recording_model_id: str,
    prompts: dict[str, str],
    labels_file: str,
    labels_sha256: str,
) -> JudgeCalibration:
    """판정기를 평가 때와 **같은 요청**(요약 전체 문장, 그 건의 핵심 사실 전체)으로 불러 표본 번호의 판정을 고른다.

    그래서 평가 녹화와 보정 녹화가 같은 행을 쓴다. 같은 (요약, 원문) 쌍은 한 번만 부른다.
    """
    sentence_cache: dict[tuple[str, str], list[SentenceJudgment]] = {}
    keyfact_cache: dict[tuple[str, str], list[KeyFactJudgment]] = {}
    human_s: list[str | None] = []
    judged_s: list[str] = []
    who_s: list[str | None] = []
    human_k: list[str | None] = []
    judged_k: list[str] = []
    who_k: list[str | None] = []
    for row in rows:
        if row.label is None:
            # 라벨이 없는 행은 판정기를 부르지 않는다 (미표기 수만 센다)
            if isinstance(row, SentenceLabelRow):
                human_s.append(None)
                judged_s.append(JUDGE_FAILED)
                who_s.append(None)
            else:
                human_k.append(None)
                judged_k.append(JUDGE_FAILED)
                who_k.append(None)
            continue
        if isinstance(row, SentenceLabelRow):
            key = (row.source_id, row.summary)
            if key not in sentence_cache:
                sentences = split_sentences(row.summary)
                sentence_cache[key] = judge_sentences(row.source_id, source_text(row.source_id), sentences)
            judgments = sentence_cache[key]
            if row.sentence_index >= len(judgments) or judgments[row.sentence_index].sentence != row.sentence:
                raise ValueError(f"{row.sample_id}: 요약을 다시 나눈 문장이 라벨 행의 문장과 다릅니다")
            human_s.append(row.label)
            judged_s.append(judgments[row.sentence_index].verdict)
            who_s.append(row.annotator)
        else:
            facts = key_facts(row.source_id)
            if row.fact_index >= len(facts) or facts[row.fact_index] != row.fact:
                raise ValueError(f"{row.sample_id}: 골든 핵심 사실이 라벨 행의 사실과 다릅니다")
            kkey = (row.source_id, row.summary)
            if kkey not in keyfact_cache:
                keyfact_cache[kkey] = judge_keyfacts(row.source_id, row.summary, facts)
            human_k.append(row.label)
            judged_k.append(keyfact_cache[kkey][row.fact_index].verdict)
            who_k.append(row.annotator)
    faith = agreement("faithfulness", human_s, judged_s, annotators=who_s)
    keyfact = agreement("keyfact", human_k, judged_k, annotators=who_k)
    return JudgeCalibration(
        judge_profile=judge_profile,
        recording_model_id=recording_model_id,
        prompts=dict(sorted(prompts.items())),
        labels_file=labels_file,
        labels_sha256=labels_sha256,
        faithfulness=faith,
        keyfact=keyfact,
        human_labels=faith.non_human_labels == 0 and keyfact.non_human_labels == 0,
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_calibration_path(golden_dir: Path, judge_profile: str) -> Path:
    return golden_dir / f"judge_calibration.{judge_profile}.json"


class CalibrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    faithfulness: bool
    keyfact: bool
    reason: str
    kappa_binary_faithfulness: float | None = None
    kappa_binary_keyfact: float | None = None
    human_labels: bool | None = None


def calibration_status(
    path: Path | None,
    *,
    judge_profile: str,
    recording_model_id: str,
    prompts: dict[str, str],
) -> CalibrationStatus:
    """보정 파일이 없거나, 판정기·모델·프롬프트가 다르거나, κ 미달이면 그 과제는 미보정이다."""
    if path is None or not path.is_file():
        return CalibrationStatus(faithfulness=False, keyfact=False, reason="보정 파일 없음")
    try:
        calibration = JudgeCalibration.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ValueError(f"판정기 보정 파일이 올바르지 않습니다: {path.name}") from exc
    mismatch = []
    if calibration.judge_profile != judge_profile:
        mismatch.append("판정기 프로필")
    if calibration.recording_model_id != recording_model_id:
        mismatch.append("recording_model_id")
    if calibration.prompts != dict(sorted(prompts.items())):
        mismatch.append("프롬프트 sha256")
    if mismatch:
        return CalibrationStatus(
            faithfulness=False, keyfact=False, reason=f"보정 뒤 바뀜: {', '.join(mismatch)} (다시 보정 필요)"
        )
    faith, keyfact = calibration.faithfulness.passed, calibration.keyfact.passed
    reasons = [*(f"충실도: {r}" for r in calibration.faithfulness.reasons)]
    reasons += [f"핵심 사실: {r}" for r in calibration.keyfact.reasons]
    return CalibrationStatus(
        faithfulness=faith,
        keyfact=keyfact,
        reason="보정 통과" if faith and keyfact else "; ".join(reasons),
        kappa_binary_faithfulness=calibration.faithfulness.kappa_binary,
        kappa_binary_keyfact=calibration.keyfact.kappa_binary,
        human_labels=calibration.human_labels,
    )
