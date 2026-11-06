# Phase 3 검색 리팩터링 보고서

작성일: 2026-10-29 (Asia/Seoul)

## 결과 요약

`src/jupjup`의 검색·질의 이해·데모 페이지 구조를 기능 변경 없이 정리했다. 공개 API 응답 스키마,
CLI 인자, `SearchService.search`와 `SearchService.parse_only` 시그니처는 유지했다. 골든셋과
`data/baselines/mock.json`도 수정하지 않았다.

리팩터링 전후 `mock/all` 평가 JSON은 생성 시각(`created_at`)과 지연 시간(`perf`)을 제외하면 완전히
동일하다. 따라서 235개 질의의 이해 결과, 결과 목록과 순위, 빈 결과 판정, 완화 기록, 안전 지표,
게이트 판정에 차이가 없다.

## 변경 내용

### 검색 파이프라인 책임 분리

- `SearchService.search`는 입력 검증·질의 이해·경로 선택·응답 조립만 담당하도록 줄였다.
- 필터 전용 browse를 `_execute_browse`, 일반 검색의 검색→결합→재순위→게이트를
  `_execute_ranked`, 완화 반복을 `_execute_relaxations`로 분리했다.
- 게이트 적용과 결과 DTO 조립을 각각 `_apply_gate`, `_build_items`로 분리해 중복과 분기 중첩을
  줄였다.
- 내부 실행 상태는 Pydantic 모델 대신 타입이 명확한 dataclass로 표현했다.
- 짧은 변수명 대신 `candidate`, `bundle`, `keyword_hits`처럼 역할이 드러나는 이름을 사용했다.

### 질의 규칙과 설정 정리

- `query/settings.py`에 `QuerySettings`와 기본 기간 margin을 모으고 이를
  `SearchSettings.query`에서 소유하도록 했다.
- 최대 질의 길이, 최소 용어 길이, facet 퍼지 거리, 철자 교정 거리와 장단어 경계, 보조 질의
  timeout/token 수, 모호 질의 기준을 같은 설정 객체로 주입한다. 기본값은 기존 상수와 같다.
- 완화 fallback margin·월 최소 확장 폭은 `SearchSettings.relaxation`으로, 재순위의 recency 감쇠와
  기간 window 최저 점수는 `SearchSettings.rerank`로 옮겼다.
- 의미 일치 근거 순위와 빈 결과 제안 개수도 `SearchSettings`에서 관리한다.
- 첫 등장 순서를 유지하는 문자열 중복 제거를 `text/terms.py::unique_strings`로 합쳐 질의 이해,
  검색, 완화, 재순위, 인덱스 문서 빌더의 중복 구현을 제거했다.
- 기존 `query.temporal.DEFAULT_MARGINS` import 경로는 호환성을 위해 별칭으로 유지했다.

### 데모 페이지와 패키징

- 720줄 Python raw string을 `demo/page.html`로 옮기고 `importlib.resources`로 한 번 읽도록 했다.
- 외부 CDN이나 새 네트워크 자산을 추가하지 않았다.
- 이전 `HTML_PAGE`에서 추출한 내용과 새 HTML 파일을 `cmp`로 비교해 바이트 동일성을 확인했다.
- wheel을 빌드해 `page.html`, loader 모듈, 새 설정/유틸 모듈이 모두 포함되는 것을 확인했다.

### 근거가 명확한 낭비 제거

- 재순위 후보마다 같게 계산하던 n-gram 질의 토큰화를 후보 목록당 한 번만 계산한다. 기본
  `fusion.top_n=50`이므로 한 검색에서 같은 토큰화가 최대 50회 반복되던 경로를 제거했다.
- fallback match reason을 만들 때 결과마다 `UserIndexRegistry.get`을 다시 호출하지 않고 이미 검증한
  `UserIndex`를 전달한다.
- 이 최적화의 성능 수치는 실행 환경 영향을 받으므로 품질 동일성 판정이나 성과 주장에는 사용하지
  않았다.

## 전후 동일성 증거

동일한 명령을 코드 변경 전과 후에 실행했다.

```bash
uv run jupjup eval run --mode mock --split all --baseline data/baselines/mock.json
```

보존한 리포트:

- 전: `reports/eval_mock_all_before.json`, `reports/eval_mock_all_before.md`
- 후: `reports/eval_mock_all_after.json`, `reports/eval_mock_all_after.md`

지연 시간과 생성 시각을 제외한 구조 비교:

```bash
cmp -s \
  <(jq 'del(.created_at, .perf)' reports/eval_mock_all_before.json) \
  <(jq 'del(.created_at, .perf)' reports/eval_mock_all_after.json)
# exit 0
```

| 지표 | 전 | 후 |
|---|---:|---:|
| Recall@10 | 0.967262 | 0.967262 |
| Recall@5 | 0.947778 | 0.947778 |
| MRR@10 | 0.985714 | 0.985714 |
| nDCG@10 | 0.972224 | 0.972224 |
| Success@1 | 0.976190 | 0.976190 |
| 카테고리 Recall@10 최저 | 0.916667 | 0.916667 |
| 기간 정확도 | 1.000000 | 1.000000 |
| 플랫폼 F1 | 1.000000 | 1.000000 |
| 유형 F1 | 1.000000 | 1.000000 |
| 키워드 포함률 | 0.958763 | 0.958763 |
| 정답 빈 결과율 | 0.760000 | 0.760000 |
| 오답 빈 결과율 | 0.000000 | 0.000000 |
| 격리 위반 | 0 | 0 |
| 요청 필터 위반 | 0 | 0 |

두 실행 모두 절대 기준과 baseline 회귀 기준을 모두 통과했다. 지연 시간은 요구사항대로 동일성
비교에서 제외했다.

## 테스트와 정적 검사

| 명령 | 결과 |
|---|---|
| `uv run ruff check` | PASS: `All checks passed!` |
| `uv run mypy src` | PASS: 50개 소스 파일, 오류 0 |
| `uv run pytest` | PASS: 453 passed, 경고 1건 |
| `uv run jupjup eval validate` | PASS: seeds 200, queries 235, lexicon cases 139 |
| `uv run jupjup eval run --mode mock --split all --baseline data/baselines/mock.json` | PASS |
| wheel build 및 자산 목록 확인 | PASS: `jupjup/demo/page.html` 포함 |

pytest 경고 1건은 기존 FastAPI TestClient의 Starlette/httpx deprecation 경고다.

## 손대지 않은 개선 후보

1. 532줄의 `query/temporal.py`는 규칙 수가 많지만 현재 테스트가 촘촘하고 시간 해석 순서가 검색
   결과에 직접 영향을 준다. Phase 3에서는 기본 margin 소유권만 옮기고 parser 규칙 분할은 보류했다.
2. 데모 HTML의 CSS와 JavaScript를 별도 패키지 자산/라우트로 나누면 편집성은 더 좋아지지만 HTTP
   요청 수와 응답 구성이 달라진다. 이번에는 단일 HTML 응답 동작을 보존했다.
3. `QueryAssistant`의 executor 수명 관리와 실제 live/recorded 제공자 최적화는 기본 mock 검색 경로
   밖이며, 제공자 구현과 함께 별도 검증하는 편이 안전하다.
4. `model_reranker` 조립은 현재 공개 생성자 호환을 위해 유지했지만 실제 검색 경로에서는 아직 쓰지
   않는다. T17 제공자 작업에서 사용 여부를 확정한 뒤 제거 또는 연결할 수 있다.
