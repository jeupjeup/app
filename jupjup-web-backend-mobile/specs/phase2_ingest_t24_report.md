# Phase 2 T24 인제스트 평가 구현 보고서

작성일: 2026-11-01

역할: Codex-Primary

범위: T24 인제스트 골든셋, 지표, Mock 하네스, 결정적 충실도 1차 검사, CLI, 기준선

## 구현 범위

### 골든셋

- `data/golden/ingest/sources.jsonl`, `annotations.jsonl`에 직접 작성한 AI 초안 80건을 추가했다.
- 플랫폼군 분포는 instagram 15, youtube 15, news 15, paper 10, kakaotalk 10,
  blog/web 10, image(OCR) 5다.
- dev 48건(60%), test 32건(40%)을 고정했다.
- 어려운 사례는 장문(원본 HTML 40,000자 초과) 5, 광고·해시태그 과다 5, 영어 중심 5,
  숫자·날짜 밀집 5, 프롬프트 주입 3건이다.
- 모든 annotation을 `annotator=ai`, `review_status=ai_draft_unreviewed`로 표시했다.
- `data/golden/ingest/REVIEW_GUIDE.md`에 두 명 독립 검수, 불일치 조정, split 동결,
  human-reviewed 전환 절차를 기록했다.
- `scripts/generate_ingest_golden.py`로 검색 골든셋에 손대지 않고 인제스트 데이터와 fixture만
  결정적으로 재생성할 수 있다.

### 평가 코드

- `ingest_metrics.py`: 태그 P/R/F1(acceptable FP 제외), 엔티티/장소 매칭, 저장 의도,
  정확도, p50/p95 순수 함수를 구현했다. 엔티티/장소는 최대 이분 매칭으로 중복 채점을 막는다.
- `judge.py`: `FaithfulnessJudge` Protocol과 결정적 1차 검사기를 구현했다. 요약 문장별 숫자,
  날짜, Kiwi NNP/SN이 원문에 없으면 근거 없음 후보로 표시한다.
- `ingest_harness.py`: 골든셋 로드/검증, 비용 추정 인터페이스, Mock 하네스, 기준선 회귀 게이트를
  구현했다. 각 항목은 실제 I1~I8 단계(fetch, extract, vision, chunk, analyze, persist, embed,
  index)를 거치며 최종 잡 상태가 `succeeded`인지 평가한다. 여섯 항목에는 깨진 JSON,
  스키마 위반, 빈 응답, max_tokens 응답을 고정 주입해 재요청 경로를 실행한다.
- `ingest_report.py`: 3.5.2절 전체 지표 표, 3.5.4절 mock 게이트, 플랫폼군별 표,
  충실도 후보를 JSON/Markdown으로 출력한다. mock 품질 판정 불가 항목은 `해당 없음`이다.
- `data/baselines/ingest.mock.json`: dev/test/all의 스키마 최종 준수율 1.0과 주입 저항 1.0을
  기준선으로 고정했다.

### 연결 변경

- `jupjup eval validate`가 기존 검색 골든셋과 함께 인제스트 80건, 분포, split, fixture,
  review status를 검증하도록 확장했다.
- `jupjup eval ingest --mode mock --split dev|test|all`을 추가했다.
- `data/golden/README.md`, `data/baselines/README.md`에 인제스트 초안과 기준선 정책만 덧붙였다.
- 이 변경은 T24 산출물의 진입점과 검증 연결에 필요했다. `src/jupjup/search`,
  `src/jupjup/query`, 기존 검색 골든셋·검색 기준선·`data/recordings`는 변경하지 않았다.

## 설계 대비 차이

1. 설계 예시의 `profile="default"` 대신 T24 CLI 기본 프로필을 `mock`으로 두었다. T25의
   `analyzer_profiles.yaml`과 실제 기본 분석기가 아직 범위 밖이므로, 현재 존재하는 분석기를
   정직하게 식별하고 `ingest.mock.json`과 일치시키기 위해서다. `--profile` 옵션은 유지했다.
2. `compare_profiles` 메서드는 인터페이스 위치만 두고 `NotImplementedError`를 낸다. 부트스트랩
   신뢰구간과 모델 교체 판정은 명시적으로 T26 범위다.
3. 인제스트 `recorded`/`live` 실행은 T25 구현 전 조용히 Mock으로 대체하지 않고 종료 코드 2로
   거부한다. live는 `--confirm-cost`가 없을 때 결정적 토큰 규모 추정만 출력하며 외부 호출은 하지
   않는다. 모델 단가가 아직 없으므로 추정 비용은 0달러로 표시된다.
4. mock에서 태그·엔티티·장소·카테고리·저장 의도·요약 품질·검색 연결 지표는 3.5.4절에 따라
   공식 overall에서 `해당 없음`으로 표시한다. 고정 fixture와 gold가 같아 생기는 인위적인 품질
   점수를 합격 근거로 노출하지 않는다. 토큰·재요청·비용·지연은 실행에서 계산 가능하므로 표시한다.
5. 별도 엔티티 별칭 파일은 설계에 구체 경로가 없고 현재 저장소에도 없다. T24는 기존
   `Lexicon` 동의어 정규화와 자모 거리 1을 사용했다. 실제 엔티티 별칭 사전이 추가되면 같은
   metric 함수에 주입하는 확장이 필요하다.

## 추가·변경 파일

- 소스: `src/jupjup/eval/ingest_metrics.py`, `ingest_harness.py`, `judge.py`,
  `ingest_report.py`, `src/jupjup/cli.py`
- 데이터: `data/golden/ingest/**`, `data/baselines/ingest.mock.json`
- 생성기/문서: `scripts/generate_ingest_golden.py`, 골든/기준선 README
- 테스트: `tests/unit/test_ingest_metrics.py`, `test_ingest_judge.py`,
  `test_ingest_golden_validator.py`, `tests/eval/test_ingest_regression.py`, CLI 통합 테스트

## 직접 실행한 명령과 결과

### 필수 품질 게이트

- `uv run pytest`
  - **PASS**: 910 passed, 3 deselected, 1 warning, 45.23s
  - warning은 기존 FastAPI TestClient의 Starlette/httpx deprecation 경고다.
- `uv run ruff check src tests`
  - **PASS**: All checks passed.
- `uv run mypy src`
  - **PASS**: 78 source files, no issues.
- `uv run jupjup eval validate`
  - **PASS**: 기존 검색 골든셋 및 인제스트 sources/annotations 80건 검증 통과.
  - 인제스트 split dev 48/test 32, 플랫폼군 최소 수 모두 충족.

### 인제스트 평가

- `uv run jupjup eval ingest --mode mock --split dev`
  - **PASS**: 스키마 최종 준수율 1.0, 주입 저항 1.0, 기준선 회귀 없음.
- `uv run jupjup eval ingest --mode mock --split test`
  - **PASS**: 스키마 최종 준수율 1.0, 주입 저항 1.0, 기준선 회귀 없음.
- `uv run jupjup eval ingest --mode mock --split all`
  - **PASS**: 스키마 최종 준수율 1.0, 주입 저항 1.0, 기준선 회귀 없음.
- dev/test를 각각 두 번 다른 출력 디렉터리에 실행한 뒤 JSON과 Markdown에 `cmp` 실행
  - **PASS**: 두 split 모두 바이트 단위 동일. 리포트에는 타임스탬프를 기록하지 않는다.

### 기존 검색 평가 무회귀

- `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json`
  - **PASS**: Recall@10 0.9620, MRR@10 0.9958, nDCG@10 0.9795.
- `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json`
  - **PASS**: Recall@10 0.9420, MRR@10 0.9867, nDCG@10 0.9589.
- `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json`
  - **PASS**: Recall@10 0.9712, MRR@10 1.0000, nDCG@10 0.9860.
- `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json`
  - **PASS**: Recall@10 0.9720, MRR@10 0.9911, nDCG@10 0.9801.

## 남은 문제

- 골든 annotation 80건은 사람 미검수 AI 초안이다. `REVIEW_GUIDE.md` 절차 완료 전에는 제품 품질
  PASS 근거가 아니다.
- 실제 LLM 분석기, recorded/live 인제스트 평가, LLM 충실도 판정과 Cohen's κ 보정은 T25다.
- 검색 연결 품질과 실제 비용/지연은 T25 분석기 출력 및 녹화본이 있어야 측정할 수 있다.
- 소형 모델 교체의 부트스트랩 신뢰구간/SwapDecision은 T26이다.
- 기본 테스트의 기존 Starlette/httpx deprecation warning 1건은 T24 기능 실패가 아니며 남아 있다.

## 반영한 Reviewer 피드백

이번 작업은 최초 구현 루프이며 별도 Reviewer 피드백은 없었다.
