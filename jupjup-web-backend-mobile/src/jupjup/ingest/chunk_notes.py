"""맵 단계: 분석 청크에서 근거 번호가 붙은 노트를 뽑는다 (설계 ``design_local_analyzer.md`` 6.6절).

- 청크 문장마다 ``[s12]`` 번호를 붙여 프롬프트에 넣는다. 문장 분리는 T25a에서 고친 ``split_sentences``
  (소수점·버전 표기에서 자르지 않음)를 그대로 쓴다.
- 재요청은 **1회**만 한다. 그래도 실패하면 빈 노트를 돌려주고 ``failed=True``로 표시한다. 청크 절반 넘게 실패하면
  잡을 실패시키는 판단은 호출자(``LLMContentAnalyzer``)가 한다.
- 이 모듈은 엔진을 모른다. ``LLMClient``만 쓴다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from jupjup.domain.errors import LLMRefusalError
from jupjup.eval.judge import split_sentences
from jupjup.ingest.chunking import AnalysisChunk
from jupjup.ingest.profiles import AnalyzerProfile
from jupjup.ingest.schemas import ChunkNotes
from jupjup.ingest.validation import ChunkNotesValidator, ValidationIssue
from jupjup.providers.llm import LLMClient, LLMRawResponse

if TYPE_CHECKING:
    from jupjup.ingest.analyzer import PromptStore

CHUNK_MAX_REPAIRS = 1


class NumberedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int = Field(ge=0)
    text: str  # 근거 검사용 청크 원문 (번호 없이)
    sentences: list[tuple[str, str]]  # [("s1", "…"), …]

    def numbered_text(self) -> str:
        return "\n".join(f"[{sentence_id}] {sentence}" for sentence_id, sentence in self.sentences)


def number_sentences(chunk: AnalysisChunk) -> NumberedChunk:
    sentences = [(f"s{index}", sentence) for index, sentence in enumerate(split_sentences(chunk.text), start=1)]
    return NumberedChunk(chunk_index=chunk.index, text=chunk.text, sentences=sentences)


class ChunkNotesResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_index: int
    notes: ChunkNotes
    failed: bool = False
    first_pass_ok: bool
    attempts: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    prompt_versions: list[str]
    repairs: list[str] = Field(default_factory=list)
    # facts의 evidence_ids가 가리키는 청크 원문 문장 ({"s3": "…"}). 리듀스 v2가 근거 구절로 그대로 붙인다 (T25p R1(a)).
    sources: dict[str, str] = Field(default_factory=dict)


def render_issues(issues: list[ValidationIssue]) -> str:
    """재요청 프롬프트용 이슈 목록. ``path``, ``code``, ``message``만 넣는다 (원문 미포함 규칙, 5.4절)."""
    rows = [{"path": issue.path, "code": issue.code, "message": issue.message} for issue in issues]
    return json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)


# 재요청 v2의 ``{{attempt_note}}`` (데이터 블록 밖, 코드가 만드는 고정 문구라 원문이 들어가지 않는다).
# greedy 디코딩에서는 같은 프롬프트가 같은 출력을 내므로, 회차와 "직전 출력 복사" 사실을 넣어 재요청마다 프롬프트를
# 다르게 만든다 (T25p R1(b)). 문구를 바꾸면 user 바이트가 바뀌어 녹화 미스로 드러난다.
def repair_attempt_note(attempt: int, *, repeated: bool) -> str:
    note = f"(재요청 {attempt}회째)"
    if repeated:
        note += (
            " 직전 재요청의 출력이 그 앞 출력과 글자 하나까지 같았다. 같은 출력은 다시 실패한다."
            " 이번에는 <validation_issues>의 path가 가리키는 값을 원문의 사실만으로 반드시 다시 쓴다."
        )
    return note


class LLMChunkNoteExtractor:
    def __init__(
        self,
        llm: LLMClient,
        profile: AnalyzerProfile,
        prompts: PromptStore,
        validator: ChunkNotesValidator,
    ) -> None:
        self.llm = llm
        self.profile = profile
        self.prompts = prompts
        self.validator = validator

    def render(self, numbered: NumberedChunk) -> tuple[str, str]:
        template = self.prompts.load(self.profile.chunk_prompt_version)
        return template.render(source_chunk=numbered.numbered_text())

    def render_repair(
        self, numbered: NumberedChunk, previous_output: str, issues: list[ValidationIssue]
    ) -> tuple[str, str]:
        template = self.prompts.load(self.profile.repair_prompt_version)
        values = {
            "source_document": numbered.numbered_text(),
            "previous_output": previous_output,
            "validation_issues": render_issues(issues),
        }
        if "attempt_note" in template.placeholders:
            # 맵 단계 재요청은 1회뿐이라 "직전 출력 복사"는 생기지 않는다.
            values["attempt_note"] = repair_attempt_note(1, repeated=False)
        return template.render(**values)

    def extract(self, chunk: AnalysisChunk) -> ChunkNotesResult:
        numbered = number_sentences(chunk)
        profile = self.profile
        responses: list[LLMRawResponse] = []
        versions = [profile.chunk_prompt_version]
        base_prompt = self.render(numbered)
        prompt = base_prompt
        max_tokens = profile.chunk_max_output_tokens
        timeout_s = profile.timeouts.chunk_s
        truncation_retried = False
        repair_attempts = 0
        issues: list[ValidationIssue] = []

        while True:
            response = self.llm.complete_json(prompt[0], prompt[1], ChunkNotes, timeout_s, max_tokens, profile.effort)
            responses.append(response)
            if response.stop_reason == "refusal":
                raise LLMRefusalError("LLM이 청크 노트 요청을 거절했습니다", {"attempts": len(responses)})
            if response.stop_reason == "max_tokens" and not truncation_retried:
                # validate_and_repair와 같은 규칙: 같은 프롬프트, 출력 상한 2배로 1회
                truncation_retried = True
                max_tokens *= 2
                continue
            notes, issues = self.validator.validate(response.text, numbered)
            if notes is not None and not any(not issue.fixable for issue in issues):
                repairs = [
                    f"chunk[{chunk.index}]{issue.path[1:]}: {issue.message}" for issue in issues if issue.fixable
                ]
                sentences = dict(numbered.sentences)
                used = {sid: sentences[sid] for fact in notes.facts for sid in fact.evidence_ids if sid in sentences}
                return self._result(chunk, notes, responses, versions, repairs, failed=False, sources=used)
            if repair_attempts >= CHUNK_MAX_REPAIRS:
                break
            repair_attempts += 1
            if profile.repair_prompt_version not in versions:
                versions.append(profile.repair_prompt_version)
            prompt = self.render_repair(numbered, response.text, issues)
            timeout_s = profile.timeouts.repair_s

        return self._result(
            chunk, ChunkNotes.empty(), responses, versions, [f"chunk[{chunk.index}]: notes_failed"], failed=True
        )

    @staticmethod
    def _result(
        chunk: AnalysisChunk,
        notes: ChunkNotes,
        responses: list[LLMRawResponse],
        versions: list[str],
        repairs: list[str],
        *,
        failed: bool,
        sources: dict[str, str] | None = None,
    ) -> ChunkNotesResult:
        return ChunkNotesResult(
            chunk_index=chunk.index,
            notes=notes,
            failed=failed,
            first_pass_ok=not failed and len(responses) == 1,
            attempts=len(responses),
            input_tokens=sum(response.input_tokens for response in responses),
            output_tokens=sum(response.output_tokens for response in responses),
            latency_ms=sum(response.latency_ms for response in responses),
            prompt_versions=list(versions),
            repairs=repairs,
            sources=dict(sorted((sources or {}).items())),
        )
