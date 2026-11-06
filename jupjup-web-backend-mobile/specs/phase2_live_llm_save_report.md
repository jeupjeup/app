# 실제 로컬 LLM 저장 구현 결과

단독 Codex-Primary, 지정 워크트리만 수정. 핵심 커밋 7661698, 실행 도구·UI·검증 c06ac73. 실제 DB/기존 API·worker/Vite/8780 서버는 변경·재시작하지 않았고 push하지 않았다.

- 정상 원문은 기존 LLMContentAnalyzer/검증/제한 재시도 유지. 빈 대표 태그·제공자 실패는 생성 성공으로 대체하지 않는다.
- YouTube 제목·설명도 실제 LLM summary/tags/category 생성. classifier=local-metadata-llm-v1, source_scope=youtube_metadata, 모델 지문 보존. 이전 규칙 결과 읽기 유지. 새 유효 accepted run의 요약만 상세/목록/검색에 사용한다.
- 고정 enum→한국어 컬렉션 매핑, 사용자별 같은 이름 재사용/생성, 멤버십 추가를 분석 확정 트랜잭션에 포함. UNIQUE/FK/충돌 처리로 경합·멱등·소유권·실패 롤백 보장. 수동 요약/태그/detail patch/메모/원문/수동 소속 보존.
- 기존 자동 적용 UI 유지. 실제 모델/원문 범위/자동 컬렉션 안내 추가. mock 평가 기본값과 config 프로필 해시, 검색 순위 코드·query·기존 embedding 녹화 데이터 불변. migration 추가 없음.

## 직접 실행

`specs/live_llm_save_validation.json`에 실제 결과 기록. 2026-11-05 UTC 13:46:42~13:47:01, 캡처된 공개 제목·설명 131자를 격리 SQLite의 실제 POST 저장→worker→확정→컬렉션→bge-m3→검색으로 실행. Kanana 2.1B GGUF는 프로필 sha256 검증 후 사용했다. 요약 생성, 태그 3개(c++프로그래밍/전북대학교컴퓨터공학부/강의소개), 학습·연구 컬렉션 생성, 검색 HTTP 200·1위·의미 유사도 0.71. 별도 작성한 C++ 원문도 요약·태그 5개·컬렉션 저장 성공. 실제 영상 자막을 확보했다고 주장하지 않는다.

실행 환경은 models/t25r-venv Python 3.12 + llama-cpp-python 0.3.36 Metal, PM/.venv 앱 의존성 경로를 재사용했다. bge-cache의 기존 BAAI/bge-m3 사용. offline 환경으로 다운로드/외부 LLM 없이 실행했다. 최초 실행은 결과 생성 후 종료 때 Metal native 정리 assert가 발생했다. 명시적 close를 넣은 재실행은 exit 0. 서비스 제공자에도 atexit 해제를 추가했다.

품질 한계: 실제 출력은 대학 학부 이름을 locations.level=country로 잘못 분류했다. 샘플 저장/연결 성공이며 기존 네 모델 품질 기준을 통과한 것이 아니다. 프롬프트/골든 split/품질 기준을 변경하거나 재튜닝하지 않았다.

## 검사

관련 pytest 156 passed / 2 skipped. 신규 11개: text/metadata auto·confirm 저장, 빈 태그/모델 실패/저장 중 실패 롤백, 컬렉션 동시 추가·소유권·멱등, 사용자 수정 보존. 기존 metadata/save/collections/analyzer/local-provider 회귀 포함. ruff 변경 Python 전체 통과, mypy src 113 files 통과. npm check 37 tests 통과, build 통과(기존 lint 경고 8개). 브라우저 실배포 검증은 PM에게 남겼다.

## 재현 및 PM 전환 명령

현재 워크트리에서 다음은 격리 DB를 생성·검증 후 정리한다. 결과 로그는 로컬 var에 저장하면 된다.

```bash
scripts/live_local.sh scripts/verify_live_local_save.py /Users/minjun/orca/workspaces/dc2/phase-2-youtube-metadata-classification/var/metadata-validation/live_explicit_raw.json
```

PM이 코드 통합·DB 백업·기존 핸들 확인 후 실행할 명령(여기서는 실행하지 않음):

```bash
JUPJUP_DB_PATH=/PM이_확인한_DB_절대경로 scripts/live_local.sh -m jupjup.cli api serve --host 127.0.0.1 --port 8791
JUPJUP_DB_PATH=/PM이_확인한_DB_절대경로 scripts/live_local.sh -m jupjup.cli worker run --concurrency 1
```

스크립트는 mode=live/engine=local/required=true/profile=local-kanana-2b를 함께 지정하여 mock 결합을 해제한다. bge-m3 캐시를 사용하고 새 임베딩 녹화는 해당 워크트리 var/live-recordings에만 쓴다. 모델 변경은 JUPJUP_ANALYZER__PROFILE로 명시한다. 두 프로세스의 DB·프로필은 같게 유지한다. Vite 원본/기존 서버 전환은 PM이 맡는다. 새 프론트 npm check/build 후 실제 저장 화면의 범위·오류·소속 표시를 실브라우저에서 확인해야 한다.
