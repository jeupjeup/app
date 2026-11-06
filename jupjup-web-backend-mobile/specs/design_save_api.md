# 줍줍저장소 저장 코어 및 정식 저장 API 설계

- 문서 상태: Phase 1 설계, 구현 전 기준선
- 작성일: 2026-11-03
- 대상 작업: T27a 이후
- 기준 문서: `specs/prd_and_design.md` 5.9, 5.10, 6.2절
- 관련 문서: `specs/design_local_analyzer.md`, `specs/backlog_instagram_demo.md`

> 이 문서는 T18~T24에서 완성한 비동기 인제스트 파이프라인을 정식 저장 제품 API로 노출하는 설계다. 분석기 자체는 T25 트랙 B의 `mock`/`local` 프로필 교체 지점으로 취급한다. 저장 코어는 분석기 구현을 알지 않고 `ContentAnalyzer` 계약만 사용한다.

---

## 0. 결정 요약

구현자가 해석을 다시 하지 않아도 되도록 기본 결정을 먼저 고정한다.

1. 정식 저장 API는 `/v1/contents`, 잡 조회는 `/v1/jobs` 아래에 둔다. 기존 `/v1/admin/*`는 호환용 dev API로 유지하고 정식 API 구현에 재사용하되 새 기능의 정본으로 삼지 않는다.
2. 저장 요청은 `source.kind`로 `url`, `text`, `image`를 구분한다. `image`는 MVP에서 이미지 파일이 아니라 필수 `ocr_text`와 선택 메타데이터를 받는다.
3. 모든 쓰기와 조회는 인증 어댑터가 만든 `Principal.user_id`로 범위를 제한한다. 요청 body나 path에서 `user_id`를 받지 않는다.
4. 실제 인증 방식은 열린 질문이다. PM 기본값은 dev/test에서만 허용되는 `X-User-Id` 어댑터다. 이 어댑터를 쓰는 서버는 루프백 외부 바인드를 금지한다.
5. `POST /v1/contents`와 재분석은 `Idempotency-Key`를 필수로 받는다. 같은 사용자·작업·키·요청이면 최초 응답을 재생하고, 같은 키에 다른 요청이면 409를 반환한다.
6. 중복은 같은 사용자 안에서만 판정한다. URL은 동기적으로 정규화 URL을 비교하고, 추출 뒤에는 `content_hash`를 비교한다. 다른 사용자끼리는 절대 합치지 않는다.
7. URL 중복은 기존 저장물을 반환한다. 비동기 `content_hash` 중복은 새 임시 저장물을 canonical 저장물의 별칭으로 종결하고 잡 응답의 `result_content_id`로 canonical id를 알려 준다. 기존 저장물을 묵시적으로 수정하지 않는다.
8. `automation_level=auto`는 기존 I1~I8을 끝까지 실행한다. `confirm`은 분석 결과를 후보로 저장한 뒤 `awaiting_confirmation`에서 멈춘다. 승인하면 I6부터 재개하고, 거절하면 AI 결과를 적용하지 않은 채 스냅샷 기반 저장물은 보존한다.
9. 사용자 수정은 AI 층과 분리한다. 사용자 요약, 사용자 대표 태그, `detail_tags.user_patch`, 숨긴 AI 태그를 재분석이 덮어쓰지 않는다.
10. 원본 URL을 GET 때 다시 읽지 않는다. 저장 당시 스냅샷과 확정된 요약은 원본 상태와 무관하게 남는다.
11. 잡 trace는 모델의 숨은 사고 과정이 아니라 실제 파이프라인 입력 참조, 전처리, 모델/프롬프트 식별자, 출력, evidence, 검증 결과, 이벤트다. 없는 값은 만들지 않는다.
12. 기존 DB는 `create_all`만으로 올리지 않는다. 버전이 있는 전진 전용 migration runner를 먼저 넣고 나서 API를 연다.

---

## 1. 목표와 범위

### 1.1 목표

- URL, 직접 텍스트, OCR이 끝난 이미지 텍스트를 정식 API 한 경로로 저장한다.
- 요청이 즉시 끝나지 않아도 콘텐츠 id와 잡 id를 안정적으로 돌려주고, 클라이언트가 실제 단계 상태를 조회할 수 있게 한다.
- 전체 보관함을 사용자별로 조회하고, 필터·정렬·커서 페이지를 제공한다.
- 사용자가 AI 요약·대표 태그·세부 태그를 고치거나 저장물을 숨길 수 있게 한다.
- 자동 분석과 승인 후 반영을 모두 지원한다.
- 재시도, 중복 요청, 워커 재시작, 재분석에서도 사용자 데이터와 사용자 수정을 보존한다.
- 저장 시점의 실제 처리 trace를 보존해 로컬 데모와 문제 분석에서 같은 자료를 읽게 한다.
- 기존 검색, 인덱싱, 인제스트 테스트에 회귀를 만들지 않는다.

### 1.2 이번 범위에서 하지 않는 것

- 실제 로그인 제품, 토큰 발급, 세션 관리, 계정 복구. 인증 인터페이스와 dev 어댑터까지만 만든다.
- 이미지/영상 원본 파일 업로드와 장기 보관, 서버 OCR, 비전 분석, 음성 전사.
- Redis/Celery/Kafka 같은 외부 큐. SQLite 큐와 단일 머신 워커를 유지한다.
- 콘텐츠 공유, 협업 권한, 컬렉션 UI, 휴지통 복원, 보존 정책 UI.
- 중복 저장물 자동 내용 병합, 기존 저장물의 `user_note` 자동 합치기.
- 분석기 품질 변경, 프롬프트 변경, 검색 알고리즘 변경.
- 모델의 비공개 chain-of-thought 저장 또는 노출.

### 1.3 트랙 B와의 파일 경계

동시에 진행되는 분석기 트랙 B와 충돌하지 않도록 저장 API 구현 작업에서 다음 파일·디렉터리는 **수정하지 않는다**.

```text
src/jupjup/ingest/analyzer.py
src/jupjup/ingest/prompts/
src/jupjup/ingest/chunk_notes.py
src/jupjup/providers/llm*.py
src/jupjup/providers/json_grammar.py
src/jupjup/eval/ingest*.py
src/jupjup/eval/judge*.py
config/analyzer_profiles.yaml
src/jupjup/search/
src/jupjup/query/
src/jupjup/demo/
```

저장 트랙은 `ContentAnalyzer.analyze(AnalysisInput) -> (AnalysisOutput, AnalysisRunMeta)`를 동결된 포트로 사용한다. trace에 추가 메타데이터가 필요하면 분석기 파일을 고치지 않고 현재 `meta.model`, `meta.prompt_version`, profile 설정을 읽어 저장 계층에서 보강한다. 계약 변경이 정말 필요하면 트랙 B 완료 뒤 별도 작업으로 합의한다.

---

## 2. 현재 구현 평가와 재사용 계획

### 2.1 그대로 재사용할 것

| 현재 구성 | 재사용 방식 |
|---|---|
| `api/app.py`의 FastAPI factory, UTF-8 응답, 공통 에러 envelope | 라우터를 분리하되 같은 factory와 handler를 사용한다. |
| `api/dto.py`의 `IngestBody` 입력 제한 | 정식 DTO의 길이·timezone·extra forbid 규칙으로 옮긴다. fixture와 `image_path`는 admin 전용에만 남긴다. |
| `ingest/service.py` | 콘텐츠+잡 원자 생성 원칙, 재분석 시작 단계를 재사용한다. 새 저장 service가 orchestration을 감싼다. |
| `ingest/jobs.py` | lease, CAS, 단계별 attempts, 이벤트, 사용자 소유권 검사를 확장한다. |
| `ingest/worker.py` | I1~I8, 결정적 backoff, heartbeat, 축약/완전 인덱싱을 유지한다. confirm과 중복 종결 hook만 추가한다. |
| `domain/models.py` | 유효 요약, 유효 태그, RFC 7396 merge patch, detail schema 검증을 정본으로 쓴다. |
| `storage/tables.py`, `repositories.py` | 기존 테이블을 유지하고 전용 부분 갱신 메서드를 추가한다. |
| `index/service.py`, revision trigger | 저장·수정·숨김·삭제 뒤 인덱스 일관성을 맞추는 데 사용한다. |
| `api/errors.py` | envelope를 유지하고 도메인 에러 매핑만 확장한다. |

### 2.2 현재 구현의 빈칸

1. URL source는 fixture fetcher만 있어 일반 `https://` URL을 가져오지 못한다.
2. 정식 콘텐츠 GET/list/PATCH/DELETE/reanalyze와 정식 잡 API가 없다.
3. 인증 dependency가 `_user_id` 함수에 직접 묶여 있다.
4. idempotency key와 사용자별 중복 fingerprint 저장소가 없다.
5. `create_all`은 기존 SQLite에 새 컬럼을 추가하지 않아 migration이 필요하다.
6. 현재 범용 `SqlContentRepository._upsert`는 snapshot, summary, tag, detail row를 지우고 다시 쓴다. 정식 PATCH와 재분석에서 사용하면 동시 사용자 수정 또는 과거 버전을 잃을 수 있다.
7. 잡 이벤트는 단계 상태의 뼈대는 있지만 단계별 완료 시각, 실제 trace artifact, 승인/거절 상태가 없다.
8. `analysis_runs`는 모델 결과를 I6에서 쓰므로 confirm의 승인 전 후보를 별도로 보관할 곳이 없다.
9. 콘텐츠 전체 숨김과 목록용 cursor/revision이 없다.

따라서 정식 API는 기존 admin route 이름만 바꾸는 작업이 아니다. 큐와 파이프라인은 재사용하되 저장소의 쓰기 단위를 먼저 안전하게 나눠야 한다.

---

## 3. 시스템 구조와 상태 모델

### 3.1 요청 경로

```text
HTTP request
  -> Authenticator -> Principal(user_id)
  -> DTO validation
  -> ContentCommandService / ContentQueryService / JobQueryService
  -> ContentRepository + JobQueue + IdempotencyRepository + FingerprintRepository
  -> SQLite transaction
  -> worker(I1~I8, ContentAnalyzer port, IndexingService)
```

API route는 SQLAlchemy table이나 analyzer concrete class를 직접 import하지 않는다. 사용자 격리, 멱등, 중복, 상태 전이는 service/repository에서 한 번만 구현한다.

### 3.2 콘텐츠 상태

`contents.status`의 유효값을 다음으로 확장한다.

| 상태 | 의미 | 검색/목록 |
|---|---|---|
| `pending` | 새 저장 또는 재분석이 처리 중 | I2 전에는 목록만, I2 뒤 축약 검색 가능 |
| `awaiting_confirmation` | confirm 분석 후보가 준비되어 사용자 결정을 기다림 | 스냅샷 축약 검색 가능, 목록/상세에 후보 표시 |
| `ready` | AI 결과 반영과 완전 인덱싱 완료 | 검색·목록 가능 |
| `analysis_failed` | 분석 실패. 스냅샷 또는 이전 성공 결과는 보존 | 신규 실패는 축약 검색, 재분석 실패는 이전 ready 상태 복원 |
| `analysis_rejected` | 사용자가 후보를 거절함. AI 후보 미반영 | 저장물과 스냅샷은 유지, 축약 검색 가능 |
| `duplicate` | 비동기 hash 중복으로 canonical에 귀속된 임시 저장물 | 기본 목록/검색 제외, 상세는 canonical id 안내 |

`is_hidden=true`인 저장물은 상태와 무관하게 검색에서 제외한다. 목록은 기본적으로 `hidden=false`이며 명시적 필터로 숨긴 항목을 볼 수 있다.

기존 `analysis_pending`은 호환을 위해 유지한다. 의미는 "AI 분석이 실행 중"이 아니라 "현재 인덱스가 snapshot-only 축약 인덱스"로 좁힌다. `analysis_rejected`도 축약 인덱스지만 더 이상 대기 중이 아니므로 새 코드에서는 `status`와 `analysis_pending`을 함께 해석한다. 장기적으로 `index_mode=reduced|full`로 바꾸는 것은 후속 migration이다.

### 3.3 잡 상태와 단계

잡 status:

```text
queued -> running -> retry_wait -> running
                  -> awaiting_confirmation -> queued(stage=persist) -> running -> succeeded
                  -> rejected
                  -> needs_review
                  -> failed
                  -> deduplicated
                  -> cancelled
```

- active: `queued`, `running`, `retry_wait`, `awaiting_confirmation`
- terminal: `succeeded`, `failed`, `needs_review`, `rejected`, `deduplicated`, `cancelled`
- `needs_review`는 모델 refusal 등 시스템 판단 보류이고, `awaiting_confirmation`은 사용자가 요청한 confirm 흐름이므로 섞지 않는다.

표시 단계는 기존 `fetch`, `extract`, `vision`, `chunk`, `analyze`, `persist`, `embed`, `index`에 가상 단계 `confirm`을 더한다. auto 잡은 `confirm=skipped`, confirm 잡은 후보 생성 후 `confirm=waiting`이다.

### 3.4 auto 흐름

1. API가 멱등 키를 예약하고 Content(pending)+Job(queued)을 한 트랜잭션에 만든다.
2. URL preflight 중복이면 기존 content를 즉시 반환하고 잡을 만들지 않는다.
3. 워커가 I1~I2를 수행하고 snapshot 및 `content_hash`를 저장한다.
4. hash fingerprint가 기존 canonical과 충돌하면 잡을 `deduplicated`, 새 content를 `duplicate`로 끝낸다.
5. 충돌이 없으면 I3~I8을 수행한다.
6. I6는 AI 층만 갱신하고 사용자 층은 보존한다.
7. I8 성공 뒤 content를 ready로 바꾼다.

### 3.5 confirm 흐름

1. I1~I5는 auto와 같다.
2. I5의 검증된 output/meta를 `analysis_candidates`와 `analysis_runs`에 저장한다. 이때 effective summary/tag/detail은 바꾸지 않는다.
3. 잡 status를 `awaiting_confirmation`, content status를 같은 값으로 CAS 갱신한다. lease를 해제한다.
4. `GET /v1/contents/{id}`와 `GET /v1/jobs/{id}`가 후보 결과와 evidence를 돌려준다.
5. approve는 candidate id와 상태를 확인한 뒤 잡을 `queued`, stage `persist`로 바꾼다. 워커가 I6~I8을 수행한다.
6. reject는 candidate를 rejected, 잡을 rejected, content를 `analysis_rejected`로 바꾼다. 후보 output은 감사 기록으로 남지만 effective 값과 검색 문서에는 넣지 않는다.
7. 같은 결정을 재전송하면 성공 응답을 재생한다. 반대 결정을 보내거나 superseded candidate를 보내면 409다.

거절은 저장 자체 취소가 아니다. 사용자가 저장한 snapshot과 note는 남고, 필요하면 PATCH로 직접 요약/태그를 넣거나 다시 분석할 수 있다.

---

## 4. 인증과 사용자 격리

### 4.1 인터페이스

```python
class Principal(BaseModel):
    user_id: str
    auth_kind: str
    scopes: frozenset[str]

class Authenticator(Protocol):
    def authenticate(self, request: Request) -> Principal: ...
```

FastAPI dependency는 `Principal`을 반환한다. 모든 service/repository 공개 메서드는 첫 인자로 `user_id` 또는 `Principal`을 필수로 받고, 콘텐츠/잡/후보/trace 조회 SQL에 `user_id` 조건을 넣는다.

### 4.2 dev header 어댑터

- `DevHeaderAuthenticator`는 현재 정규식 `^u_[a-z0-9_]{1,64}$`를 유지한다.
- `X-User-Id`가 없으면 400 `MISSING_USER`, 형식 오류면 400 `INVALID_USER`다. 기존 클라이언트 회귀를 막기 위한 과도기 응답이다.
- `JUPJUP_ENV=dev|test`에서만 조립할 수 있다.
- `prod`에서 `auth_backend=dev_header`면 라우터만 숨기지 않고 애플리케이션 시작을 실패시킨다. 검색 API도 같은 인증 dependency로 옮긴다.
- body의 `user_id`, query의 `user_id`는 스키마상 허용하지 않는다.

### 4.3 존재 여부 은닉

다른 사용자의 content, job, candidate, trace는 없는 id와 똑같이 404 `NOT_FOUND`를 반환한다. 중복 판정 응답도 다른 사용자의 id나 존재 여부를 절대 드러내지 않는다.

---

## 5. 공통 HTTP 계약

### 5.1 기본

- Base path: `/v1`
- JSON: `application/json; charset=utf-8`
- PATCH: `application/merge-patch+json` 권장, `application/json`도 같은 의미로 허용
- 날짜: timezone-aware ISO 8601. 저장은 UTC, 응답은 offset 포함. 기존 데이터의 +09:00 값도 의미를 보존한다.
- id는 opaque string이다. 클라이언트가 prefix 외 구조를 해석하지 않는다.
- 성공 응답의 알 수 없는 필드는 클라이언트가 무시할 수 있어야 한다.
- 에러 envelope는 기존 형식을 유지한다.

```json
{
  "error": {
    "code": "INVALID_CONTENT",
    "message": "저장할 원본 형식이 올바르지 않아요.",
    "details": {"field": "source.url"}
  }
}
```

### 5.2 멱등 헤더

- `POST /v1/contents`, `POST /v1/contents/{id}:reanalyze`는 `Idempotency-Key` 필수다.
- 허용 형식: printable ASCII 1~128자. 로그에는 원문 대신 SHA-256 앞 12자만 남긴다.
- scope는 `(user_id, operation, key)`다. operation에는 method와 route template이 들어간다.
- request hash는 path parameter와 canonical JSON body의 SHA-256이다. 헤더 순서와 JSON key 순서는 영향을 주지 않는다.
- 최초 트랜잭션이 완료되면 status code, 안전한 response JSON, resource ids를 24시간 저장한다.
- 같은 hash 재호출은 최초 status/body를 반환하고 `Idempotency-Replayed: true`를 단다.
- 다른 hash는 409 `IDEMPOTENCY_CONFLICT`다.
- 아직 처리 중인 키는 409 `IDEMPOTENCY_IN_PROGRESS`와 `Retry-After: 1`을 반환한다.
- source 원문과 user note는 idempotency table에 저장하지 않는다.

승인/거절은 `(candidate_id, decision)` 자체가 멱등 식별자이므로 별도 키를 요구하지 않는다. DELETE는 목표 상태에 대해 멱등이고 PATCH는 같은 effective 값을 다시 적용하면 새 summary version/revision을 만들지 않는다.

### 5.3 리소스 revision

`contents.revision`은 사용자 수정, AI 확정, 숨김, 상태 변경 때 증가한다. 상세 응답은 `ETag: "content:<id>:<revision>"`을 보낸다. PATCH의 `If-Match`는 선택이지만 주어지면 반드시 검사하며 stale이면 409 `VERSION_CONFLICT`다.

---

## 6. 정식 API

### 6.1 `POST /v1/contents`

요청:

```json
{
  "source": {
    "kind": "url",
    "url": "https://example.com/article?utm_source=share"
  },
  "platform_hint": "news",
  "content_type_hint": "article",
  "title": null,
  "author": null,
  "user_note": "주말에 다시 읽기",
  "automation_level": "auto"
}
```

source union:

```json
{"kind":"url", "url":"https://..."}
{"kind":"text", "text":"..."}
{"kind":"image", "ocr_text":"...", "image":{"mime_type":"image/jpeg", "sha256":"<optional 64 hex>"}}
```

규칙:

- 한 요청에는 source variant 하나만 허용한다. extra field는 422다.
- URL은 http/https, 최대 2,048자다. fragment는 저장 전 제거한다.
- text/ocr_text는 trim 뒤 1~100,000자다. 숫자·기호만 있는 텍스트도 허용한다.
- `image` object는 원본 파일 자체가 아니라 식별 메타다. `ocr_text`가 반드시 있어야 한다.
- `platform_hint`, `content_type_hint`는 6.1절 enum만 허용한다. 둘이 없으면 source/hostname으로 결정한다.
- 명백히 모순되는 조합(예: `platform_hint=kakaotalk`, `content_type_hint=article`)은 접수 전에 422 `INVALID_CONTENT`다.
- `user_note`는 최대 2,000자다.
- `automation_level`은 `auto|confirm`, 기본 `auto`다.
- 클라이언트가 `saved_at`을 조작하지 않는다. 정식 API는 서버 접수 시각을 쓴다. 시간 주입은 admin/test 경로에만 남긴다.
- 정식 요청에는 `fixture`, `image_path`, analyzer profile을 허용하지 않는다.

새 저장 응답은 202다.

```json
{
  "content_id": "c_...",
  "job_id": "job_...",
  "status": "queued",
  "automation_level": "auto",
  "deduplicated": false,
  "result_content_id": "c_..."
}
```

헤더:

- `Location: /v1/contents/c_...`
- `Content-Location: /v1/jobs/job_...`

동기 URL/text hash 중복을 발견한 경우 200이다.

```json
{
  "content_id": "c_existing",
  "job_id": null,
  "status": "ready",
  "automation_level": "auto",
  "deduplicated": true,
  "duplicate_reason": "normalized_url",
  "result_content_id": "c_existing",
  "warnings": ["user_note_not_applied"]
}
```

중복 응답은 기존 저장물의 note, title, automation level을 바꾸지 않는다.

### 6.2 `GET /v1/contents/{content_id}`

200 응답은 저장물의 effective 값과 출처 층을 함께 준다.

```json
{
  "id": "c_...",
  "canonical_id": "c_...",
  "revision": 7,
  "status": "ready",
  "hidden": false,
  "source": {
    "kind": "url",
    "url": "https://example.com/article",
    "original_status": "unknown"
  },
  "platform": "news",
  "content_type": "article",
  "title": "제목",
  "author": "작성자",
  "published_at": null,
  "saved_at": "2026-11-03T10:00:00+09:00",
  "user_note": "주말에 다시 읽기",
  "summary": {
    "effective": "사용자 또는 AI 요약",
    "source": "user",
    "ai": "AI 요약",
    "user": "사용자 요약"
  },
  "representative_tags": {
    "effective": ["카페", "성수동"],
    "ai": ["카페", "디저트"],
    "user": ["성수동"],
    "hidden_ai": ["디저트"]
  },
  "detail_tags": {
    "effective": {"schema_version": 1, "topics": ["카페"]},
    "ai": {"schema_version": 1, "topics": ["디저트"]},
    "user_patch": {"topics": ["카페"]}
  },
  "snapshot": {
    "id": "snap_...",
    "captured_at": "2026-11-03T01:00:02Z",
    "text": "저장 당시 추출 본문",
    "ocr_text": null,
    "content_hash": "...",
    "truncated": false
  },
  "analysis": {
    "automation_level": "auto",
    "analysis_pending": false,
    "latest_job_id": "job_...",
    "candidate": null
  },
  "created_at": "...",
  "updated_at": "..."
}
```

- GET은 원본 URL에 네트워크 요청을 하지 않는다.
- `status=duplicate`이면 `canonical_id`가 다른 값이고, 본문 대신 최소 alias 정보와 canonical link를 반환한다.
- confirm 대기 중이면 `analysis.candidate`에 candidate id, summary, tags, detail tags, evidence, model/profile 정보를 넣는다.
- snapshot text는 사용자 자신의 데이터이므로 상세 응답에 포함한다. 추후 모바일 대역폭 요구가 생기면 `include_snapshot=false`를 추가한다.

### 6.3 `GET /v1/contents`

전체 보관함 목록이다.

Query:

| 파라미터 | 기본 | 규칙 |
|---|---|---|
| `platform` | 없음 | 반복 가능, 최대 10개 |
| `content_type` | 없음 | 반복 가능, 최대 10개 |
| `status` | 없음 | 반복 가능. `duplicate`는 명시해야 포함 |
| `hidden` | `false` | `false|true|all` |
| `saved_from`, `saved_to` | 없음 | timezone-aware, inclusive/exclusive `[from,to)` |
| `tag` | 없음 | 정규화된 effective 대표 태그 exact match, 최대 10개, 모두 AND |
| `sort` | `saved_at` | `saved_at|updated_at` |
| `order` | `desc` | `asc|desc` |
| `limit` | 20 | 1~100 |
| `cursor` | 없음 | opaque signed cursor |

정렬 tie-breaker는 항상 `id`다. 예: `saved_at desc, id desc`. offset은 사용하지 않는다.

응답:

```json
{
  "items": [
    {
      "id": "c_...",
      "revision": 7,
      "status": "ready",
      "hidden": false,
      "title": "제목",
      "platform": "news",
      "content_type": "article",
      "summary": "유효 요약",
      "representative_tags": ["태그"],
      "saved_at": "...",
      "updated_at": "...",
      "source_url": "https://...",
      "original_available": true,
      "analysis_pending": false
    }
  ],
  "next_cursor": "opaque-or-null",
  "has_more": true
}
```

cursor payload는 version, user scope digest, filter/sort digest, 마지막 `(sort_value,id)`를 담고 서버 secret으로 HMAC 서명한다. 다른 사용자, 다른 필터, 다른 정렬에서 재사용하거나 변조하면 422 `INVALID_CURSOR`다. response에 total count는 넣지 않는다.

### 6.4 `PATCH /v1/contents/{content_id}`

요청은 다음 필드만 허용한다.

```json
{
  "summary": "사용자가 고친 요약",
  "representative_tags": ["성수동", "데이트"],
  "detail_tags": {
    "topics": ["브런치"],
    "attributes": {"price": null}
  },
  "hidden": true
}
```

필드 생략은 변경 없음이다.

- `summary: string`: 새 `source=user` summary version을 만든다. 1~1,000자.
- `summary: null`: 모든 user summary override를 제거해 최신 AI summary로 되돌린다.
- `representative_tags: array`: 현재 사용자가 원하는 effective 목록으로 해석한다. NFKC, 앞 `#` 제거, 공백 제거, 중복 제거 후 0~15개다. 제출한 값은 user tag로 저장하고 현재 AI 태그 중 빠진 값은 `hidden_tags`에 넣는다.
- `representative_tags: null`: user tags와 `hidden_tags`를 비워 AI 태그로 되돌린다.
- `detail_tags: object`: 현재 effective detail에 RFC 7396 JSON Merge Patch로 적용한다. 중첩 `null`은 그 AI 값을 가리는 tombstone으로 `user_patch`에 보존한다.
- `detail_tags: null`: user patch 전체를 없애 AI detail로 되돌린다.
- `hidden`: 콘텐츠 전체 숨김이다. `true`면 검색에서 즉시 제외하고 `false`면 다시 인덱싱한다.
- `schema_version`은 수정할 수 없다. merge 결과는 `detail_tags.v1.json`을 통과해야 한다.
- 결과가 현재 effective 값과 같으면 새 version/revision을 만들지 않는다.

유효값은 기존 6.2절을 그대로 따른다.

```text
effective summary = 최신 user summary, 없으면 최신 ai summary
effective tags = user tags ∪ (ai tags - hidden_tags - user와 같은 이름)
effective detail = merge_patch(ai_json, user_patch)
```

재분석은 AI summary/tag/detail만 교체하므로 위 사용자 층을 덮어쓰지 못한다. 향후 생성된 새로운 AI 태그는 기존 규칙상 effective tag에 추가될 수 있지만, 사용자가 숨긴 이름과 user tag는 그대로 우선한다.

응답은 갱신된 상세 resource 200이다. 다른 사용자 id는 404, invalid patch는 422, 활성 delete/duplicate 상태는 409다.

### 6.5 `DELETE /v1/contents/{content_id}`

- 성공 204, body 없음.
- active job은 같은 트랜잭션에서 먼저 `cancelled`로 CAS해 stale worker를 막는다. hard delete이므로 이어지는 cascade 뒤에는 job/event도 조회되지 않는다.
- snapshot, summary, tags, detail, embeddings, analysis runs, candidates, trace artifacts는 FK cascade로 삭제한다.
- 메모리 인덱스에서도 제거하고 revision을 올린다.
- 원본 URL의 외부 리소스는 건드리지 않는다.
- 다른 사용자 또는 없는 id는 동일한 404다.

MVP는 휴지통 없는 hard delete다. material delete가 끝난 뒤의 같은 DELETE는 404여도 HTTP 메서드의 목표 상태는 이미 달성되므로 허용한다.

### 6.6 `POST /v1/contents/{content_id}:reanalyze`

헤더 `Idempotency-Key` 필수.

```json
{
  "automation_level": "auto"
}
```

- profile은 정식 API에서 받지 않고 서버 기본 profile을 쓴다. dev admin/CLI만 profile을 지정할 수 있다.
- 기본은 저장된 최신 snapshot부터 `chunk` 단계로 시작한다. 원본 URL을 다시 fetch하지 않아 원본 소실과 무관하게 재분석할 수 있다.
- body의 automation level은 `auto|confirm`, 생략하면 기존 콘텐츠 값을 사용한다.
- active job이 있으면 409 `CONTENT_BUSY`다.
- user summary/tags/detail patch/hidden tags/is_hidden은 job 시작과 성공/실패 모두에서 보존한다.
- 실패하면 기존 successful AI 결과와 content 상태를 복원한다. 신규 분석 output은 effective 값이 되지 않는다.

응답 202는 create 응답과 같은 `content_id`, `job_id`, `status`를 반환한다.

### 6.7 `POST /v1/contents/{content_id}:review`

confirm 결과의 승인/거절 endpoint다.

```json
{
  "candidate_id": "cand_...",
  "decision": "approve"
}
```

- `approve`: 202, job을 persist 단계 queued로 바꾸고 worker가 I6~I8을 수행한다.
- `reject`: 200, job/candidate를 rejected로 바꾸고 content를 `analysis_rejected`로 바꾼다.
- 같은 candidate에 같은 decision은 현재 결과를 그대로 반환한다.
- 다른 decision, 최신이 아닌 candidate, content/job 소유권 불일치, 대기 상태가 아닌 경우 409 `REVIEW_CONFLICT`다.
- approve와 동시에 PATCH가 와도 사용자 층과 AI 층이 다른 row/transaction으로 갱신되어 사용자 수정을 잃지 않는다.

### 6.8 `GET /v1/jobs/{job_id}`

Query `trace=none|summary|full`, 기본 `summary`.

```json
{
  "id": "job_...",
  "content_id": "c_requested",
  "result_content_id": "c_canonical",
  "kind": "ingest",
  "automation_level": "confirm",
  "status": "awaiting_confirmation",
  "current_stage": "confirm",
  "attempts": {"fetch": 1, "analyze": 2},
  "created_at": "...",
  "updated_at": "...",
  "next_run_at": null,
  "error": null,
  "steps": [
    {
      "stage": "fetch",
      "status": "succeeded",
      "attempts": 1,
      "started_at": "...",
      "finished_at": "...",
      "duration_ms": 41,
      "error": null
    },
    {
      "stage": "confirm",
      "status": "waiting",
      "attempts": 0,
      "started_at": "...",
      "finished_at": null,
      "duration_ms": null,
      "error": null
    }
  ],
  "candidate": {"id": "cand_...", "status": "pending"},
  "trace": {
    "input": {},
    "preprocessing": {},
    "model_processing": {},
    "result": {},
    "evidence": [],
    "execution_log": []
  }
}
```

- steps는 항상 고정 순서로 모두 반환하고 아직 안 간 단계는 `pending`, 해당 없는 vision/confirm은 `skipped`다.
- retry 중에는 현재 단계 status가 `retry_wait`, `next_run_at`이 실제 예약 시각이다.
- error는 `{code, message, stage, retryable, attempt}`의 안전한 필드만 포함한다. 원문, 로컬 path, provider payload, stack trace는 포함하지 않는다.
- `trace=full`은 snapshot/chunk/model 입출력 같은 민감한 사용자 데이터를 포함할 수 있다. 소유 사용자만 접근하고 `Cache-Control: private, no-store`를 단다.

---

## 7. 저장 핵심 로직

### 7.1 URL 정규화

`normalize_source_url`은 I/O 없는 결정적 함수다.

1. scheme과 host를 소문자로 바꾸고 host는 IDNA ASCII로 정규화한다.
2. fragment는 제거한다.
3. 기본 port 80/443은 제거한다.
4. 빈 path는 `/`로 만들고 dot segment를 제거한다. percent encoding은 unreserved 문자만 decode한다.
5. query는 key/value로 파싱해 key와 value 순으로 안정 정렬한다.
6. `utm_*`, `fbclid`, `gclid`, `igshid`, `mc_cid`, `mc_eid`는 제거한다.
7. 인증 정보가 든 URL(`user:pass@host`)은 거부한다.
8. YouTube `youtu.be/<id>`, watch URL은 같은 canonical watch URL로 맞춘다. Instagram은 게시물/Reels 식별 path 뒤 slash를 통일하고 tracking query를 제거한다.

정규화 규칙 version을 `url-normalization-v1`로 fingerprint row에 저장한다. 규칙 변경은 기존 unique 의미를 바꾸므로 migration과 회귀 fixture가 필요하다.

### 7.2 URL fetch 안전성

정식 URL 저장을 위해 `HttpSourceFetcher`를 `FetcherRouter` 뒤에 추가한다.

- http/https만 허용, DNS 결과의 loopback/private/link-local/multicast/reserved 주소 차단
- redirect 최대 3회, 매 hop scheme/host/IP 재검사
- connect 3초, total 10초, body 최대 10 MiB
- 허용 content type: HTML, plain text, 공개 자막 형식. 나머지는 `INGEST_UNSUPPORTED`
- 압축 해제 뒤 크기 제한 재검사
- 쿠키 로그인, 브라우저 세션, robots/auth 우회 금지
- 응답 body와 URL credential을 로그에 남기지 않음
- 429/5xx/timeout/connection은 retryable, 4xx/차단/지원하지 않는 MIME은 permanent

로컬 분석기는 네트워크를 사용하지 않는다는 T25 원칙과 충돌하지 않는다. 네트워크는 I1 공개 원본 수집에만 사용하고 모델 로드/실행에서는 사용하지 않는다.

### 7.3 content hash

기존 정의를 유지한다.

```text
sha256(normalized_snapshot_text + "\0" + normalized_ocr_text)
```

- title, URL, user_note, 저장 시각은 hash에 넣지 않는다.
- text/image inline source는 요청 단계에서 같은 정규화 함수를 사용해 preflight할 수 있다.
- URL은 추출 결과가 나온 I2에서 claim한다.
- hash 알고리즘 version은 `content-hash-v1`로 저장한다.

### 7.4 fingerprint claim과 중복 경쟁

`content_fingerprints`의 unique `(user_id, kind, version, fingerprint)`가 최종 판정자다.

1. service가 normalized URL fingerprint를 transaction 안에서 claim한다.
2. 충돌하면 기존 fingerprint의 canonical content를 반환한다.
3. I2가 content hash를 같은 방식으로 claim한다.
4. 두 워커가 같은 hash를 동시에 claim하면 한 transaction만 성공한다.
5. 패자는 새 content를 duplicate alias로 바꾸고 잡을 deduplicated로 종결한다. canonical content의 사용자 데이터는 수정하지 않는다.
6. alias GET은 canonical을 안내하지만 기본 목록, 검색, 인덱스에는 들어가지 않는다.
7. 다른 사용자 row는 unique scope가 달라 서로 영향이 없다.

같은 URL의 페이지가 바뀌었더라도 MVP는 기존 저장물을 반환한다. 최신 내용을 다시 캡처하는 기능은 별도 `refresh source` 작업으로 남긴다. 재분석은 기존 snapshot을 사용하므로 refresh가 아니다.

### 7.5 원본 소실과 snapshot 불변식

- I2가 성공한 snapshot은 append-only다. 새 snapshot이 필요하면 새 row를 추가하고 과거 row를 삭제하지 않는다.
- GET/search/index는 최신 captured snapshot을 사용하되, 과거 analysis run은 자신이 사용한 snapshot id를 기록한다.
- 원본 fetch 실패나 `original_status=deleted`는 기존 snapshot, summary, tags, detail을 지우지 않는다.
- 재분석은 기존 snapshot을 사용하며 실패해도 마지막 성공 AI 결과를 유지한다.
- hard DELETE만 snapshot과 확정 요약을 지운다.

### 7.6 사용자 수정 보존

범용 bundle upsert 대신 다음 원자 연산을 둔다.

```python
class ContentRepository(Protocol):
    def create_with_job(...): ...
    def get_detail(user_id: str, content_id: str) -> ContentDetail: ...
    def list_page(user_id: str, query: ContentListQuery) -> ContentPage: ...
    def append_snapshot(user_id: str, content_id: str, snapshot: Snapshot) -> None: ...
    def apply_user_patch(user_id: str, content_id: str, patch: UserContentPatch, expected_revision: int | None) -> ContentDetail: ...
    def persist_ai_analysis(user_id: str, content_id: str, run: AnalysisRun, output: AnalysisOutput) -> None: ...
    def mark_hidden(...): ...
    def delete_owned(...): ...
```

`persist_ai_analysis`는 다음만 바꾼다.

- 새 AI summary version 추가
- AI tag set 교체
- `detail_tags.ai_json`과 `analysis_run_id` 교체
- 비어 있는 경우에만 AI title suggestion 반영

다음은 읽기만 하고 절대 수정하지 않는다.

- user summary rows
- user tag rows
- `contents.hidden_tags`
- `detail_tags.user_patch`
- `contents.user_note`
- `contents.is_hidden`

I6와 PATCH는 transaction 안에서 최신 row를 다시 읽고 적용한다. service가 오래 전에 읽은 `ContentBundle` 전체를 다시 upsert하지 않는다.

### 7.7 재시도와 실패 분류

기존 횟수와 backoff를 유지한다.

| 단계 | 최대 시도 | retryable | permanent 대표 사유 |
|---|---:|---|---|
| fetch | 4 | timeout, connection, 429, 5xx | invalid URL, blocked address, 4xx, unsupported MIME |
| extract | 3 | 일시 I/O/storage | empty body, unsupported encoding/shape |
| vision | 3 | provider timeout/5xx | image에 OCR text 없음 |
| chunk | 3 | storage read 오류 | 불변식/스키마 오류 |
| analyze | 3 | provider unavailable, 허용된 timeout 1회 | schema repair 소진, refusal은 needs_review |
| persist | 3 | SQLite busy/transient | ownership/state conflict |
| embed | 5 | provider/storage transient | invalid dimension/config |
| index | 5 | transient index/storage | invariant/config error |

backoff는 기존 `2s * 2^(n-1)`, cap 5분, job hash 기반 ±20% deterministic jitter다. `last_error`와 event에는 안전한 code만 남기고, 상세 trace와 운영 로그를 분리한다.

클라이언트와 운영자가 분기할 수 있는 실패 사유는 다음 표로 고정한다. provider의 자유 형식 메시지는 code를 대신하지 않는다.

| 공개 code | 단계 | 재시도 | 의미/다음 행동 |
|---|---|---:|---|
| `INGEST_FETCH_FAILED` | fetch | 조건부 | timeout, connection, 429, 5xx면 재시도. 횟수 소진 뒤 원본 접근 상태 확인 |
| `INGEST_UNSUPPORTED` | fetch | 아니오 | scheme/MIME/인증 필요/보안 차단/지원하지 않는 source |
| `INGEST_EXTRACT_FAILED` | extract | 아니오 | 가져왔지만 본문을 만들 수 없음 |
| `INGEST_NO_TEXT` | extract/vision | 아니오 | text/OCR/추출 본문이 모두 비었음 |
| `VISION_UNAVAILABLE` | vision | 예 | 구성된 vision provider의 일시 장애. OCR-only MVP에서는 보통 발생하지 않음 |
| `ANALYZER_UNAVAILABLE` | analyze | 아니오 | local model/extra/sha/config 준비 실패. 설치나 설정 수정 뒤 재분석 |
| `LLM_TIMEOUT` | analyze | 1회 | 결정적 local 생성 timeout. 같은 job에서 허용 횟수 제한 |
| `LLM_UNAVAILABLE` | analyze | 조건부 | provider transport/5xx. mock cache miss는 permanent로 분류 |
| `LLM_CONTEXT_OVERFLOW` | analyze | 아니오 | 입력/청킹/프로필 설정 불일치 |
| `LLM_REFUSED` | analyze | 아니오 | job을 `needs_review`로 종결 |
| `ANALYSIS_SCHEMA_INVALID` | analyze | 아니오 | repair 소진 뒤에도 유효 출력 없음 |
| `STORAGE_UNAVAILABLE` | 모든 쓰기 | 예 | SQLite busy/I/O transient. integrity/state conflict는 별도 409 또는 permanent |
| `EMBEDDING_UNAVAILABLE` | embed | 조건부 | provider transient는 재시도, config/dimension 오류는 permanent |
| `INDEX_UNAVAILABLE` | index | 조건부 | 일시 저장/인덱스 오류. 실패해도 snapshot/분석 결과는 DB에 보존 |
| `INGEST_LEASE_LOST` | 모든 단계 | 아니오 | 현재 실행은 결과를 버리고 새 lease 소유자가 복구 |
| `CONTENT_DEDUPLICATED` | extract | 해당 없음 | 실패가 아닌 terminal dedupe. `result_content_id` 사용 |
| `CONTENT_DELETED` | 모든 단계 | 해당 없음 | 사용자가 실행 중 삭제해 job이 cancelled 됨 |

retryable 여부는 code만으로 단정하지 않고 안전하게 정규화한 `details.status`, `details.retryable`과 단계 정책으로 결정한다. job 응답은 최종 판정값을 `error.retryable`에 넣는다.

### 7.8 삭제와 실행 중 워커 경쟁

- DELETE transaction이 active job을 cancelled로 바꾸고 content를 삭제한다.
- stale worker는 lease/CAS 실패로 결과를 쓰지 못한다.
- 외부 모델 호출이 이미 진행 중이면 호출 자체를 취소하지 못할 수 있지만 반환 결과는 폐기한다.
- index remove 실패 시 DB가 정본이며 다음 refresh/rebuild가 수선한다. API는 실패를 숨기지 않고 503을 반환하거나 outbox 보정 작업을 남긴다.

---

## 8. 저장 시점 trace

### 8.1 원칙

`specs/backlog_instagram_demo.md`의 "추론 과정"은 모델의 숨은 생각이 아니다. 다음 실제 자료만 저장한다.

| 범주 | 저장 내용 |
|---|---|
| 입력 | source kind, 정규화 URL, snapshot id/hash, 분석 대상 길이와 실제 chunk 참조 |
| 전처리 | 추출기/정규화 version, before/after 길이, language, truncation, chunk 경계와 coverage |
| 모델 처리 | profile, model id와 포함된 model sha 지문, prompt version, decoding/profile fingerprint, 요청 횟수, map/reduce chunk output |
| 결과 | 검증된 summary, keywords/tags/detail/save intent, candidate/확정 여부 |
| 근거 | evidence source span, validator issue/repair, 실제 제공되는 score |
| 실행 로그 | 단계 event, attempt, 시작/종료/소요 시간, retry/error code |

값을 제공하지 않는 provider에는 `null`을 넣지 않고 필드를 생략한다. 임의 score나 가짜 진행률을 계산하지 않는다.

### 8.2 보안과 보존

- trace는 일반 로그가 아니라 사용자 콘텐츠 하위 데이터다. 모든 조회에 user scope를 적용한다.
- source text와 model input은 snapshot/chunk artifact로 저장할 수 있지만 stdout, error detail, idempotency row에는 넣지 않는다.
- prompt 원문은 중복 저장하지 않고 prompt version/hash를 저장한다. 렌더된 사용자 입력이 필요하면 `full` artifact에 저장한다.
- trace retention은 콘텐츠 수명과 같다. DELETE cascade 대상이다.
- API 기본 `trace=summary`는 길이/식별자/결과/evidence 중심이다. `full`만 chunk text와 model raw output을 준다.
- 기존 `ingest_jobs.stage_data`는 재개용 작업 공간일 뿐 장기 trace 정본이 아니다. terminal 상태가 되면 snapshot/candidate/trace에 필요한 값을 먼저 확정한 뒤 raw body, 분석 입력, model output을 제거한다. `awaiting_confirmation`도 candidate가 확정됐으므로 같은 정리를 할 수 있다.
- 향후 실제 멀티테넌트 배포 전 DB at-rest encryption과 trace 축소 정책을 다시 결정한다.

### 8.3 단계 event에서 step 계산

각 attempt의 started와 terminal event에 동일한 `attempt`를 기록한다. `finished_at - started_at`으로 duration을 계산해도 되지만 조회 비용과 누락 검출을 위해 terminal event에 `duration_ms`도 함께 저장한다. retry 뒤 다음 started는 별도 attempt다. running 중이면 현재 시각으로 가짜 duration을 확정하지 않는다.

---

## 9. 데이터 모델 변경

### 9.1 기존 테이블 변경

**contents 추가 컬럼**

| 컬럼 | 타입/기본 | 용도 |
|---|---|---|
| `source_kind` | TEXT, 기존 row는 추론 | `url|text|image` |
| `normalized_url` | TEXT NULL | 표시가 아닌 중복/진단용 canonical URL |
| `automation_level` | TEXT `auto` | `auto|confirm` |
| `is_hidden` | INTEGER `0` | 전체 숨김 |
| `revision` | INTEGER `0` | optimistic concurrency/ETag |
| `duplicate_of_content_id` | TEXT NULL self FK, ON DELETE CASCADE | async duplicate alias의 canonical id. canonical 삭제 시 내부 alias도 함께 삭제 |

status enum 값은 3.2절 값으로 확장한다. `(user_id, is_hidden, saved_at, id)`, `(user_id, updated_at, id)`, `(user_id, status)` 인덱스를 추가한다.

**ingest_jobs 추가 컬럼**

| 컬럼 | 타입 | 용도 |
|---|---|---|
| `automation_level` | TEXT `auto` | confirm 분기 |
| `result_content_id` | TEXT NULL | dedupe canonical 결과 |
| `candidate_id` | TEXT NULL | 승인 대상 |
| `completed_at` | TEXT NULL | terminal 시간 |

active unique partial index에 `awaiting_confirmation`을 포함한다.

**analysis_runs 추가 컬럼**

| 컬럼 | 타입 | 용도 |
|---|---|---|
| `snapshot_id` | TEXT NULL | 어떤 원본으로 분석했는지 |
| `candidate_id` | TEXT NULL | confirm 후보 연결 |
| `model_fingerprint` | TEXT NULL | 제공되는 실제 모델/decoding 지문 |
| `validator_json` | TEXT `{}` | issue, repair, 실제 점수 |
| `accepted_at` | TEXT NULL | effective 결과가 된 시각 |

기존 `output_json`은 유지한다. 분석 run은 append-only이며 재분석 성공으로 이전 run을 지우지 않는다.

### 9.2 새 테이블

**schema_migrations**

`(version INTEGER PK, name TEXT, checksum TEXT, applied_at TEXT)`

**idempotency_keys**

| 컬럼 | 내용 |
|---|---|
| `user_id, operation, key_hash` | UNIQUE scope |
| `request_hash` | canonical request SHA-256 |
| `state` | `in_progress|completed` |
| `response_status, response_json` | 재생할 안전한 응답 |
| `resource_id, job_id` | 참조 id, FK는 두지 않아 delete 뒤에도 retry 판정 가능 |
| `created_at, expires_at` | 기본 24시간 |

원래 key와 요청 원문은 저장하지 않는다.

**content_fingerprints**

| 컬럼 | 내용 |
|---|---|
| `user_id` | 격리 scope |
| `kind` | `normalized_url|content_hash` |
| `version` | normalization/hash version |
| `fingerprint` | URL hash 또는 content hash |
| `content_id` | canonical content FK |
| `created_at` | claim 시각 |
| 제약 | UNIQUE(user_id, kind, version, fingerprint) |

정규화 URL 원문은 `contents.normalized_url`에 있고 fingerprint에는 SHA-256을 넣어 인덱스 노출을 줄인다.

**analysis_candidates**

| 컬럼 | 내용 |
|---|---|
| `id` | PK |
| `user_id, content_id, job_id, analysis_run_id` | 소유권/연결 |
| `status` | `pending|approved|rejected|superseded` |
| `output_json, meta_json` | 검증된 후보와 실제 메타 |
| `created_at, decided_at` | 시각 |
| `decision_revision` | 중복 결정 CAS |

job당 candidate 하나를 기본으로 하고 `(job_id)` unique를 둔다.

**ingest_trace_artifacts**

| 컬럼 | 내용 |
|---|---|
| `id` | PK |
| `user_id, content_id, job_id` | scope와 FK |
| `stage` | 단계 |
| `attempt` | 시도 번호 |
| `artifact_type` | `input|preprocessing|model|result|evidence|validation|log` |
| `schema_version` | trace payload version |
| `payload_json` | 실제 구조화 자료 |
| `payload_hash` | canonical JSON SHA-256 |
| `sensitive` | full 응답 분기 |
| `created_at` | 시각 |

같은 `(job_id, stage, attempt, artifact_type, payload_hash)`는 unique로 만들어 단계 재실행에도 중복 row가 생기지 않게 한다.

### 9.3 migration 전략

1. T27a가 API route보다 먼저 migration runner와 migration test를 만든다.
2. 애플리케이션 시작 시 DB version을 읽는다. dev 기본은 자동 전진 migration, prod는 `JUPJUP_AUTO_MIGRATE=false` 기본으로 사전 CLI 실행을 요구한다.
3. 각 migration은 transaction 안에서 실행하고 checksum이 바뀐 과거 migration은 시작 실패다.
4. SQLite `ALTER TABLE ADD COLUMN`으로 가능한 변경을 먼저 하고, table rebuild가 필요한 제약은 temp table 복사·count 검증·rename 방식으로 한다.
5. migration 전 `PRAGMA foreign_key_check`, 후 동일 검사와 row count를 수행한다. 실패하면 원본 DB를 그대로 둔다.
6. 기존 contents backfill:
   - source_url 있으면 `source_kind=url`, 정규화 가능하면 normalized_url
   - content_type=image이고 ocr snapshot이면 `image`, 나머지는 `text`
   - `automation_level=auto`, `is_hidden=0`, `revision=0`
7. 기존 normalized URL/content hash fingerprint는 사용자별 `created_at, id`가 가장 이른 row만 canonical claim한다. 충돌 row를 자동 삭제/alias 처리하지 않고 migration report에 남긴다. 중복 정책은 신규 요청부터 강제한다.
8. 기존 analysis run은 snapshot id를 확실히 연결할 수 있을 때만 backfill하고 아니면 NULL로 둔다.
9. `create_db_engine`의 `metadata.create_all`은 빈 DB bootstrap 뒤 migration runner를 호출하도록 바꾼다. create_all만으로 최신이라고 간주하지 않는다.
10. downgrade는 제공하지 않는다. 개발 DB도 migration 전에 자동 timestamp backup을 만들고 경로를 출력한다.

---

## 10. 에러 매핑

기존 envelope와 5.9절 의미를 유지한다.

| HTTP | code | 조건 |
|---:|---|---|
| 400 | `MISSING_USER`, `INVALID_USER` | dev auth header 없음/형식 오류 |
| 400 | `MISSING_IDEMPOTENCY_KEY`, `INVALID_IDEMPOTENCY_KEY` | 필수 키 없음/형식 오류 |
| 401 | `UNAUTHENTICATED` | 향후 실제 auth 자격 증명 없음/만료 |
| 403 | `FORBIDDEN` | 향후 scope 부족. 소유권 불일치는 쓰지 않고 404 |
| 404 | `NOT_FOUND` | content/job/candidate 없음 또는 다른 사용자 |
| 409 | `IDEMPOTENCY_CONFLICT`, `IDEMPOTENCY_IN_PROGRESS` | 키 충돌/진행 중 |
| 409 | `CONTENT_BUSY` | active ingest/reanalyze/review가 있음 |
| 409 | `VERSION_CONFLICT` | If-Match stale |
| 409 | `REVIEW_CONFLICT` | 잘못된 후보/반대 결정/이미 superseded |
| 409 | `INVALID_CONTENT_STATE` | duplicate/deleting 등 상태에서 허용되지 않은 작업 |
| 422 | `INVALID_CONTENT` | source union, URL, 길이, enum, detail schema 오류 |
| 422 | `INVALID_PATCH` | 허용되지 않은 patch 또는 effective 값 위반 |
| 422 | `INVALID_CURSOR` | cursor 변조/scope/filter 불일치 |
| 422 | `VALIDATION_ERROR` | 그 밖의 DTO 오류 |
| 405 | `METHOD_NOT_ALLOWED` | 기존 규칙 |
| 503 | `STORAGE_UNAVAILABLE`, `INDEX_UNAVAILABLE` | 저장/인덱스 일시 실패 |
| 503 | `ANALYZER_UNAVAILABLE` | local analyzer 준비 안 됨. job 내부 실패는 job error로 표시 |
| 500 | `INTERNAL` | 내부 정보 없는 공통 오류 |

`ContentValidationError`는 현재처럼 500으로 빠지지 않게 route 이전에 422로 명시 매핑한다. 잡 내부 오류와 HTTP 접수 오류를 구분한다. POST가 유효하게 접수된 뒤의 fetch/analyze 실패는 최초 POST를 500으로 바꾸지 않고 job status에서 보고한다.

---

## 11. 루프백 바인드와 dev gate

1. 기본 bind는 `127.0.0.1`이다.
2. `auth_backend=dev_header`일 때는 `--allow-external-bind`를 줘도 non-loopback bind를 거부한다. 현재 경고 후 허용 동작보다 안전하게 바꾼다.
3. 향후 실제 auth backend일 때만 명시적 external bind를 허용하며 TLS는 reverse proxy 책임으로 문서화한다.
4. `/v1/admin/*`, fixture path, saved_at/now 주입, profile 선택은 `JUPJUP_ENV=dev`와 `admin_api_enabled=true`일 때만 route를 등록한다. 그 외에는 403이 아니라 404다.
5. `/v1/contents`와 `/v1/jobs`는 admin path가 아니지만 반드시 auth adapter가 있어야 한다. 실제 auth가 없는 현재 기본 배포는 dev+loopback으로 한정한다.
6. `/healthz`는 인증 없이 최소 상태만 반환하고 DB path, user count, model local path를 노출하지 않는다.

---

## 12. 모듈 배치와 인터페이스

권장 변경 구조:

```text
src/jupjup/
  auth.py                         # Principal, Authenticator, DevHeaderAuthenticator
  api/
    app.py                        # factory와 router 조립
    dto.py                        # 검색 DTO 유지
    routes_contents.py            # 정식 contents API
    routes_jobs.py                # 정식 jobs API
    content_dto.py                # create/list/detail/patch/review DTO
    errors.py                     # 공통 mapping 확장
  domain/
    models.py                     # status, user patch 모델 확장
    save_models.py                # cursor/query/candidate/trace domain DTO
    errors.py
  ingest/
    fetch.py                      # HttpSourceFetcher 추가 가능
    jobs.py                       # confirm/dedupe/cancel 상태
    service.py                    # 기존 admin compatibility
    worker.py                     # hook와 부분 저장 사용
    trace.py                      # trace builder/sanitizer
  storage/
    migrations/                   # versioned migrations
    migration.py                  # runner
    repositories.py              # 기존 + 부분 갱신
    save_repositories.py          # idempotency/fingerprint/candidate/trace
    tables.py
  save/
    service.py                    # command orchestration
    query.py                      # list/detail/cursor
    dedupe.py                     # URL normalize/fingerprint claim
    cursor.py                     # signed keyset cursor
```

핵심 service 포트:

```python
class ContentCommandService:
    def create(self, principal: Principal, request: CreateContent, idempotency_key: str) -> CreateResult: ...
    def patch(self, principal: Principal, content_id: str, patch: ContentPatch, etag: str | None) -> ContentDetail: ...
    def delete(self, principal: Principal, content_id: str) -> None: ...
    def reanalyze(self, principal: Principal, content_id: str, request: ReanalyzeRequest, idempotency_key: str) -> SubmitResult: ...
    def review(self, principal: Principal, content_id: str, request: ReviewRequest) -> ReviewResult: ...

class ContentQueryService:
    def get(self, principal: Principal, content_id: str) -> ContentDetail: ...
    def list(self, principal: Principal, query: ContentListQuery) -> ContentPage: ...

class JobQueryService:
    def get(self, principal: Principal, job_id: str, trace_level: TraceLevel) -> JobDetail: ...
```

동기 API service가 worker concrete class를 직접 호출하지 않는다. 테스트의 `run_inline`만 기존 IngestService를 통해 사용한다.

---

## 13. 작업 분할과 의존성

### 13.1 의존성 트리

```text
T27a migration + 비파괴 저장소 API + 새 테이블
 ├─ T27b auth adapter + 공통 DTO/error/router 골격 + bind/dev gate
 ├─ T27c idempotency + URL normalize/fingerprint + HttpSourceFetcher
 │    └─ T27d POST /contents + async hash dedupe
 └─ T27e detail/list + signed cursor

T27a, T27e ──> T27f PATCH/DELETE + index consistency
T27a, T27d ──> T27g confirm candidate/review + job 상태/trace API
T27f, T27g ──> T27h reanalyze 정식 API + E2E/회귀/운영 hardening
```

T27b, T27c, T27e는 T27a의 schema/interface가 고정된 뒤 파일 충돌이 없으면 병렬 가능하다. T27g는 worker/jobs를 고치므로 T27d와 같은 파일을 동시에 수정하지 않는다.

### 13.2 작업별 완료 조건

| ID | 내용 | 완료 조건과 필수 테스트 |
|---|---|---|
| T27a | migration runner, 새 컬럼/테이블/index, 부분 갱신 repository | 빈 DB와 기존 fixture DB 모두 최신 version. migration 두 번 실행 무변화. FK check/row count 통과. AI persist와 user patch 경쟁 테스트에서 user row 보존. 기존 T6/T22 테스트 통과. |
| T27b | `Authenticator`, dev header, Principal dependency, route 분리, loopback/dev gate | 기존 X-User-Id 정상/오류 유지. prod+dev_header 시작 실패. dev header로 external bind 실패. admin은 non-dev 404. 타 사용자 content/job 404 동일 body. |
| T27c | idempotency repository, URL normalizer v1, cursor secret 설정, 안전 HTTP fetcher | canonical JSON/key replay/충돌/concurrent reservation. URL fixture 표. DNS rebinding/redirect/private IP/oversize/timeout 테스트. 로그에 key/source 없음. |
| T27d | create service/route, URL·text·image, preflight/async dedupe | 세 source 202 E2E. 동일 key exact replay. 동일 URL same user 200 existing, other user 새 저장. hash race에서 canonical 하나. duplicate alias가 검색/목록에 없음. |
| T27e | detail와 보관함 list, filter/sort/keyset cursor | effective/user/AI layer 응답. 각 필터 경계, tie pagination 누락/중복 없음, cursor 변조·다른 user·필터 변경 422. 원본 서버가 내려가도 GET 성공. |
| T27f | PATCH/DELETE, revision/ETag, index 반영 | 요약 set/clear, tag 정규화/set/clear, nested detail tombstone/clear, invalid schema, hide/unhide 검색 반영. no-op revision 불변. stale If-Match 409. active worker와 delete 경쟁에서 resurrection 없음. |
| T27g | confirm 후보, approve/reject, job steps, trace artifact | auto confirm skipped. confirm은 I5 뒤 멈춤. approve I6~I8, reject AI 미반영. 같은 결정 멱등, 반대 결정 409. 단계 시간/재시도/error 실제 event와 일치. trace full 사용자 격리/삭제 cascade. |
| T27h | 정식 reanalyze, 호환 admin, 전체 회귀/문서 | snapshot 시작, user override 보존, 실패 시 이전 결과 복원, active conflict, mock/local 프로필 교체 smoke. 전체 pytest/ruff/mypy 통과. OpenAPI에 정식 route/error가 노출. |

### 13.3 구현 순서에서 지켜야 할 것

- T27a 전에는 정식 write route를 열지 않는다.
- 기존 `upsert(bundle)`는 seed/admin compatibility에만 남기고 정식 command에서 호출 금지 테스트를 둔다.
- 각 단계는 network 없는 mock 테스트를 기본으로 한다. HttpSourceFetcher 테스트는 local fake server와 resolver stub만 쓴다.
- 분석기 테스트는 mock이 필수이고, local은 설치되어 있을 때 smoke marker로만 실행한다.
- 트랙 B 제외 파일 변경이 필요해 보이면 구현을 멈추고 interface adapter로 우회한다.

---

## 14. 인수 기준

### 14.1 기능

- AC-S1 URL/text/image+ocr_text가 202로 접수되고 Content+Job이 한 transaction에 생긴다.
- AC-S2 create 응답 뒤 실제 job 단계가 I1~I8을 거쳐 ready가 되고 검색된다.
- AC-S3 GET detail은 effective 값과 AI/user 층, 저장 당시 snapshot을 정확히 반환한다.
- AC-S4 list는 filter/sort/cursor 계약을 지키고 한 페이지 경계에서 누락·중복이 없다.
- AC-S5 PATCH 네 필드의 set/clear/no-op이 6.2절 유효값 규칙과 일치한다.
- AC-S6 hidden content는 검색에서 빠지고 보관함 `hidden=true|all`에서 조회된다.
- AC-S7 DELETE 뒤 DB child row와 index 결과가 모두 사라진다.
- AC-S8 reanalyze는 최신 snapshot을 쓰고 사용자 수정과 이전 성공 결과를 보존한다.
- AC-S9 confirm 후보는 승인 전 effective 값이 아니며 승인 뒤에만 반영된다. 거절 뒤 snapshot은 남는다.
- AC-S10 job 응답의 단계/시간/오류/attempt가 event와 일치하고 가짜 진행률이 없다.

### 14.2 멱등·중복·경쟁

- AC-S11 같은 idempotency key/request를 순차·동시 재전송해도 content/job이 하나다.
- AC-S12 같은 key의 다른 request는 409이며 원래 resource는 바뀌지 않는다.
- AC-S13 URL normalization fixture의 동치 URL은 같은 사용자 안에서 하나로 판정된다.
- AC-S14 다른 URL의 같은 본문과 동시 동일 본문은 hash canonical 하나로 귀결된다.
- AC-S15 다른 사용자의 동일 URL/hash는 각각 저장되고 id가 노출되지 않는다.
- AC-S16 PATCH와 I6, approve와 PATCH, delete와 stale worker 경쟁에서 사용자 수정 손실이나 content 부활이 없다.

### 14.3 보존과 trace

- AC-S17 원본 URL이 404/삭제/네트워크 단절이어도 기존 snapshot/summary로 GET/search가 된다.
- AC-S18 재분석 성공/실패 모두 user summary/tag/detail patch/hidden tags/is_hidden을 바꾸지 않는다.
- AC-S19 trace에 입력 참조, 전처리, model/profile/prompt 식별자, 실제 출력, evidence, validator, event가 제공되는 만큼만 남는다.
- AC-S20 trace와 error/log 어디에도 숨은 chain-of-thought를 만들거나 표시하지 않는다.
- AC-S21 기본 운영 로그와 HTTP error에는 source text, OCR text, note, model raw output, idempotency key 원문이 없다.

### 14.4 보안·운영·호환

- AC-S22 모든 content/job/candidate/trace SQL이 user scope를 갖고 격리 위반 테스트가 0이다.
- AC-S23 dev header 인증으로 non-loopback bind가 불가능하고 admin route는 non-dev에서 404다.
- AC-S24 URL fetcher가 SSRF, redirect 우회, oversized/decompression 입력을 차단한다.
- AC-S25 기존 DB migration이 데이터 손실 없이 성공하고 재실행이 멱등이다. 구 schema에서 바로 API를 띄우면 자동/수동 정책에 따라 upgrade 또는 명확한 시작 실패다.
- AC-S26 기존 search, index, ingest T18~T24, mock eval 테스트 결과가 변하지 않는다.
- AC-S27 analyzer mock/local 교체가 저장 API 계약과 DB schema를 바꾸지 않는다.
- AC-S28 OpenAPI가 request union, response, 200/202/204/4xx 계약을 포함하고 runtime 응답과 일치한다.

---

## 15. 필수 회귀 사례

다음은 별도 이름이 있는 통합 테스트로 남긴다.

1. `retry_same_create_key_returns_original_202`
2. `same_key_different_text_is_409_without_second_content`
3. `tracking_url_and_canonical_url_dedupe_per_user_only`
4. `different_urls_same_extracted_hash_end_at_one_canonical`
5. `original_404_does_not_remove_snapshot_or_summary`
6. `user_summary_wins_after_successful_reanalysis`
7. `user_detail_tombstone_survives_new_ai_json`
8. `hidden_ai_tag_does_not_reappear_after_reanalysis`
9. `confirm_candidate_is_not_indexed_before_approve`
10. `reject_keeps_snapshot_and_reduced_search`
11. `double_approve_is_idempotent_and_approve_then_reject_conflicts`
12. `other_user_content_job_candidate_trace_all_404`
13. `cursor_cannot_cross_user_or_filter_boundary`
14. `equal_saved_at_cursor_uses_id_tiebreaker`
15. `hide_removes_search_hit_and_unhide_restores_it`
16. `delete_during_analyze_cannot_resurrect_content`
17. `reanalyze_failure_restores_previous_ready_analysis`
18. `migration_from_pre_t27_db_preserves_counts_and_search`
19. `prod_rejects_dev_header_auth_at_startup`
20. `dev_header_rejects_external_bind_even_with_override`
21. `trace_omits_unavailable_scores_and_contains_no_fake_progress`
22. `error_and_logs_do_not_contain_source_fixture_or_note`

---

## 16. 열린 질문과 PM 추천 기본값

| # | 열린 질문 | PM 추천 기본값 |
|---|---|---|
| Q1 | 실제 인증은 무엇으로 할까? | 이번 범위는 `Authenticator`만 두고 dev/test의 `X-User-Id` 어댑터를 사용한다. prod는 시작 실패. 제품 인증 선택 뒤 OIDC/session adapter를 별도 설계한다. |
| Q2 | 같은 URL을 나중에 다시 저장하면 새 snapshot으로 갱신할까? | 기존 content를 200으로 반환하고 묵시 갱신하지 않는다. 명시적 refresh-source API는 후속 작업. |
| Q3 | confirm 거절 시 저장물도 삭제할까? | 삭제하지 않는다. snapshot/note는 보존하고 `analysis_rejected`+축약 검색으로 둔다. DELETE는 사용자가 따로 선택한다. |
| Q4 | image source에서 실제 파일을 받을까? | MVP는 `ocr_text` 필수와 선택 메타만 받는다. binary upload/object storage/EXIF 제거는 별도 범위. |
| Q5 | trace full을 얼마나 오래 보관할까? | 콘텐츠 수명과 동일하게 보관하고 DELETE cascade. 실제 멀티테넌트 출시 전 암호화/축소 정책 재검토. |
| Q6 | idempotency key 보존 기간은? | 24시간. terminal response만 저장하고 백그라운드 정리. |
| Q7 | DELETE를 휴지통으로 할까? | MVP는 hard delete. 복구 요구가 생기면 별도 soft-delete migration. |
| Q8 | 대표 태그 전체 교체 뒤 새 AI 태그가 추가되어도 될까? | 기존 6.2절 규칙 유지: 사용자/숨김 이름은 보호하되 재분석의 새로운 AI 태그는 추가 가능. 완전 lock은 후속 옵션. |
| Q9 | 목록에 전체 count가 필요한가? | MVP는 제공하지 않는다. keyset page의 `has_more`만 제공한다. |
| Q10 | dev header로 외부 bind를 예외 허용할까? | 허용하지 않는다. 실제 auth adapter가 생긴 뒤에만 외부 bind를 연다. |
| Q11 | 과거 DB의 기존 중복 row를 자동 병합할까? | 자동 병합하지 않는다. migration report만 만들고 신규 요청부터 fingerprint를 강제한다. |
| Q12 | URL fetch가 로그인/봇 차단에 걸리면 우회할까? | 우회하지 않는다. 명확한 permanent failure code와 원본 snapshot 부재 상태를 보여 준다. |

위 기본값으로 구현을 시작해도 API나 데이터 손실 위험이 없다. Q1과 Q4가 바뀌면 별도 보안/스토리지 설계가 필요하므로 T27 범위에 묵시적으로 포함하지 않는다.

---

## 17. 다음 워커 전달 요약

Codex-Primary는 T27a부터 시작한다. 첫 구현의 핵심은 route가 아니라 migration과 비파괴 저장소다. 기존 `upsert(bundle)`를 정식 PATCH/I6에서 재사용하지 말고 AI 층과 사용자 층을 분리해 갱신한다. 이후 auth dependency, idempotency/fingerprint, create/list/patch, confirm/trace 순으로 올린다.

분석기는 mock/local 어느 쪽이든 같은 frozen port로 호출한다. 1.3절 제외 파일은 건드리지 않는다. 검색 코드는 수정하지 않고 기존 IndexingService와 revision refresh 공개 인터페이스만 사용한다.
