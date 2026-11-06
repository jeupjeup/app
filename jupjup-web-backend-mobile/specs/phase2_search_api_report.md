# Phase 2 T15 검색 API 구현 보고서

## 구현 범위

`specs/prd_and_design.md` 5.8.1절, 5.9절과 작업표 T15에 따라 검색 HTTP API를 구현했다.
기존 `AppContainer`, `SearchService`, `IndexingService`, 저장소를 그대로 조립했으며 검색·완화·순위
로직과 설정값은 변경하지 않았다. T23 범위인 인제스트 API와 워커는 포함하지 않았다.

- `src/jupjup/api/app.py`: FastAPI 앱 팩토리, 사용자 헤더 검사, 라우트, 응답 투영, dev admin 처리
- `src/jupjup/api/dto.py`: 요청·응답 DTO와 `extra="forbid"` 스키마 경계
- `src/jupjup/api/errors.py`: 공통 오류 봉투, 도메인/검증/내부 오류 HTTP 매핑
- `src/jupjup/api/__init__.py`: `create_app` 공개
- `src/jupjup/cli.py`: `jupjup api serve`, 기본 `127.0.0.1:8000`, 외부 바인딩 안전장치
- `tests/integration/test_api_search.py`: T15 API 계약·오류·격리·admin 통합 테스트 20건
- `tests/integration/test_cli.py`: API CLI 기본 바인딩 테스트

앱 생성 시 SQLite 정본에서 사용자별 메모리 인덱스를 재구축한다. 재구축에 실패하면 앱은 살아
있지만 `index_ready=false`가 되고 검색·파싱은 `503 INDEX_NOT_READY`를 반환한다.

## 엔드포인트별 동작

### `POST /v1/search`

- `X-User-Id`를 `^u_[a-z0-9_]{1,64}$`로 검증하고 이를 `SearchRequest.user_id`의 유일한 출처로 쓴다.
- 공개 요청의 필터를 기존 `SearchFilters`로 변환하고 기존 `SearchService.search`를 호출한다.
- 응답은 5.9절 공개 스키마로 투영한다. 서비스 내부의 추가 해석·판정 진단은 기본 응답에 노출하지
  않는다.
- `explain=false`이면 결과에 `debug` 키가 없고, `true`이면 `ranks`, `rrf`, `features`만 공개한다.
- 결과가 없으면 HTTP 200, `results=[]`, `empty_state.message="다른 표현으로 다시 찾아볼까요?"`다.
- `now`는 `JUPJUP_ENV=dev`에서만 허용한다. test/prod에서는 `422 VALIDATION_ERROR`다.
- 요청 필터와 결과 조회 모두 사용자 id로 범위를 좁혀 다른 사용자의 콘텐츠를 반환하지 않는다.

### `POST /v1/query:parse`

- 같은 사용자 인덱스의 vocabulary와 서버 시계를 사용해 기존 `SearchService.parse_only`를 호출한다.
- 검색 응답과 같은 공개 `understanding` 구조를 반환한다.
- 명세에 없는 `now`를 비롯한 추가 필드는 `422 VALIDATION_ERROR`로 거부한다.

### dev admin

- `JUPJUP_ENV=dev`일 때만 `POST /v1/admin/contents:bulkUpsert`와
  `DELETE /v1/admin/contents/{content_id}`를 등록한다. 그 밖의 환경에서는 라우트 자체가 없어 404다.
- bulk upsert는 최대 500개 시드 형식 레코드를 받고 `SeedRecord.to_bundle()` 검증 후 기존 저장소와
  인덱서를 사용한다. 레코드 `user_id`가 헤더와 다르면 해당 항목은 `INVALID_CONTENT` 실패다.
- `strict=true`는 검증 실패가 하나라도 있으면 아무 항목도 쓰지 않으며, 모두 유효할 때 저장소
  bulk 트랜잭션으로 기록한다. `strict=false`는 항목별 성공/실패를 모은다.
- delete는 헤더 사용자의 저장소와 인덱스에서만 삭제하며 성공 시 204다.
- ingest 관련 라우트는 T23 범위이므로 만들지 않았다.

### `GET /healthz`

헤더 없이 `status`, `index_ready`, embedder model id, 실행 mode를 반환한다.

## 오류 매핑

모든 API 오류는 `{"error":{"code":...,"message":...,"details":...}}`이고 JSON 응답은
`application/json; charset=utf-8`이다.

| HTTP | code | 처리 |
|---:|---|---|
| 400 | `MISSING_USER` | `X-User-Id` 없음 |
| 400 | `INVALID_USER` | 사용자 id 정규식 불일치 |
| 422 | `INVALID_QUERY` | 빈 문자열, 200자 초과, 기호만 등 기존 질의 검증 실패 |
| 422 | `INVALID_FILTER` | 알 수 없는 facet, 역전된 저장 기간, limit 1..50 밖 |
| 422 | `VALIDATION_ERROR` | 누락·타입·추가 필드와 비-dev `now` |
| 503 | `INDEX_NOT_READY` | 앱 인덱스 준비 상태가 false |
| 500 | `INTERNAL` | 매핑되지 않은 도메인 오류와 예외. 예외 문자열·내부 상세 비노출 |

dev delete의 존재하지 않는 콘텐츠와 미등록 경로에는 404 `NOT_FOUND`도 일관된 봉투로 반환한다.

## 명세와 다른 점과 이유

1. PRD 5.8.8 예시는 `jupjup serve`지만 작업 브리프가 명시한 `jupjup api serve`로 구현했다.
   다른 명령군과 충돌하지 않고 API 표면을 명확히 구분하기 위해 최신 작업 지시를 우선했다.
2. 인덱스 재구축은 앱 팩토리에서 동기 실행한다. 따라서 정상 시작 중에는 서버가 포트를 받기 전에
   재구축이 끝나고, 재구축 실패 또는 명시적으로 준비 상태가 내려간 경우에만 503을 관찰한다.
   현재 인메모리 레지스트리가 동시 갱신용 준비 상태를 제공하지 않으므로 검색 중 부분 인덱스를
   보이는 비동기 시작보다 안전한 동작을 택했다.
3. `strict`의 상세 의미는 5.9절에 정의돼 있지 않아 기존 strict 시드 로더와 같은 “검증 오류 시
   전체 미기록”으로 정했다.
4. 명세보다 보수적으로 API CLI의 비-loopback 바인딩은 `--allow-external-bind`가 없으면 거부한다.
   `X-User-Id`는 실제 인증이 아니므로 실수로 외부에 노출되는 것을 막기 위한 안전장치다.

## 직접 실행한 명령과 결과

평가 리포트 출력은 저장소를 오염시키지 않도록 `/tmp/jupjup-t15-eval/` 아래에 썼다. baseline과
`data/recordings/`는 수정하지 않았다.

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 632 passed, 3 deselected, warning 1건 |
| `uv run ruff check src tests` | PASS |
| `uv run mypy src` | PASS — 60 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json ...` | PASS — Recall@10 0.9620, MRR@10 0.9958, nDCG@10 0.9795, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json ...` | PASS — Recall@10 0.9420, MRR@10 0.9867, nDCG@10 0.9589, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json ...` | PASS — Recall@10 0.9712, MRR@10 1.0000, nDCG@10 0.9860, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json ...` | PASS — Recall@10 0.9720, MRR@10 0.9911, nDCG@10 0.9801, 격리/필터 위반 0 |

네 평가 모두 절대 기준과 `regression:recall@10`, `regression:mrr@10`, `regression:ndcg@10`,
`regression:time_exact`, `regression:platform_f1`을 통과했다. 기준치와 기준선은 변경하지 않았다.

## 남은 문제

1. `TestClient` 실행 때 FastAPI가 현재 httpx 호환 경로에 대한 `StarletteDeprecationWarning` 1건을
   낸다. 테스트 실패는 아니며 상위 라이브러리 전환 시 제거해야 한다.
2. 시작 재구축은 동기식이라 큰 데이터셋에서는 서버 시작 시간이 길어질 수 있다. 준비 상태를 가진
   원자적 레지스트리 교체가 도입되면 백그라운드 rebuild와 실제 시작 중 503으로 확장할 수 있다.
3. `X-User-Id`는 MVP 격리 키일 뿐 인증이 아니다. 외부 서비스 배포 전 실제 인증·인가 계층이 필요하다.
