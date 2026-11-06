"""Template and gold-grounding checks for the natural-language ingest golden v2 (design 8.1, T25c).

``validate_ingest_golden``(구조 검사)와 따로, v2 골든이 템플릿 문장으로 되돌아가지 않았는지와 gold가 원문에
근거하는지를 본다. ``jupjup eval validate-ingest``가 둘을 함께 돌린다. v1(템플릿) 골든은 ``legacy=True``로
구조 검사만 한다.

- (a) 같은 플랫폼군 원문 사이 글자 8-gram 중복률 ≤ 0.15
- (b) 금지 문구(``핵심 정보 \\d+``, ``평가용 원문``, ``자료 \\d+ 저장``) 없음
- (c) key_facts가 원문 문장의 완전 복사가 아님 (정규화 후 부분 문자열이면 경고)
- (d) gold 엔티티·장소 이름이 원문에 있음
- forbidden_claims: 원문에 없음, 2자 이상(공백 제외), 같은 건의 key_facts·대표/허용 태그·엔티티 이름에 들어 있지 않음
  (T25c 검수 M1: '입장료는 없다'를 담은 충실한 요약이 forbidden '입장료'로 비충실 1.0이 됐다)
- 경고: 장소 level 누락, 긴 글 내부 고유 문장 비율 < 0.5 (T25c 검수 L3·L5)
- 그 밖: key_facts의 숫자가 원문에 있음, 플랫폼군별 category·save_intent 2종 이상,
  어려운 사례가 이름값을 하는지(긴 글 4만 자 초과, 영어 중심, 해시태그 과다, 숫자 밀집, 주입 문장 포함)

``test.sha256``은 test split 원문·fixture·gold의 결합 해시다. ``annotator``·``review_status``는 넣지 않는다
(검수 상태만 바뀌어도 봉인이 깨지지 않게). gold나 원문을 고치면 봉인을 다시 하고 이유를 남겨야 한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from jupjup.domain.errors import JupjupError
from jupjup.eval.judge import split_sentences
from jupjup.ingest.extract import extract_snapshot
from jupjup.ingest.fetch import (
    FetcherRouter,
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    InlineTextFetcher,
    SourceFetcher,
)
from jupjup.text.normalize import normalize_text

if TYPE_CHECKING:
    from jupjup.eval.ingest_harness import IngestGoldenSet, IngestGoldenSource

NGRAM_SIZE = 8
MAX_NGRAM_OVERLAP = 0.15
FORBIDDEN_TEMPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"핵심 정보 \d+"),
    re.compile(r"평가용 원문"),
    re.compile(r"자료 \d+ 저장"),
)
LONG_TEXT_MIN_CHARS = 40_000
MOSTLY_ENGLISH_MIN_RATIO = 0.6
AD_HASHTAG_MIN_COUNT = 15
NUMBER_DENSE_MIN_TERMS = 10
LONG_TEXT_MIN_UNIQUE_SENTENCE_RATIO = 0.5
FORBIDDEN_CLAIM_MIN_CHARS = 2
SEAL_FILENAME = "test.sha256"
_FIXED_CLOCK = datetime(2026, 1, 1, tzinfo=UTC)
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_HASHTAG = re.compile(r"#[0-9A-Za-z가-힣_]+")


@dataclass
class TemplateCheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 플랫폼군별 최대 8-gram 중복률과 그 쌍
    max_overlap: dict[str, tuple[float, str, str]] = field(default_factory=dict)
    text_lengths: dict[str, int] = field(default_factory=dict)


def golden_source_text(source: IngestGoldenSource, fixtures_root: Path) -> str:
    """하네스와 같은 fetch·extract 경로로 원문 텍스트를 만든다 (네트워크 없음, 고정 시계)."""
    fetchers: list[SourceFetcher] = [InlineTextFetcher(clock=lambda: _FIXED_CLOCK)]
    if fixtures_root.is_dir():
        fetchers.extend(
            [
                FixtureHtmlFetcher(fixtures_root, clock=lambda: _FIXED_CLOCK),
                FixtureTranscriptFetcher(fixtures_root, clock=lambda: _FIXED_CLOCK),
            ]
        )
    raw = FetcherRouter(fetchers).fetch(source.source)
    draft = extract_snapshot(raw, source.platform)
    return "\n\n".join(part for part in (draft.text, draft.ocr_text) if part)


def char_ngrams(text: str, size: int = NGRAM_SIZE) -> set[str]:
    compact = re.sub(r"\s+", "", normalize_text(text))
    return {compact[index : index + size] for index in range(len(compact) - size + 1)}


def ngram_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text))


def _grounded(name: str, normalized_source: str, compact_source: str) -> bool:
    normalized = normalize_text(name)
    return bool(normalized) and (normalized in normalized_source or _compact(name) in compact_source)


def _numbers(text: str) -> set[str]:
    """천 단위 쉼표를 지운 뒤의 숫자 묶음. ``12.13``(날짜)과 ``3.4``(소수)는 ``12``, ``13``처럼 나눠 본다."""
    return set(re.findall(r"\d+", _THOUSANDS.sub("", normalize_text(text))))


def _english_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isascii() for char in letters) / len(letters)


def check_ingest_templates(golden: IngestGoldenSet, fixtures_root: Path) -> TemplateCheckReport:
    report = TemplateCheckReport()
    annotations = {annotation.source_id: annotation for annotation in golden.annotations}
    texts: dict[str, str] = {}
    for source in golden.sources:
        try:
            texts[source.source_id] = golden_source_text(source, fixtures_root)
        except JupjupError as exc:
            report.errors.append(f"{source.source_id}: 원문 추출 실패 ({exc.code})")
    report.text_lengths = {source_id: len(text) for source_id, text in texts.items()}

    by_group: dict[str, list[str]] = defaultdict(list)
    for source in golden.sources:
        if source.source_id in texts:
            by_group[source.platform_group].append(source.source_id)
    for group, source_ids in sorted(by_group.items()):
        grams = {source_id: char_ngrams(texts[source_id]) for source_id in source_ids}
        worst = (0.0, "", "")
        for left, right in combinations(source_ids, 2):
            overlap = ngram_overlap(grams[left], grams[right])
            if overlap > worst[0]:
                worst = (overlap, left, right)
            if overlap > MAX_NGRAM_OVERLAP:
                report.errors.append(
                    f"{group}: {left}와 {right}의 8-gram 중복률 {overlap:.3f} > {MAX_NGRAM_OVERLAP} (템플릿 의심)"
                )
        report.max_overlap[group] = worst

    for source in golden.sources:
        source_id = source.source_id
        annotation = annotations.get(source_id)
        text = texts.get(source_id)
        if annotation is None or text is None:
            continue
        gold = annotation.gold
        normalized_source = normalize_text(text)
        compact_source = _compact(text)
        for label, value in [
            ("원문", text),
            ("title", source.title or ""),
            *[("key_facts", f) for f in gold.key_facts],
        ]:
            for pattern in FORBIDDEN_TEMPLATE_PATTERNS:
                if pattern.search(value):
                    report.errors.append(f"{source_id}: {label}에 템플릿 금지 문구 {pattern.pattern!r}")
        for fact in gold.key_facts:
            stripped = normalize_text(fact).rstrip(" .!?")
            if stripped and stripped in normalized_source:
                report.warnings.append(f"{source_id}: key_fact가 원문 부분 문자열과 같습니다 (바꿔 쓰기 권장): {fact}")
            missing = sorted(_numbers(fact) - _numbers(text))
            if missing:
                report.errors.append(f"{source_id}: key_fact 숫자가 원문에 없습니다 {missing}: {fact}")
        for entity in gold.entities:
            if not _grounded(entity.name, normalized_source, compact_source):
                report.errors.append(f"{source_id}: 엔티티 {entity.name!r}가 원문에 없습니다")
        for location in gold.locations:
            if not _grounded(location.name, normalized_source, compact_source):
                report.errors.append(f"{source_id}: 장소 {location.name!r}가 원문에 없습니다")
        for location in gold.locations:
            if not location.level:
                report.warnings.append(f"{source_id}: 장소 {location.name!r}에 level이 없습니다")
        own_gold = [
            ("key_facts", gold.key_facts),
            ("representative_tags", gold.representative_tags),
            ("acceptable_tags", gold.acceptable_tags),
            ("entities", [entity.name for entity in gold.entities]),
        ]
        for claim in gold.forbidden_claims:
            normalized_claim = normalize_text(claim)
            if normalized_claim in normalized_source:
                report.errors.append(f"{source_id}: forbidden_claim {claim!r}가 원문에 있습니다 (충실한 요약을 벌점)")
            if len(_compact(claim)) < FORBIDDEN_CLAIM_MIN_CHARS:
                report.errors.append(
                    f"{source_id}: forbidden_claim {claim!r}는 {FORBIDDEN_CLAIM_MIN_CHARS}자 이상이어야 합니다 "
                    "(한 글자는 무관한 단어에도 걸린다. '굴을 넣'처럼 서술형으로 쓴다)"
                )
            for label, values in own_gold:
                if any(normalized_claim in normalize_text(value) for value in values):
                    report.errors.append(
                        f"{source_id}: forbidden_claim {claim!r}가 같은 건의 {label}에 들어 있습니다 "
                        "(gold 자기모순: 그 내용을 담은 요약이 비충실 1.0이 된다)"
                    )
        if source.injection_target and normalize_text(source.injection_target) not in normalized_source:
            report.errors.append(f"{source_id}: injection_target이 원문에 없습니다")
        gold_text = normalize_text(gold.model_dump_json())
        if source.injection_target and normalize_text(source.injection_target) in gold_text:
            report.errors.append(f"{source_id}: gold에 주입 문구가 들어 있습니다")
        report.errors.extend(_difficult_case_errors(source, text, [*gold.key_facts]))
        if "long_text" in source.difficult_cases:
            sentences = split_sentences(text)
            ratio = len(set(sentences)) / len(sentences) if sentences else 1.0
            if ratio < LONG_TEXT_MIN_UNIQUE_SENTENCE_RATIO:
                report.warnings.append(
                    f"{source_id}: 긴 글 내부 고유 문장 비율 {ratio:.2f} < {LONG_TEXT_MIN_UNIQUE_SENTENCE_RATIO} "
                    "(반복 틀이 많아 실제 긴 글보다 쉬운 입력)"
                )

    for group, source_ids in sorted(by_group.items()):
        group_annotations = [annotations[source_id] for source_id in source_ids if source_id in annotations]
        categories = {annotation.gold.category for annotation in group_annotations}
        intents = {
            annotation.gold.save_intent.labels[0]
            for annotation in group_annotations
            if annotation.gold.save_intent.labels
        }
        if len(categories) < 2:
            report.errors.append(f"{group}: category가 한 가지뿐입니다 {sorted(categories)}")
        if len(intents) < 2:
            report.errors.append(f"{group}: 대표 save_intent가 한 가지뿐입니다 {sorted(intents)}")
    return report


def _difficult_case_errors(source: IngestGoldenSource, text: str, key_facts: list[str]) -> list[str]:
    errors: list[str] = []
    source_id = source.source_id
    cases = set(source.difficult_cases)
    if "long_text" in cases and len(text) <= LONG_TEXT_MIN_CHARS:
        errors.append(f"{source_id}: long_text인데 추출 본문이 {len(text)}자입니다 (> {LONG_TEXT_MIN_CHARS} 필요)")
    if "mostly_english" in cases and _english_ratio(text) < MOSTLY_ENGLISH_MIN_RATIO:
        errors.append(f"{source_id}: mostly_english인데 영문자 비율이 {_english_ratio(text):.2f}입니다")
    if "ad_hashtag_heavy" in cases and len(_HASHTAG.findall(text)) < AD_HASHTAG_MIN_COUNT:
        errors.append(f"{source_id}: ad_hashtag_heavy인데 해시태그가 {len(_HASHTAG.findall(text))}개입니다")
    if "number_date_dense" in cases:
        if len(_DIGITS.findall(text)) < NUMBER_DENSE_MIN_TERMS:
            errors.append(f"{source_id}: number_date_dense인데 숫자 표현이 적습니다")
        if not any(_numbers(fact) for fact in key_facts):
            errors.append(f"{source_id}: number_date_dense인데 key_facts에 숫자가 없습니다")
    return errors


# ------------------------------------------------------------------------------------------------ test 봉인
def _fixture_digest(fixtures_root: Path, fixture: str | None) -> str | None:
    if fixture is None:
        return None
    parts = PurePosixPath(fixture.replace("\\", "/")).parts
    path = fixtures_root.joinpath(*parts)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def compute_split_digest(golden: IngestGoldenSet, fixtures_root: Path, split: str) -> tuple[str, int]:
    """split(dev|test|all) 원문·fixture 바이트·gold·split의 결합 sha256과 건수.

    test에서는 ``test.sha256`` 봉인값과 같다. 리포트 ``golden_sha256``(T26a 비교 거부 조건)도 이 값이다.
    """
    annotations = {annotation.source_id: annotation for annotation in golden.annotations}
    rows: list[str] = []
    for source in sorted(golden.sources, key=lambda item: item.source_id):
        annotation = annotations.get(source.source_id)
        if annotation is None or (split != "all" and annotation.split != split):
            continue
        rows.append(
            json.dumps(
                {
                    "source": source.model_dump(mode="json"),
                    "fixture_sha256": _fixture_digest(fixtures_root, source.source.fixture),
                    "gold": annotation.gold.model_dump(mode="json"),
                    "split": annotation.split,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    return digest, len(rows)


def compute_test_seal(golden: IngestGoldenSet, fixtures_root: Path) -> tuple[str, int]:
    """test split 원문·fixture 바이트·gold·split의 결합 sha256과 건수."""
    return compute_split_digest(golden, fixtures_root, "test")


def format_seal(digest: str, count: int) -> str:
    return f"{digest}  test split {count} records (sources + fixtures + gold)\n"


def read_seal(path: Path) -> str:
    first = path.read_text(encoding="utf-8").split()
    if not first or not re.fullmatch(r"[0-9a-f]{64}", first[0]):
        raise ValueError(f"{path.name}: sha256 형식이 아닙니다")
    return first[0]


def check_test_seal(golden: IngestGoldenSet, golden_dir: Path, *, required: bool) -> list[str]:
    seal_path = golden_dir / SEAL_FILENAME
    if not seal_path.is_file():
        return [f"{SEAL_FILENAME}가 없습니다 (test split 봉인 필요)"] if required else []
    try:
        expected = read_seal(seal_path)
    except ValueError as exc:
        return [str(exc)]
    actual, count = compute_test_seal(golden, golden_dir / "fixtures")
    if actual != expected:
        return [
            f"test split 봉인 불일치: {SEAL_FILENAME} {expected[:16]}… != 현재 {actual[:16]}… ({count}건). "
            "test 원문·gold를 바꿨다면 이유를 기록하고 다시 봉인하세요"
        ]
    return []


def difficult_case_counts(golden: IngestGoldenSet) -> Counter[str]:
    return Counter(case for source in golden.sources for case in source.difficult_cases)
