# Phase 4 최종 검수: 인제스트 T19(원본 수집·스냅샷 추출), Loop 2/3

- **점수:** 95 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 29 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 낮음 항목은 T20/T22 착수 전에 정리하기를 권한다. 고칠 곳은 Phase 2 `src/jupjup/ingest/extract.py`, `src/jupjup/ingest/fetch.py`다.
- **검수 대상:** `phase-4-review-ingest-t19-loop2` HEAD `b71877b` (`fix: address T19 ingest review loop 1 feedback`). 비교 기준은 Loop 1 검수 커밋 `636fe8e`(85점 REJECT)다.
- **기준 문서:** `specs/prd_and_design.md` 1.2절(범위 제외, 45줄), 5.8.1절, 5.10.1·5.10.2절(I1·I2), 5.10.4절, 5.10.8절(1364~1378줄 `SourceFetcher`·`extract_snapshot` 시그니처), 7.3절 T19 행(1722줄)과 완료 조건, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`(특히 `phase4_review_ingest-t19_loop1.md`). 구현 보고서 `specs/phase2_ingest-t19_loop2_report.md`의 주장은 모두 직접 다시 확인했다.
- **채점 정책:** Loop 1과 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖 항목(T20 이후의 청킹·분석기·잡 큐·워커·인제스트 API, 실제 네트워크 수집, 실제 LLM 연동)은 "참고"로만 적었다. M3의 Architect 추인이 아직 없는 점은 절차 문제라서 감점하지 않고 PM 조치 사항으로 남긴다.

## 0. 요약

- **Loop 1 재검수 조건 1~6을 모두 충족했다.**
  - **H1:** `Notebook`/`Style`/`Regional`/`Language:`로 시작하는 SRT·VTT cue가 보존된다. 타이밍 뒤 `NOTE 이건 발화`도 남는다. VTT 헤더(`Kind:`/`Language:`)와 첫 cue 앞 `NOTE`/`STYLE` 블록은 지금처럼 빠진다. `kind=text`는 platform이 youtube여도 일반 텍스트 경로로 간다.
  - **M1:** `/>` 없는 `<input>`·`<embed>` 뒤 본문이 보존된다. `<br>` 2만 줄은 8.7초에서 **0.06초**, 5만 단계 중첩은 16.9초에서 **0.12초**로 줄었다.
  - **M2:** `body.has-sidebar`와 `div.layout.no-sidebar > main` 두 입력에서 본문이 나온다.
  - **M3:** 검수 권장안대로 바뀌었다. 블록·제목은 `\n\n`, `<br>`은 `\n`으로 나뉜다. inline 요소에는 공백이 생기지 않는다. 대소문자와 이모지가 보존되고, 자막은 3분 구간과 `transcript_segments`로 남는다.
  - **L1~L5:** 모두 처리됐다.
- **검증 결과:** 정적 검사, 테스트, eval 4종, `search`/`query`/`data` diff 0줄이 보고서 수치와 같다. 네트워크 호출은 0회다.
- **남은 결함은 모두 낮음이다.**
  - Loop 2에서 새로 생긴 작은 회귀가 하나 있다. 제목 조각을 공백 없이 이어 붙여서 여러 `h1`이나 `h1` 안 `<br>`이 `첫둘`, `Python입문`처럼 붙는다(N1).
  - 영구 실패 분류에 빈틈이 하나 있다(N2).
  - `kind=youtube`+`text/plain` 경로의 자막 판정이 느슨하다(N3).
  - M2는 일부 경우가 아직 남아 있다(보고서 4절 2번에 이미 적혀 있다).

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **733 passed, 3 deselected, 1 warning** (32.8s). Loop 1의 692에 새 회귀 테스트 41건을 더한 값이다. 경고는 기존 Starlette `httpx` 경고다 |
| `uv run pytest tests/unit/test_ingest_fetch_extract.py tests/unit/test_ingest_extract_regressions.py` | 59 passed (0.41s) |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check src/jupjup/ingest tests/unit/test_ingest_fetch_extract.py tests/unit/test_ingest_extract_regressions.py` | 7 files already formatted (L5 해결) |
| `uv run mypy src` | Success: no issues found in 65 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259(dev 158/test 101), lexicon 139. review_status ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | 전부 OK: R@10 0.9620, MRR 0.9958, nDCG 0.9795, time_exact 1.0, platform_f1 1.0 |
| `eval run --mode mock --split test …` | 전부 OK: R@10 0.9420, MRR 0.9867, nDCG 0.9589 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | 전부 OK: R@10 0.9712, MRR 1.0000, nDCG 0.9860 |
| `eval run --mode recorded --split test …` | 전부 OK: R@10 0.9720 (하한 0.972와 같은 값), MRR 0.9911, nDCG 0.9801 |
| `git diff 636fe8e HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `git diff 636fe8e HEAD --stat` | `ingest/extract.py`, `ingest/fetch.py`, 테스트 2개, 보고서만 바뀌었다 |
| `grep -rn jupjup.ingest src` (ingest 밖) | 없음. 검색 경로는 인제스트 모듈에 의존하지 않는다 |
| `grep -nE "socket\|urllib\|http\|requests\|httpx\|subprocess" src/jupjup/ingest/*.py` | 없음 |

eval 수치는 Loop 1 검수, 보고서 3.3절 표와 소수점 4자리까지 같다. 순위 무회귀를 확인했다.

### 1.2 CLI 회귀·경계값

명령은 `uv run jupjup seed load --db var/review.db`, 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`이다. seed load 결과는 200줄, 적재 200, 인덱싱 200이다(u_alice 160, u_bob 30, u_carol 10).

| 사례 | 결과 | 판정 |
|---|---|---|
| `성수 카페` (bob) | 2건(노티드 instagram, 카페 추천 세 곳 blog), 완화 없음 | OK |
| `성수 카페` (carol, 사용자 격리) | 1건(carol 본인의 성수동 카페 브런치) | OK |
| `성슈 카페` (오타) | 같은 2건 | OK |
| 빈 문자열 / 201자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` | OK |
| `!!!@@` (특수문자) | `[INVALID_QUERY] 검색할 단어가 없어요.` | OK |
| `지난주 유튜브` (필터 전용) | 1건(1분 계란말이 쇼츠, youtube) | OK |
| `유튜브` + `--platform instagram` (요청 잠금) | `overridden_by_request=["platforms"]`, 10건 모두 instagram | OK |
| `경주 맛집 인스타` / `하체 운동 유튜브` (과소 완화 회귀) | 각각 `platform_filter_dropped`. 정답(황리단길 blog / 하체 루틴 릴스)이 1위 | OK |
| `경주 맛집 카톡 논문` | `platform_filter_dropped`, `content_type_filter_dropped` 둘 다 기록 | OK |
| `python async tutorial 영상` (영어 혼합) | 0건 (기존 동작) | OK |
| `화성 식민지 부동산` (없는 대상, 과잉 완화 확인) | 0건, `empty_state.reason=no_relevant_match`, `applied_relaxations=[]` | OK |
| `카페` (u_nobody) | 저장물 없음 안내 | OK |
| `JUPJUP_MODE=recorded` `성수 카페` | `[EMBEDDING_CACHE_MISS]` (녹화본에 없는 텍스트, 기존 동작) | OK |

### 1.3 T19 직접 재현 (스크래치 스크립트, 테스트 fixture와 다른 입력)

- 스크립트 시작 시 `socket.socket`, `socket.create_connection`, `socket.getaddrinfo`, `urllib.request.urlopen`을 호출하면 바로 예외가 나는 함수로 바꿨다. 아래 모든 사례에서 네트워크 호출은 **0회**였다.
- fixture 루트는 스크래치 임시 디렉터리로 잡았다.
- 스크립트: `/private/tmp/claude-501/-Users-minjun-orca-workspaces-dc2-phase-4-review-ingest-t19-loop2/c444828e-e834-4d0b-b04d-54099ce1bde5/scratchpad/probe.py`, `/private/tmp/claude-501/-Users-minjun-orca-workspaces-dc2-phase-4-review-ingest-t19-loop2/c444828e-e834-4d0b-b04d-54099ce1bde5/scratchpad/p2.py`

| 입력 | 결과 | 판정 |
|---|---|---|
| **[완료 조건] 직접 만든 HTML 10건** (Loop 1과 같은 조합: nav/footer+article+.ad-slot, header+main+aside, .sidebar+#content+.share-buttons, role=main+.cookie-consent, .entry-content+#comments+.related-posts, itemprop=articleBody+iframe+script, 컨테이너 없음+.banner, .story-body+엔티티+.sponsored, .post-content+form+.popup, article>header>h1+.taboola) | 10건 모두 본문만 남는다. 예: `'T1\n\n본문1'`, `'본문8 & <태그>'`, `'제목10\n\n본문10'`. 제외 문구는 섞이지 않는다 | OK |
| HTML 메타 (`og:title`, `author`, 시간대 없는 `article:published_time`, `lang="ko-KR"`) | `('OG 제목','홍길동',2026-10-01T09:00+00:00,'ko')` | OK |
| **[완료 조건] 본문 0자**: nav·script·광고만 있는 HTML / 공백 HTML / `[음악]`뿐인 VTT / 빈 text / 이모지만 / ZWSP만 | 모두 `ExtractionError` "추출된 본문이 비었습니다" | OK |
| 이미지 OCR `"  영수증  합계 "` | `text=''`, OCR 본문은 공백만 정리돼 보존 | OK |
| **[완료 조건] VTT**: 롤링 누적 cue, `<c.yellow>`, 인라인 타임스탬프, `[음악]`, `♪` | `'안녕하세요 여러분 오늘은 노트북을 봅니다'`, segments `[{start_sec:1.0, offset:0}]` | OK |
| **[완료 조건] SRT**: CRLF, `<i>`, `{\an8}`, 중복 줄, `[웃음]` | `'첫 줄 둘째 줄'` | OK |
| **H1** SRT `Notebook LM…` / `Style 팁도`+`알려드려요` / `Regional 맛집` / `Language: 한국어로…` | `'Notebook LM 소개합니다 Style 팁도 알려드려요 Regional 맛집 Language: 한국어로 진행합니다'` | **해결** |
| **H1** VTT 헤더 `Kind`/`Language`, 첫 cue 앞 `NOTE`/`STYLE` + 타이밍 뒤 cue `NOTE 이건 발화` / `Style 팁` | 헤더·메타 블록은 빠지고 `'NOTE 이건 발화 Style 팁'`만 남는다 | **해결** |
| **H1** `kind=text` `"NOTE 메모…\n주말에…\n네\n좋아요\n네 (웃음)"`, platform youtube | 원문 그대로 보존(줄바꿈 유지, 중복 `네`와 `(웃음)`도 유지) | **해결** |
| SRT 숫자만 있는 발화(`2024`, `100`/`200`) | `'2024 100 200'` (cue 번호로 오인하지 않음) | OK |
| **M1** `<input type=checkbox>` 뒤 본문, `<embed src=x>` 뒤 본문 | `'앞 문단\n\n체크 뒤 본문\n\n마지막 문단\n\n임베드 뒤'` | **해결** |
| **M1** `<br>본문 줄` ×20,000 / `<div>` 50,000단계 | 0.06초 / 0.12초 (Loop 1에서는 8.7초 / 16.9초) | **해결** |
| 닫지 않은 `<p>` 100,000개 / 닫지 않은 `<span>` 30,000개 + 짝 없는 `</b>` 30,000개 / `<div><span>` 20,000쌍 교차 닫기 | 0.45초 / 0.11초 / 0.15초, 결과 정상 | OK |
| **M2** `<body class="has-sidebar"><article>` / `<div class="layout no-sidebar"><main>` | 둘 다 `'진짜 본문'` | **해결** |
| M2 `<div class="ad-wrap"><div role="main">…<div class="share">` | `'본문'` (main 되살림, 안의 share는 제외) | OK |
| M2 `<main>` + `<div class="sidebar"><article>티저` / `<article>` 안 `div.post.related` | `'main 본문'` / `'본문'` (사이드바 티저·관련글 제외 유지) | OK |
| M2 `<div class="menu-open"><article><p>진짜 본문` | `ExtractionError` | 남음 (보고서 4절 2번에 적혀 있다, R1) |
| **M3** `<p>카페 <a>노티드</a>에서 <b>Python</b> 3.12 공부 😀</p>` | `'카페 노티드에서 Python 3.12 공부 😀'` | **해결** |
| **M3** `<h2>섹션1</h2><p>문단 하나.</p><h2>섹션2</h2><p>문단 둘.<br>둘째 줄</p>` | `'섹션1\n\n문단 하나.\n\n섹션2\n\n문단 둘.\n둘째 줄'` | **해결** |
| `<pre>` / 표 | `'a b\nc\n\nx'` / `'a b\n\nc'` (셀은 공백, 행은 블록) | OK (보고서 4절 4번) |
| 자막 3분 구간: 1초, 185초, 3600초 cue | `'하나\n\n둘\n\n셋'`, segments `[(1.0,0),(185.0,4),(3600.0,7)]`. 오프셋이 실제 텍스트 위치와 맞다 | OK |
| JSON `tStartMs` 0 / 200,000 | `'하나 둘\n\n셋'`, segments `[(0.0,0),(200.0,6)]`, title `영상` | OK |
| 자막 `max_chars=30` 자르기 | 30자, `truncated=True`, 잘린 뒤 범위 밖 segment는 빠짐 | OK |
| 제어문자 `\x00`, `\x07`, ZWSP, RLO, ZWJ | `'abcd\u200def'` (ZWJ만 남음) | OK |
| **L2** JSON 정수 5,000자리 / 3,000단계 / 100단계 / 200,000단계 중첩 | 모두 `ExtractionError` | **해결** |
| 잘못된 JSON `{not json` (application/json) | 텍스트 경로로 넘어가 `'{not json'` 보존 | OK |
| **L3** `<meta charset=euc-kr>` + EUC-KR 바이트 (MIME에 `charset=utf-8`이 있어도) / `http-equiv` / UTF-16 BOM | 모두 한글이 정상으로 나온다 | **해결** |
| L3 UTF-8 바이트인데 `euc-kr` 선언 | `'한글 본문입니다 가나다라'` (cp949 strict 실패 → UTF-8) | OK |
| L3 `0x80~0xFF` 바이트 열 | `ExtractionError` "원본 인코딩을 해석하지 못했습니다" | **해결** |
| **L4** `<title>진짜 제목</title>` + `<svg><title>icon</title></svg>` | title `'진짜 제목'` | **해결** |
| 여러 `h1` (`<h1>첫</h1>…<h1>둘</h1>`) / `<h1>Python<br>입문</h1>` / 로고 `h1` + 기사 `h1` | title `'첫둘'` / `'Python입문'` / `'사이트명기사 제목'` | **N1 (새 회귀)** |
| 5,000,001바이트 원본 | `ExtractionError` "원본이 너무 큽니다" | OK |
| `max_chars=0` | `ValueError` | OK |
| 같은 입력 두 번 | `SnapshotDraft` 동일 | OK |
| `kind=youtube`, `text/plain`, `"메모\n00:00:01,000 --> 00:00:02,000\n이건…"` | `'이건 타임라인이 있는 메모'` (`메모` 줄이 cue id로 오인돼 사라짐) | N3 |
| **[완료 조건] 경로 탈출**: `../secret.html`, `h/../../secret.html`, 절대경로, `C:\x.html`, `h\1.html` | `UnsupportedSourceError` "안전하지 않은 fixture 경로" | OK (L1 해결) |
| 루트 밖 파일 심볼릭 링크 / 디렉터리 심볼릭 링크 경유 | `UnsupportedSourceError` "심볼릭 링크는 허용하지 않습니다" | OK |
| NUL 포함, `%2e%2e/secret.html`, 없는 파일 | `UnsupportedSourceError` "찾을 수 없습니다" | OK |
| 빈 문자열, 디렉터리 `h` | `UnsupportedSourceError` (확장자 불일치) | OK |
| **300자 파일명** | **`FetchError`(재시도 가능)** "fixture 경로를 확인하지 못했습니다" (`ENAMETOOLONG`) | **N2** |
| `h/./1.html`, `h/1.html` | 허용, MIME `text/html` (charset 없음) | OK |
| 잘못된 UTF-8 VTT fixture / 없는 fixture 루트 | `UnsupportedSourceError` | OK |
| Router: fixture 없는 URL, `.pdf`, youtube+`.html` | `UnsupportedSourceError` | OK |

## 2. 피드백 (심각도 순)

이번 루프에는 높음·중간 결함이 없다. 아래는 모두 낮음이다.

### N1 (낮음, 정확성. Loop 2 회귀). 제목 조각을 구분자 없이 이어 붙여 여러 `h1`이나 `h1` 안 `<br>`이 한 단어로 붙는다

- `src/jupjup/ingest/extract.py:515`, `:424-425`
  - 문제: L4를 고치면서 제목 조각을 `" ".join` 대신 `"".join(parser.heading_text)`로 바꿨다. inline 요소 안 조각(`<h1>첫 <span>둘</span></h1>`)에는 맞는 처리다. 그런데 서로 다른 `h1` 요소 사이와 `h1` 안 `<br>`에는 경계가 사라진다.
  - 재현 결과:
    - `<h1>첫</h1>…<h1>둘</h1>` → `첫둘`
    - `<h1>Python<br>입문</h1>` → `Python입문`
    - 로고 `h1` + 기사 `h1` → `사이트명기사 제목`
  - 영향: `og:title`이 없는 페이지에서 `title_guess`가 오염된다. 5.10.1절은 I2 직후 "스냅샷 본문과 제목만으로 우선 인덱싱"을 한다. 그래서 형태소·n-gram 키워드 검색에 붙은 단어가 들어간다. Loop 1에서는 `사이트명 기사 제목`처럼 적어도 공백은 있었다.
- **개선 방향:**
  - `h1` 요소가 끝날 때, 그리고 `h1` 안 `<br>`에서 경계를 둔다. 예를 들어 `heading_text`를 요소 단위 리스트로 모은다.
  - 제목 후보로는 콘텐츠 루트 안의 첫 `h1`을 우선한다. 없으면 첫 `h1`, 그다음 `<title>` 순으로 고른다.
  - 회귀 테스트로 위 세 입력을 고정한다.

### N2 (낮음, 안전성). 영구적인 `OSError`가 재시도 가능 `FetchError`로 분류된다

- `src/jupjup/ingest/fetch.py:136-139`, `:158-161`
  - 문제: 영구 실패로 분류하는 대상이 `FileNotFoundError`, `NotADirectoryError`, `RuntimeError`, `ValueError`뿐이다. 나머지 `OSError`는 모두 재시도 가능으로 간다. 그런데 `ENAMETOOLONG`(300자 파일명, 재현함), `PermissionError`(`EACCES`), `ELOOP`, `IsADirectoryError`는 다시 해도 결과가 같다.
  - 보고서 1절 L1의 "일시적인 `OSError`(EIO 등)만 `FetchError`" 원칙과 실제 구현이 다르다. T22가 설계대로 연결하면 이런 입력 하나가 fetch `max_attempts=4`와 백오프를 다 쓴다. fixture 이름은 내부 입력이라 영향은 작다.
- **개선 방향:**
  - 반대로 짠다. 재시도 가능한 errno 허용 목록(`EIO`, `EAGAIN`, `EINTR`, `EBUSY`, `ETIMEDOUT` 등)만 `FetchError`로 보내고, 나머지 `OSError`는 `UnsupportedSourceError`로 보낸다.
  - 또는 `PermissionError`와 `errno.ENAMETOOLONG`, `errno.ELOOP`를 영구 쪽에 더한다.
  - 300자 이름 테스트를 `test_permanent_fixture_failures_are_unsupported_not_retryable`에 더한다.

### N3 (낮음, 정확성). `kind=youtube` + `text/plain` 입력은 첫 50줄에 타이밍 줄이 하나만 있어도 자막으로 처리된다

- `src/jupjup/ingest/extract.py:746-750`, `:814`, `:653-654`
  - 문제: `_looks_like_subtitles`는 앞 50줄 중 타이밍 줄이 **하나라도** 있으면 참이다. 그다음 `_subtitle_cues`는 타이밍 줄 바로 앞 줄을 cue id로 보고 버린다. 그래서 `"메모\n00:00:01,000 --> 00:00:02,000\n…"`에서 `메모`가 사라진다.
  - 지금은 이 조합(`kind=youtube`, 자막 MIME이 아닌 입력)을 만드는 fetcher가 없다. `FixtureTranscriptFetcher`는 항상 자막 MIME을 붙이고, `InlineTextFetcher`는 `text`/`image`만 낸다. 그래서 실제 영향은 없다. 다만 T22/T23에서 youtube 설명란 같은 경로가 생기면 그대로 드러난다.
- **개선 방향:**
  - 자막 판정 조건을 강화한다. 예: `WEBVTT` 서명이 있거나, 타이밍 줄이 2개 이상이면서 전체 블록 중 상당 비율이 타이밍 블록일 때만 자막으로 본다.
  - 또는 youtube 직접 입력은 `kind=text`로만 받는다고 T23 입력 계약에 적는다.

### R1 (낮음, 정확성. Loop 1 M2 잔여, 보고서에 적혀 있음). 상태 접미형 클래스 래퍼 안의 `<article>`은 아직 제외된다

- `src/jupjup/ingest/extract.py:263-266`, `:379-383`
  - 문제: 상태 접두형(`has-`, `no-`)은 걸러진다. 하지만 상태 접미형(`menu-open`, `nav-fixed`, `share-enabled`)은 조각 매칭에 걸린다. 그런 래퍼 안에서 되살리는 대상은 `<main>`/`role=main`뿐이다. 그래서 `<div class="menu-open"><article>…`은 영구 오류 `ExtractionError`가 된다.
  - Loop 1 재검수 조건 3은 두 입력으로 한정했으므로 조건은 충족했다. 보고서가 사이드바 티저 카드 때문에 `article`을 되살리지 않은 판단도 타당하다(재현으로 확인함).
- **개선 방향:** 제외 결과가 비었을 때만 한 번 더 시도한다. 즉 soft 제외 구간에 있던 콘텐츠 루트 텍스트를 따로 모아 두고, 본문이 0자이면 그것을 쓴다. 그러면 티저 오탐 없이 영구 실패만 막을 수 있다. T20/T22에서 실제 페이지 분포를 보고 정해도 된다.

### M-1 (낮음, 유지보수성). `extract.py`가 한 파일에 너무 많은 책임을 진다. 판단 근거가 설계서에 아직 없다

- `src/jupjup/ingest/extract.py` 전체(867줄)
  - 문제: HTML 파서, 문자 인코딩 판별, 자막(VTT/SRT/JSON) 파서와 병합, 진입점이 한 모듈에 있다. `:458-464`의 디코딩 후보 튜플은 walrus와 조건식이 중첩돼 읽기 어렵다.
  - 새 상수(`MAX_SOURCE_BYTES`, `TRANSCRIPT_SEGMENT_SECONDS`, `_MAX_REPLACEMENT_RATIO`)와 M3 계약(`tidy_snapshot_text`, `raw_meta.transcript_segments` 형식, 검색 정규화는 I8)이 아직 설계서 5.10.2절이나 6.2절에 없다. 보고서 2절에는 정직하게 적혀 있다.
- **개선 방향:**
  - Phase 3에서 `ingest/html_extract.py`, `ingest/transcript.py`, `ingest/decoding.py`로 나눈다. 디코딩 후보는 `_candidate_codecs(raw, is_html) -> list[str]` 같은 함수로 뺀다.
  - Claude-Architect가 M3 결정을 설계서에 반영한다(아래 3절 PM 조치).

### 참고 (감점 없음, T20/T22 착수 시 참고)

- **제목 블록 구분 없음.** HTML 제목(`h2` 등)과 문단이 똑같이 `\n\n` 블록으로 남는다. T20의 "HTML 제목(h1~h3) 단위 분할"이 제목과 문단을 구별해야 하면 블록 종류 힌트가 필요하다. 방법은 `raw_meta`에 제목 블록 오프셋을 넣거나, 별도 구조 필드를 두는 것이다. 지금 계약으로도 문단 단위 분할은 된다.
- **크기 상한 단위.** `_source_size`는 `str` 본문을 문자 수로 센다(`:779`). 그래서 직접 입력 한글 500만 자는 UTF-8로 약 15MB까지 통과한다. 지금은 입력 상한이 T23 API 몫이고 처리 시간도 선형이라 감점하지 않았다.
- **회귀 테스트의 시간 단언.** `tests/unit/test_ingest_extract_regressions.py:146, 163`은 1초·2초 단언이다. 실측은 0.06~0.12초라 여유가 충분하다. 다만 느린 CI에서 흔들리면 상한을 넉넉히 두거나 `@pytest.mark.slow`로 분리한다.
- **charset 판별은 앞 2KB만 본다.** 선언이 틀린 문서에서 cp949 strict가 우연히 성공하는 경우가 남는다. 보고서 4절 3번에 적혀 있다. 재현한 UTF-8+`euc-kr` 선언 입력은 정상으로 나왔다.
- **언어 추정 휴리스틱**(한글 한 글자면 `ko`)은 이전과 같다.

## 3. 채점 근거

| 항목 | 점수 | 감점 내역 |
|---|---|---|
| 정확성 (40) | **38** | H1·M1·M2·M3·L3·L4가 직접 재현으로 해결된 것을 확인했다. T19 완료 조건 4개를 모두 재현했다. 감점: N1 −1 (새 회귀, 제목 오염), R1 −0.5 (본문이 있는데 영구 실패하는 경로가 남음), N3 −0.5 (느슨한 자막 판정, 지금은 만드는 경로 없음) |
| 안전성 (30) | **29** | 경로 탈출·심볼릭 링크 차단, 네트워크 0회, 결정성, 크기 상한, 병적 JSON·HTML의 선형 처리가 모두 좋다. 감점: N2 −1 (영구 `OSError` 일부를 재시도로 분류, L1 원칙과 불일치) |
| 유지보수성 (30) | **28** | 회귀 테스트 41건이 검수 재현 입력을 빠짐없이 고정한다. format·lint·mypy 통과. 판단 기록이 정직하다. 감점: M-1 −1.5 (단일 모듈 비대, 읽기 어려운 디코딩 후보 구성), N1 회귀를 잡는 테스트 부재 −0.5 |
| **합계** | **95 / 100** | **PASS** (90점 이상) |

## 4. PASS 이후 조치 (PM 확인용)

1. **M3 결정 추인 (Claude-Architect).** 다음을 설계서 5.10.1·5.10.2절과 6.2절에 반영한다.
   - 스냅샷 `text`는 `tidy_snapshot_text`(경계 보존 가벼운 정리)로 만들고, 검색용 `normalize_text`는 I8에서 적용한다.
   - `raw_meta.transcript_segments = [{start_sec, offset}]` 형식을 적는다. 오프셋은 잘린 뒤 텍스트 기준이다.
   - 상수를 적는다: `MAX_SOURCE_BYTES = 5,000,000`, 자막 구간 180초.
   - fixture 경로 실패는 영구(`UnsupportedSourceError`)라는 분류를 적는다.
   - T22/I8 축약 인덱싱이 스냅샷 텍스트에 `normalize_text`를 꼭 적용해야 한다는 점을 T22 완료 조건에 넣는다.
2. **T20 착수 전 정리 권장 (Phase 2, 작은 수정).** N1(제목 구분자)과 N2(errno 분류)를 고친다. 각각 회귀 테스트를 1~2건 더한다.
3. **T20 설계 시 함께 정할 것.** 제목 블록 힌트(참고 1), R1 폴백, N3 자막 판정 기준.
4. **Phase 3 후보.** M-1 모듈 분리.
