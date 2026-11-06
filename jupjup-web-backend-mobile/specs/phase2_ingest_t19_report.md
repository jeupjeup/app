# Phase 2 T19 원본 수집·스냅샷 추출 구현 보고서

- 작업 역할: Codex-Primary
- 기준 설계: `specs/prd_and_design.md` 1.2, 5.7, 5.8.1, 5.10.1~2, 5.10.8, 7.3절 T19
- 결과: T19 범위 구현 및 완료 조건 통과

## 1. 구현 범위

### `src/jupjup/ingest/fetch.py`

- `SourceSpec`, `RawSource`와 runtime-checkable `SourceFetcher` Protocol
- 직접 입력 본문과 이미지 OCR 텍스트를 처리하는 `InlineTextFetcher`
- UTF-8 HTML fixture를 읽는 `FixtureHtmlFetcher`
- VTT, SRT, JSON fixture를 읽는 `FixtureTranscriptFetcher`
- 등록 순서대로 첫 지원 fetcher를 고르는 `FetcherRouter`
- fixture 루트 고정과 경로 검증
  - 절대경로 거부
  - `..` 경로 거부
  - Windows 형식/역슬래시 경로 거부
  - 경로 구성요소의 심볼릭 링크 거부
  - 최종 resolve 결과의 루트 내부 여부 재검증
- fetch 시각을 주입할 수 있는 clock으로 결정적 테스트 지원
- HTTP 클라이언트, URL open, socket 호출이 없는 offline-only 구현

### `src/jupjup/ingest/extract.py`

- `extract_snapshot(raw, platform, max_chars=100_000)`과 `SnapshotDraft`
- 표준 라이브러리 `HTMLParser` 기반 본문 추출
  - `article`, `main`, `role=main`, 흔한 article/content 컨테이너 우선
  - `nav`, `aside`, `footer`, form/script/style 계열 제거
  - 광고, 후원, 배너, 메뉴, 공유, 댓글, 관련글, 쿠키 팝업 등의 class/id/role 제거
  - title, author, published time, language 메타데이터 추정
- VTT/SRT/JSON 자막 정리
  - 헤더, cue id, 타임스탬프, STYLE/REGION/NOTE 블록 제거
  - HTML/ASS 자막 태그와 `[음악]`, `(박수)` 같은 비발화 표지 제거
  - 반복 cue와 누적/겹침 caption 병합
- 기존 `normalize_text`를 통한 정규화, 간단한 언어 추정, SHA-256 `content_hash`
- 본문/OCR 길이 제한과 `truncated`, 추출 결과가 0자이면 `ExtractionError`

### 에러와 fixture

- `src/jupjup/domain/errors.py`에 설계 코드 그대로 추가
  - `FetchError`: `INGEST_FETCH_FAILED`
  - `UnsupportedSourceError`: `INGEST_UNSUPPORTED`
  - `ExtractionError`: `INGEST_EXTRACT_FAILED`
- `tests/fixtures/ingest/html/`에 구조가 다른 HTML 10건
- `tests/fixtures/ingest/transcript/`에 VTT, SRT, JSON 각 1건

## 2. 설계 대비 차이와 판단

1. 설계에는 `SourceSpec`, `RawSource`, `SnapshotDraft`의 필드만 있고 배치 파일이 명시되지 않았다. T18 소유인
   `ingest/schemas.py`를 건드리지 않기 위해 fetch 입력/출력 모델은 `ingest/fetch.py`, 추출 출력 모델은
   `ingest/extract.py`에 배치했다. 모두 frozen Pydantic 모델이며 공개 필드는 설계 표와 일치한다.
2. 설계의 API 설명은 source kind를 `text|url|image`로 적고, fetcher 주석은 `youtube + fixture`라고 적는다.
   호환을 위해 transcript fetcher는 `kind="youtube"`와 transcript 확장자를 가진 `kind="url"`을 모두 받는다.
3. 경로 탈출만 막으라는 요구보다 보수적으로 fixture 경로 안의 **모든 심볼릭 링크**를 거부한다. 현재 fixture는
   정적 테스트 자산이므로 정상 기능을 줄이지 않으면서 교체 경쟁과 링크 기반 우회를 함께 없애는 선택이다.
4. HTML 추출용 새 패키지를 넣지 않고 순수 Python `HTMLParser`와 명시적 content/noise 규칙을 사용했다. 기본 설치와
   offline 조건을 유지하고 의존성 표면을 늘리지 않기 위해서다. **새 의존성은 없다.**
5. 별도 언어 감지기가 설계 범위에 지정되지 않아 HTML/JSON의 language hint를 우선하고, 없으면 한글·일본어·한자·
   Latin 문자 범위로 `ko|ja|zh|en|und`를 결정한다. timezone 없는 발행 시각 hint는 공통 aware-datetime 계약을
   만족시키기 위해 UTC로 해석한다.

## 3. 추가 테스트

`tests/unit/test_ingest_fetch_extract.py`에 18건을 추가했다.

- 구조가 다른 HTML fixture 10건의 기대 본문 포함과 내비게이션/광고 문구 제외
- HTML title/author/published time/language 메타데이터
- VTT 누적 cue와 음악 표지 제거
- SRT cue 번호, 타임스탬프, 중복 줄, 박수 표지 제거
- JSON/YouTube `events[].segs[].utf8` 정리와 메타데이터
- `../`, 절대경로, 외부를 가리키는 심볼릭 링크 차단과 정상 상대경로 허용
- `socket.socket`과 `socket.create_connection`을 실패 함수로 바꾼 상태에서 inline/HTML/transcript fetch 성공
- `SourceFetcher` Protocol, router 디스패치, 지원하지 않는 원본 오류
- inline text/OCR 분리
- HTML에서 유효 본문 0자일 때 `ExtractionError`
- `max_chars`, `truncated`, 같은 입력의 동일 `SnapshotDraft`와 hash

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest tests/unit/test_ingest_fetch_extract.py -q --disable-warnings` | PASS — 18 passed |
| `uv run pytest` | PASS — 674 passed, 3 deselected, 1 warning, 33.45s |
| `uv run ruff check src tests` | PASS — All checks passed |
| `uv run mypy src` | PASS — 65 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9620, nDCG@10 0.9795, true-empty 1.0 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS — R@10 0.9420, nDCG@10 0.9589, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, nDCG@10 0.9860, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json` | PASS — R@10 0.9720, nDCG@10 0.9801, true-empty 1.0 |
| `git diff --check` | PASS |
| 금지 범위 대상 `git diff` 확인 | 변경 없음 — T18 schemas/validation 및 테스트, search/query, baselines, recordings |

pytest 경고 1건은 기존 FastAPI/Starlette TestClient의 `httpx` deprecation 경고이며 T19 변경과 무관하다.

## 5. 남은 문제와 범위 밖

- 본문 추출은 fixture와 일반적인 semantic/content class 규칙을 대상으로 한 결정적 휴리스틱이다. 실제 웹의 난해한
  DOM, JavaScript 렌더링, paywall/readability 점수화는 네트워크 수집과 함께 후속 범위다.
- 언어 추정은 경량 문자 휴리스틱이므로 다국어 혼합 문서의 주 언어 판별까지 보장하지 않는다.
- 실제 URL/YouTube 네트워크 접근은 의도적으로 구현하지 않았다. URL만 있고 fixture가 없으면
  `UnsupportedSourceError`다.
- T20 이후의 청킹, 분석기, 잡 큐, 워커, API 연결은 구현하지 않았다.
