"""T21 mock analyzer, LLM recording/replay, and OCR-only image understanding."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field, create_model

from jupjup.domain.errors import (
    AnalysisSchemaError,
    LLMCacheMiss,
    LLMProviderError,
    LLMRefusalError,
    VisionProviderError,
)
from jupjup.domain.models import Snapshot
from jupjup.ingest.analyzer import ContentAnalyzer, MockAnalyzer, prompt_path
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings, ContentMeta, chunk_for_analysis
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.validation import AnalysisValidator, ValidationIssue
from jupjup.providers.llm import LLMRawResponse, MockLLM, prompt_hash
from jupjup.providers.recording import RecordedLLM, RecordingLLM, complete_request_hash, schema_fingerprint
from jupjup.providers.vision import (
    ImageDescription,
    ImageInput,
    ImageUnderstander,
    MockImageUnderstander,
    OcrOnlyUnderstander,
    image_key,
)
from jupjup.text.lexicon import Lexicon

SOURCE = (
    "성수동 카페 어니언은 가을 신메뉴 밤 라떼를 출시했습니다. "
    "매장은 서울 성동구 성수동에 있고 주말 오전에 방문할 수 있습니다."
)
VALID: dict[str, Any] = {
    "summary": "성수동 카페 어니언이 가을 신메뉴 밤 라떼를 출시했습니다. 주말 오전에 매장을 방문할 수 있습니다.",
    "representative_tags": ["성수동", "카페", "밤라떼"],
    "detail_tags": {
        "schema_version": 1,
        "category": "food_drink",
        "topics": ["카페"],
        "locations": [{"name": "성수동", "level": "neighborhood"}],
    },
    "save_intent": {"labels": ["방문예정"], "confidence": 0.9, "rationale": "주말 방문 정보"},
    "title_suggestion": "성수 어니언 가을 신메뉴",
    "language": "ko",
    "evidence": [{"claim": "신메뉴 출시", "source_span": "가을 신메뉴 밤 라떼를 출시했습니다"}],
}


def analysis_input(source_id: str = "src_0005") -> AnalysisInput:
    return AnalysisInput(
        mode="single",
        text=SOURCE,
        meta=ContentMeta(source_id=source_id),
        source_token_count=len(SOURCE),
    )


def test_mock_analyzer_replays_failure_script_in_order_through_t18_validator(lexicon: Lexicon) -> None:
    class RecordingValidator(AnalysisValidator):
        def __init__(self) -> None:
            super().__init__(lexicon)
            self.raw_outputs: list[str] = []

        def validate(self, raw_json: str, source_text: str) -> tuple[AnalysisOutput | None, list[ValidationIssue]]:
            self.raw_outputs.append(raw_json)
            return super().validate(raw_json, source_text)

    validator = RecordingValidator()
    analyzer = MockAnalyzer(
        {"src_0005": VALID},
        {"src_0005": ["truncated_json", "schema_violation", "ok"]},
        validator=validator,
    )
    assert isinstance(analyzer, ContentAnalyzer)

    output, meta = analyzer.analyze(analysis_input())

    assert output.summary == VALID["summary"]
    assert meta.attempts == 3
    assert not meta.first_pass_ok
    assert meta.model == "mock-analyzer-v1"
    assert meta.prompt_version == "analyze_v1"
    fixture_text = json.dumps(VALID, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert validator.raw_outputs == [fixture_text[:-1], "{}", fixture_text]


def test_mock_analyzer_invalid_output_takes_repair_path_and_is_deterministic() -> None:
    analyzer = MockAnalyzer({"src_0005": VALID}, {"src_0005": ["schema_violation", "ok"]})

    first = analyzer.analyze(analysis_input())
    second = analyzer.analyze(analysis_input())

    assert first[1].attempts == 2
    assert first[0].model_dump_json() == second[0].model_dump_json()
    assert first[1].model_dump_json() == second[1].model_dump_json()


def test_mock_analyzer_supports_default_and_rejects_unknown_actions() -> None:
    analyzer = MockAnalyzer({"default": VALID})
    assert analyzer.analyze(analysis_input("unregistered"))[1].attempts == 1
    with pytest.raises(ValueError, match="알 수 없는"):
        MockAnalyzer({"src_0005": VALID}, {"src_0005": ["typo"]})


class Out(BaseModel):
    keywords: list[str] = []


class CountingLLM:
    model_id = "fixture-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        del schema, timeout_s, max_tokens, effort
        self.calls += 1
        return LLMRawResponse(
            text=json.dumps({"keywords": [user]}, ensure_ascii=False),
            input_tokens=len(system) + len(user),
            output_tokens=1,
        )

    def count_tokens(self, system: str, user: str) -> int | None:
        return len(system) + len(user)


def test_recording_llm_writes_new_path_once_and_recorded_llm_replays(tmp_path: Path) -> None:
    store = tmp_path / "new-recordings" / "llm.fixture-model.jsonl"
    inner = CountingLLM()
    recorder = RecordingLLM(inner, store)

    expected = recorder.complete_json("system", "사용자", Out, 1.0, max_tokens=123, effort="low")
    recorder.complete_json("system", "사용자", Out, 1.0, max_tokens=123, effort="low")
    assert recorder.count_tokens("system", "사용자") == len("system") + len("사용자")

    lines = store.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(lines) == 2  # complete 1행 + count_tokens 1행. 같은 요청 반복은 1행이다
    complete_row = next(row for row in rows if row["kind"] == "complete_json")
    assert complete_row["prompt_hash"] == prompt_hash("system", "사용자")
    assert complete_row["max_tokens"] == 123 and complete_row["effort"] == "low"
    assert complete_row["schema_name"] == "Out"
    assert all("system" not in row and "user" not in row for row in rows)
    assert inner.calls == 1

    replay = RecordedLLM(store, "fixture-model")
    assert replay.complete_json("system", "사용자", Out, 1.0, max_tokens=123, effort="low") == expected
    assert replay.count_tokens("system", "사용자") == len("system") + len("사용자")


def test_recording_llm_append_reuses_existing_rows_without_calling_inner(tmp_path: Path) -> None:
    store = tmp_path / "llm.fixture-model.jsonl"
    original = CountingLLM()
    recorder = RecordingLLM(original, store)
    expected = recorder.complete_json("system", "user", Out, 1.0, max_tokens=123)
    expected_tokens = recorder.count_tokens("system", "user")

    class MustNotRun(CountingLLM):
        def complete_json(
            self,
            system: str,
            user: str,
            schema: type[BaseModel],
            timeout_s: float,
            max_tokens: int = 4000,
            effort: str | None = None,
        ) -> LLMRawResponse:
            raise AssertionError("--append must not call the live model for an existing request")

        def count_tokens(self, system: str, user: str) -> int | None:
            raise AssertionError("--append must not recount tokens for an existing request")

    before = store.read_bytes()
    resumed = RecordingLLM(MustNotRun(), store)
    assert resumed.complete_json("system", "user", Out, 1.0, max_tokens=123) == expected
    assert resumed.count_tokens("system", "user") == expected_tokens
    assert store.read_bytes() == before


def test_recorded_llm_cache_miss_and_bad_recording_are_explicit(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    fixture = MockLLM({prompt_hash("s", "u"): {"keywords": ["ok"]}})
    RecordingLLM(fixture, store).complete_json("s", "u", Out, 1.0)
    replay = RecordedLLM(store, fixture.model_id)

    with pytest.raises(LLMCacheMiss) as caught:
        replay.complete_json("s", "missing", Out, 1.0)
    assert caught.value.details["prompt_hash"] == prompt_hash("s", "missing")
    with pytest.raises(LLMCacheMiss):
        replay.count_tokens("s", "missing")

    malformed = tmp_path / "bad.jsonl"
    malformed.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(LLMProviderError, match="형식"):
        RecordedLLM(malformed, "fixture-model")


def test_ocr_only_and_mock_image_understanders_are_network_free_and_deterministic() -> None:
    image = ImageInput(path=Path("fixture.png"), ocr_text="  성수동   카페\r\n\r\n  밤 라떼  ")
    ocr = OcrOnlyUnderstander()
    assert isinstance(ocr, ImageUnderstander)
    assert ocr.describe(image) == ImageDescription(ocr_text="성수동 카페\n\n밤 라떼", source="ocr")

    fixture = ImageDescription(ocr_text="보이는 글자", caption="카페 메뉴판", objects=["메뉴판"], source="vision")
    mock = MockImageUnderstander({image_key(image): fixture})
    assert mock.describe(image) == fixture
    assert mock.describe(image) == fixture
    assert mock.calls == [image_key(image), image_key(image)]

    with pytest.raises(VisionProviderError) as caught:
        ocr.describe(ImageInput(path=Path("no-ocr.png")))
    assert caught.value.details == {"reason": "no_text"}


def test_versioned_prompts_exist_and_mark_source_as_untrusted() -> None:
    for name in ("analyze_v1", "chunk_notes_v1", "repair_v1"):
        text = prompt_path(name).read_text(encoding="utf-8")
        assert text.strip() and "untrusted" in text
    with pytest.raises(ValueError):
        prompt_path("../secret")


# --- T21 loop 1 M2: failure_script 전체 동작과 소진·거절 분기 ---

FIXTURE_TEXT = json.dumps(VALID, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
TRUNCATED = FIXTURE_TEXT[:-1]


class SpyValidator(AnalysisValidator):
    def __init__(self, lexicon: Lexicon) -> None:
        super().__init__(lexicon)
        self.raw_outputs: list[str] = []

    def validate(self, raw_json: str, source_text: str) -> tuple[AnalysisOutput | None, list[ValidationIssue]]:
        self.raw_outputs.append(raw_json)
        return super().validate(raw_json, source_text)


SV = "schema_violation"
MT = "max_tokens"


@pytest.mark.parametrize(
    ("script", "attempts", "first_pass_ok", "raws"),
    [
        pytest.param([], 1, True, [FIXTURE_TEXT], id="no-script"),
        pytest.param(["ok"], 1, True, [FIXTURE_TEXT], id="ok"),
        pytest.param(["empty", "ok"], 2, False, ["", FIXTURE_TEXT], id="empty"),
        pytest.param(["empty_response", "ok"], 2, False, ["", FIXTURE_TEXT], id="empty_response"),
        pytest.param(
            ["invalid_json", "empty_response", "ok"], 3, False, [TRUNCATED, "", FIXTURE_TEXT], id="invalid_json"
        ),
        pytest.param(["truncated_json", SV, "ok"], 3, False, [TRUNCATED, "{}", FIXTURE_TEXT], id="truncated_json"),
        pytest.param([SV, SV], 3, False, ["{}", "{}", FIXTURE_TEXT], id="script-ends-then-ok"),
        pytest.param([MT, "ok"], 2, False, [FIXTURE_TEXT], id="max_tokens-retried-without-validation"),
        pytest.param([MT, MT, "ok"], 3, False, [TRUNCATED, FIXTURE_TEXT], id="second-max_tokens-is-validated"),
        pytest.param([MT, SV, SV, "ok"], 4, False, ["{}", "{}", FIXTURE_TEXT], id="max_tokens-counted-separately"),
        pytest.param(["ok", SV], 1, True, [FIXTURE_TEXT], id="actions-after-success-unused"),
    ],
)
def test_failure_script_success_paths(
    lexicon: Lexicon, script: list[str], attempts: int, first_pass_ok: bool, raws: list[str]
) -> None:
    validator = SpyValidator(lexicon)
    output, meta = MockAnalyzer({"src_0005": VALID}, {"src_0005": script}, validator=validator).analyze(
        analysis_input()
    )
    assert output.summary == VALID["summary"]
    assert (meta.attempts, meta.first_pass_ok, meta.partial) == (attempts, first_pass_ok, False)
    assert validator.raw_outputs == raws


@pytest.mark.parametrize(
    ("script", "error", "attempts", "raws"),
    [
        pytest.param([SV, SV, SV], AnalysisSchemaError, 3, ["{}", "{}", "{}"], id="repairs-exhausted"),
        pytest.param([MT, SV, SV, SV], AnalysisSchemaError, 4, ["{}", "{}", "{}"], id="max_tokens-plus-exhausted"),
        pytest.param(["refusal"], LLMRefusalError, 1, [], id="refusal"),
        pytest.param([SV, "refusal"], LLMRefusalError, 2, ["{}"], id="refusal-during-repair"),
        pytest.param(["provider_error"], LLMProviderError, None, [], id="provider_error"),
        pytest.param([SV, "provider_error", "ok"], LLMProviderError, None, ["{}"], id="provider_error-during-repair"),
    ],
)
def test_failure_script_failure_paths(
    lexicon: Lexicon, script: list[str], error: type[Exception], attempts: int | None, raws: list[str]
) -> None:
    validator = SpyValidator(lexicon)
    analyzer = MockAnalyzer({"src_0005": VALID}, {"src_0005": script}, validator=validator)
    with pytest.raises(error) as caught:
        analyzer.analyze(analysis_input())
    assert validator.raw_outputs == raws
    if attempts is not None:
        details = getattr(caught.value, "details", {})
        assert details["attempts"] == attempts
    if error is AnalysisSchemaError:
        assert caught.value.details["repair_attempts"] == 2  # type: ignore[attr-defined]


def test_failure_script_exhaustion_with_valid_summary_is_partial(lexicon: Lexicon) -> None:
    bad_intent = copy.deepcopy(VALID)
    bad_intent["save_intent"]["labels"] = ["데이트"]
    validator = SpyValidator(lexicon)
    output, meta = MockAnalyzer({"src_0005": bad_intent}, validator=validator).analyze(analysis_input())
    assert meta.partial and meta.attempts == 3 and len(meta.repairs) >= 0
    assert output.save_intent.labels == []
    assert output.summary == VALID["summary"]
    assert len(validator.raw_outputs) == 3


def test_failure_script_applies_to_map_reduce_input(lexicon: Lexicon) -> None:
    text = "\n\n".join(f"{index}번 문단. {SOURCE}" for index in range(400))
    plan = chunk_for_analysis(
        Snapshot(id="s_mr", content_id="c_mr", captured_at="2026-10-20T00:00:00Z", text=text),
        ContentMeta(source_id="src_mr", content_type="article", language="ko"),
        ChunkSettings(),
    )
    assert plan.mode == "map_reduce" and plan.chunks is not None and len(plan.chunks) > 1
    validator = SpyValidator(lexicon)
    _, meta = MockAnalyzer({"src_mr": VALID}, {"src_mr": ["truncated_json", "ok"]}, validator=validator).analyze(plan)
    assert meta.attempts == 2
    assert meta.input_tokens == 2 * len("\n\n".join(chunk.text for chunk in plan.chunks))
    assert validator.raw_outputs == [TRUNCATED, FIXTURE_TEXT]


def test_failure_script_without_source_id_uses_input_hash_then_default(lexicon: Lexicon) -> None:
    inp = AnalysisInput(mode="single", text=SOURCE, meta=ContentMeta(), source_token_count=len(SOURCE))
    canonical = inp.model_dump_json(exclude={"meta": {"source_id"}})
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    validator = SpyValidator(lexicon)
    _, meta = MockAnalyzer({"default": VALID}, {digest: [SV, "ok"]}, validator=validator).analyze(inp)
    assert meta.attempts == 2
    assert validator.raw_outputs == ["{}", FIXTURE_TEXT]

    _, by_default = MockAnalyzer({"default": VALID}, {"default": [SV, "ok"]}).analyze(inp)
    assert by_default.attempts == 2


def test_missing_fixture_names_the_key(lexicon: Lexicon) -> None:
    analyzer = MockAnalyzer({"a": VALID, "b": VALID}, validator=AnalysisValidator(lexicon))
    with pytest.raises(LLMProviderError) as caught:
        analyzer.analyze(analysis_input("zzz"))
    assert caught.value.details == {"fixture_key": "zzz"}


# --- T21 loop 1 M1: 녹화 키가 요청 파라미터(max_tokens, effort, schema)를 담는다 ---


class BudgetLLM:
    """max_tokens < 8000이면 잘린 응답, 이상이면 정상 응답을 내는 live 대역."""

    model_id = "budget-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        del system, user, timeout_s
        self.calls += 1
        if max_tokens < 8000:
            return LLMRawResponse(text='{"keywords": ["잘', stop_reason="max_tokens")
        return LLMRawResponse(text=json.dumps({"schema": schema.__name__, "effort": effort}), stop_reason="end_turn")

    def count_tokens(self, system: str, user: str) -> int | None:
        return 42


class Other(BaseModel):
    other: int = 0


def test_truncation_retry_recording_replays_each_budget_separately(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    recorder = RecordingLLM(BudgetLLM(), store)
    truncated = recorder.complete_json("sys", "같은 프롬프트", Out, 1.0, max_tokens=4000)
    full = recorder.complete_json("sys", "같은 프롬프트", Out, 1.0, max_tokens=8000)
    assert truncated.stop_reason == "max_tokens" and full.stop_reason == "end_turn"
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2

    replay = RecordedLLM(store, "budget-model")
    assert replay.complete_json("sys", "같은 프롬프트", Out, 99.0, max_tokens=8000) == full  # timeout은 키가 아니다
    assert replay.complete_json("sys", "같은 프롬프트", Out, 1.0, max_tokens=4000) == truncated
    with pytest.raises(LLMCacheMiss) as caught:
        replay.complete_json("sys", "같은 프롬프트", Out, 1.0, max_tokens=16000)
    assert caught.value.details["max_tokens"] == 16000


@pytest.mark.parametrize(
    "call",
    [
        pytest.param({"schema": Other}, id="schema"),
        pytest.param({"effort": "high"}, id="effort"),
        pytest.param({"max_tokens": 9000}, id="max_tokens"),
    ],
)
def test_replay_with_different_request_parameter_is_explicit_miss(tmp_path: Path, call: dict[str, Any]) -> None:
    store = tmp_path / "llm.jsonl"
    RecordingLLM(BudgetLLM(), store).complete_json("sys", "u", Out, 1.0, max_tokens=8000)
    params: dict[str, Any] = {"schema": Out, "max_tokens": 8000, "effort": None} | call
    with pytest.raises(LLMCacheMiss):
        RecordedLLM(store, "budget-model").complete_json(
            "sys", "u", params["schema"], 1.0, params["max_tokens"], params["effort"]
        )


def test_same_schema_name_with_different_shape_is_a_miss(tmp_path: Path) -> None:
    class Shape(BaseModel):
        a: int = 0

    first = Shape
    store = tmp_path / "llm.jsonl"
    RecordingLLM(BudgetLLM(), store).complete_json("sys", "u", first, 1.0, max_tokens=8000)

    class Shape(BaseModel):  # type: ignore[no-redef]  # 같은 이름, 다른 필드
        b: str = ""

    with pytest.raises(LLMCacheMiss):
        RecordedLLM(store, "budget-model").complete_json("sys", "u", Shape, 1.0, max_tokens=8000)


def test_schema_fingerprint_ignores_documentation_but_tracks_structure() -> None:
    documented_a = create_model(
        "Shape",
        value=(str, Field(min_length=2, max_length=8, title="첫 제목", description="첫 설명")),
    )
    documented_b = create_model(
        "Shape",
        value=(str, Field(min_length=2, max_length=8, title="다른 제목", description="다른 설명")),
    )
    documented_a.__doc__ = "첫 모델 설명"
    documented_b.__doc__ = "다른 모델 설명"
    longer = create_model("Shape", value=(str, Field(min_length=3, max_length=8)))
    different_type = create_model("Shape", value=(int, ...))
    optional = create_model("Shape", value=(str, Field(default="기본값", min_length=2, max_length=8)))
    field_named_title = create_model("Shape", title=(str, ...))

    assert schema_fingerprint(documented_a) == schema_fingerprint(documented_b)
    assert schema_fingerprint(documented_a) != schema_fingerprint(longer)
    assert schema_fingerprint(documented_a) != schema_fingerprint(different_type)
    assert schema_fingerprint(documented_a) != schema_fingerprint(optional)
    assert schema_fingerprint(documented_a) != schema_fingerprint(field_named_title)


def test_request_key_has_no_separator_ambiguity(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    recorder = RecordingLLM(BudgetLLM(), store)
    recorder.complete_json("a\x00b", "c", Out, 1.0, max_tokens=8000)
    recorder.complete_json("a", "b\x00c", Out, 1.0, max_tokens=8000)
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2


def test_version_1_recording_is_rejected_with_rerecord_hint(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    row = {"format_version": 1, "model_id": "m", "prompt_hash": "x", "response": {"text": "{}"}}
    store.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(LLMProviderError) as caught:
        RecordedLLM(store, "m")
    assert caught.value.details["line"] == 1


def test_count_tokens_is_recorded_and_replayed_with_explicit_miss(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    recorder = RecordingLLM(BudgetLLM(), store)
    recorder.complete_json("sys", "u", Out, 1.0, max_tokens=8000)
    assert recorder.count_tokens("sys", "u") == 42

    replay = RecordedLLM(store, "budget-model")
    assert replay.count_tokens("sys", "u") == 42  # complete 응답의 input_tokens(0)가 아니라 live count 값
    with pytest.raises(LLMCacheMiss):
        replay.count_tokens("sys", "녹화 안 됨")


# --- T21 loop 1 M2: 녹화 쪽 빈틈 (충돌 행, 쓰기 실패, 다른 모델, 동시 기록) ---


def _recorded_row(tmp_path: Path) -> dict[str, Any]:
    store = tmp_path / "seed.jsonl"
    RecordingLLM(BudgetLLM(), store).complete_json("sys", "u", Out, 1.0, max_tokens=8000)
    row: dict[str, Any] = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    return row


def test_conflicting_duplicate_rows_are_rejected_but_identical_ones_allowed(tmp_path: Path) -> None:
    row = _recorded_row(tmp_path)
    same = tmp_path / "same.jsonl"
    same.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    RecordedLLM(same, "budget-model")

    other = copy.deepcopy(row)
    other["response"]["text"] = "{}"
    conflict = tmp_path / "conflict.jsonl"
    conflict.write_text(json.dumps(row) + "\n" + json.dumps(other) + "\n", encoding="utf-8")
    with pytest.raises(LLMProviderError) as caught:
        RecordedLLM(conflict, "budget-model")
    assert caught.value.details["line"] == 2


def test_other_model_id_misses(tmp_path: Path) -> None:
    row = _recorded_row(tmp_path)
    store = tmp_path / "one.jsonl"
    store.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(LLMCacheMiss):
        RecordedLLM(store, "another-model").complete_json("sys", "u", Out, 1.0, max_tokens=8000)


def test_write_failure_is_provider_error(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    recorder = RecordingLLM(BudgetLLM(), blocker / "llm.jsonl")
    with pytest.raises(LLMProviderError, match="쓰지"):
        recorder.complete_json("sys", "u", Out, 1.0, max_tokens=8000)


def test_concurrent_recording_writes_each_request_once(tmp_path: Path) -> None:
    store = tmp_path / "llm.jsonl"
    recorder = RecordingLLM(BudgetLLM(), store)
    threads = [
        threading.Thread(target=recorder.complete_json, args=("sys", f"프롬프트 {index % 10}", Out, 1.0, 8000))
        for index in range(200)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.read_text(encoding="utf-8").splitlines()) == 10


# --- T25p: 판정기 오류 사이드카 (T25g 검수 M1) -----------------------------------------------------------------------


def test_recording_failure_sidecar_replays_error_codes_and_response_wins(tmp_path: Path) -> None:
    from pydantic import BaseModel as _Model

    from jupjup.domain.errors import LLMCacheMiss, LLMProviderError, LLMTimeoutError
    from jupjup.providers.llm import LLMRawResponse
    from jupjup.providers.recording import RecordedLLM, RecordingLLM, failure_store_path

    class Out(_Model):
        value: str

    class Flaky:
        model_id = "judge-model"

        def __init__(self) -> None:
            self.fail: dict[str, Exception] = {}

        def complete_json(
            self,
            system: str,
            user: str,
            schema: type[_Model],
            timeout_s: float,
            max_tokens: int = 4000,
            effort: str | None = None,
        ) -> LLMRawResponse:
            if user in self.fail:
                raise self.fail[user]
            return LLMRawResponse(text='{"value":"ok"}', input_tokens=1, output_tokens=1, latency_ms=1.0)

        def count_tokens(self, system: str, user: str) -> int | None:
            return None

    store = tmp_path / "judge.m.jsonl"
    sidecar = failure_store_path(store)
    assert sidecar.name == "judge.m.failures.jsonl"
    inner = Flaky()
    inner.fail = {
        "timeout": LLMTimeoutError("느림 <원문>", {"retryable": True, "timeout_s": 5}),
        "oom": LLMProviderError("메모리 <원문>"),
        "later_ok": LLMTimeoutError("느림", {"retryable": True}),
    }
    recording = RecordingLLM(inner, store, failures_path=sidecar)
    recording.complete_json("s", "fine", Out, 5.0)
    for user in ("timeout", "oom", "later_ok", "timeout"):  # 같은 오류 요청은 한 번만 남는다
        with pytest.raises(LLMProviderError):
            recording.complete_json("s", user, Out, 5.0)
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3 and "<원문>" not in sidecar.read_text(encoding="utf-8")
    assert [row["error"] for row in rows] == [
        {"code": "LLM_TIMEOUT", "retryable": True},
        {"code": "LLM_UNAVAILABLE", "retryable": None},
        {"code": "LLM_TIMEOUT", "retryable": True},
    ]
    # 다시 녹화해서 성공하면 응답 행이 생기고, 재생은 응답이 이긴다
    del inner.fail["later_ok"]
    RecordingLLM(inner, store, failures_path=sidecar).complete_json("s", "later_ok", Out, 5.0)

    replay = RecordedLLM(store, "judge-model", failures_path=sidecar)
    assert replay.complete_json("s", "fine", Out, 5.0).text == '{"value":"ok"}'
    assert replay.complete_json("s", "later_ok", Out, 5.0).text == '{"value":"ok"}'
    with pytest.raises(LLMTimeoutError) as timeout:
        replay.complete_json("s", "timeout", Out, 5.0)
    assert timeout.value.code == "LLM_TIMEOUT" and timeout.value.details["replayed"] is True
    with pytest.raises(LLMProviderError) as oom:
        replay.complete_json("s", "oom", Out, 5.0)
    assert oom.value.code == "LLM_UNAVAILABLE" and not isinstance(oom.value, LLMTimeoutError)
    with pytest.raises(LLMCacheMiss):
        replay.complete_json("s", "never", Out, 5.0)
    # 사이드카 없이 재생하면 예전처럼 미스다
    with pytest.raises(LLMCacheMiss):
        RecordedLLM(store, "judge-model").complete_json("s", "timeout", Out, 5.0)
    # 응답 파일 형식(v2)은 그대로다: 오류 요청은 응답 파일에 없다
    kinds = {json.loads(line)["kind"] for line in store.read_text(encoding="utf-8").splitlines()}
    assert kinds == {"complete_json"}

    sidecar.write_text('{"format_version": 2, "kind": "complete_json_error"}\n', encoding="utf-8")
    with pytest.raises(LLMProviderError, match="오류 녹화본 형식"):
        RecordedLLM(store, "judge-model", failures_path=sidecar)


def test_failure_only_recording_replays_without_success_file(tmp_path: Path) -> None:
    from jupjup.domain.errors import LLMTimeoutError
    from jupjup.providers.recording import failure_store_path

    store = tmp_path / "analyze.failed.jsonl"
    sidecar = failure_store_path(store)
    sidecar.write_text(
        json.dumps(
            {
                "format_version": 2,
                "kind": "complete_json_error",
                "model_id": "m",
                "request_hash": complete_request_hash("s", "u", Out, 4000, None),
                "error": {"code": "LLM_TIMEOUT", "retryable": True},
            }
        )
        + "\n"
    )
    assert not store.exists()
    replay = RecordedLLM(store, "m", failures_path=sidecar)
    with pytest.raises(LLMTimeoutError):
        replay.complete_json("s", "u", Out, 30.0)
    with pytest.raises(LLMCacheMiss):
        replay.complete_json("s", "missing", Out, 30.0)
