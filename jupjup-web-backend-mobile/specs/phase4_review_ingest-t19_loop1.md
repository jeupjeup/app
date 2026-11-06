# Phase 4 최종 검수: 인제스트 T19(원본 수집·스냅샷 추출), Loop 1/3

- **점수:** 85 / 100
- **상태:** REJECT
- **항목별:** 정확성 32 / 40, 안전성 26 / 30, 유지보수성 27 / 30
- **루프백 대상:** Phase 2 (기능/버그 문제). 고칠 파일은 `src/jupjup/ingest/extract.py`, `src/jupjup/ingest/fetch.py`, `tests/unit/test_ingest_fetch_extract.py`다. M3는 먼저 Claude-Architect 확인이 필요하다(아래 참고).
- **검수 대상:** `phase-4-review-ingest-t19-loop1` HEAD `2cdbd49` (PM 병합). T19 구현 커밋은 `7842c67` (`feat: implement T19 offline source extraction`). 비교 기준은 직전 검수 `212629a`(T18 Loop 2, 95점 PASS)다.
- **기준 문서:** `specs/prd_and_design.md` 1.2절(범위 제외, 45줄), 5.8.1절, 5.10.1·5.10.2절(I1·I2), 5.10.4절, 5.10.8절(1364~1378줄 `SourceFetcher`·`extract_snapshot`·`clean_transcript` 시그니처), 6.2절 `snapshots`, 7.3절 T19 행과 완료 조건, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`. 구현 보고서 `specs/phase2_ingest_t19_report.md`의 주장은 모두 직접 다시 확인했다.
- **채점 정책:** 이전 검수와 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖 항목(T20 이후의 청킹·분석기·잡 큐·워커·인제스트 API, 실제 네트워크 수집, 실제 LLM 연동)은 "T20/T22 착수 시 참고"로만 적었다. fixture는 저장소 안의 정적 자산이라 신뢰도가 높다. 그래서 병적인 입력(L2)은 가볍게 감점했다.

## 0. 요약

- **잘된 점.**
  - 시그니처가 설계와 맞는다. `SourceFetcher` Protocol, Inline/FixtureHtml/FixtureTranscript fetcher, `FetcherRouter`, `extract_snapshot(raw, platform, max_chars=100_000)`, `clean_transcript`가 모두 있다.
  - 에러 코드 3개(`INGEST_FETCH_FAILED`, `INGEST_UNSUPPORTED`, `INGEST_EXTRACT_FAILED`)도 설계 그대로다.
  - 경로 탈출 차단이 탄탄하다. `..`, 절대경로, Windows 경로, 역슬래시, NUL, 파일·디렉터리 심볼릭 링크, 디렉터리 지정을 모두 막는다.
  - 네트워크 코드가 없다. 새 의존성도 없다. 결과는 결정적이다.
  - 검색 순위 무회귀를 확인했다. eval 4종이 T18 Loop 2와 소수점 4자리까지 같고, `src/jupjup/search`·`src/jupjup/query`·`data/` diff는 0줄이다.
- **T19 완료 조건 4개는 fixture와 내가 만든 입력 10건에서 모두 재현된다.** 그런데 조금만 벗어난 정상 입력에서 본문이 **조용히 사라지는** 결함이 셋 있다.
  - **H1, 자막 정리가 정상 발화를 지운다.** `Note`·`Style`·`Region`으로 시작하는 자막 줄과 그 뒤 줄들, 그리고 `Language:`·`Kind:`로 시작하는 줄이 지워진다. 또 `kind=text`라도 `platform=youtube`면 사용자가 직접 넣은 글을 자막 정리기로 돌린다. 그 결과 본문이 지워지거나 `ExtractionError`가 난다.
  - **M1, HTML void 요소 처리 누락.** `<input>`·`<embed>` 같은 void 요소를 `/>` 없이 쓰면, 그 뒤 형제 본문이 부모 태그가 닫힐 때까지 모두 사라진다. void 프레임이 스택에 계속 쌓여서 처리 시간도 제곱으로 늘어난다.
  - **M2, 감싸는 요소의 클래스 오탐.** `<body class="has-sidebar">`처럼 페이지 전체를 감싸는 요소의 클래스 조각에 걸려 본문 전체가 빠지고 `ExtractionError`가 난다.
- **설계 정합 문제(M3).** 스냅샷 본문을 검색용 `normalize_text`로 만든다. 이 함수는 소문자화, 이모지 제거, 모든 줄·문단 경계 제거를 한다. 이렇게 되면 T20의 "구조 단위 우선 분할"(5.10.4절: h1~h3, 문단, 자막 3분 구간)에 필요한 정보가 I2에서 없어진다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **692 passed, 3 deselected, 1 warning** (33.1s). 674(T18 Loop 2)에 T19 18건을 더한 값이다. 경고는 기존 Starlette `httpx` 비권장 경고다. 보고서 표의 "674 passed"는 T18 기준 숫자를 잘못 옮긴 것으로 보인다(참고) |
| `uv run pytest tests/unit/test_ingest_fetch_extract.py -q` | 18 passed |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check src/jupjup/ingest src/jupjup/domain tests/unit/test_ingest_fetch_extract.py` | **2 files would be reformatted** (`ingest/extract.py`, `ingest/fetch.py`) → L5 |
| `uv run mypy src` | Success: no issues found in 65 source files |
| `uv run jupjup eval validate` | PASS. seeds 200, queries 259(dev 158/test 101), lexicon 139. review_status ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS: R@10 0.9620, MRR 0.9958, nDCG 0.9795, category min 0.8838 (T18 Loop 2와 같음) |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589 (같음) |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860 (같음) |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720 (하한 0.972), MRR 0.9911, nDCG 0.9801 (같음) |
| `git diff 212629a..HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `git diff 212629a..HEAD --stat` | 신규 파일과 `domain/errors.py`의 클래스 3개 추가뿐이다. 기존 T18 파일·테스트는 바뀌지 않았다 |
| `grep -rn jupjup.ingest src` (ingest 밖) | 없음. 검색 경로가 새 모듈에 의존하지 않는다 |
| `grep -nE "socket\|urllib\|http\|requests\|httpx\|subprocess" src/jupjup/ingest/{fetch,extract}.py` | 없음 |

### 1.2 CLI 회귀·경계값 (`uv run jupjup seed load --db var/review.db`, 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`)

seed load 결과는 200줄, 적재 200, 인덱싱 200이다(alice 160, bob 30, carol 10). 검색 코드가 바뀌지 않았으므로 동작이 그대로인지 확인하는 목적이다. 모두 이전 검수와 같다.

| 사례 | 결과 |
|---|---|
| `성수 카페` (bob) | 2건(노티드 instagram, 카페 추천 세 곳 blog), 완화 없음. 사용자 격리 정상 |
| `성슈 카페` (오타) | 같은 2건 |
| 빈 문자열 / 201자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` |
| `!!!@@` (특수문자) | `[INVALID_QUERY] 검색할 단어가 없어요.` |
| `지난주 유튜브` (필터 전용) | 1건(1분 계란말이 쇼츠, youtube) |
| `유튜브` + `--platform instagram` (요청 잠금) | `overridden_by_request=["platforms"]`, 10건 모두 instagram |
| `경주 맛집 인스타` / `하체 운동 유튜브` (과소 완화 회귀, known_issues 1) | 각각 `platform_filter_dropped`. 정답(황리단길 blog / 하체 루틴 릴스)이 1위 |
| `경주 맛집 카톡 논문` (known_issues 2) | `platform_filter_dropped`, `content_type_filter_dropped` 둘 다 기록 |
| `python async tutorial 영상` (영어 혼합) | 0건, `no_relevant_match` (기존 동작) |
| `화성 식민지 부동산` (없는 대상) | 0건, `no_relevant_match`, `applied_relaxations=[]` (과잉 완화 없음) |
| `카페` (u_nobody) | 저장물 없음 안내 |
| `JUPJUP_MODE=recorded` `성수 카페` | `[EMBEDDING_CACHE_MISS]` (녹화본에 없는 텍스트, 기존 동작) |

### 1.3 T19 직접 재현 (스크래치 스크립트, 테스트 fixture와 다른 입력)

스크립트를 시작할 때 `socket.socket`, `socket.create_connection`, `socket.getaddrinfo`, `urllib.request.urlopen`을 호출하면 바로 예외가 나는 함수로 바꿨다. 아래 모든 사례에서 네트워크 호출은 0회였다. fixture 루트는 임시 디렉터리로 잡았다.

| 입력 | 결과 | 판정 |
|---|---|---|
| **[완료 조건] 직접 만든 HTML 10건**: `nav`/`footer`+`article`+`.ad-slot`, `header`+`main`+`aside`, `.sidebar`+`#content`+`.share-buttons`, `role=main`+`.cookie-consent`, `.entry-content`+`#comments`+`.related-posts`, `itemprop=articleBody`+`iframe`+`script`, 컨테이너 없음+`.banner`, `.story-body`+엔티티+`.sponsored`, `.post-content`+`form`+`.popup`, `article>header>h1`+`.taboola` | 10건 모두 본문만 남고 메뉴·광고·공유·댓글·관련글·쿠키·폼은 빠짐. 엔티티는 `& <태그>`로 풀림 | OK |
| HTML 메타 (`og:title`, `author`, `article:published_time` 시간대 없음, `lang="ko-KR"`) | `('OG 제목','홍길동',2026-10-01T09:00+00:00,'ko')` | OK |
| **[완료 조건] 본문 0자**: nav·script·광고만 있는 HTML / 공백만 / `[음악]`뿐인 VTT / 빈 text / 공백 OCR / 이모지만 | 모두 `ExtractionError(INGEST_EXTRACT_FAILED)` | OK |
| **[완료 조건] VTT**: `NOTE` 블록, `STYLE` 블록, cue id, `align:start` 설정, `<c.yellow>`, 인라인 타임스탬프, 누적 cue, `(박수) ♪ [Music]` | `안녕하세요 여러분 오늘은 노트북을 봅니다` | OK |
| **[완료 조건] SRT**: CRLF, `<i>`, 중복 줄, `{\an8}`, `[웃음]` | `첫 줄 둘째 줄` | OK |
| JSON `events[].segs[].utf8` + title/language | `('하나 둘 셋','영상','ko')` | OK |
| **SRT 자막 `Notebook LM 소개합니다` / `Style 팁도 알려드려요`+다음 줄 / `Regional 맛집 정리`** | **`''`** (세 cue가 모두 사라짐) | **H1** |
| SRT 자막 `Language: 한국어로 진행합니다` | **`''`** | **H1** |
| `InlineTextFetcher` `kind=text` `"NOTE 메모: 꼭 볼 영상\n주말에 다시 보기"`, platform `youtube` | **`ExtractionError`** (같은 입력을 platform `web`으로 넣으면 `note 메모: 꼭 볼 영상 주말에 다시 보기`) | **H1** |
| `<article><p>앞 문단</p><input type="checkbox"> 체크 뒤 본문이 이어집니다<p>마지막 문단</p></article>` | **`앞 문단`** (뒤 두 문장이 사라짐) | **M1** |
| `<article>` 안에 `<br>본문 줄` ×20,000 | 결과는 맞지만 **8.7초** 걸림 | M1 |
| `<div>` 50,000단계 중첩 | 결과는 맞지만 **16.9초** 걸림 | M1 |
| `<body class="has-sidebar"><article><p>진짜 본문</p></article></body>` | **`ExtractionError`** | **M2** |
| `<div class="layout no-sidebar"><main><p>진짜 본문</p></main></div>` | **`ExtractionError`** | **M2** |
| `<p>카페 <a>노티드</a>에서 <b>Python</b> 3.12 공부 😀</p>` | `카페 노티드 에서 python 3.12 공부` (조사 앞에 공백이 생기고, 소문자로 바뀌고, 이모지가 빠짐) | M3 |
| `<h2>섹션1</h2><p>문단 하나.</p><h2>섹션2</h2><p>문단 둘.</p>` | `섹션1 문단 하나. 섹션2 문단 둘.` (한 줄로 합쳐짐, 경계 정보 0) | M3 |
| `<title>진짜 제목</title>` + `<svg><title>icon</title></svg>` | title_guess `진짜 제목 icon` | L4 |
| `<meta charset="euc-kr">` + EUC-KR 바이트 | 오류 없이 `ѱ` 같은 깨진 글자가 됨 | L3 |
| JSON 자막 정수 리터럴 5,000자리 | `ValueError`가 그대로 새어 나옴 (`ExtractionError` 아님) | L2 |
| JSON 자막 배열 3,000단계 중첩 | `RecursionError`가 그대로 새어 나옴 | L2 |
| 잘못된 UTF-8 VTT | `FetchError` | OK |
| `max_chars=50`, 200자 본문 / `max_chars=0` | `(50, True)` / `ValueError` | OK |
| 같은 입력 두 번 | `SnapshotDraft` 동일 | OK |
| **[완료 조건] 경로 탈출**: `../secret.html`, `h/../../x.html`, 절대경로, `C:\x.html`, `h\1.html` | `FetchError` "안전하지 않은 fixture 경로" | OK |
| 루트 밖을 가리키는 파일 심볼릭 링크 / 디렉터리 심볼릭 링크 | `FetchError` "심볼릭 링크는 허용하지 않습니다" | OK |
| NUL 포함, 빈 문자열, `.`, 디렉터리 `h` | `UnsupportedSourceError` (확장자 불일치) | OK |
| `%2e%2e/secret.html`, 300자 파일명, 없는 파일 | `FetchError` "찾을 수 없습니다" (디코딩하지 않으므로 우회 불가) | OK |
| `h/./1.html` | 허용 (루트 안) | OK |
| fixture 루트가 없음 | `FetchError` | OK |
| Router: fixture 없는 URL, `.pdf`, youtube+`.html` | `UnsupportedSourceError` | OK |

## 2. 피드백 (심각도 순)

### H1 (높음, 정확성). 자막 정리기가 정상 발화를 지운다. 플랫폼만 보고 직접 입력한 글에도 자막 정리를 적용한다

- `src/jupjup/ingest/extract.py:301-304`
  - 문제: `upper.startswith(("NOTE", "STYLE", "REGION"))`는 단어 경계 없이 접두어만 본다. 그래서 `Notebook…`, `Notes…`, `Style 팁…`, `Regional…` 같은 **자막 본문 줄**을 메타데이터 블록 시작으로 착각한다. 그 뒤 빈 줄이 나올 때까지 같은 cue의 나머지 줄도 모두 버린다(`in_metadata_block`).
  - 또 하나: WebVTT 메타 블록은 파일 머리(첫 cue 앞)에만 올 수 있다. 그런데 이 코드는 파일 어디서든, SRT에서도 이 규칙을 적용한다.
  - 재현: SRT 3 cue가 `''`가 된다.
- `src/jupjup/ingest/extract.py:305-308`
  - 문제: `KIND:`·`LANGUAGE:`·`X-TIMESTAMP-MAP=`를 위치와 상관없이 지운다. 그래서 `Language: 한국어로 진행합니다` 같은 발화가 사라진다. 이 헤더들은 `WEBVTT` 줄과 첫 빈 줄 사이에만 있다.
- `src/jupjup/ingest/extract.py:437-443`
  - 문제: 분기 순서가 `raw.kind == "image"` → HTML → `platform == "youtube" or mime in (자막 MIME)` 이다. 그래서 `InlineTextFetcher`가 만든 `kind=text`, `mime=text/plain`인 사용자 입력도 platform이 youtube이면 `clean_transcript`를 탄다.
  - 영향: 사용자가 유튜브 저장물에 직접 쓴 메모나 설명은 다음 처리를 거치게 된다. `NOTE`로 시작하는 줄과 그 뒤 문단 삭제, 최근 3줄 안 중복 줄 삭제(`네 / 좋아요 / 네` → `네 좋아요`), `(웃음)`·`[음악]` 삭제, 단어 겹침 병합. 실제로 `"NOTE 메모: …\n주말에 다시 보기"`는 영구 오류 `ExtractionError`가 된다.
  - 자막 판정은 플랫폼이 아니라 **원본 형식**(`raw.kind`·MIME·`meta.source=fixture`)으로 해야 한다.
- **개선 방향:**
  1. WebVTT 헤더(`WEBVTT` 줄부터 첫 빈 줄까지)와 첫 cue 앞의 `NOTE`/`STYLE`/`REGION` 블록만 메타로 본다. 키워드 뒤에는 공백·줄 끝 경계를 둔다(`^NOTE(?:\s|$)`). SRT에는 적용하지 않는다.
  2. 자막 처리는 `mime ∈ {text/vtt, application/x-subrip, application/json}`일 때만 한다. 또는 `raw.kind == "youtube"`이면서 텍스트가 실제로 자막 구조를 가질 때만 한다. `kind == "text"`는 항상 일반 텍스트 경로로 보낸다.
  3. 회귀 테스트를 추가한다: `Notebook`/`Style`/`Region`/`Language:`로 시작하는 cue, 그리고 `kind=text` + youtube 플랫폼.

### M1 (중간, 정확성·안전성). HTML void 요소가 스택에서 빠지지 않아 본문이 사라지고 처리 시간이 제곱으로 늘어난다

- `src/jupjup/ingest/extract.py:165-198`
  - 문제: `HTMLParser`는 `<input>`·`<br>`·`<img>`·`<embed>`·`<meta>`·`<link>`·`<hr>`·`<source>`·`<wbr>`를 `/>` 없이 쓰면 `handle_starttag`만 부르고 `handle_endtag`는 부르지 않는다. 그런데 파서는 모든 시작 태그를 `_stack`에 넣는다. void 프레임은 조상 태그가 닫힐 때까지 남는다.
  - `input`·`embed`는 `_ALWAYS_EXCLUDED_TAGS`에 있다(`:31-36`). 그래서 이런 프레임이 남아 있는 동안 `handle_data`의 `any(frame.excluded …)`(`:207`)가 참이 된다. 그 뒤의 형제 본문은 부모가 닫힐 때까지 **모두 버려진다**. 재현에서 `앞 문단`만 남았다.
  - 비용: `handle_data`가 데이터 조각마다 스택 전체를 4번 훑는다(`:204, 207, 210, 212`). `<br>` 프레임이 쌓이면 O(조각 수 × 깊이)가 된다. 20,000줄 `<br>` 글은 8.7초, 50,000단계 중첩은 16.9초 걸렸다. I2는 비동기 단계라 지연 예산은 크다. 그래도 잡 lease는 5분이고(5.10.3절), fetch 4회 재시도와 겹치면 비싼 입력 하나로 워커를 오래 잡아 둘 수 있다.
- **개선 방향:**
  1. HTML void 요소 목록을 두고 `handle_starttag`에서 스택에 넣지 않는다.
  2. `excluded`·`content_root`·`in_title`·`in_h1`을 프레임에 누적값으로 저장한다(부모 값 OR 자기 값). 그러면 `handle_data`를 O(1)로 만들 수 있다.
  3. 파서가 처리할 입력 크기 상한(예: 디코딩 전 5MB)을 정하고, 넘으면 `ExtractionError`나 `UnsupportedSourceError`로 끊는 방안도 함께 검토한다.
  4. 테스트를 추가한다: `<input>`·`<embed>` 뒤 본문 유지, `<br>` 다수 입력의 처리 시간.

### M2 (중간, 정확성). 감싸는 요소의 클래스 조각 하나 때문에 페이지 전체가 제외된다

- `src/jupjup/ingest/extract.py:136-144, 176-186`
  - 문제: `_has_nuisance_marker`는 class/id/role/aria-label/itemprop 토큰을 `-`/`_`로 쪼갠다. 조각 중 하나라도 `sidebar`·`menu`·`nav`·`share`·`ad`…이면 그 요소 **전체와 모든 자손**을 제외한다. 그 요소가 `<body>`·`<html>`이거나 `<main>`·`<article>`을 품은 레이아웃 래퍼여도 마찬가지다.
  - 근거: WordPress 테마는 `body`에 `has-sidebar`/`no-sidebar` 클래스를 흔히 붙인다. `menu-open`, `nav-fixed`, `share-enabled` 같은 상태 클래스도 많다. 재현 두 건이 모두 영구 오류 `ExtractionError`가 됐다. 정상 본문이 있는데 저장 자체가 실패하는 경로다.
- **개선 방향:**
  - `html`/`body`와 콘텐츠 루트(`article`, `main`, `role=main`, 콘텐츠 토큰)에는 조각 매칭을 적용하지 않는다.
  - 또는 제외 판정을 "그 요소가 콘텐츠 루트를 품지 않을 때"로 늦춘다. 예: 2단계 파싱, 또는 제외 구간 텍스트를 따로 모았다가 안에서 콘텐츠 루트가 나오면 되살리기.
  - 최소한 `no-`/`has-`/`with-` 접두 상태 클래스는 제외 신호로 쓰지 않는다.
  - 회귀 테스트로 위 두 입력을 고정한다.

### M3 (중간, 설계 정합·유지보수성). 스냅샷 본문이 검색용 정규화로 손실된다. T20 구조 분할에 필요한 경계가 I2에서 사라진다

- `src/jupjup/ingest/extract.py:379, 362, 436, 441, 443, 457`
  - 문제: HTML 텍스트 조각을 `" ".join`으로 합치고(`:379`), 자막 cue도 `" ".join`으로 합친다(`:362`). 그다음 검색용 `normalize_text`를 적용한다. 이 함수는 NFKC, **소문자화**, **이모지·기호(So) 제거**, 반복 구두점 제거, **모든 공백·줄바꿈을 공백 하나로 합치기**를 한다. 조각마다 공백을 넣기 때문에 `<a>노티드</a>에서`도 `노티드 에서`가 된다.
  - 이렇게 되면 생기는 일:
    1. 5.10.4절 map_reduce 1단계 "구조 단위로 먼저 나눈다: HTML 제목(h1~h3), 문단, 자막은 시간 구간(약 3분)"이 T20에서 불가능해진다. 스냅샷에 문단·제목 경계도, cue 시각도 남지 않는다(`SnapshotDraft`에도 구조 필드가 없다). T20 완료 조건 "구조 단위 우선 분할"과 바로 부딪친다.
    2. 6.2절은 snapshots를 "원본이 사라져도 남는 저장 당시 기록"으로 정의한다. 그런데 대소문자와 이모지가 영구히 사라진다. `Python`→`python`, `제목A`→`제목a`.
    3. 분석 LLM(①, Opus)이 받는 입력 품질이 떨어진다.
  - 5.10.1절 I2에 "정규화"라고 적혀 있긴 하다. 하지만 그 "정규화"가 검색 인덱스용 `normalize_text`인지, 저장·분석용 가벼운 정리(NFC, 제어문자 제거, 줄 단위 공백 정리)인지 설계에 명시돼 있지 않다. 보고서 2절에도 이 판단이 기록되지 않았다.
- **개선 방향:**
  - Claude-Architect가 먼저 "스냅샷 정규화 수준"을 확정해야 한다. 권장은 다음과 같다.
    - 스냅샷 `text`에는 블록 경계를 `\n\n`, 제목을 별도 줄로 보존하는 가벼운 정리만 한다(NFC, 제어문자 제거, 줄 안 공백 정리).
    - 자막은 시간 구간 정보를 `raw_meta`(예: 구간별 시작 오프셋)나 줄 단위로 남긴다.
    - 검색용 `normalize_text`는 인덱싱 시점(I8)에 적용한다.
    - inline 요소(`a`, `b`, `span`, `em`, `strong` …)에서는 공백을 넣지 않고, 블록 요소 경계에서만 구분자를 넣는다.
    - `content_hash`는 확정된 스냅샷 텍스트로 계산한다.

### L1 (낮음, 안전성). 영구 실패를 "재시도 가능" `FetchError`로 분류한다

- `src/jupjup/ingest/fetch.py:110-118, 125-126, 131-134, 98-100`
  - 문제: 5.10.2절은 `FetchError`를 **재시도 가능**, `UnsupportedSourceError`를 **영구**로 정의한다. 그런데 안전하지 않은 경로(`../`, 절대경로), 심볼릭 링크, 없는 fixture, 디렉터리 지정은 모두 다시 해도 결과가 같은 영구 실패인데 `FetchError`를 낸다.
  - 영향: T22가 설계대로 연결하면 경로 탈출 시도 하나가 fetch `max_attempts=4`와 백오프(최대 5분)를 다 쓰고 나서야 `failed`가 된다.
- **개선 방향:** 경로 검증 실패와 없는 파일에는 `UnsupportedSourceError`를 쓴다. 또는 `FetchError(retryable=False)` 같은 구분을 둔다. 일시적인 `OSError`(EIO 등)만 재시도 가능한 `FetchError`로 남긴다. 테스트에서 각 경우의 에러 클래스를 고정한다.

### L2 (낮음, 안전성). JSON 자막의 병적 입력이 에러 계약 밖 예외를 낸다

- `src/jupjup/ingest/extract.py:284-290, 444-448, 250-279`
  - 문제: `json.loads`는 4,301자리를 넘는 정수 리터럴에서 `JSONDecodeError`가 아닌 순수 `ValueError`를 낸다. 깊은 중첩에서는 `RecursionError`를 낸다. 재귀 함수 `_json_transcript_lines`도 깊이 제한이 없다. 재현에서 두 예외가 `extract_snapshot` 밖으로 그대로 나왔다.
  - T18 Loop 2의 M1-n과 같은 종류다. 지금 입력원은 신뢰하는 fixture라서 영향이 작다. 하지만 I2 계약은 "`ExtractionError`(영구)"다.
- **개선 방향:** `except (ValueError, RecursionError)`로 받아 `ExtractionError`로 바꾼다(`JSONDecodeError`는 `ValueError`의 하위 클래스다). 재귀에 깊이 상한을 둔다.

### L3 (낮음, 정확성). HTML 문서 안의 charset 선언을 무시하고 깨진 글자를 조용히 만든다

- `src/jupjup/ingest/fetch.py:163-166`, `src/jupjup/ingest/extract.py:216-224`
  - 문제: HTML fixture의 MIME을 항상 `charset=utf-8`로 고정한다. 디코딩에 실패하면 `errors="replace"`로 넘어간다. 그래서 `<meta charset="euc-kr">` 문서는 오류 없이 깨진 글자가 되어 분석까지 간다.
  - 보고서는 "UTF-8 HTML fixture"를 전제로 했다. 그래도 한국어 서비스에서 EUC-KR 페이지는 흔하다. 조용히 오염되는 것보다 명시적으로 실패하는 편이 낫다.
- **개선 방향:** HTML이면 앞쪽 1~2KB에서 `<meta charset>` 또는 `http-equiv` 선언을 먼저 확인한다. replace 대체 문자 비율이 높으면 `ExtractionError`로 끝낸다.

### L4 (낮음, 정확성). 본문 안 `<svg><title>`이 문서 제목에 섞인다

- `src/jupjup/ingest/extract.py:204-206`
  - 문제: title 판정을 제외 판정보다 먼저 하고, `any(frame.tag == "title")`로 조상 어디든 title이면 받는다. 그래서 제외 대상인 `svg` 안의 `<title>icon</title>`이 `title_text`에 붙는다. 재현 결과는 `진짜 제목 icon`이다.
- **개선 방향:** `head`(또는 최상위) 안의 `title`만 문서 제목으로 받고, 제외 프레임 안은 무시한다.

### L5 (낮음, 유지보수성). 새 파일이 저장소 포맷 규칙을 지키지 않는다

- `src/jupjup/ingest/extract.py:88-90, 387-389, 473-475`, `src/jupjup/ingest/fetch.py:69-71`
  - 문제: `uv run ruff format --check` 결과 2개 파일이 재포맷 대상이다. 이전 검수(T18 Loop 2)는 변경 파일 format 통과를 확인했다. 보고서 4절에는 format 검사가 없다.
- **개선 방향:** `uv run ruff format src/jupjup/ingest`.

### L6 (낮음, 유지보수성·테스트). 테스트가 "정상 fixture 통과"에 치우쳐 있다

- `tests/unit/test_ingest_fetch_extract.py`
  - 문제: 10건 HTML 테스트는 fixture마다 **제외 문구를 1개만** 확인한다. 위 H1·M1·M2·L1·L2 같은 경계 입력이 하나도 없다.
- **개선 방향:** 위 재현 입력을 그대로 회귀 테스트로 추가한다. 추가할 것:
  - 자막: `Notebook`/`Style`/`Language:` cue, `kind=text` + youtube
  - HTML: `<input>`/`<embed>` 뒤 본문, `has-sidebar` body, svg title
  - 오류: 경로 실패별 에러 클래스, 병적 JSON
  - 성능: `<br>` 2만 줄 상한 시간

### 참고 (감점 없음, T20/T22 착수 시 참고)

- `SourceSpec`에 kind별 필수 필드 검증이 없다(예: `kind=url`인데 `fixture`·`url` 둘 다 없음). 지금은 Router의 `UnsupportedSourceError`로 정리되므로 동작상 문제는 없다. T23 API 입력 검증에서 막으면 된다.
- 직접 입력 텍스트와 OCR에는 길이 상한이 `max_chars`뿐이다. 입력 단계 상한은 T23 API에서 정한다.
- 언어 추정은 문자 존재 여부 휴리스틱이다. 한글이 한 글자만 있어도 `ko`가 된다. 보고서 5절에 한계로 적혀 있으므로 감점하지 않았다.
- `SourceKind`에 `youtube`를 더한 것과 transcript fetcher가 `kind=url`도 받는 것은 보고서 2절에 근거가 있다. 설계 표기(`text|url|image`)와 함께 Architect가 문서에 반영하기를 권한다.

## 3. 채점 근거

| 항목 | 점수 | 감점 내역 |
|---|---|---|
| 정확성 (40) | **32** | H1 −4 (정상 자막 발화와 직접 입력 본문의 조용한 손실, 영구 실패 유발), M1 −1.5 (void 뒤 본문 손실), M2 −1.5 (본문이 있는데 영구 실패), M3 −0.5 (손실 정규화. 주 감점은 유지보수성에), L3·L4 −0.5 |
| 안전성 (30) | **26** | 경로 차단·네트워크 차단·결정성은 우수하다. M1 −1.5 (제곱 시간 복잡도, lease와 재시도에 겹침), L1 −1.5 (영구 실패를 재시도 분류), L2 −1 (계약 밖 예외) |
| 유지보수성 (30) | **27** | 구조·이름·설계 시그니처 정합은 좋다. M3 −1.5 (T20 구조 분할과 설계 충돌, 판단 기록 없음), L5 −0.5, L6 −1 |
| **합계** | **85 / 100** | **REJECT** (90점 미만) |

## 4. 재검수 조건 (Loop 2 PASS 조건)

1. **H1 해결.** 다음이 모두 성립해야 한다.
   - `Notebook…`, `Style…`, `Regional…`, `Language: …`로 시작하는 SRT·VTT cue 본문이 보존된다.
   - VTT 헤더와 첫 cue 앞 메타 블록은 지금처럼 제거된다.
   - `kind=text` 입력은 platform과 상관없이 일반 텍스트 경로로 처리된다.
   - 위 경우가 회귀 테스트로 고정된다.
2. **M1 해결.** 다음이 모두 성립해야 한다.
   - `<input>`·`<embed>`·`<br>`·`<img>`를 `/>` 없이 써도 뒤따르는 본문이 보존된다.
   - `<br>` 20,000줄 입력이 1초 안쪽(현재 8.7초)에서 끝난다. 또는 크기 상한으로 명시적 오류가 난다.
   - 회귀 테스트가 있다.
3. **M2 해결.** `<body class="has-sidebar">`·`<div class="layout no-sidebar"><main>…` 입력에서 본문이 추출되고, 회귀 테스트가 있다.
4. **M3는 Architect 확정 사항을 따른다.**
   - 권장안(스냅샷은 경계 보존 가벼운 정리, 검색 정규화는 I8)으로 가면 HTML 블록·제목 경계와 inline 요소 무공백을 테스트로 고정한다.
   - 현행 유지로 확정되면 그 결정과 T20 구조 분할의 대안(예: 구조 힌트를 `raw_meta`에 보존)을 설계서에 적는다. 이 경우 감점을 회수한다.
5. L1~L5는 권장 사항이다. 다만 L1(에러 분류)과 L5(format)는 고치는 비용이 작으니 함께 처리하기를 강하게 권한다.
6. 회귀 확인: `uv run pytest`, `ruff check`, `ruff format --check`(변경 파일), `mypy src`, `eval validate`, eval 4종(mock·recorded × dev·test) 결과가 이번 수치와 같아야 한다. `src/jupjup/search`·`src/jupjup/query`·`data/` diff는 0줄이어야 한다.
