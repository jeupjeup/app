"""충실도·핵심 사실 판정 (설계 design_local_analyzer.md 8.3·8.4절).

- 1차 결정적 검사 ``DeterministicFaithfulnessChecker``와 결정적 핵심 사실 매처 ``keyfact_covered_deterministic``
- 2차 로컬 판정기 ``LocalFaithfulnessJudge``·``LocalKeyFactJudge`` (``LLMClient``만 쓴다. recorded/live 전용)
- 결합 규칙 ``CombinedFaithfulness``

이 모듈은 llama_cpp를 import하지 않는다. 판정기 실패는 분석기 탓으로 돌리지 않고 ``judge_failed``로 따로 센다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jupjup.domain.errors import JupjupError, LLMCacheMiss
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import normalize_text
from jupjup.text.tokenizer import Tokenizer

if TYPE_CHECKING:  # jupjup.ingest.chunk_notes가 이 모듈의 split_sentences를 쓰므로 실행 시 import하면 순환한다
    from jupjup.ingest.analyzer import PromptStore, PromptTemplate
    from jupjup.ingest.profiles import JudgeProfile
    from jupjup.providers.llm import LLMClient

_SENTENCE_FINALS = frozenset(".!?。！？…")
_ABBREVIATIONS = frozenset(
    {
        "dr.",
        "e.g.",
        "etc.",
        "fig.",
        "i.e.",
        "jr.",
        "mr.",
        "mrs.",
        "ms.",
        "no.",
        "prof.",
        "sr.",
        "st.",
        "vs.",
    }
)
_DOTTED_ABBREVIATION = re.compile(r"(?:[A-Za-z]\.){2,}$")
_ENGLISH_FIRST_WORD = re.compile(r'^\s*["“‘(\[]*(?P<word>[A-Za-z][A-Za-z0-9]*)')
_ENGLISH_INITIAL_STOPWORDS = frozenset({"this", "the", "it", "we", "in", "a", "an", "our"})
_NUMBER_OR_DATE = re.compile(
    r"(?<![0-9A-Za-z])(?:\d{4}[-./년]\s*\d{1,2}(?:[-./월]\s*\d{1,2}일?)?|\d+(?:[.,]\d+)*%?)(?![0-9A-Za-z])"
)
_ENGLISH_PROPER = re.compile(r"(?<![0-9A-Za-z])[A-Z][A-Za-z0-9]*(?![0-9A-Za-z])")


class SentenceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentence: str
    verdict: Literal["supported", "unsupported", "partially", "judge_failed"]
    rationale: str = ""


@runtime_checkable
class FaithfulnessJudge(Protocol):
    """T25 provider boundary; implementations may call only recorded/live LLMs."""

    profile_name: str

    def judge(self, source_text: str, sentences: Sequence[str]) -> list[SentenceJudgment]: ...


class DeterministicCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentences: list[str]
    unsupported_candidates: list[str]
    missing_terms: dict[str, list[str]] = Field(default_factory=dict)


class DeterministicFaithfulnessChecker:
    """Flag a sentence when its numbers/dates/proper nouns do not occur in the source."""

    profile_name = "deterministic-v1"

    def __init__(self, tokenizer: Tokenizer) -> None:
        self.tokenizer = tokenizer

    def check(self, source_text: str, summary: str) -> DeterministicCheckResult:
        sentences = split_sentences(summary)
        source = normalize_text(source_text)
        source_numbers = {normalize_text(term) for term in _number_or_date_terms(source_text)}
        unsupported: list[str] = []
        missing_by_sentence: dict[str, list[str]] = {}
        for sentence in sentences:
            numbers = _number_or_date_terms(sentence)
            proper_nouns = self._proper_nouns(sentence, numbers)
            missing = [term for term in numbers if normalize_text(term) not in source_numbers]
            missing.extend(term for term in proper_nouns if not _term_is_grounded(term, source))
            if missing:
                unsupported.append(sentence)
                missing_by_sentence[sentence] = missing
        return DeterministicCheckResult(
            sentences=sentences,
            unsupported_candidates=unsupported,
            missing_terms=missing_by_sentence,
        )

    def _proper_nouns(self, sentence: str, number_terms: Sequence[str]) -> list[str]:
        terms: list[str] = []
        for token in self.tokenizer.tokenize(sentence):
            if token.pos.startswith(("NNP", "SN")) and token.surface not in number_terms:
                terms.append(token.surface)
        first = _ENGLISH_FIRST_WORD.match(sentence)
        first_span = None if first is None else first.span("word")
        for match in _ENGLISH_PROPER.finditer(sentence):
            term = match.group(0)
            if first_span == match.span() and term.lower() in _ENGLISH_INITIAL_STOPWORDS:
                continue
            terms.append(term)
        return list(dict.fromkeys(term for term in terms if term))


def split_sentences(text: str) -> list[str]:
    """평가·판정·맵 노트가 공유하는 결정적 문장 분리기.

    줄바꿈과 한국어·영어 종결부호에서 나누되, 소수·날짜의 숫자 사이 점, 영문 단어 안 점,
    문장 안 약어와 점 약어는 유지한다. ``No. 3``과 ``St. John``처럼 뒤 문맥이 약어를
    완성할 때만 모호한 ``no.``·``st.``를 내부 점으로 본다.
    """
    sentences: list[str] = []
    start = 0
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == "\n":
            _append_sentence(sentences, text[start:cursor])
            cursor += 1
            start = cursor
            continue
        if char not in _SENTENCE_FINALS or (char == "." and _period_is_internal(text, cursor)):
            cursor += 1
            continue
        end = cursor + 1
        while end < len(text) and text[end] in _SENTENCE_FINALS:
            end += 1
        _append_sentence(sentences, text[start:end])
        cursor = end
        start = end
    _append_sentence(sentences, text[start:])
    return sentences


def _append_sentence(sentences: list[str], value: str) -> None:
    stripped = value.strip()
    if stripped:
        sentences.append(stripped)


def _period_is_internal(text: str, index: int) -> bool:
    previous = text[index - 1] if index > 0 else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isdigit() and following.isdigit():
        return True
    if previous.isascii() and previous.isalpha() and following.isascii() and following.isalpha():
        return True
    token_start = index
    while token_start > 0 and (
        (text[token_start - 1].isascii() and text[token_start - 1].isalpha()) or text[token_start - 1] == "."
    ):
        token_start -= 1
    token = text[token_start : index + 1]
    lowered = token.lower()
    following_text = text[index + 1 :]
    if lowered == "no.":
        return re.match(r"\s*\d", following_text) is not None
    if lowered == "st.":
        return re.match(r"\s+[A-Z][A-Za-z]", following_text) is not None
    return lowered in _ABBREVIATIONS or _DOTTED_ABBREVIATION.fullmatch(token) is not None


def unsupported_sentence_metrics(
    summary: str,
    unsupported_candidates: Sequence[str],
    forbidden_claims: Sequence[str],
) -> tuple[list[str], float]:
    """Use one splitter for numerator/denominator; a forbidden claim makes the whole item unfaithful."""
    sentences = split_sentences(summary)
    if any(normalize_text(claim) in normalize_text(summary) for claim in forbidden_claims):
        return sentences, 1.0
    remaining = Counter(unsupported_candidates)
    unsupported: list[str] = []
    for sentence in sentences:
        if remaining[sentence] <= 0:
            continue
        unsupported.append(sentence)
        remaining[sentence] -= 1
    rate = len(unsupported) / max(1, len(sentences))
    return unsupported, min(1.0, max(0.0, rate))


def _number_or_date_terms(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in _NUMBER_OR_DATE.finditer(text)))


def _term_is_grounded(term: str, normalized_source: str) -> bool:
    normalized = normalize_text(term)
    if term.isascii() and term.isalnum():
        return re.search(rf"(?<![0-9a-z]){re.escape(normalized)}(?![0-9a-z])", normalized_source) is not None
    return normalized in normalized_source


def forbidden_claim_hit(summary: str, forbidden_claims: Sequence[str]) -> bool:
    normalized = normalize_text(summary)
    return any(normalize_text(claim) in normalized for claim in forbidden_claims)


# --- 결정적 핵심 사실 매처 (설계 design_local_analyzer.md 8.4절 1번) ---------------------------------------------

KEYFACT_CONTENT_POS = frozenset({"NNG", "NNP", "NR", "SN", "SL", "SH", "XR", "VV", "VA"})
KEYFACT_MATCH_THRESHOLD = 0.6
_PREDICATE_POS = frozenset({"VV", "VA"})
_KEYFACT_LIGHT_STEMS = frozenset(
    {"하", "되", "있", "없", "보", "가", "오", "주", "받", "같", "않", "알", "말", "두", "놓", "쓰", "싶", "나", "이"}
)


def keyfact_content_terms(
    text: str,
    tokenizer: Tokenizer,
    lexicon: Lexicon | None = None,
    *,
    pos: frozenset[str] = KEYFACT_CONTENT_POS,
) -> list[str]:
    """내용 형태소 lemma (명사·수사·숫자·외국어·어근·동사·형용사, 동의어 정규형). 입력 순서, 중복 제거."""
    terms: list[str] = []
    for token in tokenizer.tokenize(text):
        if token.pos not in pos:
            continue
        if token.pos in ("VV", "VA") and token.lemma in _KEYFACT_LIGHT_STEMS:
            continue
        lemma = normalize_text(token.lemma)
        if not lemma:
            continue
        terms.append(lexicon.canonical(lemma) if lexicon is not None else lemma)
    return list(dict.fromkeys(terms))


def keyfact_covered_deterministic(
    fact: str,
    summary: str,
    tokenizer: Tokenizer,
    *,
    lexicon: Lexicon | None = None,
    threshold: float = KEYFACT_MATCH_THRESHOLD,
) -> bool:
    """사실의 내용 형태소 중 요약 문장에 있는 비율 ≥ threshold **이고** 사실의 숫자·날짜가 그 문장에 모두 있으면 포함.

    - 정규화 후 요약 전체의 부분 문자열이면 바로 포함이다 (기존 부분 문자열 일치의 상위 집합. mock·v1 결과 보존).
    - 비율은 요약 **문장 하나** 안에서 잰다. 여러 문장의 낱말을 모아 맞추면 다른 주장이 섞인다 (설계 대비 강화).
    - 사실에 내용 용언(동사·형용사)이 있으면 그중 하나 이상이 그 문장에 있어야 한다 (주장의 서술어).
    - 그 문장과 사실의 부정 표현 유무가 다르면 포함이 아니다 ("유의하게 높았다" 대 "유의한 차이는 아니었다").
    """
    normalized_fact = normalize_text(fact)
    if not normalized_fact:
        return False
    if normalized_fact in normalize_text(summary):
        return True
    fact_terms = keyfact_content_terms(fact, tokenizer, lexicon)
    if not fact_terms:
        return False
    fact_predicates = keyfact_content_terms(fact, tokenizer, lexicon, pos=_PREDICATE_POS)
    fact_numbers = [normalize_text(term) for term in _number_or_date_terms(fact)]
    fact_negated = _has_negation(fact, tokenizer)
    for sentence in split_sentences(summary):
        numbers = {normalize_text(term) for term in _number_or_date_terms(sentence)}
        if any(term not in numbers for term in fact_numbers):
            continue
        sentence_terms = set(keyfact_content_terms(sentence, tokenizer, lexicon))
        ratio = sum(term in sentence_terms for term in fact_terms) / len(fact_terms)
        if ratio < threshold or _has_negation(sentence, tokenizer) != fact_negated:
            continue
        if not fact_predicates or any(term in sentence_terms for term in fact_predicates):
            return True
    return False


def _has_negation(text: str, tokenizer: Tokenizer) -> bool:
    return any(
        token.pos == "VCN"
        or (token.pos == "VX" and token.lemma in ("않", "못하"))
        or (token.pos == "MAG" and token.lemma in ("안", "못"))
        for token in tokenizer.tokenize(text)
    )


# --- 로컬 판정기 (설계 8.3절 2차, 8.4절 2번) --------------------------------------------------------------------

JUDGE_FAILED: Literal["judge_failed"] = "judge_failed"
JUDGE_BATCH_SIZE = 8
JUDGE_EVIDENCE_MAX = 120
RETRIEVED_SOURCE_SENTENCES = 12
JudgeContext = Literal["full", "retrieved"]


class JudgeItem(BaseModel):
    """판정 1건. 필드 순서는 디코딩 순서다 (근거를 먼저 인용한 뒤 판정한다)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    index: int = Field(ge=0)
    evidence: str = Field(max_length=JUDGE_EVIDENCE_MAX)
    verdict: Literal["supported", "partially", "unsupported"]


class JudgeVerdicts(BaseModel):
    """충실도 판정기 출력 스키마 (문법 제약)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    judgments: list[JudgeItem] = Field(max_length=JUDGE_BATCH_SIZE)


class KeyFactItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    index: int = Field(ge=0)
    evidence: str = Field(max_length=JUDGE_EVIDENCE_MAX)
    verdict: Literal["covered", "partial", "missing"]


class KeyFactVerdicts(BaseModel):
    """핵심 사실 판정기 출력 스키마 (문법 제약)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    judgments: list[KeyFactItem] = Field(max_length=JUDGE_BATCH_SIZE)


class KeyFactJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact: str
    verdict: Literal["covered", "partial", "missing", "judge_failed"]
    rationale: str = ""


class FaithfulnessJudgeRun(BaseModel):
    """판정 1회의 결과와 진단값 (리포트용)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    judgments: list[SentenceJudgment]
    context: JudgeContext = "full"
    calls: int = 0
    retries: int = 0


class KeyFactJudgeRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    judgments: list[KeyFactJudgment]
    calls: int = 0
    retries: int = 0


class _IndexedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: dict[int, Any]
    calls: int
    retries: int


def _indexed_items(
    llm: LLMClient,
    template: PromptTemplate,
    blocks: dict[str, str],
    schema: type[JudgeVerdicts] | type[KeyFactVerdicts],
    n_items: int,
    *,
    timeout_s: float,
    max_tokens: int,
) -> _IndexedOutcome:
    """번호 붙은 항목 n개를 판정받는다. 번호가 빠지거나 겹치거나 JSON이 깨지면 1회 재요청한다.

    재요청 뒤에도 문제가 남은 번호는 결과에서 빠진다 (호출자가 ``judge_failed``로 센다). 녹화 미스
    (``LLMCacheMiss``)는 판정기 실패가 아니라 재생 데이터 문제이므로 그대로 올린다.
    """
    best: dict[int, Any] = {}
    calls = 0
    note = ""
    for attempt in range(2):
        system, user = template.render(**blocks, retry_note=note)
        calls += 1
        problem: str
        try:
            raw = llm.complete_json(system, user, schema, timeout_s, max_tokens)
        except LLMCacheMiss:
            raise
        except JupjupError:
            break  # 제공자 오류·타임아웃은 같은 요청을 다시 보내도 대개 같다. 남은 번호는 judge_failed
        try:
            parsed = schema.model_validate_json(raw.text)
        except ValidationError:
            problem = "JSON이 스키마와 맞지 않았다"
            items: dict[int, Any] = {}
        else:
            counts = Counter(item.index for item in parsed.judgments)
            items = {
                item.index: item for item in parsed.judgments if item.index < n_items and counts[item.index] == 1
            }
            missing = [index for index in range(n_items) if index not in items]
            extra = sorted(index for index in counts if index >= n_items)
            problems = []
            if missing:
                problems.append(f"번호 {', '.join(map(str, missing))}의 판정이 없거나 두 번 이상 나왔다")
            if extra:
                problems.append(f"없는 번호 {', '.join(map(str, extra))}를 답했다")
            problem = "; ".join(problems)
        if len(items) >= len(best):
            best = items
        if not problem:
            break
        if attempt == 0:
            note = (
                f"이전 답에 문제가 있었다: {problem}. 번호 0부터 {n_items - 1}까지 각 번호에 정확히 한 번씩 "
                "판정을 담아 JSON 객체 하나로 다시 답하라."
            )
    return _IndexedOutcome(items=best, calls=calls, retries=max(0, calls - 1))


def _numbered(lines: Sequence[str], prefix: str = "") -> str:
    return "\n".join(f"[{prefix}{index}] {' '.join(line.split())}" for index, line in enumerate(lines))


class LocalFaithfulnessJudge:
    """``FaithfulnessJudge`` 구현. 요약 문장마다 supported | partially | unsupported를 받는다 (8.3절).

    판정기 입력이 ``n_ctx``를 넘으면 원문을 문장 번호로 나눠, 요약 문장마다 BM25(문자 bigram, 결정적)로 고른
    상위 12개 원문 문장만 넣고 한 문장씩 판정한다 (``context="retrieved"``).
    """

    def __init__(
        self,
        llm: LLMClient,
        profile: JudgeProfile,
        prompts: PromptStore,
        *,
        n_ctx: int = 16_384,
        context_margin_tokens: int = 256,
    ) -> None:
        self.llm = llm
        self.profile = profile
        self.profile_name = profile.name
        self.prompts = prompts
        self.n_ctx = n_ctx
        self.context_margin_tokens = context_margin_tokens
        self.template = prompts.load(profile.faithfulness_prompt_version)

    def judge(self, source_text: str, sentences: Sequence[str]) -> list[SentenceJudgment]:
        return self.run(source_text, sentences).judgments

    def run(self, source_text: str, sentences: Sequence[str]) -> FaithfulnessJudgeRun:
        judgments: list[SentenceJudgment] = []
        context: JudgeContext = "full"
        calls = retries = 0
        source = source_text.strip()
        for start in range(0, len(sentences), JUDGE_BATCH_SIZE):
            batch = list(sentences[start : start + JUDGE_BATCH_SIZE])
            blocks = {"source_document": source, "summary_sentences": _numbered(batch)}
            if self._fits(blocks):
                outcome = self._ask(blocks, len(batch))
                judgments.extend(_sentence_judgments(batch, outcome.items))
                calls += outcome.calls
                retries += outcome.retries
                continue
            context = "retrieved"
            source_sentences = split_sentences(source)
            for sentence in batch:
                picked = bm25_top_sentences(sentence, source_sentences, RETRIEVED_SOURCE_SENTENCES)
                retrieved = "\n".join(f"[s{index}] {' '.join(source_sentences[index].split())}" for index in picked)
                outcome = self._ask({"source_document": retrieved, "summary_sentences": _numbered([sentence])}, 1)
                judgments.extend(_sentence_judgments([sentence], outcome.items))
                calls += outcome.calls
                retries += outcome.retries
        return FaithfulnessJudgeRun(judgments=judgments, context=context, calls=calls, retries=retries)

    def _fits(self, blocks: dict[str, str]) -> bool:
        system, user = self.template.render(**blocks, retry_note="")
        tokens = self.llm.count_tokens(system, user)
        estimate = tokens if tokens is not None else len(system) + len(user)
        return estimate + self.profile.max_output_tokens + self.context_margin_tokens <= self.n_ctx

    def _ask(self, blocks: dict[str, str], n_items: int) -> _IndexedOutcome:
        return _indexed_items(
            self.llm,
            self.template,
            blocks,
            JudgeVerdicts,
            n_items,
            timeout_s=self.profile.timeout_s,
            max_tokens=self.profile.max_output_tokens,
        )


def _sentence_judgments(batch: Sequence[str], items: dict[int, Any]) -> list[SentenceJudgment]:
    out: list[SentenceJudgment] = []
    for index, sentence in enumerate(batch):
        item = items.get(index)
        if item is None:
            out.append(SentenceJudgment(sentence=sentence, verdict=JUDGE_FAILED))
        else:
            out.append(SentenceJudgment(sentence=sentence, verdict=item.verdict, rationale=item.evidence))
    return out


class LocalKeyFactJudge:
    """핵심 사실마다 covered | partial | missing을 받는다. ``covered``만 포함으로 센다 (8.4절 2번)."""

    def __init__(self, llm: LLMClient, profile: JudgeProfile, prompts: PromptStore) -> None:
        self.llm = llm
        self.profile = profile
        self.profile_name = profile.name
        self.template = prompts.load(profile.keyfact_prompt_version)

    def judge(self, summary: str, facts: Sequence[str]) -> list[KeyFactJudgment]:
        return self.run(summary, facts).judgments

    def run(self, summary: str, facts: Sequence[str]) -> KeyFactJudgeRun:
        judgments: list[KeyFactJudgment] = []
        calls = retries = 0
        for start in range(0, len(facts), JUDGE_BATCH_SIZE):
            batch = list(facts[start : start + JUDGE_BATCH_SIZE])
            outcome = _indexed_items(
                self.llm,
                self.template,
                {"summary": summary.strip(), "key_facts": _numbered(batch)},
                KeyFactVerdicts,
                len(batch),
                timeout_s=self.profile.timeout_s,
                max_tokens=self.profile.max_output_tokens,
            )
            calls += outcome.calls
            retries += outcome.retries
            for index, fact in enumerate(batch):
                item = outcome.items.get(index)
                if item is None:
                    judgments.append(KeyFactJudgment(fact=fact, verdict=JUDGE_FAILED))
                else:
                    judgments.append(KeyFactJudgment(fact=fact, verdict=item.verdict, rationale=item.evidence))
        return KeyFactJudgeRun(judgments=judgments, calls=calls, retries=retries)


# --- BM25 원문 문장 선택 (긴 원문, 8.3절) -------------------------------------------------------------------------


def _bigrams(text: str) -> list[str]:
    grams: list[str] = []
    for word in normalize_text(text).split():
        if len(word) == 1:
            grams.append(word)
        grams.extend(word[index : index + 2] for index in range(len(word) - 1))
    return grams


def bm25_top_sentences(query: str, sentences: Sequence[str], k: int, *, k1: float = 1.2, b: float = 0.75) -> list[int]:
    """BM25(문자 bigram) 상위 k개 문장 번호를 원문 순서로 돌려준다. 점수가 같으면 앞 문장이 먼저다."""
    if not sentences:
        return []
    docs = [Counter(_bigrams(sentence)) for sentence in sentences]
    lengths = [sum(doc.values()) for doc in docs]
    average = sum(lengths) / len(lengths) or 1.0
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.keys())
    n_docs = len(docs)
    terms = list(dict.fromkeys(_bigrams(query)))
    scores: list[tuple[float, int]] = []
    for index, doc in enumerate(docs):
        score = 0.0
        for term in terms:
            tf = doc.get(term, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lengths[index] / average))
        scores.append((score, index))
    ranked = sorted(scores, key=lambda pair: (-pair[0], pair[1]))[:k]
    return sorted(index for _, index in ranked)


# --- 1차 + 2차 결합 (8.3절 결합 규칙) ----------------------------------------------------------------------------


class CombinedFaithfulnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentences: list[str]
    unsupported: list[str]
    rate: float
    judge_used: bool
    partially: int = 0
    judge_failed: int = 0


class CombinedFaithfulness:
    """1차 + 2차 결합. 판정기가 보정(이진 κ ≥ 0.7)을 통과했으면 비충실 조건은
    ``판정 == unsupported`` 또는 (1차 후보 ∧ ``판정 != supported``)이다.

    - ``partially``는 비충실로 세지 않고 따로 센다.
    - ``judge_failed`` 문장은 판정이 없는 것으로 보고 1차 결과를 따른다 (위 규칙에서 자연히 그렇게 된다).
    - 보정 전이거나 판정 결과가 없으면 1차 결과만 쓴다. forbidden claim이 나오면 그 건은 1.0이다.
    """

    def __init__(self, *, calibrated: bool) -> None:
        self.calibrated = calibrated

    def evaluate(
        self,
        det: DeterministicCheckResult,
        judged: Sequence[SentenceJudgment] | None,
        forbidden_hit: bool,
    ) -> CombinedFaithfulnessResult:
        sentences = list(det.sentences)
        if judged is not None and [item.sentence for item in judged] != sentences:
            raise ValueError("판정 결과의 문장이 1차 검사 문장과 다릅니다 (같은 split_sentences 결과여야 함)")
        verdicts = [item.verdict for item in judged] if judged is not None else []
        partially = sum(verdict == "partially" for verdict in verdicts)
        failed = sum(verdict == JUDGE_FAILED for verdict in verdicts)
        use_judge = self.calibrated and judged is not None
        if forbidden_hit:
            return CombinedFaithfulnessResult(
                sentences=sentences,
                unsupported=sentences,
                rate=1.0,
                judge_used=use_judge,
                partially=partially,
                judge_failed=failed,
            )
        candidates = _candidate_flags(sentences, det.unsupported_candidates)
        if use_judge:
            flags = [
                verdict == "unsupported" or (candidate and verdict != "supported")
                for verdict, candidate in zip(verdicts, candidates, strict=True)
            ]
        else:
            flags = candidates
        unsupported = [sentence for sentence, flag in zip(sentences, flags, strict=True) if flag]
        rate = min(1.0, max(0.0, len(unsupported) / max(1, len(sentences))))
        return CombinedFaithfulnessResult(
            sentences=sentences,
            unsupported=unsupported,
            rate=rate,
            judge_used=use_judge,
            partially=partially,
            judge_failed=failed,
        )

    def unsupported_sentences(
        self,
        det: DeterministicCheckResult,
        judged: Sequence[SentenceJudgment] | None,
        forbidden_hit: bool,
    ) -> tuple[list[str], float]:
        result = self.evaluate(det, judged, forbidden_hit)
        return result.unsupported, result.rate


def _candidate_flags(sentences: Sequence[str], candidates: Sequence[str]) -> list[bool]:
    """1차 후보를 문장 위치에 맞춘다 (``unsupported_sentence_metrics``와 같은 위치 규칙)."""
    remaining = Counter(candidates)
    flags: list[bool] = []
    for sentence in sentences:
        flagged = remaining[sentence] > 0
        if flagged:
            remaining[sentence] -= 1
        flags.append(flagged)
    return flags
