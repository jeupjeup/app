# Phase 4 최종 검수: 검색 데모 과정 시각화, Loop 1/3

- **점수:** 98 / 100
- **상태:** PASS
- **항목별:** 정확성 39 / 40, 안전성 30 / 30, 유지보수성 29 / 30
- **루프백 대상:** 없음 (PASS). L1·L2는 다음에 trace 스키마나 테스트를 만질 때 함께 보완하면 된다.
- **검수 대상:** `4d0a385 feat: search demo "검색 과정" trace panel from SearchService explain` (기준 `e5f72b8`, PM 병합 `b57716e`)
- **검수자:** Claude-Reviewer 역할 대행 (Codex 실행). 구현 코드는 고치지 않았다. 검증 출력과 SQLite DB는 `/tmp`만 사용했다.
- **범위 밖:** 인제스트·분석기·검색 순위 로직 변경, 기준선 변경, `data/recordings` 수정. 사람 검수 미완료(`ai_draft_unreviewed`, `needs_human_review`) 자체는 감점하지 않았다.

## 0. 판정 요약

완료 조건을 모두 직접 재현했다. trace는 입력·전처리·모델 처리·분석 결과·근거·실행 로그의 6개 묶음과 단계별 시간으로 응답되며, 대표 질의 3개의 스키마·SearchService explain 값 일치·스냅숏 테스트가 통과한다. `demo serve`를 실제로 루프백에 띄워 `/demo/search`에 세 질의를 요청했고 strict 기간+플랫폼, `파스티 → 파스타` 교정, strict 결과 없음 뒤 `time_filter_dropped` 채택이 각각 응답과 스냅숏에서 같았다.

구현 보고서의 무회귀 주장은 별도로 교차 검증했다. 변경 전 `e5f72b8`을 detached worktree로 체크아웃하고 그 경로의 `jupjup`이 import됐음을 확인한 뒤, 골든 259질의를 mock·recorded로 다시 실행했다. `query_id`와 `timing_ms`만 제외한 정렬 JSON SHA-256은 현재 fixture와 **518/518 일치**했다. 변경 범위에도 `data/baselines`, `data/recordings`, `src/jupjup/ingest`, `src/jupjup/providers`, `src/jupjup/query` 수정은 없다.

기본 설치에는 `llama_cpp`가 없고, test split의 검색 mock·recorded와 인제스트 mock을 같은 프로세스에서 실행한 뒤에도 `llama_cpp`, `sentence_transformers`, `torch`가 import되지 않았다. mock·recorded 검색 서비스와 데모 경로에서 소켓 연결 함수를 차단한 탐침은 네트워크 시도 0회였다. 고·중 심각도 문제는 없다. 낮은 문제는 크로스 리랭커의 비활성 상태 표현 불일치(L1)와 값 일치 테스트가 일부 중첩 필드를 끝까지 봉인하지 않는 점(L2)이다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트와 평가

| 명령 | 직접 결과 |
|---|---|
| `uv run pytest` | 종료 0, **1333 passed, 5 deselected**, 경고 2건. 실패·skip 0 |
| `uv run pytest tests/integration/test_demo_trace.py tests/integration/test_demo.py -q` | 종료 0, **23 passed**. trace 신규 테스트 14개와 기존 데모 9개 통과 |
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run mypy src` | `Success: no issues found in 90 source files` |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259(dev 158/test 101), lexicon 139, 인제스트 80 검증 통과 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS. Recall@10 0.9620, MRR@10 0.9958, nDCG@10 0.9795, time exact 1.0, platform F1 1.0 |
| 같은 명령 `--split test` | PASS. Recall@10 0.9420, MRR@10 0.9867, nDCG@10 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS. Recall@10 0.9712, MRR@10 1.0000, nDCG@10 0.9860 |
| 같은 명령 `--split test` | PASS. Recall@10 0.9720, MRR@10 0.9911, nDCG@10 0.9801. 알려진 하한과 같은 값이며 이번 변경 회귀는 아님 |
| `git diff --check` | 출력 없음 |

### 1.2 trace 완료 조건

| 조건 | 직접 확인 | 판정 |
|---|---|---|
| trace 필드 스키마 | `DemoSearchTrace` 검증, 7개 최상위 키(6개 묶음 + `timing_ms`), 단계 1~9, 구성 요소 순서·임베더 모델/차원/모드, 기존 응답 필드 유지 테스트 통과 | 충족 |
| SearchService explain 값 일치 | 엔드포인트가 실제 받은 `SearchResult`를 spy로 잡아 대표 3질의의 입력·정규화·교정·토큰·필터·리트리버 순위/점수·RRF·재순위/게이트·완화·최종 결과·구성 요소 상태·degraded를 대조하는 테스트 통과 | 충족. L2 참고 |
| `explain=False` 바이트 무회귀 | 현재 테스트에서 mock·recorded 259질의 통과. 별도로 변경 전 `e5f72b8` 경로의 `jupjup`을 import해 다시 계산: mock 259/259, recorded 259/259, 불일치 0 | 충족 |
| `explain=True` 순위 무회귀 | 골든 앞 60질의에서 debug·비결정 필드를 제외한 응답과 결과가 explain=False와 동일 | 충족 |
| 대표 3질의 trace 스냅숏 | `period_platform.json`, `typo.json`, `empty_then_relaxed.json` 모두 통과. 시간 제외, 화면 핵심 값과 표 상위 10개 고정 | 충족 |
| 실제 `demo serve` 요청 | `/tmp` DB에 strict seed load 후 `127.0.0.1:18781`로 실행. 세 POST 모두 HTTP 200, 155,500 / 73,812 / 90,544바이트 | 충족 |

실제 서버 응답의 핵심 값은 다음과 같았다.

| 질의 | 실제 응답 |
|---|---|
| `지난달 인스타에서 본 성수동 카페` | 결과 3건, 1위 `c_alice_0001`, `strict`, 완화 없음 |
| `파스티 레시피` | `파스티 → 파스타`(spelling, 0.908333), 결과 10건, 1위 `c_alice_0041` |
| `지난주 유튜브 파스타 레시피` | strict 실패 뒤 `time_filter_dropped`, 결과 10건 전부 `relaxed=true`, 1위 `c_alice_0041` |

세 응답 모두 단계 번호 1~9, 8개 timing 키, 크로스 리랭커 구성 요소 `skipped:disabled`를 포함했다. 서버는 3회 요청 뒤 정상 종료했다.

### 1.3 결정성, 실제 모델 미실행, 기본 설치와 네트워크

| 확인 | 직접 결과 |
|---|---|
| mock 인제스트 결정성 | `eval ingest --mode mock --split dev`와 `--split test`를 각각 두 번 실행. 4회 모두 PASS, dev/test의 JSON·Markdown이 각각 `diff -rq` 무출력 및 SHA-256 동일 |
| mock·recorded 검색 결정성/무회귀 | 변경 전 코드 대 현재 fixture의 정렬 JSON SHA-256 518개 전부 동일. 제외 필드는 본래 무작위/실측인 `query_id`, `timing_ms`뿐 |
| test split 실제 모델 미실행 | 한 프로세스에서 검색 mock test, 검색 recorded test, 인제스트 mock test를 CLI로 실행해 모두 종료 0. 실행 전후 `llama_cpp`, `sentence_transformers`, `torch` 모두 `sys.modules`에 없음 |
| 기본 설치의 llama.cpp 격리 | `find_spec("llama_cpp") is None`; `import jupjup.cli` 뒤 `llama_cpp`, `jupjup.providers.llm_local`, `requests`, `urllib3`, `huggingface_hub` 미로딩 |
| 서비스 경로 네트워크 | `socket.create_connection`, `getaddrinfo`, `socket.connect`, `connect_ex`를 차단하고 mock·recorded의 직접 검색과 FastAPI 데모 요청 실행. 두 모드 모두 3건 반환, `network_attempts=0` |
| 범위 준수 | 기준 대비 변경은 demo/search trace 코드·테스트·fixture·보고서/캡처뿐. `data/baselines`, `data/recordings`, 인제스트·provider·query 변경 0 |

## 2. 피드백 (심각도 순, `파일:줄`)

고·중 심각도 문제는 없다.

### L1. 비활성 크로스 리랭커 상태가 같은 trace 안에서 두 값으로 표현된다 (낮음, 정확성)

- **위치:** `src/jupjup/search/service.py:222-226,360-367`, `src/jupjup/demo/app.py:573-583,623-631`, `tests/integration/test_demo_trace.py:97-101`.
- **직접 확인:** 대표 응답에서 `trace.model_processing.cross_reranker.status`는 `null`이지만, 같은 단계의 `components[].status`는 `skipped:disabled`이고 실행 로그는 `status="skipped", detail="disabled"`다. 화면 요약은 `enabled=false`를 보고 `disabled`라고 보정하므로 사용자 표시 자체는 맞다.
- **원인:** `pipeline.cross_reranker.status`는 실제 outcome만 보고 비활성일 때 `None`을 내보내지만, 구성 요소 블록은 별도 분기에서 `skipped:disabled`를 만든다. trace의 상세 cross 객체는 전자를, 실행 로그는 후자를 사용한다.
- **영향:** 순위·결과·화면 판정에는 영향이 없지만, trace를 기계적으로 읽는 소비자는 동일 단계의 상태를 다르게 해석할 수 있다. 구현 보고서 3절도 상세 cross 상태가 `skipped:disabled`인 것처럼 설명한다.
- **권고:** SearchService에서 비활성 상태를 한 번만 정규화해 두 위치가 같은 값을 쓰게 하고, 상세 `cross_reranker.status == "skipped:disabled"`를 테스트로 고정한다.

### L2. explain 값 일치 테스트가 일부 중첩 evidence를 직접 대조하지 않는다 (낮음, 유지보수성)

- **위치:** `tests/integration/test_demo_trace.py:104-166`, `src/jupjup/demo/app.py:416-549,585-606`.
- **직접 확인:** 테스트는 주요 필드와 모든 대표 경로를 잘 비교하지만, 계획별 `hard_filter`·`eligible_document_count`, 리트리버 `matched_fields`, 융합 `raw_scores`, 재순위 `features` 전체, 구성 요소 `component/model/input/output`, 실행 로그 항목 전체는 SearchService debug와 직접 equality를 단언하지 않는다. 일부는 스냅숏이나 단일 행동 단언으로만 고정된다.
- **영향:** 현재 값을 직접 살펴본 범위에서는 잘못된 매핑을 찾지 못했고 스냅숏도 통과하므로 완료 조건을 뒤집지는 않는다. 다만 서비스 debug의 필드명이 바뀌거나 데모 변환에서 값이 빠져도 스냅숏을 함께 갱신하면 출처 일치 회귀를 놓칠 수 있다.
- **권고:** trace 변환의 파생 필드(제목, 표시용 status)만 명시적으로 제외하고, 나머지 중첩 필드를 source debug와 표 기반 또는 작은 공용 assertion helper로 전부 대조한다.

## 3. 잘한 점

- `explain=False` 경로의 계측·dict 생성·대상 문서 집계를 분기 밖으로 흘리지 않았고, 변경 전 코드 518개 응답 해시로 실제 무회귀가 증명된다.
- 후보 제목 조회도 같은 `user_id`로 제한하고, 별도 사용자 trace에는 그 사용자 content ID만 존재하는 격리 테스트가 있다.
- 페이지는 외부 자산이 없고 DOM 값을 `textContent` 기반으로 넣어 trace의 제목·요약·태그를 HTML로 실행하지 않는다. 10행 제한, 나머지 펼치기, 인쇄 스타일, 좁은 화면 처리를 함께 제공한다.
- 없는 시간을 임의로 분할하지 않고 실제 계측 구간을 여러 단계가 공유한다고 명시했다. trace에서 실제로 없는 값은 `None`/skipped로 남긴다.
- 대표 3질의가 hard 기간+플랫폼, 오타 교정, strict empty 뒤 완화라는 서로 다른 핵심 경로를 덮고, browse skip·사용자 격리·explain on/off도 별도 테스트한다.

## 4. 채점 근거

| 항목 | 점수 | 근거 |
|---|---:|---|
| 정확성 | 39 / 40 | 완료 조건 전부 재현, 실제 서버 3질의·스냅숏·SearchService 값·변경 전 518개 해시·eval 4종 모두 일치. 동일 크로스 단계의 상태 표현 불일치 L1로 −1 |
| 안전성 | 30 / 30 | 사용자 격리, 루프백 기본, 입력 길이·aware datetime 검증, 외부 자산/XSS 회피, test 실제 모델 미실행, 기본 설치 llama.cpp 미import, mock·recorded 서비스 네트워크 시도 0. 근거 있는 감점 사항 없음 |
| 유지보수성 | 29 / 30 | Pydantic trace 스키마, 실제 explain 단일 출처, 대표 스냅숏·기존 응답 무회귀·결정성 테스트가 재현 가능하다. 일부 중첩 source equality 미봉인 L2로 −1 |
| **합계** | **98 / 100** | **PASS** |

## 5. 다음 단계

PASS이므로 재검수 조건은 없다. L1은 작은 상태 정규화 문제이고 L2는 테스트 봉인 강화이므로, 다음에 검색 trace를 확장할 때 함께 처리하면 된다. 검색 순위 로직·기준선·녹화본을 바꿔 해결할 문제는 아니다.
