# YouTube 제목·설명 분류 구현 보고

구현·PM 독립 검수·실행 서비스 반영 완료. 아래 최초 구현 인계와 PM 최종 실행 기록을 구분한다. 단일 Codex-Primary, 전용 새 워크트리 `phase-2-youtube-metadata-classification`에서만 수정했다. 설계: `specs/design_youtube_metadata_classification.md`.

## 구현·계약

- `ingest/youtube.py`, 신규 `ingest/youtube_metadata.py`: 공개 player `videoDetails.title/shortDescription`만 추출한다. og:description/전체 DOM/푸터는 사용하지 않는다. 제목 1,000자, 설명 20,000자와 잘림 표시, 줄바꿈·유니코드·링크·HTML 문자열을 텍스트 그대로 보존한다. 기존 공개 IP 고정/redirect/timeout/용량 제한을 재사용한다. 로그인·쿠키·우회·외부 서비스 없음.
- 일반 URL 저장은 정상 자막 우선, 없거나 빈 경우에만 metadata fallback. 명시적 `:reanalyze`의 `mode=youtube_metadata`는 내부 `SourceSpec.youtube_metadata_only=true`로 자막 요청 없이 메타데이터만 수집한다. default/snapshot 재분석은 기존 경로다. 차단·비공개·플레이어 없음·제목 없음은 실패 사유와 안전한 안내를 구분하고, 설명 없음/빈 설명은 title_only로 제한한다.
- 별도 `MetadataClassification`은 `source_scope=youtube_metadata`, 제목/설명 범위, 실제 설명·출처·잘림·분류 근거를 담는다. 최소 태그 수/요약을 요구하지 않는다. 로컬 단어 규칙으로만 분류하고 충분한 단서가 없으면 other/빈 태그. 실제 일치 문자열과 필드를 근거로 제공한다. 기존 AnalysisOutput/자막·본문 LLM 검증 기준은 유지했다.
- `ingest/{fetch,jobs,worker}.py`, `save/{service,dto,query}.py`, `storage/repositories.py`: 기존 소유권·idempotency·활성 잡 잠금·confirm·사용자 layer·실패 복구를 재사용한다. default 재분석의 기존 idempotency 해시도 유지한다. metadata 수집은 snapshot을 교체하지 않고 job artifact/analysis_runs에 저장한다. 확정 시 AI 태그·세부 태그만 적용하며 AI summary 행은 만들지 않는다. 기존 AI summary 행은 삭제하지 않고 계속 가린다. 사용자 summary/tags/detail patch/hidden_ai/메모와 기존 원문은 보존한다. DTO는 일반/metadata 후보를 별도 타입으로 명시한다.
- `index/service.py`: 확정 metadata를 인덱스 입력에만 투영한다. 제목·실제 설명·확정 태그·사용자 층을 사용하고 과거 watch 본문/AI 요약은 제외한다. embed/index, reload, rebuild, 사용자 수정에 같은 투영이 적용되며 투영을 원문 DB로 저장하지 않는다. 검색 순위 알고리즘은 변경하지 않았다.
- 프론트 `ContentDetailPage`, 신규 `MetadataResult`, API contracts/contents, ArchiveLayout/presentation/categories: 명시적 ‘제목·설명 가져오기/분류’, 실제 값·근거·접힌 설명·기술/기타 등 한국어 카테고리·‘YouTube 설명란’을 표시한다. fallback은 ‘자막 미확보’, 명시적 요청은 ‘자막 사용 안 함’이다. 배너는 영상 전체 AI 요약 미제공/로컬 규칙 분류/mock 고정 예시를 구분한다. CSS·모바일 레이아웃 변경 없음.

## 직접 검증

- 최종 backend **208 passed, 11.80초**. 대상: 신규 metadata unit/integration, youtube_source_repair, youtube_legacy_notice, ingest_pipeline, save_api, save_acceptance, api_ingest, api_ingest_worker_split, youtube_repair_tool, ingest_fetch_extract, ingest_jobs, integration/indexing, unit/index_document/storage.
- 정상 자막 유지, 빈 bytes/빈 events/공백 자막 fallback, title_only/other, 설명 없음/빈 설명, 차단/비공개, 악성 자막 URL/SSRF/redirect/용량 회귀, 설명 안 prompt/HTML/script·긴 텍스트/줄바꿈, 근거 문자열, 자막이 있는 player에서 명시적 metadata 모드의 요청 1회(자막 요청 0회)를 검증했다.
- 새 URL 저장/중복 반환, 기존 항목 실제 refresh, auto/confirm 승인·거절·승인 재요청, 서로 다른 요청의 동시 경합(202 하나/409 둘), idempotency 재전송, 사용자 수정 보존, persist 후 영구 실패에서 AI 복구·동시 사용자 summary 보존, 새 항목 검색 노출, index reload/사용자 수정의 안전한 입력을 검증했다.
- **실제 승인 URL** `https://www.youtube.com/watch?v=wpk7AM6FPRc` 공개 읽기: 제목 `[C++ 프로그래밍] 0. 강의 소개 - (1)`, 실제 설명 131자. 전북대 C++ 프로그래밍 강의, `github.com/diskhkme/cpp_lecture_material` 강의자료 링크, 윤성우 교재 안내가 있다. 기본 경로는 빈 자막→metadata, 명시적 경로는 자막 미요청→metadata였다. 분류는 **tech(기술)**, **C++·프로그래밍·강의**, 목적 **공부자료**다.
- 실제 응답 캡처를 격리 DB에 넣어 **auto 및 confirm→승인→persist→embed→index→reload**까지 완료했다. 설명 전체가 인덱스 입력과 일치하고 과거 잘못된 AI 요약은 제외됨을 assert했다. 캡처·결과는 git 제외 `var/metadata-validation/live{_explicit}_raw.json`, `live_result.json`; 재실행 테스트 `test_live_capture_in_isolated_db`는 캡처 없으면 skip한다. 이번 최종 실행은 skip 없이 통과했다.
- 최종 `npm --prefix frontend run check`: **8파일/29 tests 통과**, 기존 lint warning 6개 유지. `npm --prefix frontend run build`: **123 modules 성공**. 설명 접힘/펼침·HTML 안전 텍스트·제목만 정보 부족·한국어 표시·배너·서버 실패 후 동일 키 재시도·사용자 수정 보존을 포함한다.
- 변경 Python 소스/테스트 **ruff check 통과**, `mypy src/jupjup` **108 source files 통과**, `git diff --check` 통과.
- 초기 실패도 수정 후 재실행했다: metadata artifact 키 미등록으로 기존 chunk 회귀가 실패해 extract artifact 매핑 추가; 테스트의 존재하지 않는 stages/run_job 접근을 실제 worker bound runner/run_inline으로 교정; C++ 대소문자 기대값 수정. `python` 미설치, npm을 루트에서 실행한 ENOENT, 존재하지 않는 indexing 테스트 경로도 실제 Python/프론트 prefix/`tests/integration/test_indexing.py`로 교정했다. 미리보기 스크립트의 tests import 경로 오류는 PYTHONPATH 보정 후 종료했다.

## PM 배포·기존 항목 실행

1. 커밋을 PM에 병합·검수한 뒤, 실제 실행 소스인 `phase-2-frontend-integration`에도 동일 코드를 반영한다. 현재 API/worker/frontend가 새 코드를 사용하도록 PM이 배포한다. 새 DB 마이그레이션은 없다. 기존 runtime 핸들은 PM `var/orca/youtube_runtime.json`을 따른다.
2. 사용자 `u_frontend_dev`로 항목 `c_f7164cb29434443393406f5dc7e02fee` 상세를 열어 **제목·설명 가져오기/분류**를 실행한다. ‘확인 후 적용’ 설정이면 분류·근거·실제 설명을 확인한 뒤 제안 승인한다. 중복 URL POST는 여전히 기존 항목만 반환하므로 이 버튼/아래 refresh API를 사용한다.
3. API 대안(이 워커는 실항목에 호출하지 않음): `POST /v1/contents/c_f7164cb29434443393406f5dc7e02fee:reanalyze`, `X-User-Id: u_frontend_dev`, 새 `Idempotency-Key`, body `{"mode":"youtube_metadata","automation_level":"confirm"}`. `GET /v1/jobs/{job_id}`와 상세 `analysis.candidate` 확인 → 기존 `:review`에 `{"candidate_id":"...","decision":"approve"}` → job 완료 및 `analysis.metadata` 확인. 응답 불확실 시 같은 body/key로 재전송한다.
4. 거절은 기존 원문/사용자 층을 유지하고 제안 미적용 상태가 된다. 영구 worker 실패는 이전 AI 층·상태를 복구한다. 배포 코드 rollback 시 metadata 대기/승인 잡을 구버전 worker로 재개하지 않는다. 새 코드로 완료/거절을 정리하고 기존 백업·배포 절차를 따른다. 데이터 삭제/garbage 원문 복원은 필요 없다.

## 제한·범위

규칙 사전은 보수적인 초기 범위로, 전체 도메인 분류 품질을 보증하지 않는다. 기존 모델의 정식 품질 기준 통과나 모델 채택을 주장하지 않는다. 기본 mock·LLM 품질 기준·골든/test split·기준선·모델 가중치·검색/쿼리/embeddings 녹화본은 변경하지 않았다. 외부 LLM/추가 모델 다운로드/push/다른 워커 사용 없음.

실DB·실항목·원본 프론트 소스·8780·5177·8791 및 기존 worker를 변경/재시작하지 않았다. 격리 미리보기 준비 과정에서 127.0.0.1:8894가 잠시 기동됐으나 종료했으며 브라우저를 열지 않았다. 최종 브라우저·모바일 실화면 검증/실항목 실행/배포는 PM 담당이다.

## 커밋

- `9eaab7d` 짧은 설계
- `fd330e4` backend·안전한 분류/갱신·색인·회귀
- `4e37458` frontend 명시적 동작·출처·근거·회귀
- 한국어 분류/배너 후속 및 본 보고서 커밋은 이 브랜치 최신 로그 참조. 모든 커밋에 지정 Co-Authored-By 적용.

## PM 최종 반영·실항목 실행 (2026-11-05 21:25 KST)

- 독립 검수 97점 PASS, 검수 보고서 phase4_review_youtube-metadata_loop1.md. 구현·검수 커밋을 PM 및 실제 실행 worktree에 병합하고 전용 API/worker 재시작 완료.
- 브라우저에서 실제 기존 C++ 항목의 ‘제목·설명 가져오기/분류’를 실행했다. 공개 설명 131자와 기술/ C++·프로그래밍·강의 / 공부자료 제안이 반환됐다. 자막 요청을 하지 않는 명시적 metadata 경로다.
- 기존 ‘확인 후 적용’ 흐름을 유지해 현재 awaiting_confirmation이다. job `job_a6e6bf116e6d48b3a635fc14ff2607fe`, candidate `cand_job_a6e6bf116e6d48b3a635fc14ff2607fe`. 사용자 제안 승인 전이므로 실항목의 AI 층과 검색 인덱스에 새 분류를 확정 적용하지 않았다. 구현/격리 검증에서는 승인 이후 검색 반영까지 통과했다.
- 기존 snapshot·사용자 요약/태그/세부 patch·hidden AI·메모/URL/저장 시각/제목이 실행 전후 동일함을 DB 읽기 비교로 확인했다. 백업은 PM/var/backups/frontend-before-youtube-metadata-20261105-211750.db (Git 제외).
- 실제 브라우저에 분류 제안·기술 한국어 카테고리·근거·승인/거절 버튼 표시 확인. 실제 설명을 펼쳐 강의자료 GitHub 링크와 교재 안내를 확인했다.
- 반영 후 기존 실제 API/worker smoke도 저장/replay/충돌·승인·PATCH·사용자 격리·재분석/거절·검색·숨김·삭제 PASS. 테스트용 사용자 항목만 생성/정리했다.
- 현재 URL: http://127.0.0.1:5177/contents/c_f7164cb29434443393406f5dc7e02fee
- API handle term_4716aefd-211f-4993-947d-e78f5243d1eb, worker handle term_c49b651b-0deb-4030-9d45-3049cd40bcc8. 기존 Vite 유지. AI 구현/검수 워커는 종료.
