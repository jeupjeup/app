# Phase 2 T24 인제스트 평가 Loop 2 수정 보고서

- 작성일: 2026-11-01
- 역할: Codex-Primary
- 기준 검수: `specs/phase4_review_ingest-t24_loop1.md` (87점, REJECT)
- 정책: 순위 품질 판정은 recorded(실제 bge-m3 녹화 재생)다. mock은 안전·절대 기준·결정성 검증에만
  사용했다. 검색/인제스트 기준선과 임계값은 변경하거나 낮추지 않았고 test split으로 재튜닝하지 않았다.

## 1. 결과 요약

검수의 M1~M5와 L1~L7을 모두 반영했다. 영구 스키마 실패 한 건은 이제 전체 실행을 중단하지 않고
`job_status=failed`, `schema_final_pass=false`, `attempts=3`, `error_code=ANALYSIS_SCHEMA_INVALID` 항목으로
남으며 dev 최종 준수율은 47/48, gate FAIL, CLI 종료 코드는 1이다. 정상 골든의 mock dev/test/all은 모두
PASS이고 두 번 실행한 JSON/Markdown은 바이트 단위로 같다.

검색 mock/recorded dev/test 지표는 Loop 1과 소수점 4자리까지 같으며 보호 범위인 `src/jupjup/search`,
`src/jupjup/query`, 검색 기준선·녹화본·검색 골든·lexicon은 기준 커밋 대비 변경 0줄이다.

## 2. 피드백별 조치

| 피드백 | 조치 | 회귀 증거 |
|---|---|---|
| M1 영구 실패 시 하네스 중단 | 분석 결과가 없는 terminal 실패도 항목화하고 잡 오류 코드와 분석 재요청 횟수를 기록한다. 실패도 최종 준수율 분모에 포함한다. | 영구 `schema_violation` 3회 주입 시 47/48, 리포트 생성, gate FAIL, CLI exit 1 |
| M2 비충실 비율 > 1, forbidden 처리 | `split_sentences` 하나로 분자·분모를 만들고 후보 문장을 집합으로 센다. forbidden claim은 즉시 항목 비율 1.0이다. 제품 모드 overall은 항목 비율 평균으로 문서화했다. | `?` 3문장, forbidden 3문장, 중복 문장 테스트; 모든 비율 [0, 1] |
| M3 어려운 사례 gold 부실 | 숫자·날짜 5건은 실제 수치 key fact/틀린 수치 forbidden, 영어 5건은 `Orca Retrieval Lab`·`Atlas Retrieval Dataset`, 광고 5건은 건별 증정·할인 forbidden으로 재작성했다. 80건 forbidden이 동일하지 않고 잘못된 조사를 제거했다. | 생성기 재실행 `cmp` 동일, validate PASS, 능력별 gold 구조 테스트 |
| M4 동의어 미연결 | 하네스 `_item_metrics`가 container lexicon을 tag/entity/location 지표에 모두 넘긴다. | `까페` 예측 대 `카페` gold가 세 지표 모두 F1 1.0 |
| M5 key fact substring fixture 선택 | submit 결과의 `content_id`를 golden `source_id`에 명시적으로 bind해 fixture를 고른다. 원문 substring 탐색을 제거했다. 빈 key fact도 검증 단계에서 거부한다. | content-id 결합 코드와 `key_facts=[""]` 부정 테스트 |
| L1 숫자/영문 거짓 음성 | 원문과 요약 숫자·날짜를 같은 정규식 토큰 집합으로 비교한다. 대문자 시작 영문 고유명사도 후보로 잡는다. | `12억` 대 `120억`, `Samsung/Galaxy` 테스트 |
| L2 첫 시도 준수율 숨김 | mock에서도 계산 가능한 첫 시도 준수율을 overall/Markdown에 표시하고 합격 gate 제외임을 명시한다. | dev 0.895833, test 0.96875, all 0.925 |
| L3 골든 검증기 빈틈 | 공백 text/OCR, review status-annotator 조합, platform group 정합성, 빈 key fact/forbidden, test 주입 최소 2건을 검증한다. CLI는 `JupjupError`도 종료 2로 정리한다. | 경로 이탈·중복·split·공백·review/platform 부정 테스트 |
| L4 비용 추정 검증/과소 추정 | `estimate_cost`도 run과 같은 골든 검증을 먼저 수행한다. 실제 토크나이저 전에는 non-ASCII 1자=1 token의 보수적 추정을 쓴다. | annotation 누락이 KeyError가 아닌 검증 오류, test 추정 28,245→69,145 tokens |
| L5 CLI 오류 일관성 | 리포트 쓰기를 try 안으로 옮기고 OSError/ValidationError/JupjupError를 한 줄 오류와 exit 2로 낸다. | 런타임 오류·쓰기 오류 모두 traceback 없이 exit 2 |
| L6 주입 판정 evidence/test 표본 | evidence는 앞 100자가 아니라 key fact가 있는 원문 구절을 우선한다. 주입 사례를 재배치해 test가 1→2건이다. | validator 최소 표본 단언, dev/test 주입 gate PASS |
| L7 테스트/정리 | 영구 실패, 주입 누출, 기준선 회귀, forbidden/문장 분리, validator 부정 경로를 추가했다. 자모 거리 테스트는 실제 거리 1 입력으로 고쳤고 충실도 원문은 저장된 snapshot을 읽는다. 신규/수정 파일은 format check를 통과한다. | 전체 테스트 910→928 passed, 3 deselected |

## 3. 지표 전후

### 3.1 검색 — recorded가 순위 품질 기준

| 모드 / split | 지표 | Loop 1 | Loop 2 | 회귀 하한 | 판정 |
|---|---|---:|---:|---:|---|
| recorded / dev | Recall@10 | 0.9712 | 0.9712 | 0.956457 | PASS |
| recorded / dev | MRR@10 / nDCG@10 / category min | 1.0000 / 0.9860 / 0.8894 | 1.0000 / 0.9860 / 0.8894 | 0.99 / 0.969304 / 0.80 | PASS |
| recorded / test | Recall@10 | 0.9720 | 0.9720 | 0.972000 | PASS, 여유 0 |
| recorded / test | MRR@10 / nDCG@10 / category min | 0.9911 / 0.9801 / 0.8900 | 0.9911 / 0.9801 / 0.8900 | 0.976667 / 0.97075 / 0.80 | PASS |
| mock / dev | Recall@10 / MRR / nDCG / category min | 0.9620 / 0.9958 / 0.9795 / 0.8838 | 동일 | 기존 기준선 | PASS |
| mock / test | Recall@10 / MRR / nDCG / category min | 0.9420 / 0.9867 / 0.9589 / 0.7812 | 동일 | 기존 기준선 | PASS |

recorded dev/test의 true-empty는 모두 1.0, false-empty는 0.0이며 격리·필터 위반도 0이다. 기준선 파일은
변경하지 않았다.

### 3.2 인제스트 mock 배선

| 지표 | Loop 1 | Loop 2 dev | Loop 2 test | Loop 2 all |
|---|---:|---:|---:|---:|
| 스키마 첫 시도 준수율 | 해당 없음으로 숨김 | 0.895833 | 0.968750 | 0.925000 |
| 스키마 최종 준수율 | 1.0 | 1.0 | 1.0 | 1.0 |
| 주입 저항 | 1.0 | 1.0 (n=1) | 1.0 (n=2) | 1.0 (n=3) |
| retry exercised | all 6 (split별 값 미기록) | 5 | 1 | 6 |
| 영구 실패 주입 최종 준수율 | 실행 예외, 리포트 없음 | 47/48 | — | — |
| 비충실 문장 비율 경계 재현 | 최대 4.0 | 항상 0..1 | 항상 0..1 | 항상 0..1 |
| live test 입력 token 사전 추정 | 28,245 | — | 69,145 | — |

첫 시도 수치는 기존 6개 재요청 fixture의 고정 split 분포(dev 5/test 1)를 그대로 표시한 것이다. 주입 사례
한 건을 dev에서 test로 재배치한 변경과는 무관하다. 품질 지표는 mock fixture가 gold를 복사하므로 계속
`해당 없음`이고 제품 합격 근거가 아니다.

## 4. 검증 결과

### 4.1 기본 설치 (`uv sync --locked`)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 928 passed, 3 deselected, 기존 Starlette/httpx 경고 1건 |
| `uv run ruff check src tests` | PASS |
| `uv run mypy src` | PASS — 78 source files |
| `uv run jupjup eval validate` | PASS — ingest 80, dev 48/test 32, 플랫폼군 분포 유지 |
| 검색 eval mock/recorded dev/test | 4종 PASS, 3.1절 수치 |
| ingest eval mock dev/test/all | 3종 PASS |
| ingest 두 번 실행 후 JSON/Markdown 6개 `cmp` | 모두 바이트 동일 |

### 4.2 extra 설치 (`uv sync --all-extras --locked`)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 928 passed, 3 deselected |
| 실제 모델 `pytest -m 'embed or rerank'` | PASS — 3 passed, 928 deselected, 지정 cache 사용 |
| `uv run ruff check src tests` / `uv run mypy src` | 둘 다 PASS |
| `uv run jupjup eval validate` | PASS |
| 검색 eval mock/recorded dev/test | 4종 PASS, 기본 설치와 같은 수치 |
| ingest eval mock dev/test/all | 3종 PASS, 기본 설치와 같은 수치 |

실제 모델 통합 확인은
`JUPJUP_BGE_CACHE_DIR=/Users/minjun/orca/workspaces/dc2/phase-2-real-embedding/var/models`와 같은 경로의
reranker cache를 사용했다. 검증 뒤 `uv sync --locked`로 기본 설치 상태를 복원했다.

### 4.3 결정성과 범위 보호

- `scripts/generate_ingest_golden.py` 재실행 전후 sources/annotations `cmp`: 동일.
- 기준 커밋 `0d753a0` 대비 `src/jupjup/search`, `src/jupjup/query`, `data/baselines`,
  `data/recordings`, 검색 golden, lexicon: 변경 0줄.
- `data/baselines/ingest.mock.json`도 변경하지 않았다.

## 5. 설계 대비 차이

- T24 범위대로 ingest recorded/live 실제 분석기는 구현하지 않았다. 해당 모드는 mock으로 대체하지 않고 종료 2다.
- live 비용은 T25 실제 토크나이저가 연결되기 전 보수적 문자 기반 추정이다. 과소 추정 방지가 목적이며 모델
  청구 token의 정밀 추정치는 아니다.
- 영구 분석 실패에서는 검증된 output과 provider token 메타가 없으므로 item metrics와 token/latency는 빈 값/0으로
  남기고, 잡에 안전하게 보존된 오류 코드와 attempts만 기록한다.

## 6. 남은 문제

1. 80건은 계속 `ai_draft_unreviewed`다. 어려운 사례 15건은 능력 지향 gold로 고쳤지만 나머지 플랫폼군 내부
   다양성은 부족하다. `REVIEW_GUIDE.md`와 `known_issues.md`에 단순 검수가 아닌 원문·라벨 재작성 필요를 기록했다.
2. 실제 LLM 분석기/판정기, κ 보정, recorded ingest 기준선과 검색 연결 품질은 T25 범위다.
3. recorded test Recall@10은 0.9720으로 기존 회귀 하한과 정확히 같아 여유가 0이다. 이번 수정은 검색 경로와
   기준선을 건드리지 않아 회귀는 없지만, 다음 검색 변경도 recorded dev에서만 설계·튜닝해야 한다.
4. 기본 설치 pytest의 기존 Starlette/httpx deprecation warning 1건은 남아 있다. extra 설치에서는 httpx2가
   설치되어 경고가 나오지 않았다.
