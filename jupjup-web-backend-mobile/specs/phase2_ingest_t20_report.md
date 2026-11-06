# Phase 2 T20 분석용 청킹 구현 보고서

- 작업 역할: Codex-Primary
- 기준 설계: `specs/prd_and_design.md` 5.10.2절, 5.10.4절, 5.10.8절의
  `chunk_for_analysis` 시그니처, 7.3절 T20
- 결과: T20 범위 구현 및 완료 조건 통과

## 1. 구현 범위

### `src/jupjup/ingest/chunking.py`

- `chunk_for_analysis(snapshot, meta, settings) -> AnalysisInput`
  - 분석 원문 추정 토큰 수가 기본 12,000 이하면 `single`
  - 12,000을 초과하면 구조 단위 기반 `map_reduce` 계획
  - 문자 수를 보수적 기본 토큰 수로 사용하고, 제공자 토큰 계산기를 순수 callable로 주입 가능
- `ChunkSettings`
  - `single_max_tokens=12_000`
  - `chunk_target_tokens=3_000`
  - `overlap_tokens=200`
  - `max_chunks=24`
  - 잘못된 음수/0 값과 청크 크기 이상인 overlap 거부
- `AnalysisInput`, `AnalysisChunk`, `ContentMeta`
  - single/map_reduce별 `text`/`chunks` 배타 불변식 검증
  - `coverage=full|sampled`, 샘플링 전 `total_chunks`, 전체 추정 토큰 수 기록
  - 청크별 샘플링 전 원래 순번, 원문 문자 offset, 토큰 수 기록
- 구조 우선 분할
  - T19가 HTML 블록·제목과 약 3분 자막 구간에 남긴 빈 줄을 1차 구조 경계로 사용
  - 구조 단위를 합쳐 목표 3,000토큰 이하의 기본 청크 구성
  - 구조 단위 하나가 목표보다 클 때만 문장 종결부호, 공백, 마지막으로 안전한 문자 위치 순으로 내부 분할
  - 두 번째 청크부터 직전 기본 청크의 약 200토큰 suffix를 겹침으로 포함
- 24개 초과 샘플링
  - 앞 8개와 뒤 4개 고정
  - 그 사이 후보 전체에서 양 끝을 포함해 균등 간격으로 12개 선택
  - 원래 순서와 원래 청크 인덱스를 유지하고 `coverage="sampled"`로 표시
- 원본 종류별 순서
  - YouTube는 `제목 → 설명란 → 자막`
  - 논문은 제공된 초록을 본문 앞에 배치
  - 일반 본문과 별도 OCR이 함께 있으면 `본문 → OCR` 순으로 포함
- `src/jupjup/ingest/__init__.py`에서 T20 공개 인터페이스를 export

실제 맵 단계의 `ChunkNoteExtractor`, 리듀스 분석기, 프롬프트, LLM 호출, 큐/워커/API는 구현하지 않았다.

## 2. 설계 대비 차이와 판단

1. 설계에는 `ContentMeta`, `ChunkSettings`, `AnalysisChunk`, `AnalysisInput`의 구체 필드가 없어서 T20에서
   필요한 최소 계약을 frozen Pydantic 모델로 명시했다. `ContentMeta`는 제목·설명·초록·작성자·플랫폼·콘텐츠
   종류·언어·사용자 메모만 받으며 임의 필드는 거부한다. 이후 분석기가 추측 없이 같은 계획을 소비하도록
   `coverage`, 전체 토큰 수, 샘플링 전 청크 수와 원문 offset을 명시적으로 남겼다.
2. 설계의 제공자 `count_tokens(system, user)`는 T21 이후 분석기/프롬프트 인터페이스다. T20을 제공자와
   네트워크에 결합하지 않기 위해 `Callable[[str], int | None]`을 `ChunkSettings.token_counter`로 주입한다.
   어댑터가 없거나 `None`을 반환하면 설계의 `len(text) × 1.0`으로 결정적으로 대체한다.
3. HTML 제목(h1~h3), 논문 섹션이라는 태그 자체는 저장된 `Snapshot.text`에 남지 않고 T19가 보존한 빈 줄만
   남는다. 따라서 T20은 빈 줄 구조를 공통 정본으로 사용한다. 논문의 초록은 `ContentMeta.abstract`가 있으면
   별도로 맨 앞에 둔다. DOM 태그를 다시 추론하지 않아 T19 확정 파일을 수정하지 않았다.
4. I4 실패 분류는 설계상 없지만, 도메인 `Snapshot`은 직접 만들면 본문과 OCR이 모두 빈 상태일 수 있다.
   정상 I2 출력에서는 불가능한 호출이므로 빈 입력을 조용히 계획하지 않고 `ValueError`로 방어했다.
5. 설계의 고정 기본값은 그대로지만 작은 결정적 테스트와 이후 프로필을 위해 `max_chunks`를 설정 가능하게
   두었다. 기본값 24에서는 정확히 앞 8·가운데 12·뒤 4 규칙이 적용된다.

## 3. 테스트 목록

`tests/unit/test_ingest_chunking.py`에 13개 테스트를 추가했다.

- 정확히 12,000토큰은 single, 12,001토큰은 map_reduce
- 빈 줄로 구분된 문단을 자르지 않고 먼저 합치는 구조 단위 우선 분할
- 목표보다 큰 단일 구조 단위의 문장 경계 분할과 내용 보존
- 청크 끝 구조 경계를 유지하면서 직전 청크 suffix overlap 포함
- 30개 청크에서 앞 8·균등 중간 12·뒤 4의 정확한 인덱스
- 정확히 24개일 때 샘플링 없이 full coverage
- 같은 입력/설정의 모델 및 직렬화 결과 결정성
- 주입 토큰 계산기 사용과 `None` 반환 시 문자 수 fallback
- OCR 단독 입력과 본문+OCR 순서
- YouTube 제목/설명/자막 및 논문 초록/본문 순서
- 잘못된 설정과 single/map_reduce 모델 형태 거부
- 빈 snapshot의 명시적 거부

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest tests/unit/test_ingest_chunking.py -q` | PASS — 13 passed |
| `uv run pytest` | PASS — 746 passed, 3 deselected, 1 warning, 33.72s (최종 실행) |
| `uv run ruff check src tests` | PASS — All checks passed |
| `uv run mypy src` | PASS — 66 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9620, MRR 0.9958, nDCG 0.9795, true-empty 1.0 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS — R@10 0.9420, MRR 0.9867, nDCG 0.9589, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, MRR 1.0000, nDCG 0.9860, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json` | PASS — R@10 0.9720, MRR 0.9911, nDCG 0.9801, true-empty 1.0 |
| `uv run ruff format --check` (T20 변경 Python 파일) | PASS — 3 files already formatted |
| `git diff --check` | PASS |
| `git diff -- src/jupjup/search src/jupjup/query data \| wc -l` | `0` — 금지 범위 변경 없음 |

pytest 경고 1건은 기존 FastAPI/Starlette TestClient의 `httpx` deprecation 경고다. 선택 extra가 필요한
embed/rerank 테스트 3개는 기본 설치 정책에 따라 deselect됐다. 평가가 만든 `reports/` 파일은 기존 ignore
대상이며 기준선과 녹화 데이터는 수정하지 않았다. 외부 네트워크와 실제 LLM API 호출은 없었다.

## 5. 남은 문제

- 저장된 `Snapshot.text`에는 원래 HTML 태그 종류(h1/h2/h3)나 논문 섹션 역할이 없으므로, 빈 줄로 보존되지
  않은 구조를 T20에서 복원하지는 못한다. 현재 T19 출력 계약 안에서는 블록·제목·3분 자막 경계가 빈 줄로
  보존되어 완료 조건을 만족한다.
- 실제 제공자 tokenizer의 정확한 토큰 수는 해당 어댑터를 T21 이후에서 wrapper로 주입해야 사용된다. 기본
  경로는 설계대로 보수적 문자 수 추정이다.
- map 단계의 노트 추출과 reduce 실행은 T21 이후 범위이며, 이번 결과는 실행 가능한 순서·범위·coverage를
  담은 계획까지만 만든다.
