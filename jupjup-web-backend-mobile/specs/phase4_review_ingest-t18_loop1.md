# Phase 4 최종 검수: 인제스트 T18(분석 스키마·검증), Loop 1/3

- **점수:** 87 / 100
- **상태:** REJECT
- **항목별:** 정확성 34 / 40, 안전성 26 / 30, 유지보수성 27 / 30
- **루프백 대상:** Phase 2 (기능/버그 문제). H1 한 건과 M1·M2가 고쳐지면 PASS권이다. 수정 범위는 `src/jupjup/ingest/`와 해당 단위 테스트로 작다.
- **검수 대상:** `phase-4-review-ingest-t18-loop1` HEAD `2770641` (`feat: implement T18 ingest analysis validation`). 직전 검수 `397d2a3`(보강 Loop 1)
- **기준 문서:** `specs/prd_and_design.md` 5.10절(특히 5.10.5·5.10.6·5.10.8), 6.4절, 5.8.1절, 7.3절 T18 행, AC-25, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`. T18 이전 검수 파일은 없다(이번이 첫 회).
- **채점 정책:** 이전 검수와 같은 엄격도. 사람 검수 0건은 감점하지 않았다. 범위 밖: T19 이후(수집, 청킹, 잡 큐, 워커, 인제스트 API), 실제 LLM 연동, 리랭커 채택. 범위 밖 항목은 "T22 착수 시 참고"로만 적고 점수에 넣지 않았다.

## 0. 요약

- **T18 완료 조건 6개는 모두 재현된다.** 잘린 JSON → `json_parse` 재요청, enum 밖 값 → `$.save_intent.labels[0]` 재요청, 태그 8개 → 정규화 후 7개 절단(재요청 없음), 근거 없는 엔티티 → 제거(재요청 없음), `max_tokens` → 재요청 횟수와 별도 1회·배수 2, 재요청 2회 소진 → 요약 유효 시 partial / 요약 무효 시 `AnalysisSchemaError`. 호출 횟수는 소진 시 정확히 3회로 묶이고 무한 루프가 없다. 거절(`refusal`)은 1회 호출 뒤 `LLMRefusalError(LLM_REFUSED)`로 끝난다.
- **검색 순위 무회귀.** eval 4종이 직전 검수와 소수점 4자리까지 같다(기준선 회귀 게이트 포함). `src/jupjup/search`, `src/jupjup/query`, `data/` diff는 0줄이고 `jupjup.ingest`를 import하는 검색 경로도 없다.
- **하지만 partial/failed 분기 자체에 계약 위반이 있다(H1).** 대표 태그 하나가 정규화 후 21~30자인 응답이 3번 오면 `validate_and_repair`가 `AnalysisSchemaError`도 partial도 아닌 **pydantic `ValidationError`를 그대로 던진다**. 5.10.2절 실패 분류(I5는 `AnalysisSchemaError`/`LLMProviderError`/`LLMRefusalError`만)를 깨므로 T22 워커가 분류할 수 없는 예외가 된다.
- **요약 문장 수 규칙이 소수점에서 틀린다(M1).** `3.12`, `4.5점`, `1.5만원`의 `.`을 문장 끝으로 센다. 4문장 요약이 5문장으로 거부되고, 1문장 요약이 2문장으로 통과한다. 요약 실패는 소진 시 잡 `failed`로 이어지는 유일한 경로라 영향이 크다.
- **생성 JSON Schema가 5.10.5절과 한 군데 다르다(M2).** `representative_tags.items`의 `minLength: 1`, `maxLength: 20`이 빠졌다. 길이 검사를 `field_validator`로만 해서 LLM에 강제할 스키마에 실리지 않는다. 나머지 필드는 필드 단위로 일치한다(2절).

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본 addopts) | **656 passed, 3 deselected, 1 warning** (33.3s). 직전 646 + T18 10개. 경고는 기존 Starlette `httpx` 비권장 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 63 source files |
| `uv run jupjup eval validate` | PASS. seeds 200, queries 259 (dev 158 / test 101), lexicon 139, reviewed 0 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS: R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat-min 0.8838 (직전과 동일) |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589, cat-min 0.7812 (동일) |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860, cat-min 0.8894 (동일) |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720 (회귀 하한 0.972), MRR 0.9911, nDCG 0.9801, cat-min 0.8900 (동일) |
| 4종 모두 `safety` | isolation_violations 0, filter_violations 0 |
| `git diff 397d2a3 HEAD -- src/jupjup/search src/jupjup/query data` | 0줄 |
| `grep -rn jupjup.ingest src` (ingest 밖) | 없음. 검색 경로가 새 모듈에 의존하지 않는다 |

### 1.2 CLI 회귀·경계값 (`uv run jupjup seed load --db var/review.db`, 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00`)

seed load: 200줄 / 적재 200 / 인덱싱 200 (alice 160, bob 30, carol 10). 검색 코드가 바뀌지 않았으므로 동작 확인 목적으로만 돌렸고, 모두 직전 검수 때와 같은 양상이다.

| 사례 | 결과 |
|---|---|
| `성수 카페` (bob) | 성수→성수동(synonym), bob 저장물만 2건. 사용자 격리 정상 |
| `성슈 카페` (오타) | 3건, 1위 익선동 한옥 카페(키워드 `카페` + 의미). 기존 동작 그대로(T18 무관) |
| 빈 문자열 / 201자 이상 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` |
| `!!!@@` | `[INVALID_QUERY] 검색할 단어가 없어요.` |
| `지난주 유튜브` | browse, 기간 2026-10-05 ~ 2026-10-12 |
| `유튜브` + `--platform instagram` (요청 잠금) | "요청 필터가 대체: platforms", 인스타그램만 반환 |
| `python async tutorial 영상` (영어 혼합) | lookup 정상 |
| `화성 식민지 부동산` (없는 대상) | 0건 + 재질의 안내 (과잉 완화 없음) |
| `u_nobody` | 저장물 없음 안내 |

### 1.3 T18 직접 재현 (스크래치 스크립트, 테스트 파일과 별개 입력)

`AnalysisValidator(Lexicon.load(data/lexicon))`와 스크립트형 `call`로 `validate_and_repair`를 돌렸다.

| 입력 | 결과 | 판정 |
|---|---|---|
| 잘린 JSON `{"summary": "잘린` → 정상 | attempts 2, repair 1, `json_parse` | OK |
| `""`, `null`, `[]`, `"str"`, `{}`, `NaN`, `{"summary": 1}` ×3 | 모두 `AnalysisSchemaError`, 호출 3회 | OK |
| `labels: ["데이트"]` ×5 준비 | 호출 정확히 3회 후 partial, labels `[]` | OK |
| `max_repairs=0` + 무효 | 호출 1회 후 partial | OK |
| 태그 `["#카페#맛집","카페","성수"]` | `["카페맛집","카페","성수동"]` | OK |
| 태그 `["카페☕","🔥","성수","밤라떼"]` | 이모지 제거, 빈 태그 제거 → `["카페","성수동","밤라떼"]` | OK |
| 태그 `["인스타","유튜브",…]`, `["instagram","Youtube",…]` | 플랫폼 단독 태그 제거 | OK |
| 태그 `["카페 ","cafe","Cafe",…]` | 동의어·중복 제거 → `카페` 하나 | OK |
| 엔티티 `홍길동`(원문 없음) | 제거 | OK |
| 엔티티 `Onion Cafe`(영문, 원문 한국어) | 제거 | OK (spec대로 별칭이 없으면 제거) |
| `refusal` | 1회 호출, `LLMRefusalError` code `LLM_REFUSED` | OK |
| `max_tokens` → `max_tokens` → 정상 | 컨텍스트 `[None, (max_tokens,×2), (validation,×1)]`, attempts 3, repair 1 | OK (L4 참고) |
| evidence 오타 `신매뉴…출시했읍니다` | 자모 유사도로 통과 / 무관 문장은 거부 / 빈 문자열·기호만 거부 | OK |
| evidence 21개 ×3 | partial, evidence 20개로 잘림 | OK |
| evidence 무근거 ×3 | partial, evidence `[]` | OK |
| 원본 JSON 문자열 | 변경 없음(깊은 복사 확인) | OK |
| 같은 정상 출력 반복 | `RepairOutcome` 동일 | OK |
| 성능: 100k자 원문 + 무근거 evidence 20개 | 1.47s / 12k자 원문 0.18s | OK (분석 잡 p95 60초 예산 안) |
| **태그 25자 `대한민국서울특별시…골목길입니다` ×3** | **`pydantic_core.ValidationError` 누출** (`validate_and_repair:411` → `partial_output:326` → `AnalysisOutput.__init__`) | **H1** |
| **요약 "Python 3.12 버전이 출시되었습니다. …(4문장)"** | **`summary_sentence_count`** (5문장으로 셈) | **M1** |
| **요약 "…밤 라떼 가격은 6.5천원입니다" (1문장)** | **문제 없음으로 통과** (2문장으로 셈) | **M1** |
| `analysis_output_json_schema()` 의 `representative_tags.items` | `{"type": "string"}` 뿐 | **M2** |
| `confidence: "0.9"`, `confidence: true` | 둘 다 통과, `first_pass_ok=True`, `true`→1.0 | L1 |
| `language: "KO"` / `"zz"` | 통과, 성공 경로는 `"KO"` 그대로 저장 | L2 |
| 엔티티 `홍길동` + 별칭 `["수"]` | 별칭 한 글자가 원문에 있어 **유지** | L3 |
| `language: "korean"` ×3 | partial, language를 `"ko"`로 채움 | L2 |
| 대표 태그 2개(요약 유효) ×3 | `AnalysisSchemaError` (보고서 차이 4로 문서화됨) | L6 |

## 2. 스키마 필드 단위 대조 (5.10.5절·6.4절 ↔ `analysis_output_json_schema()`)

| 필드 | 설계 | 생성 스키마 / Pydantic | 일치 |
|---|---|---|---|
| 최상위 | object, `additionalProperties: false`, required 7개 | 같음 (`extra="forbid"`, required 7개 같은 집합) | O |
| `summary` | string, 20~400, description | 같음 | O |
| `title_suggestion` | `["string","null"]`, maxLength 80, required | `anyOf[string≤80, null]`, required(기본값 없음) | O (표현만 다름) |
| `representative_tags` | array 3~7, **items string 1~20** | array 3~7, items `{"type":"string"}` | **X (M2)** — 길이는 `field_validator`(schemas.py:63-68)로만 검사 |
| `detail_tags` | `$ref jupjup/detail_tags/v1` | `$ref #/$defs/DetailTagsV1`, 내용이 `detail_tags.v1.json`과 바이트 동일(직접 비교 True) | O |
| `save_intent` | object, additionalProperties false, required 3 | 같음 | O |
| `save_intent.labels` | array ≤3, enum 12개 | 같음, 순서까지 동일 | O |
| `save_intent.confidence` | number 0~1 | 같음 (Pydantic은 lax라 문자열·bool도 받음 → L1) | O(스키마) |
| `save_intent.rationale` | string ≤120 | 같음 | O |
| `language` | string, "ISO 639-1" | 같음 + 후처리 `^[a-z]{2}$` (대소문자 무시) | O (L2) |
| `evidence` | array ≤20, item `{claim, source_span≤200}` additionalProperties false | 같음 | O |
| 6.4 `save_intent` 하위 필드 | `labels`, `confidence`, `inferred` | `materialized_detail_tags()`가 같은 키로 만들고 v1로 재검증 | O |
| 5.8.1 추가 에러 | `AnalysisSchemaError(ANALYSIS_SCHEMA_INVALID)`, `LLMRefusalError(LLM_REFUSED)` | 둘 다 추가, code 일치 | O (L5) |
| 5.10.8 인터페이스 | `ValidationIssue(path, code, message, fixable)`, `validate`, `auto_fix`, `validate_and_repair(call, validator, source_text, max_repairs=2) -> RepairOutcome(output, attempts, first_pass_ok, partial, repairs, issues)` | 모두 같은 시그니처. `RepairOutcome`에 `repair_attempts` 추가 | O (`auto_fix`는 MT1) |

## 3. 피드백 (심각도 순)

### H1 (높음) partial 경로가 pydantic `ValidationError`를 누출한다 — `src/jupjup/ingest/validation.py:288-334`, 호출부 `:411`

- **재현:** `representative_tags = ["대한민국서울특별시성동구성수동카페거리골목길입니다", "카페", "성수"]`(25자, 나머지는 정상)인 응답을 3번 받는다. `validate()`는 `schema_value_error`(unfixable)로 재요청을 2번 하고, 소진 뒤 `partial_output()`이 호출된다. `partial_output`은 태그 개수(3~7)와 문자열 여부만 보고(`:290`) 길이는 보지 않은 채 `AnalysisOutput(...)`을 직접 만든다(`:326`). 여기서 `ValidationError`가 터지고, `validate_and_repair`는 이를 잡지 않는다.
- **왜 문제인가:** 5.10.2절은 I5 실패를 `LLMProviderError`(재시도), `AnalysisSchemaError`(영구), `LLMRefusalError`(영구) 셋으로만 분류한다. 이 예외는 `JupjupError`도 아니어서 T22 워커가 재시도/영구를 정할 수 없고, API에서는 500이 된다. T18 완료 조건 "재요청 2회 소진 시 partial/failed 분기"의 바로 그 분기다. `normalize_tag_name`이 30자까지만 자르므로(`domain/models.py:57`) 21~30자 태그는 정규화로 걸러지지 않는다.
- **같은 종류의 위험:** `partial_output`은 각 필드를 직접 검사한 뒤 생성자에 넣는 구조라, 앞으로 `AnalysisOutput`에 제약이 하나 늘 때마다 같은 누출이 생긴다.
- **고칠 방향:** (1) `partial_output`의 마지막 생성을 `try/except ValidationError: return None`으로 감싸 "만들 수 없으면 failed"로 떨어뜨린다. (2) 더 좋게는 태그 단계에서 20자 초과 태그를 fixable 이슈로 제거하거나(설계 3번 "고칠 수 있는 오류는 후처리로"와 맞다), partial에서 길이 위반 태그만 빼고 3개 이상 남는지 본다. (3) 회귀 테스트: 21자 태그 ×3 → `AnalysisSchemaError` 또는 partial 중 하나이고 다른 예외는 없음.

### M1 (중간) 요약 문장 수가 소수점·약어에서 틀린다 — `src/jupjup/ingest/validation.py:22`, `:89-100`

- **재현:** `_SENTENCE_END = r"[.!?。！？]+"`로 split한다. "Python 3.12 버전이 출시되었습니다. 새 기능이 많습니다. 성능이 좋아졌습니다. 타입 힌트가 개선되었습니다." (실제 4문장) → 5로 세어 `summary_sentence_count`. 반대로 "성수동 카페 어니언의 밤 라떼 가격은 6.5천원입니다" (실제 1문장) → 2로 세어 통과. 가격(`1.5만원`), 평점(`4.5점`), 버전(`3.12`), 도메인(`example.com`)은 이 서비스 요약에 흔하다.
- **왜 문제인가:** 요약 실패는 unfixable이라 재요청을 쓰고, 소진되면 `partial_output`도 같은 함수로 요약을 거부해(`:285`) 잡이 `failed`가 된다. 정상 요약이 잡 실패로 이어지는 거짓 양성과, 1문장 요약이 통과하는 거짓 음성이 모두 있다. 3.5절 "스키마 최종 준수율" 지표도 왜곡된다.
- **고칠 방향:** 숫자 사이 마침표(`(?<=\d)\.(?=\d)`)와 영숫자 사이 마침표(도메인·약어)는 문장 끝으로 보지 않는다. 예: `[.!?。！？]+(?=\s|$)`처럼 "뒤에 공백이나 끝이 오는 종결부호"만 센다. 테스트: 소수점 포함 4문장 통과, 소수점 포함 1문장 거부, 말줄임표 `...` 한 번은 한 경계.

### M2 (중간) 생성 JSON Schema에 대표 태그 item 길이 제약이 없다 — `src/jupjup/ingest/schemas.py:56`, `:63-68`

- **재현:** `analysis_output_json_schema()["properties"]["representative_tags"]["items"] == {"type": "string"}`. 5.10.5절은 `{"type": "string", "minLength": 1, "maxLength": 20}`이다.
- **왜 문제인가:** 5.10.5절 마지막 줄 "LLM에 보낼 JSON Schema는 모델에서 생성한다"와 5.10.6-1 "구조화 출력(JSON Schema 강제)"의 전제가 이 스키마다. 제약이 빠지면 제공자가 긴 태그를 막지 못하고, 그 태그가 그대로 H1 경로로 들어간다. 기존 테스트(`test_analysis_output_schema_reuses_detail_tags_v1`)는 `maxItems`만 확인해 이 차이를 잡지 못한다.
- **고칠 방향:** `representative_tags: list[Annotated[str, StringConstraints(min_length=1, max_length=20)]]`로 바꾸고 `field_validator`는 지운다. 테스트에 5.10.5절 스키마의 각 제약(items 길이, enum 목록, required 집합)을 필드 단위로 단언한다.

### L1 (낮음) Pydantic lax 모드가 스키마 밖 타입을 받는다 — `src/jupjup/ingest/schemas.py:32`, `:35`, `:53`

`confidence: "0.9"`(문자열)와 `confidence: true`(→1.0)가 통과하고 `first_pass_ok=True`로 기록된다. 6.4·5.10.5절의 `type: number`와 다르고, 5.10.6-2(b) "Pydantic/JSON Schema 검증"의 뜻과도 어긋난다. `ConfigDict(strict=True)`(또는 필드별 `Strict`)를 쓰거나 `model_validate_json(..., strict=True)` 경로로 바꾼다. 첫 시도 준수율(3.5절) 지표를 정확히 하려면 필요하다.

### L2 (낮음) `language` 정규화가 경로마다 다르다 — `src/jupjup/ingest/validation.py:24`, `:247`, `:312-313`, `:332`

성공 경로는 `"KO"`를 그대로 저장하고 partial 경로만 `.lower()`한다. `"zz"`처럼 없는 코드도 통과한다. partial에서 무효 language를 `"ko"`로 채우는 것은 원문 언어를 지어내는 셈이다(영어 원문이면 틀린 값). 소문자로 통일하고, 가능하면 ISO 639-1 목록(또는 최소 허용 목록)으로 검사하고, partial의 대체값은 스냅샷의 감지 언어(I2 `SnapshotDraft.language`)를 받도록 인자를 열어 두거나 `"und"` 같은 명시적 미상값을 설계와 합의한다.

### L3 (낮음) 한 글자 별칭으로 무근거 엔티티가 살아남는다 — `src/jupjup/ingest/validation.py:200-202`, `:65-68`

`{"name": "홍길동", "aliases": ["수"]}`가 원문 "성수동"의 `수`에 걸려 유지된다. 별칭도 설계 근거지만, 한두 글자 별칭이나 이름과 상관없는 별칭으로 환각 엔티티가 그대로 인덱스(`entities[].name`, `aliases`)에 들어간다. 별칭 근거는 최소 길이(예: 2자 이상, 영문 3자 이상) 또는 토큰 경계 일치로 제한하고, 근거 없는 별칭만 따로 제거하는 것을 권한다.

### L4 (낮음) `max_tokens` 재시도 뒤 재요청이 배수를 잃는다 — `src/jupjup/ingest/validation.py:399-407`

잘림 → ×2 재시도 → 그 응답이 의미 규칙 위반이면 다음 `RepairContext`의 `max_tokens_multiplier`가 기본값 1로 돌아간다. 이미 한 번 잘린 입력이라 재요청도 잘릴 가능성이 높고, 두 번째 잘림은 재시도 없이 `json_parse`로 재요청 1회를 소모한다. 5.10.6-5 문구("1회 재시도")를 어기지는 않지만, `truncation_retried`면 이후 컨텍스트에도 배수 2를 유지하는 편이 맞다. 테스트도 함께.

### L5 (낮음, T22 착수 시 참고) `LLMRefusalError`가 `ProviderError`를 상속한다 — `src/jupjup/domain/errors.py:53`

5.10.2·5.10.3절에서 거절은 영구 오류(`needs_review`)인데, 재시도 대상인 `LLMProviderError`와 같은 `ProviderError` 아래에 있다. 지금은 `except ProviderError` 처리부가 없어 버그는 아니지만, API 매핑(`api/errors.py:87`)은 `ProviderError`를 503(재시도 권유)으로 보낸다. T22에서 "ProviderError면 재시도"로 분류하면 거절이 재시도된다. 상속을 `JupjupError`로 옮기거나, T22 분류표에서 `LLMRefusalError`를 먼저 잡도록 명시한다.

### L6 (낮음) partial 범위가 설계보다 좁다 (문서화됨) — `src/jupjup/ingest/validation.py:289-291`

대표 태그가 3개 미만이면 요약이 유효해도 `AnalysisSchemaError`다. 보고서 "설계 대비 차이 4"에 근거와 함께 적혀 있고 검색은 스냅샷 축약 인덱스로 이어지므로 안전한 쪽 선택이다. 다만 설계 문구("그 필드를 비우고 partial")와 다르므로 Architect가 partial 전용 스키마(태그 `minItems` 0 허용) 여부를 결정해 5.10.6절을 고쳐야 한다. 감점은 0.5점만 했다.

### L7 (낮음) `first_pass_ok`가 정규화만 일어나도 거짓이 된다 — `src/jupjup/ingest/validation.py:394`

`["성수", …]`처럼 스키마를 완전히 통과한 응답도 동의어 정규형(`성수→성수동`)이나 공백 제거가 일어나면 `issues`가 생겨 `first_pass_ok=False`다. 3.5절 "스키마 첫 시도 준수율"은 "첫 응답이 JSON 스키마를 통과한 비율"이므로, fixable 이슈만 있는 경우는 통과로 세는 편이 정의에 맞다(`not any(not i.fixable for i in issues)`). 자동 수정 비율은 `repairs`로 따로 볼 수 있다. AC-25 기록 의미를 Architect와 맞추기를 권한다.

### L8 (낮음) `materialized_detail_tags`가 저장 의도 라벨을 조용히 버릴 수 있다 — `src/jupjup/ingest/schemas.py:95`

`purpose`가 이미 5개면 `save_intent.labels`가 `[:5]` 절단으로 빠진다(재현: purpose `a~e` + label `방문예정` → `a~e`). 5.10.5절 "labels를 purpose에 반영한다"를 지키려면 라벨을 앞에 두거나 수정 이력에 남긴다.

### 유지보수성

- **MT1** `auto_fix`가 실제로 고치지 않는다 — `src/jupjup/ingest/validation.py:266-274`. 모든 수정은 `_prepare_payload`(`:130-215`)가 Pydantic 이전에 하고, `auto_fix`는 이슈를 문자열로 바꾸기만 하며 `source_text`를 버린다. 보고서 차이 3의 이유(8개 태그가 `maxItems`에서 먼저 거부됨)는 타당하지만, 5.10.8절 시그니처만 남은 빈 메서드는 다음 작업자를 헷갈리게 한다. docstring으로 역할("수정 이력 수집")을 밝히거나, 시그니처를 설계와 함께 고친다.
- **MT2** 스키마 주입이 두 군데다 — `schemas.py:79-89`(`__get_pydantic_json_schema__`가 detail_tags를 인라인)와 `:106-115`(다시 `$ref`로 덮음). `model_json_schema()`와 `analysis_output_json_schema()`가 서로 다른 모양을 낸다. 하나로 줄인다. 또 최상위 `description`에 클래스 docstring(개발자용 문장)이 그대로 실려 LLM에 전달된다. `json_schema_extra`나 docstring 정리로 뺀다.
- **MT3** 테스트 공백 — `tests/unit/test_ingest_validation.py`. 거절(`refusal`), evidence 무근거, 요약 비한국어 단독, 플랫폼명 단독 태그, 21~30자 태그 소진(H1), 소수점 요약(M1), 스키마 item 길이(M2), 잘림 두 번, partial에서 detail_tags만 무효인 경우가 없다. T18 완료 조건 6개 자체는 모두 테스트돼 있다.

## 4. 항목별 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 34 / 40 | 완료 조건 6개 재현, 스키마 대부분 일치, 검색 무회귀(+). H1 소진 분기 예외 누출 −3, M1 문장 수 오판 −2, M2 스키마 item 제약 누락 −1 |
| 안전성 | 26 / 30 | 루프 상한·원본 불변·거절 즉시 중단·evidence 성능 정상(+). H1 미분류 예외(워커/API 500) −2, L1 lax 타입 −1, L3 별칭 근거 약함 −0.5, L2·L5 −0.5 |
| 유지보수성 | 27 / 30 | 모듈 분리·정본 하위 스키마 재사용·차이 문서화 좋음(+). MT1·MT2 −1.5, MT3 테스트 공백 −1.5 |
| **합계** | **87 / 100** | 90 미만 → **REJECT** |

## 5. 재검수 조건 (Loop 2 PASS 기준)

1. **H1:** 어떤 LLM 응답 3연속에서도 `validate_and_repair`가 `RepairOutcome`, `AnalysisSchemaError`, `LLMRefusalError` 외의 예외를 내지 않는다. 21~30자 태그 ×3 회귀 테스트 추가. (권장: 무작위·퍼즈 입력 몇 개로 같은 불변식을 단언)
2. **M1:** 소수점·도메인이 든 요약의 문장 수를 바르게 센다. 소수점 포함 4문장 통과, 소수점 포함 1문장 거부 테스트 추가.
3. **M2:** `analysis_output_json_schema()`의 `representative_tags.items`가 `minLength: 1`, `maxLength: 20`을 갖고, 테스트가 5.10.5절 제약을 필드 단위로 단언한다.
4. L1~L4, MT1~MT3는 같은 작업에서 처리하기를 권한다(특히 L1 strict, L4 배수 유지, MT3 거절·evidence 테스트). L5·L6·L7은 Architect 확인 사항으로 남겨도 된다.
5. 게이트 유지: pytest 전부 통과, ruff·mypy 무경고, eval 4종 수치가 이번 검수와 같고 `src/jupjup/search`·`src/jupjup/query`·`data/` diff 0.
