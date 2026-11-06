# Phase 4 최종 검수: 인제스트 T18(분석 스키마·검증), Loop 2/3

- **점수:** 95 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 28 / 30, 유지보수성 29 / 30
- **루프백 대상:** 없음 (PASS). 아래 M1-n은 T22 착수 전에 작은 수정으로 처리하기를 권한다(Phase 2, `src/jupjup/ingest/validation.py`만 해당).
- **검수 대상:** `phase-4-review-ingest-t18-loop2` HEAD `f56ce5b` (`fix: address T18 ingest review loop 1 feedback`). 직전 검수 `b77d0fb`(T18 Loop 1, 87점 REJECT)
- **기준 문서:** `specs/prd_and_design.md` 5.10절(특히 5.10.5·5.10.6), 6.4절, 5.8.1절, 7.3절 T18 행과 완료 조건, AC-25, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`, `specs/phase4_review_ingest-t18_loop1.md`. 구현 보고서 `specs/phase2_ingest-t18_loop2_report.md`의 주장은 모두 직접 다시 확인했다.
- **채점 정책:** Loop 1과 같은 엄격도. 사람 검수 0건은 감점하지 않았다. 범위 밖: T19 이후(수집, 청킹, 잡 큐, 워커, 인제스트 API), 실제 LLM 연동, 리랭커 채택. 범위 밖 항목은 "T22 착수 시 참고"로만 적었다.

## 0. 요약

- **Loop 1 필수 항목 H1·M1·M2는 모두 고쳐졌다.** 21~40자 대표 태그 ×3은 이제 fixable `tag_too_long`으로 빠지고, 3개 미만이 되면 `AnalysisSchemaError`로 끝난다. pydantic `ValidationError`는 더 새지 않는다. 소수점·도메인이 든 4문장 요약은 통과하고, `6.5천원` 1문장 요약은 거부된다. 생성 스키마 `representative_tags.items`는 `{"type":"string","minLength":1,"maxLength":20}`다.
- **권장 항목 L1~L5, L7, L8, MT1~MT3도 처리됐다.** strict 타입(`"0.9"`·`true` 거부), language 소문자화와 ISO 639-1 검사, 별칭 근거 강화, 잘림 뒤 배수 2 유지, `LLMRefusalError`의 `ProviderError` 분리, `first_pass_ok` 정의, 라벨 우선 purpose, 스키마 주입 일원화, 테스트 10→28개. L6은 Architect 결정 사항으로 남았다(문서화됨).
- **T18 완료 조건 6개는 별도 입력으로 모두 재현된다.** 검색 순위 무회귀도 확인했다: eval 4종이 Loop 1과 소수점 4자리까지 같고, `src/jupjup/search`·`src/jupjup/query`·`data/` diff는 0줄이다.
- **남은 결함 한 건(M1-n, 중간):** 병적인 JSON 두 가지가 여전히 계약 밖 예외를 낸다. 4,301자리 넘는 정수 리터럴은 `json.loads`에서 `JSONDecodeError`가 아닌 순수 `ValueError`를 내고, 497단계 넘게 중첩된 배열은 `copy.deepcopy`에서 `RecursionError`를 낸다. 둘 다 첫 응답에서 바로 터지고 재요청을 하지 않는다. Loop 1 재검수 조건 1("어떤 LLM 응답에서도")을 글자 그대로는 어기지만, H1과 달리 정상적인 LLM 출력에서는 생기기 어렵다. 그래서 PASS를 막지 않고 2.5점만 감점했다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **674 passed, 3 deselected, 1 warning** (33.0s). 보고서 주장과 같다. 경고는 기존 Starlette `httpx` 비권장 |
| `uv run pytest tests/unit/test_ingest_validation.py` | 28 passed |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check` (변경 파일 5개) | 5 files already formatted |
| `uv run mypy src` | Success: no issues found in 63 source files |
| `uv run jupjup eval validate` | PASS. 카테고리 15종, review_status ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS: R@10 0.9620, MRR 0.9958, nDCG 0.9795 (Loop 1과 같음) |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589 (같음) |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860 (같음) |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720 (하한 0.972), MRR 0.9911, nDCG 0.9801 (같음) |
| 4종 공통 | filter_violations 0, browse precision·sort·filter 1.0, time_exact·platform_f1 1.0 |
| `git diff 397d2a3 HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | 0 |
| `grep -rn jupjup.ingest src` (ingest 밖) | 없음. 검색 경로가 새 모듈에 의존하지 않는다 |

### 1.2 CLI 회귀·경계값 (`uv run jupjup seed load --db var/review.db`, 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00`)

seed load: 200줄 / 적재 200 / 인덱싱 200 (alice 160, bob 30, carol 10). 검색 코드가 바뀌지 않았으므로 동작 확인 목적이다. 모두 Loop 1 때와 같다.

| 사례 | 결과 |
|---|---|
| `성수 카페` (bob) | 성수→성수동(synonym), 2건(노티드, 카페 추천 세 곳). 사용자 격리 정상 |
| `성슈 카페` (오타) | 키워드 `성슈, 카페` + 의미 질의. 기존 동작 그대로 |
| 빈 문자열 / 201자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` |
| `!!!@@` (특수문자) | `[INVALID_QUERY] 검색할 단어가 없어요.` |
| `지난주 유튜브` (필터 전용) | browse, 2026-10-05 ~ 2026-10-12, 1건(유튜브) |
| `유튜브` + `--platform instagram` (요청 잠금) | `overridden_by_request=["platforms"]`, 10건 모두 instagram |
| `성수 카페` + `--platform youtube` | 1건(youtube), 완화 없음 |
| `python async tutorial 영상` (영어 혼합) | lookup, 유형 영상(hard), 키워드 3개 |
| `화성 식민지 부동산` (없는 대상) | 0건, `empty_state.reason=no_relevant_match`, `applied_relaxations=[]` (과잉 완화 없음) |
| `카페` (u_nobody) | 저장물 없음 안내 |
| `JUPJUP_MODE=recorded` 임의 질의 | `[EMBEDDING_CACHE_MISS]` (녹화본에 없는 텍스트, 기존 동작) |

### 1.3 T18 직접 재현 (스크래치 스크립트, 테스트 파일과 다른 입력)

`AnalysisValidator(Lexicon.load(Path("data/lexicon")))`와 스크립트형 `call`로 `validate_and_repair`를 돌렸다. 원문에는 `6.5천원`, `Python 3.12`, `example.com`을 넣었다.

| 입력 | 결과 | 판정 |
|---|---|---|
| **[완료 조건] 잘린 JSON** `{"summary": "잘` → 정상 | attempts 2, repair 1, ctx `validation` | OK |
| **[완료 조건] enum 밖 값** `labels:["데이트"]` → 정상 | attempts 2 | OK |
| enum 밖 ×3 | partial, `save_intent.labels=[]`, 호출 3회 | OK |
| **[완료 조건] 태그 8개** (`…주말, 브런치`) | 재요청 없음, 7개 유지. 단 `브런치`는 플랫폼명으로 제거됨(L1-n) | OK |
| **[완료 조건] 근거 없는 엔티티** `홍길동` | 제거, 재요청 없음 | OK |
| **[완료 조건] `max_tokens`** → 정상 | ctx `[None, (max_tokens, ×2)]`, repair 0 | OK |
| `max_tokens` → `max_tokens` → 무효 → 정상 | ctx `[None, (max_tokens,×2), (validation,×2,1), (validation,×2,2)]`, attempts 4 | OK (Loop 1 L4 해결) |
| **[완료 조건] 소진 → partial** (evidence 무근거 ×3) | partial, evidence `[]` | OK |
| **[완료 조건] 소진 → failed** (요약 `짧음` ×3) | `AnalysisSchemaError(ANALYSIS_SCHEMA_INVALID)`, 호출 3회 | OK |
| `refusal` | 호출 1회, `LLMRefusalError(LLM_REFUSED)`, `ProviderError` 아님 | OK (L5 해결) |
| **H1** 25자 태그 + 3개 정상 | `tag_too_long` 제거, 첫 시도 통과 | OK |
| **H1** 21자 태그 + 2개 ×3 | `AnalysisSchemaError` (3개 미만) | OK |
| **H1** 25·30·40자 ×3 | `AnalysisSchemaError` | OK |
| **M1** 소수점·도메인 포함 4문장 | 통과 | OK |
| **M1** `…6.5천원입니다` 1문장 | `summary_sentence_count`로 거부 | OK |
| 5문장 | 거부 | OK |
| `"…인기예요." 라고 했습니다. …` (인용 안 마침표) | 2문장으로 셈, 통과 | OK (참고 L3-n) |
| `…출시했습니다.주말 오전…` (마침표 뒤 공백 없음) | 1문장으로 세어 재요청 | 참고 L3-n |
| **M2** `representative_tags` 스키마 | `items {type string, minLength 1, maxLength 20}`, minItems 3, maxItems 7 | OK |
| `AnalysisOutput.model_json_schema() == analysis_output_json_schema()` | True, 최상위 `description` 없음 | OK (MT2 해결) |
| `confidence: "0.9"` / `true` | 각각 1회 재요청 뒤 성공(첫 시도 거부) | OK (L1 해결) |
| `confidence: 1` (JSON 정수) | 통과 | OK (JSON Schema `number`와 같음) |
| `confidence: NaN` / `Infinity` ×3 | `schema_less_than_equal` → partial, labels `[]` | OK |
| `language: "KO"` | `ko`로 정규화, fixable | OK (L2 해결) |
| `language: "zz"` / `" ko"` / `"korean"` ×3 | `language_invalid` → `AnalysisSchemaError` | OK (설계 차이 2, L2-n) |
| `language: "en"` | 통과 | OK |
| 엔티티 `홍길동` + 별칭 `["수"]` | 별칭 제거 → 엔티티 제거 | OK (L3 해결) |
| 엔티티 `Pyth` + 별칭 `["pyt"]` (영문 부분 문자열) | 별칭 제거 | OK |
| 엔티티 `파이썬` + 별칭 `["python"]` (토큰 일치) | 유지 | OK |
| 엔티티 `홍길동` + 별칭 `["성수"]` (2자, 이름과 무관) | **유지** | L2-n |
| 엔티티 name `수` (1자) | **유지** | L2-n |
| purpose 5개 + labels 3개 | labels 3개가 앞, purpose `[방문예정, 레시피, a, b, c]` | OK (L8 해결) |
| title 81자 / detail_tags 무효 / extra 키 ×3 | 모두 partial, 해당 필드만 빈 값 | OK |
| evidence 21개 ×3 | partial, 20개 | OK |
| 플랫폼 태그 제거로 2개 남음 ×3 | `AnalysisSchemaError` | OK |
| 태그에 정수 섞임 ×3 | `AnalysisSchemaError` | OK |
| `"["*5000+"]"*5000` (최상위 배열) | `json_type` → `AnalysisSchemaError` | OK |
| 고립 서러게이트 `\ud800` ×3 | `schema_string_unicode` → `AnalysisSchemaError` | OK |
| 태그에 NUL | 정규화로 제거 | OK |
| **`confidence`에 4,301자리 정수** | **`ValueError: Exceeds the limit (4300 digits)…` 누출**, 호출 1회 | **M1-n** |
| **`detail_tags.topics`에 497단계 중첩 배열** | **`RecursionError` 누출** (`_prepare_payload` → `copy.deepcopy`), 호출 1회 | **M1-n** |
| 성능: 100k자 원문 + 무근거 evidence 20개 ×3 | 3.10s (시도당 약 1s) | OK (분석 잡 예산 안) |

## 2. 스키마 필드 단위 대조 (5.10.5절·6.4절 ↔ `analysis_output_json_schema()`)

| 필드 | 설계 | 생성 스키마 / Pydantic | 일치 |
|---|---|---|---|
| 최상위 | object, `additionalProperties: false`, required 7개 | 같음 (`extra="forbid"`, `strict=True`) | O |
| `summary` | string, 20~400, description | 같음 | O |
| `title_suggestion` | `["string","null"]`, maxLength 80, required | `anyOf[string≤80, null]`, required | O (표현만 다름) |
| `representative_tags` | array 3~7, items string 1~20 | 같음 (`RepresentativeTag` Annotated) | **O (M2 해결)** |
| `detail_tags` | `$ref jupjup/detail_tags/v1` | `$ref #/$defs/DetailTagsV1`, 정본 `detail_tags_schema()` 깊은 복사 | O |
| `save_intent` | object, additionalProperties false, required 3 | 같음 | O |
| `save_intent.labels` | array ≤3, enum 12개 | 같음, 순서까지 같음 | O |
| `save_intent.confidence` | number 0~1 | 같음. 이제 strict라 문자열·bool 거부 | O |
| `save_intent.rationale` | string ≤120 | 같음 | O |
| `language` | string, "ISO 639-1" | 같음 + 후처리 ISO 639-1 전체 목록(184개) 검사 | O |
| `evidence` | array ≤20, item `{claim, source_span≤200}` additionalProperties false | 같음 | O |
| 6.4 `save_intent` 하위 필드 | `labels`, `confidence`, `inferred` | `materialized_detail_tags()`가 같은 키로 만들고 v1로 재검증 | O |
| 5.8.1 추가 에러 | `AnalysisSchemaError(ANALYSIS_SCHEMA_INVALID)`, `LLMRefusalError(LLM_REFUSED)` | 둘 다 `JupjupError` 직계, code 일치 | O |
| 5.10.8 인터페이스 | `ValidationIssue`, `validate`, `auto_fix`, `validate_and_repair(..., max_repairs=2) -> RepairOutcome(...)` | 같은 시그니처. `RepairOutcome.repair_attempts` 추가 | O |

## 3. Loop 1 피드백 처리 확인

| ID | 상태 | 확인 근거 |
|---|---|---|
| H1 | 해결 | `validation.py:183-192` `tag_too_long`, `:389-402` `partial_output`의 `ValidationError → None`. 1.3절 H1 3건 |
| M1 | 해결 | `validation.py:22` `(?=\s|$)`. 1.3절 소수점 4문장·1문장 |
| M2 | 해결 | `schemas.py:28`, `:50`. 테스트가 필드 단위로 단언(`test_analysis_output_schema_reuses_detail_tags_v1`) |
| L1 | 해결 | `schemas.py:32`, `:40`, `:47` `strict=True` |
| L2 | 해결(설계 차이 문서화) | `validation.py:265-275`, `:309-316`, `:374-376` |
| L3 | 대부분 해결 | `validation.py:80-92`, `:234-262`. 남은 경우는 L2-n |
| L4 | 해결 | `validation.py:475` |
| L5 | 해결 | `domain/errors.py:52` |
| L6 | 미해결(Architect 결정 대기, 문서화) | `validation.py:352-354` |
| L7 | 해결 | `validation.py:462` |
| L8 | 해결 | `schemas.py:95` |
| MT1 | 해결(docstring) | `validation.py:334` |
| MT2 | 해결 | `schemas.py:66-89`, `:106-108` |
| MT3 | 해결 | 테스트 28개. 남은 공백은 MT1-n |

## 4. 피드백 (심각도 순)

### M1-n (중간) 병적인 JSON이 계약 밖 예외를 낸다 — `src/jupjup/ingest/validation.py:280-289`, `:155`, `:341-344`

- **재현 1:** `"confidence": 1111…1`(4,301자리). `json.loads`가 `JSONDecodeError`가 아니라 일반 `ValueError("Exceeds the limit (4300 digits) for integer string conversion…")`를 낸다. `validate()`는 `except json.JSONDecodeError`만 잡으므로(`:282`) 그대로 새어 나간다. 4,300자리는 통과하고 4,301자리부터 터진다.
- **재현 2:** `detail_tags.topics`에 497단계 넘게 중첩된 배열. `json.loads`는 성공하지만 `_prepare_payload`의 `copy.deepcopy(data)`(`:155`)가 `RecursionError`를 낸다(기본 재귀 한도 1000에서 이분 탐색으로 497 확인). 최상위가 배열이면 `json_type`에서 먼저 걸려 안전하다. 객체 안에 중첩될 때만 터진다.
- **왜 문제인가:** 둘 다 첫 응답에서 바로 터져 재요청 기회를 쓰지 않고, `JupjupError`가 아니라서 5.10.2절 I5 실패 분류(재시도/영구)로 나눌 수 없다. Loop 1 재검수 조건 1 "어떤 LLM 응답 3연속에서도 `RepairOutcome`, `AnalysisSchemaError`, `LLMRefusalError` 외의 예외를 내지 않는다"를 글자 그대로는 어긴다. 다만 구조화 출력이 켜져 있으면 중첩 배열은 스키마가 막고, 수천 자리 정수는 반복 루프에 빠진 출력에서나 나온다. 실제로 생길 가능성이 낮아 PASS를 막지 않았다.
- **고칠 방향:** (1) `validate()`와 `partial_output()`의 파싱을 `except (ValueError, RecursionError)`로 넓혀 `json_parse` 이슈로 돌린다(`JSONDecodeError`는 `ValueError`의 하위라 위치 정보는 분기해서 유지). (2) `_prepare_payload`의 `deepcopy`도 `RecursionError`를 잡아 `json_depth` unfixable 이슈로 만들거나, 파싱 직후 최대 깊이(예: 32)를 검사한다. (3) `test_adversarial_llm_outputs_only_return_contract_outcomes`(`tests/unit/test_ingest_validation.py:340-355`) 말뭉치에 두 사례를 추가한다.

### L1-n (낮음) 플랫폼 금지어가 일반 명사 태그까지 지운다 — `src/jupjup/ingest/validation.py:141-146`, `:163-172`

`_forbidden_tags`가 lexicon의 플랫폼 별칭을 모두 쓴다. 그래서 `브런치`(식사), `뉴스`, `기사`, `신문`, `웹`, `사이트` 같은 일반 명사 대표 태그도 "플랫폼명 단독"으로 빠진다. 1.3절 8태그 사례에서 브런치 카페 저장물의 `브런치` 태그가 사라졌다. food_drink는 이 서비스의 핵심 카테고리라 영향이 있다. 5.10.6-2(c) 규칙의 목적은 `인스타`, `유튜브`처럼 플랫폼 자체를 가리키는 태그를 막는 것이다. 금지 목록을 플랫폼 전용 별칭(검색 질의용 별칭과 따로)으로 줄이거나, `브런치`처럼 뜻이 둘인 단어는 예외 목록으로 둔다. 검색 질의의 플랫폼 해석은 그대로 둔다.

### L2-n (낮음) 2자 한글 별칭과 1자 이름이 여전히 근거로 쓰인다 — `src/jupjup/ingest/validation.py:92`, `:249`

`{"name": "홍길동", "aliases": ["성수"]}`는 원문 `성수동`의 부분 문자열 `성수`로 유지되고, name이 `수` 한 글자인 엔티티도 `_grounded`의 부분 문자열 검사로 유지된다. Loop 1 L3의 한 글자 별칭은 막혔지만, 이름과 상관없는 짧은 별칭으로 환각 엔티티가 인덱스에 들어가는 경로는 남았다. name에도 같은 최소 길이 규칙을 쓰고, 별칭은 이름과 어떤 식으로든 연관되거나(자모 유사도, 접두) 원문의 토큰 경계와 일치할 때만 근거로 인정하는 방안을 권한다.

### L3-n (낮음, 참고) 문장 경계가 공백에만 의존한다 — `src/jupjup/ingest/validation.py:22`

`(?=\s|$)` 때문에 `…했습니다.주말…`처럼 마침표 뒤 공백이 없는 2문장은 1문장으로 세어 재요청한다(거짓 양성). `"…예요." 라고`처럼 따옴표 안 마침표는 세지 않는데, 이쪽은 오히려 바른 결과다. LLM 요약은 거의 늘 공백을 넣으므로 감점하지 않았다. 필요하면 `(?=\s|$|[가-힣A-Z])`처럼 다음 글자가 한글이나 대문자일 때도 경계로 본다(소수점·도메인과 겹치지 않는다).

### L4-n (낮음, Architect 결정) partial 범위가 설계 문구보다 좁다 — `src/jupjup/ingest/validation.py:352-354`, `:374-376`

Loop 1 L6(대표 태그 3개 미만이면 failed)에 더해, 이번에 language가 무효하면 요약이 유효해도 failed가 된다(보고서 설계 차이 2). 원문 언어를 지어내지 않는 쪽이라 안전하지만, 5.10.6-4 "요약은 통과했는데 일부 필드만 실패 → 그 필드를 비우고 partial"과 다르다. Architect가 (a) partial 전용 스키마 허용, (b) language 대체값(I2 `SnapshotDraft.language` 또는 `"und"`)을 정해 5.10.6절을 고쳐야 한다. 검색은 스냅샷 축약 인덱스로 이어지므로 0.5점만 감점했다.

### 유지보수성

- **MT1-n** 퍼즈 테스트가 얕다 — `tests/unit/test_ingest_validation.py:340-355`. 무작위 말뭉치가 깊이 1의 스칼라 값만 만들어서 M1-n 같은 파서·재귀 경로를 건드리지 않는다. 중첩 깊이, 큰 수, 서러게이트, 아주 긴 문자열을 넣은 생성기를 더한다.
- **MT2-n** 사소한 중복 — `validation.py:462`의 `first_pass_ok=attempts == 1 and not unfixable`에서 그 분기는 항상 `unfixable == []`이라 `attempts == 1`과 같다. `partial_output`(`:351`)은 `_prepare_payload`를 다시 돌린다(마지막 응답 한 번이라 비용은 작다). 동작 문제는 아니다. 감점 0.
- **MT3-n** `auto_fix`(`:328-337`)는 설계 시그니처를 지키려고 남긴 수집 함수다. docstring으로 역할이 분명해졌으므로 감점하지 않는다. T22에서 `analysis_runs.repairs` 기록부를 만들 때 이름을 그대로 둘지 정하면 된다.

### T22 착수 시 참고 (점수 제외)

- `LLMRefusalError`·`AnalysisSchemaError`의 API 상태 코드(`api/errors.py`)는 아직 없다(보고서 남은 문제와 같음).
- partial language 대체값을 받으려면 `validate_and_repair` 또는 `partial_output`에 감지 언어 인자가 필요하다(L4-n).

## 5. 항목별 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 38 / 40 | 완료 조건 6개 재현, 스키마 필드 전부 일치, H1·M1·M2 해결, 검색 무회귀(+). M1-n 첫 응답 예외 누출 −1, L1-n 일반 명사 태그 제거 −0.5, L4-n partial 범위(설계 차이, 문서화) −0.5 |
| 안전성 | 28 / 30 | 루프 상한, 원본 불변, 거절 즉시 중단, strict 타입, 별칭 근거 강화, 거절과 재시도 오류 분리(+). M1-n 미분류 예외(Loop 1 재검수 조건 1 위반이나 발생 가능성 낮음) −1.5, L2-n 짧은 별칭·1자 이름 −0.5 |
| 유지보수성 | 29 / 30 | 스키마 주입 일원화, 테스트 28개, 피드백별 테스트와 설계 차이 문서화가 좋다(+). MT1-n 퍼즈 범위 −0.5, MT2-n 사소한 중복 −0.5 |
| **합계** | **95 / 100** | 90 이상 → **PASS** |

## 6. 다음 단계 권장

1. **PASS.** T18을 PM 브랜치에 병합해도 된다. M1-n은 T22 착수 전에 작은 수정 PR로 처리하기를 권한다(파싱 예외 범위 확대와 깊이 제한, 테스트 2개).
2. L1-n(금지 태그 목록)과 L2-n(짧은 별칭)은 T21/T22 데이터 품질 작업 때 같이 처리하면 된다.
3. Architect 확인 사항: L4-n(partial 전용 스키마, language 대체값), Loop 1 L7의 `first_pass_ok` 정의가 AC-25 `analysis_runs` 기록 의미와 맞는지.
4. 게이트 유지: pytest 전부 통과, ruff·mypy 무경고, eval 4종 수치 유지, `src/jupjup/search`·`src/jupjup/query`·`data/` diff 0.
