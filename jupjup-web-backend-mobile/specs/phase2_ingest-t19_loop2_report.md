# Phase 2 인제스트 T19(원본 수집·스냅샷 추출) Loop 2/3 루프백 수정 보고

- **워커:** Codex-Primary 역할. Claude가 같은 지침(`.claude/agents/codex-primary.md`)으로 실행했다.
- **기준 검수:** `specs/phase4_review_ingest-t19_loop1.md` (85점 REJECT). 브랜치 `ultra-penguin/phase-2-ingest-t19-loop2-fixes`, 베이스 `636fe8e`.
- **고친 파일:** `src/jupjup/ingest/extract.py`, `src/jupjup/ingest/fetch.py`, `tests/unit/test_ingest_fetch_extract.py`, 새 파일 `tests/unit/test_ingest_extract_regressions.py`.
- **건드리지 않은 곳:** `src/jupjup/search`, `src/jupjup/query`, `data/` (diff 0줄). 기준선, 튜닝 값, golden set은 바꾸지 않았다. test split은 재튜닝에 쓰지 않았다.

## 1. 피드백별 조치표

| ID | 조치 | 위치 | 고정한 테스트 |
|---|---|---|---|
| **H1** 자막 정리가 정상 발화를 지움 | 자막을 빈 줄 기준 블록으로 파싱한다. **VTT일 때만** 다음을 메타로 버린다: 헤더(`WEBVTT` 줄부터 첫 빈 줄까지. Kind, Language, X-TIMESTAMP-MAP 포함), 첫 cue 앞의 `NOTE`/`STYLE`/`REGION` 블록, 블록 단위 `NOTE` 주석. 키워드는 대소문자를 구분하고 뒤에 공백이나 줄 끝 경계가 있어야 한다(`^NOTE(?:[ \t]\|$)`). 타이밍 줄 뒤의 cue 본문은 첫 단어와 상관없이 보존한다. SRT에는 메타 규칙을 아예 적용하지 않는다. | `extract.py` `_subtitle_cues` | `test_srt_cues_starting_with_vtt_keywords_are_kept` (Notebook/Style+다음 줄/Regional/Language:/Kind:), `test_vtt_header_and_pre_cue_metadata_blocks_are_still_removed` |
| **H1** 플랫폼만 보고 자막 정리 적용 | 경로를 **원본 형식**으로만 고른다. 분기 순서는 `image` → `kind=text`(항상 일반 텍스트) → HTML(MIME, 또는 `kind=url`일 때 태그로 판별) → 자막(MIME이 vtt/subrip/json이거나, `kind=youtube`이면서 실제 자막 구조가 있을 때) → 일반 텍스트. `platform`은 이제 오류 details에만 쓴다. | `extract.py` `extract_snapshot` | `test_direct_text_never_goes_through_subtitle_cleaner` (youtube/instagram/web), `test_youtube_plain_text_without_subtitle_structure_uses_plain_path` |
| **M1** void 요소가 스택에 남음 | void 요소(`br`, `img`, `input`, `embed`, `meta`, `link`, `hr`, `source`, `wbr` 등)는 스택에 넣지 않는다. 프레임에 `excluded`, `in_content`, `in_title`, `in_h1`, `in_pre`를 누적값으로 저장해 `handle_data`를 O(1)로 만들었다. 태그별 열린 개수(`Counter`)를 세서, 열려 있지 않은 태그의 닫는 태그는 스택을 훑지 않고 바로 무시한다. 같은 형제 태그가 이어지면(`<p>a<p>b`, `<li>`) 앞의 것을 암묵적으로 닫는다. 디코딩 전 입력 상한은 `MAX_SOURCE_BYTES = 5,000,000`이고, 넘으면 `ExtractionError`다. | `extract.py` `_ArticleParser` | `test_void_elements_without_slash_keep_following_body` (input/embed/br/img), `test_many_br_lines_finish_quickly` (< 1초), `test_deep_nesting_finishes_quickly`, `test_stray_end_tags_do_not_scan_the_whole_stack`, `test_oversized_source_fails_explicitly` |
| **M2** 감싸는 요소 클래스 오탐 | (1) `html`과 `body`에는 클래스 조각 매칭을 하지 않는다. (2) `has-`, `no-`, `with-`, `is-`, `show-`, `hide-` 등으로 시작하는 상태 클래스는 제외 신호로 보지 않는다. (3) 콘텐츠 루트(article, main, role=main, 콘텐츠 토큰)는 토큰 전체가 일치할 때만 제외한다(`post related`는 여전히 제외). (4) 클래스 때문에 제외된 래퍼("soft" 제외) 안의 `<main>`/`role=main`은 되살린다. `aside`, `nav`처럼 태그 자체로 제외되는 영역은 되살리지 않는다. | `extract.py` `_has_nuisance_marker`, `_start` | `test_layout_wrapper_classes_do_not_drop_the_page` (5건: 검수 재현 2건 포함), `test_real_nuisance_regions_are_still_excluded` |
| **M3** 스냅샷 손실 정규화 | 검수 권장안대로 구현했다(아래 2절 참고, Architect 추인 필요). 스냅샷 `text`에는 `tidy_snapshot_text`만 적용한다. NFC, 제어문자와 서식 문자 제거(ZWJ는 남김), 줄 안 공백 정리, 빈 줄 연속을 하나로 줄이기까지만 한다. 대소문자, 이모지, 전각 문자는 보존한다. HTML은 블록·제목 경계를 `\n\n`으로, `<br>`을 `\n`으로 남긴다. inline 요소(`a`, `b`, `span` 등) 경계에는 공백을 넣지 않는다. 자막은 약 3분(`TRANSCRIPT_SEGMENT_SECONDS=180`) 구간마다 `\n\n`으로 나누고, 구간 시작 시각과 문자 오프셋을 `raw_meta["transcript_segments"]`에 남긴다(JSON `tStartMs`/`start`도 지원). `content_hash`는 최종 스냅샷 텍스트로 계산한다. "본문 0자" 판정은 계속 `normalize_text` 결과로 한다. 그래서 공백, 이모지, `[음악]`뿐인 입력은 지금처럼 `ExtractionError`다. | `extract.py` | `test_html_snapshot_keeps_block_and_heading_boundaries`, `test_inline_elements_do_not_insert_spaces_and_case_emoji_survive`, `test_snapshot_cleanup_is_light_and_hash_tracks_final_text`, `test_transcript_snapshot_is_split_into_three_minute_segments`, `test_json_transcript_segments_use_tstartms`, `test_bodies_without_searchable_text_still_fail`, `test_music_only_vtt_still_fails` |
| **L1** 영구 실패를 재시도 가능으로 분류 | 다음 경우는 `UnsupportedSourceError`(영구)로 바꿨다: 안전하지 않은 경로, 심볼릭 링크, 없는 파일, 디렉터리 지정, 루트 밖 해석, fixture 루트 없음, UTF-8이 아닌 자막 fixture. 일시적인 `OSError`(EIO 등)만 `FetchError`(재시도 가능)로 남긴다. | `fetch.py` | `test_permanent_fixture_failures_are_unsupported_not_retryable` (9개 경로 + 없는 루트), `test_invalid_utf8_transcript_fixture_is_permanent`, `test_transient_io_error_stays_retryable`. 기존 경로 탈출 테스트의 기대 클래스도 바꿨다 |
| **L2** JSON 병적 입력 | `json.loads`의 `ValueError`(긴 정수)와 `RecursionError`를 `ExtractionError`로 바꾼다. `JSONDecodeError`는 지금처럼 텍스트 자막 파싱으로 넘어간다. 재귀 깊이 상한은 64다. | `extract.py` `_load_json`, `_json_transcript_cues` | `test_pathological_json_transcripts_raise_extraction_error` (5,000자리 정수, 3,000단계, 100단계) |
| **L3** charset 무시 | 디코딩 후보를 BOM → MIME charset → (HTML) 앞 2KB의 `<meta charset>`/`http-equiv` → UTF-8 순으로 strict하게 시도한다. `euc-kr` 계열은 WHATWG처럼 `cp949`로 읽는다. 모두 실패하면 replace로 디코딩하되, 대체 문자 비율이 1%를 넘으면 `ExtractionError`다. fixture HTML MIME에서 근거 없는 `charset=utf-8`을 뺐다. | `extract.py` `_decode_body`, `fetch.py` | `test_meta_charset_euc_kr_is_honoured` (MIME utf-8 표기가 있어도 성공), `test_http_equiv_charset_is_honoured`, `test_undecodable_bytes_fail_instead_of_silent_mojibake`, `test_fixture_html_mime_does_not_claim_a_charset` |
| **L4** svg title이 제목에 섞임 | `svg`/`math` 안의 `title`은 문서 제목으로 받지 않는다. 제목 텍스트를 조각 사이 공백 없이 이어 붙이고 공백을 정리한다. | `extract.py` | `test_svg_title_does_not_leak_into_document_title` |
| **L5** 포맷 | `ruff format`을 적용했다. 변경 파일 4개 모두 `already formatted`다. | — | — |
| **L6** 테스트 편중 | 위 재현 입력을 모두 회귀 테스트로 고정했다. 새 파일에 41개다. | `tests/unit/test_ingest_extract_regressions.py` | — |

## 2. 설계와 달라진 점, 판단 기록

1. **M3 정규화 수준(Architect 추인 필요).** 검수 4절의 조건은 "Architect 확정 사항을 따른다"였다. 그런데 이 루프 시작 시점에 Architect의 확정 기록이 없었다. 그래서 검수 권장안(스냅샷은 경계를 보존하는 가벼운 정리, 검색 정규화는 I8)으로 구현했다. 이유는 셋이다.
   - T20의 "구조 단위 우선 분할"을 막지 않는다.
   - 6.2절 "저장 당시 기록" 정의에 맞는다.
   - 나중에 현행안으로 되돌리기도 쉽다(I8에서 `normalize_text`를 한 번 더 부르면 된다).

   설계서 5.10.1절 I2의 "정규화" 문구는 수정하지 않았다(Architect 담당). PM이 이 결정을 추인하고 설계서에 반영해야 한다. 함께 정할 것: 이 결정과 `raw_meta.transcript_segments`(`[{start_sec, offset}]`, 오프셋은 잘린 뒤 텍스트 기준) 형식, 그리고 T22/I8이 스냅샷 텍스트로 인덱싱할 때 `normalize_text`를 적용해야 한다는 점.
2. **기존 테스트 기대값 두 건을 바꿨다**(의도한 계약 변경). 하나는 경로 탈출이 `FetchError`가 아니라 `UnsupportedSourceError`라는 점(L1)이다. 다른 하나는 직접 입력 `"  Hello   WORLD  "`의 결과가 `"hello world"`가 아니라 `"Hello WORLD"`라는 점(M3)이다. 나머지 T19 테스트 16개와 fixture 10건의 기대값은 그대로 통과한다.
3. **잘못된 UTF-8 자막 fixture는 영구 실패로 바꿨다.** 검수표는 이 경우 `FetchError`를 "OK"로 적었다. 하지만 L1 원칙(다시 해도 같은 결과는 영구)에 맞춰 `UnsupportedSourceError`로 바꿨다. fixture 루트가 없을 때도 같다.
4. **추출 경로에서 `platform`을 쓰지 않는다**(H1). `extract_snapshot` 시그니처는 그대로 두었다.
5. **입력 크기 상한 5MB**(`MAX_SOURCE_BYTES`)를 새로 넣었다. 설계서에 없는 값이라 T22/T23에서 설정으로 옮길지 정해야 한다.

## 3. 실행 결과 (모두 이 브랜치에서 직접 실행)

### 3.1 기본 설치 (`uv sync`)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **733 passed, 3 deselected, 1 warning** (33.4s). Loop 1 검수의 692에 새 회귀 41건을 더한 값이다. 경고는 기존 Starlette `httpx` 경고다 |
| `uv run pytest tests/unit/test_ingest_fetch_extract.py tests/unit/test_ingest_extract_regressions.py` | 59 passed (18 + 41) |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check src/jupjup/ingest tests/unit/test_ingest_fetch_extract.py tests/unit/test_ingest_extract_regressions.py` | 7 files already formatted |
| `uv run mypy src` | Success: no issues found in 65 source files |
| `uv run jupjup eval validate` | PASS (exit 0). seeds 200, queries 259, review_status ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| eval 4종 | 아래 3.3 표. 모두 PASS |

### 3.2 extra 설치 (`uv run --extra local-models`, sentence-transformers 5.7.0, torch 2.15.0, `JUPJUP_BGE_CACHE_DIR=…/phase-2-real-embedding/var/models`)

| 명령 | 결과 |
|---|---|
| `pytest` | 733 passed, 3 deselected (34.1s) |
| `pytest -m "embed or rerank"` | **3 passed**, 733 deselected (46.9s). 실제 bge-m3와 reranker 추론이다 |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 65 source files |
| `jupjup eval validate` | PASS (exit 0) |
| eval 4종 | 기본 설치와 소수점 4자리까지 같다. 모두 PASS |

확인을 마친 뒤 `uv sync`로 기본 환경으로 되돌렸다.

### 3.3 지표 전후 (순위 판정 기준은 recorded, mock은 안전 지표)

| 모드 / split | 지표 | Loop 1 검수(전) | Loop 2(후) | 기준선 하한 | 판정 |
|---|---|---|---|---|---|
| **recorded / dev** | R@10 · MRR · nDCG · cat_min | 0.9712 · 1.0000 · 0.9860 · 0.8894 | 0.9712 · 1.0000 · 0.9860 · 0.8894 | 0.956457 · 0.99 · 0.969304 | PASS, 변화 없음 |
| **recorded / test** | R@10 · MRR · nDCG · cat_min | 0.9720 · 0.9911 · 0.9801 · 0.8900 | 0.9720 · 0.9911 · 0.9801 · 0.8900 | 0.972 · 0.976667 · 0.97075 | PASS, 변화 없음 |
| mock / dev | R@10 · MRR · nDCG · cat_min | 0.9620 · 0.9958 · 0.9795 · 0.8838 | 0.9620 · 0.9958 · 0.9795 · 0.8838 | 0.943571 · 0.981597 · 0.964195 | PASS, 변화 없음 |
| mock / test | R@10 · MRR · nDCG · cat_min | 0.9420 · 0.9867 · 0.9589 · 0.7812 | 0.9420 · 0.9867 · 0.9589 · 0.7812 | 0.932 · 0.976667 · 0.948865 | PASS, 변화 없음 |

- `git diff HEAD -- src/jupjup/search src/jupjup/query data | wc -l` 결과는 **0**이다. 인제스트 모듈은 검색 경로에서 쓰이지 않는다. 그래서 순위 지표가 같은 것이 예상한 결과다.
- recorded test R@10은 0.9720으로, 하한 0.972와 같은 값에서 통과했다. Loop 1과 같은 값이며 여유는 없다. 하한은 낮추지 않았다.

### 3.4 CLI·직접 재현 (스크래치, 네트워크 함수 차단)

- `seed load` 결과는 200건(alice 160, bob 30, carol 10)이다.
- 검색 결과는 이전과 같다.
  - `성수 카페`(bob): 2건(노티드, 카페 추천 세 곳)
  - `경주 맛집 인스타`(alice): 황리단길 1위, `platform_filter_dropped`
  - `하체 운동 유튜브`(alice): 하체 루틴 릴스 1위, `platform_filter_dropped`
  - `화성 식민지 부동산`: 0건, 완화 없음
- 검수 1.3절의 HTML 10종 조합을 다시 만들어 돌렸다. 10건 모두 본문만 남았다(nav, footer, ad-slot, aside, sidebar, share, cookie, comments, related, iframe, script, banner, sponsored, form, popup, taboola 제외). 엔티티는 `& <태그>`로 풀린다.
- 메타 추출은 `('OG 제목','홍길동',2026-10-01T09:00+00:00,'ko')`로 이전과 같다. `max_chars=50`은 `(50, True)`다.
- fixture 10건의 출력은 이제 제목과 문단이 `\n\n`으로 나뉜다. 예: `첫 번째 기사\n\n성수동에 …\n\n주말에는 …`. 제외 문구는 하나도 섞이지 않는다.

## 4. 남은 문제 (숨기지 않음)

1. **M3는 Architect 추인 전이다.** 2절 1번을 보라. 추인되지 않고 현행안으로 돌아가면 `extract_snapshot`의 tidy를 `normalize_text`로 바꾸고 회귀 테스트 5건을 고쳐야 한다.
2. **M2는 일부만 해결했다.** 클래스로 제외된 래퍼 안에서 되살리는 대상은 `<main>`/`role=main`뿐이다. 그래서 `<div class="menu-open"><article>…</article></div>`처럼 body가 아닌 래퍼에 상태 접미형 클래스(`menu-open`, `nav-fixed`)가 붙고 그 안에 `<article>`만 있으면 지금도 빠진다. `article`까지 되살리면 사이드바 안의 티저 카드(`<div class="sidebar"><article>`)가 본문에 섞인다. 그래서 일부러 제외했다. 근본 해결은 2단계 파싱(제외 구간 텍스트를 따로 모았다가 판단)이다. T20/T22에서 실제 페이지 분포를 보고 정하기를 권한다.
3. **charset 판별은 앞 2KB만 본다.** `<meta charset>`이 2KB 뒤에 있거나 선언이 틀린 문서(UTF-8인데 `euc-kr` 선언)는 cp949 strict 디코딩이 우연히 성공하면 깨진 글자가 될 수 있다. 브라우저 동작과 같은 한계다.
4. **표 셀(`td`/`th`)은 공백으로, 행(`tr`)은 블록으로 나눈다.** 표 구조를 더 보존해야 하면 T20에서 정한다.
5. **VTT 중간의 `NOTE` 블록은 주석으로 버린다**(WebVTT 명세상 주석). 타이밍 줄 없이 놓인 그 밖의 텍스트 블록은 관대하게 직전 cue 시각으로 보존한다.
6. **언어 추정 휴리스틱은 바꾸지 않았다.** 한글이 한 글자만 있어도 `ko`가 된다. 이전 보고서에 적은 한계 그대로다.
7. **5MB 상한과 3분 구간 길이는 코드 상수다.** 설정으로 뺄지는 T22에서 정한다.
8. **사람 검수는 0건이다**(review_status 변화 없음). 범위 밖이다.
