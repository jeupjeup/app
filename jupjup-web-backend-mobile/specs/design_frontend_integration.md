# 프론트엔드 통합 설계

- 작성: 2026-11-05, Codex-Primary 단일 통합 워커 / Orca PM 감독
- 상태: 원본 import 완료, 구현 전 검토안. **이 문서의 연결 코드는 아직 구현하지 않았다. PM 후속 지시 후 착수한다.**
- 기준: `specs/prd_and_design.md` (5.9 검색, 5.10 인제스트, 6장 모델), `specs/design_save_api.md`. 두 기존 문서는 변경하지 않는다.
- 계약 판정: 위 설계의 과거 미구현 목록보다 현재 `src/jupjup/save/{routes,dto,query,service,patch,jobs}.py`, `api/{app,dto,errors}.py`, `auth.py`, `ingest/{fetch,extract,jobs,worker}.py` 구현을 우선한다.

## 1. 목표와 이번 단계의 경계

사용자가 만든 라우트, 카드, 레이아웃, CSS, 반응형 스타일을 유지하며 실제 보관함 목록·상세·저장·수정·삭제·재분석·자연어 검색을 기존 API에 연결한다. 필요한 로딩/오류/승인대기 표시는 기존 디자인 언어 안에서 추가한다. 샘플 타이머와 localStorage를 실제 서버 처리로 오인시키지 않는다.

이번 커밋까지는 원본 보존과 설계만 한다. API client, Store, 라우터, CSS, 백엔드 구현은 변경하지 않는다. 외부 전송/외부 LLM 호출, 서버 실행, 기존 데모 DB·포트 변경/종료, push는 하지 않는다. 단일 워커가 현재 워크트리에서만 작업하며 전역 모델 설정도 변경하지 않는다.

후속 구현에서도 분석기는 mock 기본을 유지한다. 검색 순위·질의 해석·품질 기준·프롬프트·튜닝은 범위 밖이다. `src/jupjup/search`, `src/jupjup/query`, `data/recordings/embeddings`를 수정하지 않는다. 실제 OAuth, 이미지 바이너리 업로드/OCR/비전, 영상·음성 전사, 컬렉션 서버 동기화는 별도 승인 범위다.

## 2. 원본 보존과 추적

- 원본은 `/Users/minjun/Documents/ChatGPT/줍줍프론트`이며 경로 탐색 시 NFC 정규화로 식별했다. 원본 디렉터리와 `.git`에 쓰기 작업을 하지 않았다.
- `frontend/`에 src, public, package/lock, index, tsconfig 3종, vite 설정, `.env.example`, `.gitignore`, `.oxlintrc.json`, README, PRODUCT를 그대로 복사했다.
- 78개 파일, 615,849 bytes. `src/assets/hero.png`는 앱의 원래 소스 자산이라 포함했다. 검수 스크린샷은 포함하지 않았다.
- `node_modules`, `dist`, `.git`, `.DS_Store`, 스크린샷, `.impeccable` 제외. 원본의 untracked 상태를 보존하며 원본에서 add/commit/install/build를 실행하지 않았다.
- `specs/frontend_import_manifest.json`에 각 파일의 상대 경로·크기·SHA-256을 기록했다. 복사 전/후 원본과 복사본 해시를 비교했다.
- 독립 import 커밋: `30d1f68` (`chore(frontend): preserve original frontend source import`). 이후 연결 변경은 반드시 별도 커밋이다. manifest는 import 시점의 동결 기준이며 연결 구현 후 해시로 덮어쓰지 않는다.

## 3. 현재 화면과 실제 계약의 차이

| 위치 | 현재 동작 | 후속 연결 방침 |
|---|---|---|
| `AppRouter.tsx` | `/dashboard`, `/contents`, `/contents/new`, `/contents/:contentId`, `/search`, 컬렉션·설정·인증·온보딩 라우트 | 경로/중첩 레이아웃 유지. 상세 직접 URL도 API로 조회 |
| `ArchiveStore.tsx` | seed 10건, localStorage 쓰기, 동기 save/update/delete, 2.6초 가짜 분석·결정적 가짜 실패 | 서버 콘텐츠 캐시/비동기 mutation으로 교체. API 실패 시 seed로 fallback 금지 |
| `NewContentPage.tsx` | URL/텍스트 두 모드, 동기 저장 성공 toast, `user-` id로 최근 항목 식별 | POST 접수 후 content/job 추적, pending 버튼, 서버 saved_at 기반 최근 목록. id prefix 가정 제거 |
| `ContentDetailPage.tsx` | title/대표·세부 태그/메모 수정, 자체 1.8초 재분석 샘플 생성, 즐겨찾기·컬렉션 | 지원 필드만 서버 PATCH. 자체 타이머/샘플 요약/수동 태그 보호용 별도 로컬 플래그 제거, 서버 사용자 층 사용 |
| `SearchResultsPage.tsx`, `archiveSearch.ts` | 별칭 substring 점수, 로컬 필터, 검색 후 날짜순 재정렬, 샘플 관련 콘텐츠 | `/v1/search` 결과 순위와 match_reasons 유지. 로컬 검색·임의 관련 추천으로 결과 보충 금지 |
| `HomeDashboardPage`, `ContentsPage` | Store 전체 배열로 수·분포·필터·정렬 계산 | 커서 페이지 조회로 변경. 전체 통계 API 부재를 명시하고 현재 불러온 범위 수치만 표시 |
| `client.ts`, `env.ts` | 기본 `/api`, 예시 `http://localhost:8000/api`, top-level message만 해석 | `/api` 개발 proxy → 백엔드 루트, 호출 path `/v1/...`. 중첩 error envelope·응답 헤더·204 처리 추가 |
| 인증·설정 | 존재하지 않는 OAuth 경로, Google 연결됨 데모 문구, 로컬 데이터 초기화 | 개발 사용자임을 명시. 실제 로그인/서버 초기화처럼 표시 금지 |

`features/jupjup-dashboard/DashboardApp.tsx`와 `public/jupjup-landing.html` 등 보존된 독립 데모도 실제 데이터 경로로 끼워 넣지 않는다. 현재 Router가 사용하는 archive 화면이 통합 대상이다. 랜딩의 정적 제품 미리보기는 예시임을 구분한다.

## 4. 연결 구조와 프론트 모듈 계약 (제안)

이미 설치 명세에 있는 React Query를 활용한다. 별도 UI 라이브러리를 추가하지 않는다.

```text
shared/api/client.ts          HTTP/헤더/에러/AbortSignal, JSON 및 204
shared/api/contracts.ts       실제 요청·응답 DTO, opaque id, 상태 union
shared/api/contents.ts        list/get/create/patch/delete/reanalyze/review
shared/api/search.ts          search/parse
shared/api/jobs.ts            getJob
features/archive/adapters.ts  DTO → 표시 모델 (목록/상세/검색 각각)
features/archive/queries.ts   query keys, cursor, mutation, job polling/invalidation
features/archive/ArchiveStore.tsx  기존 화면의 점진적 연결 facade + 로컬 UI 설정
```

제안 인터페이스 (아직 구현하지 않음):

```ts
listContents(params: ContentListParams, signal?: AbortSignal): Promise<ContentPage>
getContent(id: string, signal?: AbortSignal): Promise<{ data: ContentDetail | AliasDetail; etag: string | null }>
createContent(body: CreateContent, key: string): Promise<SubmitResponse>
patchContent(id: string, patch: ContentPatch, etag: string): Promise<{ data: ContentDetail; etag: string | null }>
deleteContent(id: string): Promise<void>
reanalyzeContent(id: string, body: ReanalyzeRequest, key: string): Promise<SubmitResponse>
reviewContent(id: string, candidateId: string, decision: 'approve' | 'reject'): Promise<ReviewResponse>
getJob(id: string, signal?: AbortSignal): Promise<JobDetail>
searchContents(body: SearchBody, signal?: AbortSignal): Promise<SearchResponse>
```

query key는 `['contents', userId, filters]`, `['content', userId, id]`, `['job', userId, jobId]`, `['search', userId, query, filters]`처럼 사용자·조건을 포함한다. 사용자 변경 시 요청 abort 및 캐시 제거. 서버 콘텐츠를 기존 `jupjup_archive_items_v1`에서 자동 수입하지 않는다. 선택적 샘플 미리보기를 남길 경우 명시적 별도 모드·캐시로 분리하며 API 모드에서는 실행되지 않아야 한다.

save/update/delete/retry는 Promise 기반으로 바꾸고 모든 호출부가 await·오류·중복 클릭을 처리한다. 쓰기 성공 전에 성공 toast/화면 닫기/입력 삭제를 하지 않는다. PATCH 후 상세/목록/검색을 invalidate하고, job 상태 변화·완료 후에도 같은 캐시를 갱신한다. 현재 없는 부분 필드를 `undefined`/미수신으로 유지하여 검색 카드의 정보 부족을 실제 false 값으로 캐시에 덮어쓰지 않는다.

## 5. API 표 (현재 구현)

모든 `/v1` 요청은 동일한 `X-User-Id`를 보낸다. API body에는 user_id를 넣지 않는다. 정식 API를 사용하고 admin API로 우회하지 않는다.

| 메서드·경로 | 요청 / 옵션 | 실제 응답과 화면 |
|---|---|---|
| GET `/healthz` | 인증 불필요 | 200/503 준비 상태. 저장/검색 성공 여부 대신 사용하지 않음 |
| GET `/v1/contents` | 반복 query `platform`, `content_type`, `status`, `tag`; `hidden=false\|true\|all`; `saved_from`, `saved_to`; `sort=saved_at\|updated_at`, `order=asc\|desc`, `limit=1..100`, `cursor` | 200 `{items,next_cursor,has_more}`. total 없음 |
| GET `/v1/contents/{id}` | opaque content id | 200 상세 또는 `{id,canonical_id,status:'duplicate',revision}` 별칭; ETag 헤더 |
| POST `/v1/contents` | `source:{kind:'url',url}` 또는 `{kind:'text',text}`; 선택 title/author/user_note, platform/content_type hint, `automation_level` | 신규 202 SubmitResponse; URL 중복 200, job_id null. Idempotency-Key 필수 |
| PATCH `/v1/contents/{id}` | summary, representative_tags, detail_tags, hidden만. `If-Match`에 상세 ETag | 200 갱신 상세+ETag. 제목·메모·favorite·collection·source 수정 불가 |
| DELETE `/v1/contents/{id}` | body 없음 | 204 hard delete, 복구 API 없음 |
| POST `/v1/contents/{id}:reanalyze` | `{}` 또는 `{automation_level:'auto'\|'confirm'}` + 새 동작용 Idempotency-Key | 202 새 job. 원본 재수집이 아니라 저장 snapshot에서 chunk 단계부터 |
| POST `/v1/contents/{id}:review` | `{candidate_id,decision:'approve'\|'reject'}` | 승인 202 queued, 거절 200 rejected. 같은 결정 재전송 허용, 반대 결정 409 |
| GET `/v1/jobs/{id}` | `trace=none\|summary\|full`, 기본 summary | 200 JobDetail, `Cache-Control: private, no-store`. id/current_stage/attempts/steps/error/candidate/result_content_id |
| POST `/v1/search` | `{query,limit,filters?:{platforms,content_types,saved_from,saved_to},explain?:false}` | 200 `{results,understanding,applied_relaxations,empty_state,degraded,...}`. HTTP 200 빈 배열도 정상 |
| POST `/v1/query:parse` | `{query}` | 200 understanding. 검색 전에 반드시 호출할 필요 없음 |

서버 DTO는 extra forbid다. 프론트 ArchiveItem 전체나 빈 문자열 날짜를 그대로 body에 보내지 않는다. image source는 `{kind:'image',ocr_text,image?:{mime_type,sha256}}` JSON만 받지만 이번 UI 통합에서는 URL/텍스트만 연결한다.

### 목록·검색 필터와 범위

- 목록 날짜는 `saved_from` 포함, `saved_to` 미포함이다. 날짜 UI는 Asia/Seoul 경계를 offset 포함 ISO로 변환한다. 원래 timestamp를 버리지 않고 날짜/시각은 표시할 때만 포맷한다.
- 목록 `new/old` → saved_at desc/asc. title 정렬은 API 미지원이므로 실제 모드에서 비활성화하고 이유를 표시한다. 한 페이지를 정렬하고 전체 정렬이라고 표시하지 않는다.
- 필터 변경 시 cursor를 버린다. cursor는 사용자/필터에 묶인 opaque token이다. has_more/next_cursor로만 다음 페이지를 읽고 id로 중복 렌더링을 방지한다.
- 검색 기본은 관련도 순이다. 현재 코드처럼 서버 결과를 날짜순으로 다시 정렬하지 않는다. 서버 검색에는 cursor/전체 count가 없다. 결과 수는 반환된 수이고 전체 보관함 수가 아니다.
- 검색 필터에 collection/status/favorite/tag 필드는 없다. 미지원 필터는 비활성화한다. 제한된 top-k 결과를 로컬 필터하고 전체 검색이라고 표시하지 않는다. 빈 질의는 전송하지 않고 입력 상태를 보여 준다.
- '최근 저장'·'오래된 자료' 홈 바로가기는 명시적 목록 날짜/정렬 조건으로 보낸다. 자연어 질의는 원문 그대로 서버 검색에 맡긴다. 클라이언트 별칭 사전/시간 해석을 추가하지 않는다.
- 응답 `match_reasons`로 근거를 표시한다. applied_relaxations/degraded/empty_state는 서버가 제공한 뜻대로 안내하고, 임의 유사 결과나 관련 컬렉션을 생성하지 않는다.

## 6. 필드·타입 변환

서버 DTO를 보존하고 기존 카드에 필요한 표시 모델만 파생한다. 프론트 기존 3개 분석 상태/4개 유형만으로 서버 원본 상태를 저장하지 않는다.

| 서버 필드 | 프론트 표시/쓰기 방침 |
|---|---|
| id / 검색 content_id | 카드 id, URL 라우트는 encodeURIComponent. `user-` prefix·Date.now id 제거 |
| title nullable | title → source URL → '제목 없는 콘텐츠' 표시 fallback. 서버 값을 조작해 저장하지 않음 |
| platform | instagram/youtube/kakaotalk/news/blog/x/web/local 유지 + 표시명 매핑. 모르는 값은 일반 아이콘 |
| content_type | post→post; video/short_video→video; article/paper/webpage→web; image/message는 독자 표시값 추가. source.kind=text일 때 메모 표시 가능하나 서버 타입과 분리 |
| 목록 summary / 상세 summary.effective | 유효 요약 표시. summary.ai/user/source를 별도 유지하여 사용자 요약을 'AI 요약'으로 오표시하지 않음 |
| representative_tags 목록 배열 / 상세 effective 배열 | primaryTags 표시. AI/user/hidden_ai 층 보존; PATCH는 사용자 편집 최종 태그 배열 (최대 15개) |
| detail_tags.effective JSON | 구조화 객체 보존. 표시용 chip을 topics/keywords 등에서 파생하되 역변환에 사용하지 않음 |
| snapshot.text / ocr_text | 저장된 원문 표시. 직접 텍스트를 userMemo(user_note)에 넣지 않음 |
| user_note | 저장 시 선택 메모(최대 2000). 조회 가능하나 현재 PATCH 불가이므로 상세 메모 읽기 전용 |
| source.url / 목록 source_url | null 허용. 원본 보기 링크는 http/https 검사, 자동 이미지/iframe 로드 금지 |
| source.original_status | available/deleted/unknown 구분. unknown을 available로 단정하지 않음 |
| 목록 original_available | deleted가 아닌지를 의미하므로 true만으로 현재 접근 보장 불가. 상세 상태를 우선 |
| saved_at/updated_at | offset 포함 timestamp 보존. 클라이언트 isoToday/lastSavedAt로 덮어쓰지 않음 |
| hidden | 사용자 숨김이며 favorite와 다른 기능. 숨김은 기본 목록/검색에서 제외 |
| analysis.latest_job_id | 상세 재진입·새로고침 시 잡 복원. 목록 row에는 job_id가 없으므로 처리 중 상세 조회로 확인 |
| relatedContentIds/art | 관련 추천 서버 API 없음. 임의 추천 비활성화. art는 로컬 장식 자산임을 구분 |

### 수정 의미

- 수정 가능한 요약 UI를 기존 상세 모달에 배치하고 `summary` PATCH를 보낸다. 문자열 길이는 1..1000. `summary:null`은 사용자 override 해제(기존 AI 값 복귀), 빈 문자열과 다르다.
- 대표 태그 `[]`는 현재 AI 태그까지 숨기는 명시적 빈 유효 목록, `null`은 사용자 태그/AI 숨김 해제다. 이후 재분석의 새로운 AI 태그는 추가될 수 있다. 완전 잠금이라고 약속하지 않는다.
- 세부 태그는 RFC 7396 형식의 객체 patch. 처음에는 편집 UI를 명확히 `topics` 편집으로 한정하고 기존 comma 입력을 이 배열에만 매핑한다(최대 10, 각 30자). 기존 JSON의 keywords/locations/entities 등은 보존한다. 합쳐 표시한 chip 전체를 topics로 재저장하지 않는다. 구조 필드 편집 확대는 후속 단계다.
- `detail_tags:null`은 사용자 patch 전체 해제, 중첩 null은 AI 필드 삭제 tombstone이다. schema_version은 수정 불가. hidden은 boolean만 허용한다.
- 누락 필드는 무변경이다. 필요한 필드만 전송한다. title/user_note 편집은 읽기 전용 안내로 전환하고, API 확장은 PM에 별도 제안한다.
- 상세 ETag를 그대로 If-Match로 보내며 VERSION_CONFLICT는 새 상세를 받아 사용자에게 차이를 확인시킨다. 무조건 자동 덮어쓰기 금지.

## 7. 상태와 비동기 작업

| 콘텐츠 원상태 | 표시와 행동 |
|---|---|
| pending | 저장 접수/분석 중, latest job 조회. 실패·승인대기 판단은 job도 함께 확인 |
| awaiting_confirmation | '적용 확인 대기', 분석 중과 구분. 후보는 별도 패널이며 effective 요약으로 합치지 않음 |
| ready | 정리 완료. 재분석 중에는 이전 결과를 보존하고 진행 상태를 별도 표시 |
| analysis_failed | 실패 원인·snapshot 유무 표시. snapshot 없으면 재분석 불가 |
| analysis_rejected | '제안 미적용', 실패로 묶지 않음. snapshot 유지 |
| duplicate | canonical_id 조회/상세 대체. 임시 별칭 카드 제거 |

job active는 queued/running/retry_wait/awaiting_confirmation, terminal은 succeeded/failed/needs_review/rejected/deduplicated/cancelled다. needs_review는 사용자가 고른 confirm 승인대기와 다르므로 자동 승인 버튼을 붙이지 않는다. analysis_pending은 축약 인덱스 여부의 성격이 있어 완료/실패 판정에 단독 사용하지 않는다. 재분석 실패 후 콘텐츠가 이전 ready로 복구되어도 최신 job 실패는 별도 안내한다.

### Polling

- POST 202는 접수 완료이지 분석 완료가 아니다. content_id/job_id를 받고 상세·최근 목록을 갱신한다.
- GET job은 화면 활성 중 약 1초에서 시작해 2/5초까지 늘린다. 네트워크 오류에는 제한된 backoff와 '연결 끊김/다시 확인'을 제공한다. 시간 초과를 서버 분석 실패로 바꾸지 않는다.
- 현재 query 기본 staleTime=30초를 job에 적용하지 않는다. 같은 job polling은 한 query로 공유하고 화면 이탈/숨김 시 중단, 복귀 시 재조회한다. AbortSignal은 HTTP 조회만 멈춘다.
- awaiting_confirmation에서는 빠른 polling을 멈추고 후보 GET 상세를 표시한다. approve 후 queued부터 재개, reject 후 snapshot/유효값 재조회. 다른 탭의 결정은 포커스 복귀 또는 명시 새로고침으로 반영한다.
- terminal에서 polling 중단, 상세/목록/검색 invalidate. deduplicated면 result_content_id로 이동하며 기존 canonical을 수정하지 않는다.
- steps/current_stage/attempts/next_run_at/error만 사실대로 표시한다. 8단계 균등 퍼센트·고정 완료 시간·가짜 사고 과정은 만들지 않는다. trace full은 명시적 상세 보기에서만 로컬 API로 읽고 analytics/외부 로그에 보내지 않는다.
- queued 장기 지속은 워커 미실행 가능성으로 안내한다. API 프로세스는 잡을 실행하지 않으므로 별도 worker가 필수다.

### Retry / cancel / delete

- 자동 재시도는 서버 RetryPolicy 책임이다. retry_wait의 next_run_at을 안내하며 프론트가 추가 재분석 job을 만들지 않는다.
- 수동 '재분석'은 새 idempotency key로 `:reanalyze` 호출한다. 저장 snapshot에서 chunk부터 처리하며 원본 URL을 새로 읽지 않는다. active면 CONTENT_BUSY, snapshot 없으면 INVALID_CONTENT_STATE다.
- fetch 실패로 snapshot이 없는 URL을 같은 URL로 재저장하면 기존 중복만 반환될 수 있다. 현 API에 source refresh/실패 잡 재접수 API가 없으므로 자동 복구처럼 표시하지 않는다. 텍스트 직접 저장을 안내하거나 사용자가 명시적으로 삭제 후 새로 저장하는 별도 동작만 제공한다.
- **공개 job cancel/retry 엔드포인트는 없다.** cancelled 상태 enum은 취소 API의 존재를 뜻하지 않는다. '분석만 취소' 버튼은 비활성화하고 후속 API 요구로 남긴다. 화면 이탈/AbortController를 서버 취소 성공으로 알리지 않는다.
- DELETE는 콘텐츠/잡/후보/trace를 제거하는 hard delete다. 삭제 확인과 성공 후 캐시 제거, 204 처리, 해당 polling 중단을 한다. 로컬 목록에서 먼저 지운 뒤 실패를 숨기지 않는다.
- 기존 '실행 취소'는 복구 가능한 undo가 아니다. 실제 모드에서는 '저장 항목 삭제'라는 명시 동작으로만 제공한다. 중복으로 반환된 기존 콘텐츠에는 자동 undo/delete를 붙이지 않는다.

## 8. Duplicate와 idempotency

- 생성과 재분석마다 UUID 키 하나를 만들고 같은 사용자·동작·동일 body의 네트워크 재전송에 그대로 재사용한다. 재클릭/timeout으로 새 키를 발급하지 않는다. body 변경이나 명시 새 작업에만 새 키다. mutation 자동 retry는 기본 off, 재전송 UI는 동일 키를 보유한다.
- 보존기간은 현재 서버 구현의 24시간이다. 이후에는 멱등 재생을 보장하지 않으므로 자동 재전송하지 않는다. 새로고침 복구가 필요하면 사용자·작업·키·받은 id 같은 최소 메타만 보관하고 원문 body를 localStorage/로그에 새로 저장하지 않는다. 응답 유실 상태는 목록을 확인하고 사용자가 동일 입력을 다시 제출할 때 보유 키를 재사용한다.
- 동일 키/동일 요청은 최초 HTTP 상태와 payload를 재생하므로 replay 202의 status=queued가 현재 상태라는 뜻은 아니다. 반환된 job을 조회한다. `Idempotency-Replayed`는 부가 정보다.
- 동일 키/다른 요청은 IDEMPOTENCY_CONFLICT. 자동 새 키로 바꾸어 우회하지 않는다.
- URL preflight 중복은 200, job_id null, deduplicated true, duplicate_reason=normalized_url. '이미 저장됨'과 상세 보기만 제공한다. saved_at/메모/요약은 묵시 갱신하지 않는다. warnings의 user_note_not_applied도 안내한다. 기존 프론트의 '최근 저장 날짜 업데이트' 문구 제거.
- 비동기 본문 hash 중복은 job deduplicated, result_content_id가 canonical이다. 새 별칭을 실제 두 콘텐츠로 표시하지 않는다. URL 정규화/본문 hash 판정은 서버가 정본이며 클라이언트 정규화로 요청을 막지 않는다.
- 중복 판정은 사용자 범위다. 다른 사용자 콘텐츠를 합치거나 id를 공유하지 않는다.

## 9. 인증과 실행 경로

현재 실제 인증 구현은 dev_header뿐이다. 형식 `^u_[a-z0-9_]{1,64}$`의 개발 id(제안 `u_frontend_dev`)를 API/워커의 격리 DB와 함께 사용한다. 이 값은 보안 자격증명이 아니며 로그인 성공으로 표현하지 않는다. 제품 OAuth 토큰을 만들어 저장하거나 존재하지 않는 `/auth/oauth/*`로 이동하지 않는다. `/login`, `/signup`, `/auth/callback`은 스타일/경로를 보존하되 실제 모드에서는 '로컬 개발 사용자' 진입 안내와 미지원 설명으로 전환한다. 설정의 Google 연결됨/로그아웃 문구도 실제 상태에 맞춘다.

현재 백엔드에 CORS middleware가 없고 X-User-Id/Idempotency-Key/If-Match가 필요하다. 후속 구현은 Vite의 same-origin 개발 proxy를 우선한다. `VITE_API_BASE_URL=/api`, Vite `/api` → `http://127.0.0.1:8791` (prefix 제거)로 제안한다. API path `/v1/...`가 실제 `/v1/...`에 도달해야 하며 `/api/v1`을 백엔드에 보내면 안 된다. 프론트 host 127.0.0.1, 제안 포트 5177, strictPort=true. preview도 127.0.0.1로 한정한다. 현재 import된 .env.example은 원본이므로 이번에는 바꾸지 않았다.

포트 8791/5177은 예약된 사실이 아니라 후보다. 실행 직전 점유 상태를 읽고 사용 중이면 다른 미사용 포트를 정한다. 기존 8780 데모나 8000 API, 다른 개발 프로세스는 건드리지 않는다. 빌드 결과의 별도 운영 배포/정적 호스팅/운영 인증은 이 개발 proxy만으로 해결되지 않으며 별도 범위다.

## 10. URL 수집이 실제로 지원하는 범위

`design_save_api.md` 2.2의 'fixture만 있음'은 과거 설계 시점이다. 현재 container는 `HttpSourceFetcher`를 조립한다. 공개 http/https GET, 매 hop 공개 IP 검사, IP 고정 연결, 최대 redirect 3회, 기본 10초, 10 MiB 수신/해제 한도, 허용 MIME(html/plain/vtt/subrip/json)를 구현했다. 추출기는 별도로 입력 5,000,000 bytes 제한이 있으므로 fetch 성공도 추출 성공을 보장하지 않는다.

로그인/쿠키 우회·JS 실행·headless browser·영상 다운로드·YouTube 자막 자동 발견·Reels 음성 전사 기능은 없다. 플랫폼 아이콘과 URL 패턴 추정은 플랫폼 콘텐츠 획득을 보장하지 않는다. Instagram 등은 공개 응답에서 추출 가능한 텍스트/메타만 처리할 수 있고 봇 차단·로그인 벽·빈 본문 때문에 실패할 수 있다. og 태그만으로 완전한 본문/분석을 얻는다고 보장하지 않는다.

- 429/5xx·네트워크 등은 서버 재시도 대상일 수 있고, 접근 불가 4xx/지원 안 되는 MIME/차단 주소 등은 영구 실패로 분류된다. 실제 job error를 기준으로 안내한다.
- API DTO가 URL을 받는 것과 수집 성공은 별개다. 브라우저에서 원본 URL을 직접 fetch하여 CORS를 우회하거나 third-party proxy에 원문을 보내지 않는다.
- 저장 이후 GET과 재분석은 snapshot을 이용한다. 현재 원본 접근성을 GET마다 새로 검사하지 않는다.
- 이번 단계는 어떤 외부 URL도 요청하지 않는다. 후속 검증도 텍스트와 네트워크 stub/fixture를 기본으로 하며 실제 원문·콘텐츠 외부 전송 및 외부 LLM을 호출하지 않는다. 콘텐츠 분석용 외부 서비스/SDK/telemetry를 추가하지 않는다.

## 11. 백엔드 미지원 항목의 정직한 처리

| 항목 | 제안 기본 처리 | 별도 승인 시 논의할 것 |
|---|---|---|
| 컬렉션 CRUD/소속/자동 정리 | 화면은 보존하되 실제 모드에서 '서버 미지원'으로 조작 비활성화. seed 컬렉션과 실데이터 혼합 금지 | 스키마·API·동기화 별도 설계 |
| favorite | 실제 모드에서 비활성화/미지원 안내 | 서버 필드 추가 또는 명시적 기기 한정 보조설정. 이번에 몰래 구현하지 않음 |
| settings/온보딩 | 보기 방식·알림 표시·향후 저장 automation 기본값만 '이 브라우저 설정'으로 유지 가능 | 계정 설정 API 별도 |
| organizeMode | automatic→auto, confirm→confirm을 새 POST에 전달. 기존 콘텐츠 일괄 변경 아님 | 컬렉션 정리와 의미 분리 |
| confirm | 기본 설정이 confirm이므로 후보 표시·승인·거절을 연결해야 한다. 없으면 기본 흐름 완료 불가 | 이번 코어 통합의 필수 보완 UI |
| 알림 | 실제 job 전이만 화면 안 알림. 브라우저 설정으로 끄기 가능 | push/email 없음 |
| 데이터 초기화 | 실제 모드에서 샘플 resetDemo/전체 삭제 기능 차단. 로컬 보기 설정 초기화만 분리 | 사용자 전체 삭제·내보내기 API 별도 |
| 제목/기존 user_note 수정 | 읽기 전용 + 지원 안 됨 안내. 새 저장 시 title/user_note는 전송 가능 | PATCH 확장 별도 요청 |
| 이미지 업로드·OCR | 현재 NewContent는 URL/텍스트뿐. 이미지 업로드 가능한 척하는 입력 추가 금지 | 파일 저장·OCR·보안 별도 |
| 관련 콘텐츠·통계 | 추천처럼 샘플 채우지 않음. 통계는 조회 범위 표시 또는 미지원 | 추천/집계 API 별도 |
| 정렬 title/검색 collection·status | 비활성화 및 지원 범위 안내 | API 계약 확장 별도 |

## 12. 오류 변환과 복구

공통 `{error:{code,message,details}}`를 해석하는 `ApiError(status,code,message,details)`로 통일한다. 현재 client의 top-level message 파싱을 고친다. 네트워크/abort/HTTP 에러는 구분하고 HTML 에러/빈 응답에도 안전하게 동작한다. 서버 내부 stack·원문·OCR·idempotency key를 사용자 메시지나 console 로그로 출력하지 않는다.

| 오류 | 화면 동작 |
|---|---|
| 400 MISSING_USER / INVALID_USER | 개발 사용자 설정 안내. OAuth로 자동 redirect 금지 |
| 400 MISSING_IDEMPOTENCY_KEY / INVALID_IDEMPOTENCY_KEY | 요청 구성 오류 안내, 반복 전송 중지 |
| 404 NOT_FOUND | 존재하지 않거나 접근 불가인 상세/잡으로 동일 안내. 타 사용자 여부 추측 금지 |
| 409 VERSION_CONFLICT | 편집 draft 보존, 서버 상세 재조회 후 다시 확인 |
| 409 CONTENT_BUSY | 새 재분석 중복 제출 금지, 최신 job 조회 |
| 409 REVIEW_CONFLICT | 후보/최신 상세 재조회, 사용자의 명시 판단 |
| 409 INVALID_CONTENT_STATE | snapshot 부재/별칭 등 실제 상태 확인, 가능한 작업만 제안 |
| 409 IDEMPOTENCY_CONFLICT | 동일 키의 body 충돌 안내, 자동 키 교체 금지 |
| 422 INVALID_CONTENT / INVALID_PATCH / VALIDATION_ERROR | 입력 옆 검증 오류. DTO details가 dict/list인 경우 모두 처리 |
| 422 INVALID_CURSOR | 필터/사용자 확인 후 첫 페이지부터 갱신 |
| 검색 INVALID_QUERY / INVALID_FILTER | 검색 입력·지원 필터 안내, 보관함 데이터 소실처럼 표시 금지 |
| 503 STORAGE_UNAVAILABLE / INDEX_UNAVAILABLE 등 | 일시 오류 표시, 입력/캐시 보존, 명시 재시도. 빈 결과로 바꾸지 않음 |
| 500/비JSON/네트워크 | 요청 실패 표시. 쓰기 결과 불확실 시 같은 키로만 재확인 |
| AbortError | 화면 이탈의 조회 중단으로 처리. 서버 저장 취소 메시지 없음 |
| job.error | 이미 접수된 작업의 처리 오류. POST 실패나 저장물 삭제와 구분 |

IDEMPOTENCY_IN_PROGRESS 같은 과거 설계의 확장 코드가 오면 안전한 기본 오류로 처리하되, 현재 구현이 항상 반환한다고 가정한 흐름을 만들지 않는다. 응답에 알 수 없는 상태/필드가 오면 성공으로 강제 캐스팅하지 않고 상태 확인 필요로 표시한다.

## 13. 후속 구현·실행·검증 순서

PM이 다음 구현 범위를 지시한 뒤 아래 의존 순서로 단일 워커가 진행한다.

1. HTTP client/DTO/오류/응답 헤더·204/개발 사용자/127.0.0.1 proxy 설정. 기존 모든 API 호출과 OAuth 의존 경로를 점검한다.
2. 실제 목록·페이지·필터·상세 직접 진입·별칭 처리. Store의 seed/localStorage fallback을 실제 모드에서 제거한다. 로딩/빈 목록/서버 실패를 구분한다.
3. URL/텍스트 저장, 멱등키, 중복·warnings, 실제 job polling. 승인대기 UI와 review를 포함한다. 성공 toast 시점과 최근 콘텐츠 id 가정을 교정한다.
4. 지원 PATCH(요약/대표 태그/topics/숨김), ETag 충돌, hard delete, snapshot 재분석을 연결한다. 상세 자체 샘플 분석 타이머를 반드시 제거한다.
5. 자연어 검색 API/필터/근거/완화/빈 결과, 관련도 순위를 연결한다. 홈/다른 화면의 로컬 검색 진입점도 확인한다.
6. 미지원 버튼·설정·샘플 초기화·계정 문구를 정직하게 처리하고 화면별 데스크톱/모바일 상태를 확인한다. 화면 스타일 전면 재작성 금지.

후속 로컬 실행 예 (이번 단계에서는 실행하지 않음):

```sh
# 저장소 루트, 새 격리 DB. API/worker 환경을 일치시킨다.
JUPJUP_ENV=dev JUPJUP_MODE=mock JUPJUP_ANALYZER__ENGINE=mock uv run jupjup api serve --db var/frontend-integration.db --host 127.0.0.1 --port 8791
JUPJUP_ENV=dev JUPJUP_MODE=mock JUPJUP_ANALYZER__ENGINE=mock uv run jupjup worker run --db var/frontend-integration.db --concurrency 1
# frontend 디렉터리. proxy 변경 구현 이후 사용한다.
npm ci
npm run dev -- --host 127.0.0.1 --port 5177 --strictPort
```

DB 경로는 현재 워크트리 루트 기준으로 고정하고 기존 demo DB를 절대 재사용하지 않는다. 실행 전에 파일·포트 충돌을 확인한다. mock embedding 모드와 mock analyzer는 별도 설정임을 유지하며 실제 모델 품질 채택을 의미하지 않는다. 설치는 복사본에서만 한다. 설치/실행 중 원문 외부 전송·모델 다운로드·외부 LLM 호출을 추가하지 않는다.

검증 순서:

- import 단계: manifest 누락/추가/해시·크기 불일치 검사, 제외 파일 검사, frontend 원본 동일성 검사, git diff 범위 확인.
- 연결 이후: `npm run check`, `npm run build`. 원본 테스트 중 샘플 동작 가정은 통합 계약으로 수정하되 UI 동작 회귀를 숨기지 않는다.
- 의미 있는 adapter/client 테스트: nullable/unknown 상태·구조 태그 보존·204·중첩 오류·ETag·동일 키 재전송·query abort 및 오래된 응답 배제.
- mock 네트워크 없는 API 통합: 기존 `tests/integration/test_save_api.py`, `test_save_acceptance.py`, `test_save_time.py`, `test_api_search.py`, `test_api_ingest_worker_split.py`를 우선. 백엔드 변경 시 필요한 회귀만 확대한다. 평가 test split/기준선 튜닝은 하지 않는다.
- 격리 DB E2E: 빈 목록 → 텍스트 저장 → 실제 queued/worker 처리 → confirm 후보 승인 → ready → 상세 직접 새로고침 → 사용자 요약/태그 수정 → 재분석 후 사용자 층 보존 → 자연어 검색 → 숨김/삭제 후 검색 제외.
- 중복 URL·비동기 hash 중복·같은 키 replay/충돌·approve/reject 충돌·stale ETag·다른 사용자 404·워커 미실행·API 연결 끊김·snapshot 없는 실패·204 삭제를 확인한다. URL 실패/수집 검증은 resolver/transport stub·fixture로 실행해 실제 외부 호출을 피한다.
- API/프론트가 127.0.0.1만 listen하는지 확인하고 기존 데모의 포트/데이터/프로세스가 그대로인지 확인한다. 이번 단계에서 테스트 서버를 띄우지 않았으므로 실행 검증 완료라고 보고하지 않는다.

인수 조건은 화면 유지, 실제 API 쓰기·재조회 일치, 샘플 자동 fallback 0, 가짜 분석 완료 0, 미지원 기능의 성공 표시 0, 사용자 범위 캐시 격리, 처리 상태/중복/오류의 사실성이다.

## 14. PM 전달 및 미결 사항

- 원본 보존/import와 설계만 완료했다. 연결 구현·패키지 설치·빌드·서버 실행은 보류했다. 이번 단계 검증은 파일 보존/정적 계약 비교다.
- PM 확인 제안: 미지원 컬렉션/favorite/제목·메모 수정은 우선 비활성화, 로컬 보기 설정만 유지하는 위 기본안. 이를 지원하는 백엔드 확장은 자동 포함하지 않는다.
- confirm이 현재 프론트 기본 설정이므로 approval UI는 코어 연결 단계에 포함해야 한다. 분석만 취소/원본 refresh/실패 fetch 재시도는 공개 API 부재로 별도 설계가 필요하다.
- 다음 착수 단위 제안: 1~2번(클라이언트·개발 proxy·목록/상세)부터 PM 지시 후 진행. 이후 저장/polling/review, 편집/삭제/재분석, 검색 순으로 나눈다.
- 세션 사용량 재확인 시 5시간 창 41%, 리셋 11-05 13:32(스크립트 표시). 스크립트는 지연 가능하므로 워커 화면의 한도 표시가 우선이며 80% 초과 감지 시 새 작업을 중지하고 진행/잔여/커밋을 인계한다. 이번 작업에서는 모델 설정을 바꾸지 않았다.

## 15. 이번 단계 검증 결과

- import 파일 집합과 manifest 집합이 정확히 일치: 78개. 모든 원본/복사본/manifest SHA-256·크기 재검증 PASS.
- 금지 디렉터리·파일 미포함 검사 PASS. 현재 워크트리 및 상위 경로에서 적용할 추가 AGENTS.md 없음.
- 기존 backend/설계 파일 수정 없음. 원본 README/환경 예제의 아직 연결되지 않은 설정도 그대로 보존했다.
- import 이후 새 변경은 이 설계 문서 하나다. git whitespace 검사 완료. 빌드·테스트·서버 실행은 하지 않았으며 실행 가능한 통합 완료를 주장하지 않는다.
