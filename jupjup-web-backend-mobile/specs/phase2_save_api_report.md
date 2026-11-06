# Phase 2 저장 코어·정식 저장 API 구현 보고

- 역할: Codex-Primary, 구현 루프 1
- 작업일: 2026-11-03
- 기준: `specs/design_save_api.md`, 시작 HEAD `17e852b`
- 워크트리: `phase-2-save-api`
- 상태: T27a~T27h 구현, 최종 검증 결과는 아래 실행 기록 참조

## 1. 재개 시 확인한 상태

이전 세션의 변경을 보존하고 이어서 작업했다. 시작 시 migration, 부분 저장소,
인증, URL 정규화, HTTP fetcher와 관련 테스트가 미커밋 상태였다. 이 부분의
테스트 19개는 통과했고, 정식 create 통합 테스트 3개는 미등록 라우트의 404로
실패했다. 이미 통과한 기반을 다시 만들지 않고 이 실패에서부터 이어갔다.

분석기 제외 파일, 검색·쿼리·데모 디렉터리, 프로필 설정, 검색 기준선,
`data/recordings/embeddings*`는 수정하지 않았다. 녹화가 필요하지 않아 새 녹화나
기존 녹화 덮어쓰기도 하지 않았다. 외부 LLM API 호출, 모델 다운로드,
모델 가중치 커밋, push는 하지 않았다.

## 2. 구현 범위와 변경 파일

| 작업 | 구현 |
|---|---|
| T27a | v27 전진 migration, checksum 검사, 기존 DB timestamp 백업, 명시적 SQLite DDL 트랜잭션, FK/기존 행 수 검사, 기존 URL/hash canonical claim, 목록·활성 잡 인덱스, 신규 콘텐츠 전용 INSERT, snapshot append 및 AI 층 부분 갱신 |
| T27b | `Principal`/`Authenticator`/dev header dependency, prod dev-header 시작 거절, API 외부 bind 거절, non-dev admin 404, 공통 오류의 민감 정보 제거 |
| T27c | canonical request hash, 사용자·메서드·route별 멱등 키, path parameter 반영, TTL, URL normalization v1, 안전 HTTP 수집, HMAC 커서 |
| T27d | URL/text/image+OCR create, Content+Job+멱등 응답+URL claim 원자 커밋, URL 중복 200, I2 hash 경쟁 정본/alias 종결, 이미지 식별 메타 snapshot 보존 |
| T27e | effective/AI/user 상세, 저장 당시 snapshot, 사용자별 목록, 반복 필터·태그 AND·UTC 날짜 경계·정렬·id tie-breaker·signed keyset cursor, 최소 alias 응답 |
| T27f | 요약/태그/detail merge patch/hidden, clear/no-op, revision/ETag/If-Match, tombstone 보존, 인덱스 반영, active job 취소 후 hard delete/cascade |
| T27g | I5 후보와 미승인 analysis run 저장, 승인 전 AI 층 비적용, 승인 I6 재개·거절 snapshot 보존, 결정 멱등/충돌, 실제 event 기반 단계/attempt/시간, 영속 trace와 사용자 격리 |
| T27h | snapshot부터 재분석, active conflict, 사용자 층 보존, I6 이후 실패까지 이전 AI/embedding 복원, OpenAPI, CLI migration, 전체 회귀 |

신규 모듈:

- `src/jupjup/auth.py`
- `src/jupjup/save/{dto,routes,service,query,cursor,dedupe,patch,jobs,recovery}.py`
- `src/jupjup/storage/{migration,save_repositories}.py`

기존 수정 모듈:

- `api/app.py`, `api/errors.py`, `cli.py`, `config.py`, `container.py`
- `domain/models.py`, `domain/errors.py`
- `storage/db.py`, `storage/tables.py`, `storage/repositories.py`
- `ingest/fetch.py`, `ingest/jobs.py`, `ingest/worker.py`
- `index/service.py`: 숨김/alias의 게시·재구축 제외만 추가했다. 검색 순위와 점수는 변경하지 않았다.

## 3. 주요 보존·경쟁 처리

- 정식 create는 기존 bundle upsert를 호출하지 않는다. 신규 콘텐츠 INSERT와 잡,
  멱등 응답, URL fingerprint를 같은 트랜잭션에서 처리한다.
- 정식 재분석·PATCH·I6은 기존 콘텐츠 전체를 upsert하지 않는다. 사용자 요약,
  사용자 태그, 숨긴 AI 태그, detail patch, note, hidden을 AI 저장이 교체하지 않는다.
- 같은 키의 동시 create는 SQLite writer 직렬화 뒤 최초 응답을 재생한다.
  동일 본문 hash의 경쟁은 사용자 범위 unique claim으로 한 정본에 귀결된다.
- 승인 전 후보는 analysis run/후보/trace에만 존재한다. 승인 시 같은 잡이
  `persist`부터 재개한다. 거절은 원문 snapshot을 삭제하지 않는다.
- 재분석은 이전 AI 태그/detail/embedding을 복구용으로 캡처한다. I6 이후 실패도
  이전 AI를 복원하고, 그 사이에 들어온 사용자 PATCH는 유지한다.
- 사용자 태그와 새 AI를 합친 결과가 기존 15개 상한을 넘으면 I6에서 원자적으로
  거절한다. 읽을 수 없는 bundle을 커밋하거나 기존 상한을 낮추지 않는다.
- DELETE는 소유 콘텐츠의 active job lease를 취소한 뒤 삭제한다. stale 결과의
  INSERT/CAS가 콘텐츠를 부활시키지 못하며, 자식과 trace도 cascade된다.
- 완료 잡은 민감한 작업 공간을 비운다. 승인 대기 잡도 raw/input/output을 비우며,
  재분석 복원용 prior 상태만 결정·종결 전까지 유지한다. 승인 재개와 trace 조회는
  영속 artifact를 읽는다.

HTTP 수집은 검증한 공개 IP에 직접 연결하고 TLS SNI/Host를 원래 호스트로 유지한다.
환경 proxy와 재접속 DNS에 의존하지 않는다. redirect마다 주소를 재검사한다.
DNS 동시 요청 수와 deadline, connect/전체 시간, 수신 및 gzip 해제 크기를 제한한다.
테스트는 resolver/transport stub과 로컬 HTTP 서버만 사용한다.

## 4. 설계 대비 배치·운영 차이

1. 설계의 모듈 트리는 권장 배치이므로 정식 DTO/route/job view는 `api/` 대신
   `save/` 패키지에 모았다. route에서 SQL 테이블이나 concrete analyzer를 import하지 않는다.
2. 첫 전진 migration은 별도 migrations 디렉터리 대신 `migration.py`의 v27로
   제공한다. migration 소스 checksum 변경은 시작 실패다. CLI는
   `jupjup migrate-db --db <path>`다. 이후 변경은 새 migration version으로 분리해야 한다.
3. 정식 멱등 요청은 별도 in-progress 커밋 없이 리소스/응답을 한 트랜잭션으로
   저장한다. 정상 동시 요청은 writer lock 뒤 replay된다. 저장소의 독립 reservation
   API는 in-progress/conflict를 지원한다. TTL 청소는 별도 상주 작업 대신 저장 요청 때 한다.
4. provider 포트가 주지 않는 raw 모델 출력, map/reduce 내부 결과, 점수,
   model weight 지문은 만들어 넣지 않는다. 실제 output/meta, profile, prompt version,
   스키마 검증, repairs, snapshot/hash, chunk 입력, 이벤트를 보존한다.
5. 기존 admin 및 health 테스트의 환경 전제를 새 정책에 맞췄다. prod의 dev-header
   서버를 health 확인용으로 띄우지 않고 test 환경에서 확인한다. non-dev admin 404는
   유지하며, 정식 API의 ingest 조립은 non-dev/test에서도 존재한다.

## 5. API 요청·응답 예시

아래 id는 설명용이다. 실제 id는 서버가 생성한다. 예시는 루프백 서버 기준이며
`X-User-Id: u_alice`가 필요하다.

### 접수와 멱등 재생

```http
POST /v1/contents
X-User-Id: u_alice
Idempotency-Key: save-example-1
Content-Type: application/json

{"source":{"kind":"text","text":"성수동 카페에서 읽은 책과 커피에 관한 기록입니다."},"automation_level":"confirm"}
```

```http
HTTP/1.1 202 Accepted
Location: /v1/contents/c_example
Content-Location: /v1/jobs/job_example

{"content_id":"c_example","job_id":"job_example","status":"queued","automation_level":"confirm","deduplicated":false,"result_content_id":"c_example"}
```

같은 요청·키 재전송은 동일 202/body와 `Idempotency-Replayed: true`를 반환한다.
같은 키의 다른 body/path는 `409 IDEMPOTENCY_CONFLICT`다. 같은 사용자의
정규화 URL 중복은 `200`, `deduplicated: true`, 기존 id와 `job_id: null`을 반환한다.

### 상세·목록·수정

```http
GET /v1/contents/c_example
GET /v1/contents?hidden=false&sort=saved_at&order=desc&limit=20
PATCH /v1/contents/c_example
If-Match: "content:c_example:7"
Content-Type: application/merge-patch+json

{"summary":"사용자가 쓴 요약","representative_tags":["#성수 동"],"detail_tags":{"topics":["독서"]},"hidden":true}
```

PATCH 200은 상세 resource와 새 ETag를 반환한다. 요약은
`{"effective":"사용자가 쓴 요약","source":"user","ai":"…","user":"사용자가 쓴 요약"}`처럼
층을 구분한다. `null`은 해당 override를 지우며, 생략은 유지한다.
동일 effective 값 재적용은 revision을 올리지 않는다. 오래된 ETag는
`409 VERSION_CONFLICT`, invalid detail patch는 `422 INVALID_PATCH`다.
목록은 `{items,next_cursor,has_more}`이며 count/offset은 제공하지 않는다.

### 후보 결정·재분석·trace·삭제

```http
POST /v1/contents/c_example:review
Content-Type: application/json

{"candidate_id":"cand_example","decision":"approve"}
```

승인은 202로 같은 잡을 persist부터 queued 처리한다. 거절은 200이며 snapshot을
유지한다. 같은 결정은 멱등이고 반대 결정/이전 후보는 409다.

```http
POST /v1/contents/c_example:reanalyze
Idempotency-Key: reanalyze-example-1
Content-Type: application/json

{"automation_level":"auto"}
```

재분석은 202, 최신 snapshot의 chunk 단계부터 시작한다. 원본 URL에 다시 접속하지 않는다.
`GET /v1/jobs/job_example?trace=full`은 실제 단계·attempt·시간·오류·입출력·검증·event를
반환하고 `Cache-Control: private, no-store`를 설정한다. 타 사용자는 404다.
`DELETE /v1/contents/c_example` 성공은 body 없는 204다.

## 6. 테스트 목록과 인수 기준 근거

신규 테스트 파일:

| 파일 | 검증 |
|---|---|
| `tests/unit/test_save_migration.py` | 기존 DB 보존/재실행/새 인덱스/백업/수동 정책/FK/DDL rollback/checksum 변조/AI-user 분리 |
| `tests/unit/test_save_auth.py` | dev principal/헤더 오류/prod 거절/admin gate |
| `tests/unit/test_save_dedupe.py` | tracking·IDNA·dot segment·기본 port·예약문자·YouTube/Instagram 정규화/credential 거절 |
| `tests/unit/test_save_repositories.py` | canonical hash/replay/conflict/in-progress/key 형식/멱등 행 민감 정보 제외 |
| `tests/unit/test_http_source_fetcher.py` | private DNS/redirect 우회/oversize/gzip/5xx/검증 IP 고정/실제 로컬 HTTP 응답/DNS deadline |
| `tests/integration/test_save_api.py` | 세 source/정확 replay/사용자 격리/URL·hash 중복/상세/동일 시각 커서/PATCH clear·no-op·ETag/숨김/삭제/confirm/reanalysis/OpenAPI/삭제 경쟁/모순 hint |
| `tests/integration/test_save_acceptance.py` | 전체 사용자 층 재분석 보존/I6 이후 실패 복원/동시 create·hash claim/거절 축약 검색/로그 민감 정보/원본 소실/승인 전 검색 제외/trace/cascade/필터/승인과 PATCH/작업 공간 정리/image metadata/patch 오류/태그 상한 |

기존 `test_api_ingest.py`, `test_local_analyzer_assembly.py`의 환경 전제만 갱신했다.
기존 검색/인덱스/인제스트, mock/recorded 재생, fake local analyzer 프로필 조립 테스트도
전체 pytest에 포함했다. 실제 GGUF 모델 smoke는 기본 설치의 선택 marker에 따라 제외된다.

AC-S1~S10의 접수/단계/상세/목록/수정/숨김/삭제/재분석/승인/trace는 위 API 통합 테스트로,
AC-S11~S16의 멱등/중복/격리/경쟁은 파일 DB의 실제 동시 요청·worker 테스트와
I6/approve/delete 경계 재현으로 검증했다. AC-S17~S25는 원본 재접속 금지,
사용자 층 보존, 실제 trace, 민감 정보, loopback/admin gate, 안전 수집 및 migration 테스트가
담당한다. AC-S26~S28은 전체 회귀, 기존 fake local 포트 조립, OpenAPI 테스트가 담당한다.

## 7. 직접 실행한 명령과 결과

모든 명령은 이 워크트리에서 실행했다. 아래 PASS는 최종 실행 기준이다.

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS, 1,388 passed / 5 deselected / 3 warnings (137.79s) |
| `uv run ruff check src tests` | PASS, All checks passed |
| `uv run mypy src` | PASS, 103 source files |
| `git diff --check` | PASS |
| `uv run jupjup eval validate` | PASS, exit 0 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json --out reports/save-api-validation/mock-dev` | PASS, exit 0, 기본 게이트와 기존 baseline 회귀 검사 5개 통과 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json --out reports/save-api-validation/mock-test` | PASS, exit 0, 기본 게이트와 기존 baseline 회귀 검사 5개 통과 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json --out reports/save-api-validation/recorded-dev` | PASS, exit 0, 기본 게이트와 기존 baseline 회귀 검사 5개 통과 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json --out reports/save-api-validation/recorded-test` | PASS, exit 0, 기본 게이트와 기존 baseline 회귀 검사 5개 통과 |
| `uv run jupjup eval ingest --mode mock --out reports/save-api-validation/ingest` | PASS, schema_final_pass_rate=1.0, injection_resistance=1.0, 기존 회귀 문턱 통과 |
| `uv run jupjup migrate-db --db var/save-api-migration-smoke.db` (2회) | PASS, v27 applied=true, 두 번째도 동일 version/checksum |

명시적 baseline 옵션 없는 mock/recorded dev/test 실행도 각각 exit 0이었다.
단위/통합 테스트를 먼저 실행해 404, 잘못된 오류 코드, 기존 DB 인덱스 누락,
작업 공간 미정리, DNS deadline 미준수 등의 실패를 재현하고 수정했다.
중간 전체 실행의 실패도 숨기지 않는다: 첫 실행 2개는 이전 admin/health 환경 전제,
다음 실행 3개는 CLI dev gate와 migration 검사 순서 및 기존 job error 형식이었다.
최종 회귀에서 모두 해결했다.

| 모드/분할 | Recall@10 | MRR@10 | NDCG@10 | isolation violations |
|---|---:|---:|---:|---:|
| mock/dev | 0.9620 | 0.9958 | 0.9795 | 0 |
| mock/test | 0.9420 | 0.9867 | 0.9589 | 0 |
| recorded/dev | 0.9712 | 1.0000 | 0.9860 | 0 |
| recorded/test | 0.9720 | 0.9911 | 0.9801 | 0 |

기계 판독용 지표·safety·gate 결과는 `specs/data/phase2_save_api_validation.json`에
포함했다. 전체 출력은 로컬 ignored 경로 `reports/save-api-validation/`에 있다.
골든셋은 기존 `ai_draft_unreviewed` 기술 게이트이며 이 결과를 제품 품질에 대한
사용자 검수 PASS로 바꾸어 주장하지 않는다. 기준선과 문턱은 수정하지 않았다.

## 8. 남은 범위와 운영 조건

- 실제 로그인/제품용 인증과 외부 공개 배포는 설계의 범위 밖이다. 현재 dev header는
  prod 시작과 외부 bind를 거절한다. cursor secret은 환경에 맞게 설정해야 한다.
- 이미지 binary 업로드/OCR, 원본 refresh, 로그인·봇 차단 우회, 휴지통은 구현 범위 밖이다.
- 실제 local GGUF 추론 품질은 이 저장 코어 변경의 검증 대상이 아니다. 기본 설치에서는
  mock과 fake local 프로필 조립/교체로 계약을 검증했고, 실제 모델 가중치는 사용·커밋하지 않았다.
- SQLite 단일 머신 큐와 hard delete, 기존 인덱스의 embedding-pending 복구 정책을 유지한다.
- 후속 인증 adapter, 장기 trace 암호화/보존 정책, 새 migration은 별도 작업이다.
- 이 보고서는 구현 워커 결과이며 별도 Claude-Reviewer 검수 판정은 포함하지 않는다.
