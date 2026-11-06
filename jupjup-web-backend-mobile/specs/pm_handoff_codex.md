# PM 인수인계: Claude PM → Codex PM (2026-11-04)

사용자 지시: "너의 역할과 임무를 전부 다 코덱스 워커를 하나 새로 파서 옮겨". 사유는 Claude 주간 사용량 98%다. 이 문서를 받은 Codex 세션이 이제 **Orca PM(메인 오케스트레이터)**이다.


> **사용자 최신 변경 (2026-11-05):** 이번 유튜브 수집·요약 수정은 기존 80% 자동 중단 규칙을 해제하고 Codex 5시간 사용량 100%까지 진행하도록 승인했다. 리셋을 기다리지 않는다. 워커는 동시에 한 명만 유지하고, PM이 계속 지시하며 컨텍스트가 커지면 인계를 남기고 교체한다. 외부 LLM 금지·로컬 처리·품질 기준 유지 등 나머지 규칙은 그대로다.

> **최근 반영 (2026-11-05):** 프론트 통합 및 YouTube 수집 검증 뒤, 사용자가 제목·설명만으로 분류하도록 추가 승인했다. 이제 `youtube_metadata` 전용 스키마/로컬 규칙 경로를 사용한다. 정상 자막 우선과 별도로 명시적 제목·설명 요청이 가능하며 영상 전체 요약으로 표시하지 않는다. 현재 C++ 강의 항목에 실제 설명 131자와 기술/C++·프로그래밍·강의/공부자료 제안이 준비되어 `awaiting_confirmation`이다. 사용자 원문·수동 수정은 보존했다. 현재 상태/배포/인수는 `specs/phase2_youtube_metadata_report.md`, 설계는 `specs/design_youtube_metadata_classification.md`를 우선 참고한다.

> **최근 컬렉션 반영 (2026-11-05):** 수동 컬렉션 CRUD·이름/색상·다중 소속·페이지 조회·프론트 연결을 v29로 배포했다. 컬렉션 삭제는 콘텐츠를 보존한다. 색상 UI 누락을 수정한 2차 검수 100점 PASS, 실제 API·브라우저 검사 및 DB 기존 데이터 보존 확인 완료. 실행 워크트리의 별도 자동 적용 프론트 수정은 23ca0a0으로 보존·통합했으며 최신 UI는 후보를 자동 적용하는 동작을 유지한다. 현재 인수/배포/백업/실행 핸들은 `specs/phase2_collections_report.md`, 설계는 `specs/design_collections.md`를 우선 참고한다. 기존 유튜브 '승인 대기' 기록은 당시 상태로, 현재 사용자 상태를 재조회해야 한다.

> **사용자 최신 저장 파이프라인 지시 (2026-11-05):** 실제 로컬 LLM으로 요약과 태그를 생성하고, 그 분류 결과를 바탕으로 컬렉션에 자동 저장하도록 명시 승인했다. 기존 mock 유지·규칙 전용 metadata 분류 보류 방침은 이 요청에 대해 변경한다. 유효 원문/제목·설명 근거와 품질 검증은 유지하며, 실패를 mock 성공으로 대체하지 않는다. 실제 영상 전체와 제목·설명 범위를 구분하고 사용자 원문·수동 수정·컬렉션 소속은 보존한다. 서비스에는 실제 의미 임베딩도 연결해 검색까지 검증한다.

## 1. 역할 (CLAUDE.md를 그대로 따른다)
- 사용자와 **친근하고 다정한 한국어**로만 대화한다. 영어로 답하지 않는다. 사용자가 지적한 적이 있다.
- PM은 코드를 직접 구현하지 않는다. 작업을 나눠 워커에게 맡기고, 병합과 보고를 맡는다.
- 워커 역할 지침은 `.claude/agents/`에 있다: claude-architect, codex-primary, codex-refactor, claude-reviewer.
  - 당분간 **모든 워커는 Codex로 띄운다.** Claude 한도가 98%라서다.
  - 검수자도 Codex가 "Claude-Reviewer 역할 대행"으로 맡는다.
- 워커를 띄울 때마다 새 Orca 워크트리를 만든다.
  - 이름: `phase-<번호>-<작업>`, kebab-case
  - 베이스: PM 브랜치. 만들기 전에 PM 브랜치가 커밋된 상태인지 확인한다.
- 루프: 구현 → 병합·검증 → 검수(0~100점, 90점 이상 PASS) → REJECT면 수정. 최대 3회까지 돌고, 3회째도 REJECT면 사용자에게 묻는다.
- 응답 끝마다 상태 로그를 붙인다. 항목은 Current Loop, Active Worker, Worker Output Summary, PM's Note, Next Routing이다.
- **push 금지.** 커밋 메시지 끝에는 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`을 붙인다.

## 2. 절대 규칙
- 원문은 기기 밖으로 나가지 않는다. 외부 LLM API는 쓰지 않는다. 분석은 로컬 모델만 쓴다.
  - 예외는 하나다: Hugging Face 공식 저장소에서 모델 가중치를 받는 것. 이때 sha256을 확인한다.
- 품질 기준과 기준선은 낮추지 않는다. test 분할로 튜닝하지 않는다. test는 설정을 동결한 뒤 1회만 돌린다.
- 검색 순위 로직(`src/jupjup/search`, `query`)과 `data/recordings/embeddings`는 바꾸지 않는다. 모델 가중치는 커밋하지 않는다. 캐시는 `/Users/minjun/orca/workspaces/dc2/models`다.
- 데모와 API는 루프백(127.0.0.1)에만 바인드한다.

## 3. Codex 사용량 절약 (사용자: "이번 리셋이 마지막이야 무조건 아껴써야해")
- 모델 등급은 PM이 고른다. 사용자 전역 기본값인 `gpt-5.6-sol high`는 쓰지 않는다.
  - light: `gpt-6-luna` medium. 녹화, 측정, 소규모 정리, 검수
  - standard: `gpt-6.1-sol` medium. 구현, 설계
  - heavy: `gpt-6.1-sol` high. 꼭 필요할 때만
- 한 번에 한 작업만 돌린다. 새 작업은 사용자에게 필요성을 짧게 확인한 뒤에 시작한다.
- **일일(5시간 창) 사용량이 80%를 넘으면 자동 중단한다.** 감시는 `var/orca/codex_guard.sh`가 한다.
  - 판정 기준은 워커 화면의 `5h limit: N% left · resets at ...`이다.
  - 사용량 스크립트 `.claude/scripts/codex_usage.sh`는 값이 늦게 갱신될 때가 있다.
  - 5시간 창이 리셋되면 하던 작업만 이어서 재개한다.
- 긴 측정은 GPU 스크립트로 돌린다. 에이전트가 기다리면서 짧은 간격으로 확인하지 않게 한다.

## 4. 자동 진행 도구 (`var/orca/`, git 추적 안 함)
- `autopilot_d.sh`는 구현 → 병합(`merge_verify`: pytest, 검색 eval 4종, ingest mock) → Codex 검수 → REJECT면 수정 루프를 돈다.
  - 필수 env: `TAG NAME BR REP TESTS OUT DOCS`
  - 선택 env: `H`(기존 터미널), `BRIEF`(새 워크트리 브리프), `TIER`, `REVIEW_TIER`(light, standard, heavy), `SKIP_IMPL=1`(이미 병합됨, 검수부터)
  - 로그: `var/autopilot.log`
  - 예시는 `run_save_fix.sh`, `run_t25t_attach.sh`
- `codex_guard.sh`는 일일 80% 감시용이다. 새 작업을 돌릴 때 함께 띄운다: `bash var/orca/codex_guard.sh &`
- macOS bash 3.2에서는 `source <(...)`가 안 된다. `eval "$(...)"`을 쓴다. 브랜치명에는 `ultra-penguin/` 접두사가 붙는다.

## 5. 현재 상태 (2026-11-04 20시 기준, PM 브랜치 `990d38e`)
- 완료, 모두 PASS:
  - 검색 엔진: 하이브리드 BM25F + bge-m3 + RRF, 완화 정책
  - 검색 API
  - 인제스트 파이프라인 T18~T24
  - 로컬 분석기 기반 T25a~g, T26a
  - 정식 저장 코어: 설계 `specs/design_save_api.md`, 95점 PASS 뒤 시각 정규화 후속 수정이 100점
  - 검색 데모의 "검색 과정" 패널(98점): http://127.0.0.1:8780, live 모드
  - 검색 파이프라인 보고서 PDF: `reports/jupjup_search_pipeline_report.pdf`
- 최근 결과: T25t 튜닝(100점 PASS, `specs/phase2_t25t_tuning_report.md`)
  - 네 모델(Kanana-2B, Qwen3-4B, Qwen2.5-7B, Kanana-8B) **모두 품질 기준 미달**이다.
  - 가장 나은 Qwen2.5-7B: 최종 형식 0.90, 첫 형식 0.77, 태그 F1 0.52, 카테고리 0.60, 핵심 사실 0.26, 비충실 0.13
  - 그래서 기본값은 mock을 유지하고, 실제 모델 채택은 보류한다.
  - 최종 linkage·벤치는 디스크 중단으로 측정하지 못했다.
- **사용자 결정 대기.** PM이 낸 선택지는 아래 넷이고, 추천은 1번 다음 2번이다.
  1. 골든셋 검수부터 한다. 사용자가 다음 두 파일을 채운다.
     - `data/golden/ingest/sample_for_user.jsonl` 24건 검수
     - `data/golden/ingest/judge_labels.dev.jsonl` 160행 라벨
  2. 분석 구조를 바꾼다(설계 → 구현). 카테고리와 태그는 임베딩과 규칙으로 정하고, 요약은 원문에서 근거 문장을 먼저 뽑은 뒤 쓴다.
  3. 기준을 다시 정한다. 사용자만 결정할 수 있다.
  4. Instagram 데모를 지금 품질로 먼저 만든다. 화면에 "시험용"이라고 표시한다.
- 백로그: `specs/backlog_instagram_demo.md`
  - 원래 조건은 T25h 완료 뒤 승인 없이 진행하는 것이었다. 지금은 T25h가 품질 미달로 막혀 있으니 사용자와 상의한다.
  - 수집은 로그인 없는 공개 og 메타태그만 쓰고, 우회하지 않는다.
  - 화면에는 6개 묶음 "추론 과정"을 보여준다. 이것은 NLP 파이프라인이 실제로 처리한 과정이다.
- 그 밖에 남은 범위: 실제 로그인·인증, 이미지 업로드·OCR, 비전 분석, Reels 음성.

## 6. 사용자 성향
- 품질을 우선하고 차근차근 진행하는 걸 좋아한다. Phase마다 확인받는다.
- 진행 상황을 자주 묻는다("어디까지 됐어"). 표와 짧은 요약으로 답한다.
- 실제로 시작됐는지 화면으로 확인한 뒤에 보고한다. 과거에 시작이 조용히 실패한 일이 있었다.
- 사용자는 지금 프론트엔드를 따로 작업 중이다.
