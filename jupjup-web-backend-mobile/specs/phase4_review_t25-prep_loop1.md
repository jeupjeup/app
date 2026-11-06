# Phase 4 최종 검수: T25 선행 정리(T25a), Loop 1/3

- **점수:** 96 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 30 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 낮음 항목 L-a·L-c는 T25g(판정기, 같은 분리기를 씀) 때, L-b는 T25e(논문 메타 초록을 채우게 될 때) 같이 정리하기를 권한다.
- **검수 대상:** `PM` 병합 커밋 `0b80f1e` (구현 `affc5af fix: complete T25a ingest prep cleanup`), 기준 `695cb6c` (T25 설계 커밋)
- **검수자:** Claude-Reviewer 역할 대행 (Claude). 코드는 고치지 않았다. 실험은 스크래치 스크립트, `var/review.db`, `var/review_old.db`, `var/rt25/`에서 했다.
- **범위 밖:** T25 로컬 분석기 구현, L4 녹화 키(채점 대상 아님. 다만 구현돼 있어 기존 녹화를 깨지 않는지만 확인), 리랭커 채택. 사람 검수 미완료(`ai_draft_unreviewed` 235건)는 감점하지 않았다.

## 0. 한 줄 판정

T24 Loop 2 N1(소수점·버전·점 날짜·약어 경계)과 hardening L1·L2·L3·L5를 **검수 문서의 재현 입력 그대로 다시 넣어 해소를 확인했다.** `증감률 6.5%를 공개했다.`는 한 문장·후보 0, 정상 골든 mock all의 비충실 후보는 5/80 → 0/80, 중복 문장은 위치 단위로 1.0(2/2)·0.667(2/3), `This`/`The`/`It`는 후보가 아니고 `Apple`은 `pineapple`로 근거가 생기지 않는다. 제자리 제목 수정은 같은 `updated_at`에서도 해당 사용자의 요약값만 바꾸고, 트리거 없는 옛 DB도 열 때 자동으로 트리거가 생긴다. pytest 944 passed, ruff·mypy 통과, 인제스트 mock 3 split PASS·두 번 실행 6/6 바이트 동일, 검색 eval 4종이 이전 검수와 소수점 4자리까지 같고 `src/jupjup/search`·`src/jupjup/query`·`data/` diff는 0줄이다. 남은 것은 분리기의 반대 방향 경계(진짜 문장 끝의 `no.`를 약어로 보고 두 문장을 합침)와 초록 경계의 반대 방향 구두점 차이 같은 **낮음** 항목뿐이다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **944 passed, 3 deselected**, 1 warning(기존 Starlette/httpx deprecation), 270.7s. 보고서 수치와 같다 (시간 차이는 기기 부하) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 78 source files |
| `uv run ruff format --check <이번 diff의 .py 18개>` | 18 files already formatted. hardening L5가 지적한 `index/service.py`, `storage/repositories.py` 포맷 차이 해소 |
| `uv run ruff format --check src tests` | 9 files would be reformatted. 이번 diff 밖의 기존 파일(검색 코드 포함)이라 감점하지 않음 (보고서 5절에 명시) |
| `git diff --check 695cb6c 0b80f1e` | 통과 |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259 (dev 158, test 101), 인제스트 sources/annotations 80/80 (dev 48, test 32), 플랫폼군 분포 이전과 같음 |

### 1.2 인제스트 평가와 결정성

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all --out var/rt25/a` | 세 split 모두 PASS, 종료 0 |
| 같은 명령을 `--out var/rt25/b`로 다시 실행 후 `cmp` 6개 파일 | **6/6 바이트 동일** |
| all 리포트 `config` | `sources_path: data/golden/ingest/sources.jsonl`, `annotations_path: …/annotations.jsonl`, `baseline_path: data/baselines/ingest.mock.json`. **상대 POSIX 경로** (T24 L-5 해소) |
| all 리포트 항목 | `unsupported_sentences`가 있는 항목 **0 / 80**, 항목 최대 비율 0 (수정 전 5건 0.6667). overall `schema_first_pass_rate 0.925`, `schema_final_pass_rate 1.0`, `injection_resistance 1.0` (수정 전과 같음) |
| `git diff 6554b6e 0b80f1e --stat -- data/` | 0줄. `data/baselines/ingest.mock.json` 마지막 변경은 `054b002`(T24) |

**ingest.mock 기준선을 바꾸지 않은 사유 확인:** 기준선 파일에는 split별 `schema_final_pass_rate`, `injection_resistance`, `counts.sources`만 들어 있다. 이번 정리로 바뀐 값은 항목별 `unsupported_sentence_rate`뿐이고 기준선이 담는 세 값은 그대로다(위 표). 갱신하지 않은 판단이 맞다.

**빈 주입 집합:** `accuracy([])`는 `None`. 기준선이 있는 dev 설정에서 `_gate({"schema_final_pass_rate": 1.0, "injection_resistance": None})`를 직접 불러 `passed=False`, `injection_resistance None False` 확인. 회귀 비교는 `None`이면 건너뛰지만 절대 기준에서 이미 실패하므로 공허 통과는 없다 (`ingest_harness.py:740-758`).

### 1.3 검색 무회귀

- `git diff --stat 695cb6c 0b80f1e -- src/jupjup/search src/jupjup/query data/` → **0줄**. `src/` 변경은 `eval/{ingest_harness,ingest_metrics,ingest_report,judge}.py`, `index/service.py`(포맷 1곳), `ingest/{chunking,validation}.py`, `providers/recording.py`, `storage/{db,repositories,tables}.py`뿐이다.

| 모드 / split | 판정 | R@10 | R@5 | MRR@10 | nDCG@10 | cat min | true / false empty |
|---|---|---|---|---|---|---|---|
| mock / dev | PASS | 0.9620 | 0.9419 | 0.9958 | 0.9795 | 0.8838 | 1.0 / 0.0 |
| mock / test | PASS | 0.9420 | 0.9281 | 0.9867 | 0.9589 | 0.7812 | 1.0 / 0.012 |
| recorded / dev | PASS | 0.9712 | 0.9495 | 1.0000 | 0.9860 | 0.8894 | 1.0 / 0.0 |
| recorded / test | PASS | 0.9720 | 0.9541 | 0.9911 | 0.9801 | 0.8900 | 1.0 / 0.0 |

T24 Loop 2 검수 1.8절과 소수점 4자리까지 같다.

### 1.4 CLI 검색 경계값 (`uv run jupjup seed load --db var/review.db` → 200건, `search --db var/review.db --now 2026-10-15T12:00+09:00 --json`, `JUPJUP_MODE=mock|recorded`)

| 질의 | mock | recorded | 비고 |
|---|---|---|---|
| `성수동 카페` (u_alice) | 블로그·이미지·유튜브·카톡 성수 카페 상위 | 이미지·블로그·카톡·인스타 성수 카페 상위 | 정상 (회귀 사례) |
| `성수동 까페` (오타) | 위와 같은 상위 4건 | `EMBEDDING_CACHE_MISS`, 종료 2 | 녹화본 밖 질의 캐시 미스는 기존 동작 |
| `""` / `카페 ×100`(299자) | `INVALID_QUERY 1~200자`, 종료 2 | 같음 | 빈 문자열·긴 질의 정상 |
| `!!!@@@###` | `INVALID_QUERY 검색할 단어가 없어요`, 종료 2 | 같음 | 특수문자 정상 |
| `seongsu cafe 디저트` (영어 혼합) | 성수 어니언 신메뉴, 애월 디저트 카페 2건 | 캐시 미스 | 기존과 같음 |
| `지난주 저장한 영상` | 하체 루틴 릴스, 계란말이 쇼츠 2건 | 같음 | 시간 필터 정상 |
| `화성 우주정거장 맛집` (없는 대상) | **0건** | 캐시 미스 | 과잉 완화 없음 |
| `인스타 --platform youtube` (요청 잠금) | youtube만 10건 | 같음 | 요청 필터가 질의 플랫폼을 이김 |
| `유튜브 --platform youtube --limit 50` (필터 전용) | youtube 30건 전부 | 같음 | 정상 |
| `유튜브에서 본 파스타 레시피` | 파스타 3건 + 레시피 영상 (5건) | 7건, 파스타 3건 상위 | 과소 완화 없음 |
| `작년에 저장한 논문` | 2025년 논문 9건 | 같음 | 정상 |
| u_bob `카페 --limit 50` | 자기 콘텐츠 2건 | 같음 | 사용자 격리 유지 |
| u_nobody `카페` | 0건 | 0건 | 격리 유지 |

검색 결과는 이전 검수들과 같다. 검색 도중 `index_revisions`가 u_alice 1598 → 1918, u_bob 286 → 346으로 오른 것을 보고 따로 추적했다. recorded 모드 첫 검색이 `bge-m3` 임베딩을 사용자별로 한 번 채워 넣은 쓰기였다(`embeddings`에 u_alice bge-m3 320행, u_bob 60행, 검색하지 않은 u_carol은 0행이고 revision도 92 그대로). 이후 같은 질의를 mock/recorded로 4번 더 돌려도 revision은 그대로였다. **읽기 전용 검색은 revision을 올리지 않는다.**

## 2. 재현 절차로 해소 확인

### 2.1 T24 N1·L-1·L-2 (`judge.py`, T24 Loop 2 검수 1.5절 원문·입력 그대로)

원문: `서울시가 2026년 10월 06일 교통 예산 1302억원을 발표. 참여 기관 37곳과 증감률 6.5%를 공개. Samsung Galaxy 출시. 버전 3.14와 v2.1, 2026.10.06 공지. Apple pineapple`, forbidden `참여 기관 76곳`.

| 요약 | 문장 분리 | 후보 / 비율 | 판정 |
|---|---|---|---|
| `증감률 6.5%를 공개했다.` | 1문장 | 0 / 0.0 | **N1 해소** (전: 2조각, 1.0) |
| `버전 3.14가 나왔다.` | 1문장 | 0 / 0.0 | **N1 해소** |
| `2026.10.06에 v2.1 공지.` | 1문장 | 0 / 0.0 | **N1 해소** (점 날짜·버전) |
| `e.g. 서울시 발표. Dr. Kim 발표.` | 2문장 (`e.g.`, `Dr.`에서 안 자름) | `Dr. Kim 발표.`만 (Kim이 원문에 없음) | 약어 경계 정상 |
| `총 37곳.2026년 10월 06일 발표.` | 2문장 | 0 | 숫자 앞 마침표·한글 뒤는 끝으로 봄. 정상 |
| `기다렸다... 다음은 Samsung.` / `기다렸다… 다음.` / `끝났다!? 정말.` | 2 / 2 / 2문장 | 0 | ASCII·유니코드 말줄임표, 겹친 종결부호 정상 |
| `기관 99곳. 기관 99곳. 좋다.` | 3문장 | 2 / **0.667** | **L-1 해소** (전: 0.333) |
| `참여 기관 76곳이다. 좋다.` | 2문장 | forbidden → **1.0** | 규칙 유지 |
| `This is fine. 서울시 발표.` / `The Galaxy launched. It works.` / `Our team. We did. In 2026년 10월 06일. A test. An idea.` | 2 / 2 / 5문장 | 모두 0 | **L-2 해소** (불용어 8개) |
| `apple 출시.` / `SAMSUNG 출시.` | 1문장 | 0 | 대소문자 무시 비교 |
| `Tesla 발표. pineapple.` | 2문장 | `Tesla 발표.`만 | 정상 |
| 원문 `pineapple sales increased.`, 요약 `Apple released a product.` (테스트 입력) | — | 후보, missing `Apple` | **L-2 단어 경계 해소** |
| `예산 130억원 발표.` | 1문장 | 후보 (`130`) | T24 L1 수정 유지 |
| `""` | 0문장 | 0.0 | 정상 |

### 2.2 hardening L1 (제자리 수정 감지, `storage/db.py`, `repositories.py`)

`var/review.db`(시드 200건)에서 `SqlContentRepository.index_fingerprint`를 직접 비교했다.

| 실험 | 결과 |
|---|---|
| sqlite3로 u_alice 콘텐츠 1건의 `title`만 수정(`updated_at`·행 수 그대로) | u_alice 요약값 **바뀜**, u_bob 요약값 그대로 (사용자 격리) |
| 같은 사용자 요약 `text`만 제자리 수정 | 바뀜 |
| 콘텐츠 삭제(FK cascade) | 바뀜 (contents 삭제 트리거. 자식 삭제 트리거는 부모가 이미 없어 아무것도 안 넣는데, 부모 쪽이 올리므로 문제없음) |
| DB 사본에서 트리거 18개와 `index_revisions` 표를 지운 뒤 `create_db_engine`으로 다시 열기 | 표·트리거 18개 다시 생성, 요약값 `(0, 159, …)`로 정상 (옛 DB 호환) |
| 테스트 `test_in_place_content_edit_with_same_updated_at_is_reloaded` | API 서버 + 별도 워커 구성에서 같은 `updated_at` 제목 수정이 다음 `/v1/search`에 반영. 통과 |

### 2.3 hardening L2 (초록 경계, `chunking.py`)

| 초록 / 본문 | 결과 | 판정 |
|---|---|---|
| `이 논문은 초록이다.` / `이 논문은 초록이다.이어붙음` | 중복 없음 | **해소** (원 재현) |
| `이 논문은 초록이다.` / `이 논문은 초록이다` | 중복 없음 | **해소** (원 재현) |
| `이 논문은 초록이다.` / `이 논문은 초록이다!\n\n서론` | 중복 없음 | 해소 |
| `이 논문은 초록이다.` / `이 논문은 초록이다만 다르다.` | 앞에 붙임 | 단어 접두 오인 거부 유지 (의도) |
| `이 논문은 초록이다` (초록 쪽 마침표 없음) / `이 논문은 초록이다.\n\n서론 본문` | **두 번** | 반대 방향 구두점 차이 남음 (L-b) |
| `이 논문은 초록이다` / `이 논문은 초록이다. 서론 본문` | **두 번** | 같음 (L-b) |
| `이 논문은 초록이다.` / `이 논문은 초록이다\n서론 본문` (마침표 없음 + 줄바꿈 1개) | **두 번** | 남음 (L-b) |

검수 L2가 든 재현 두 가지는 해소됐다. 다만 L2 권고("양쪽 끝 종결부호를 떼고 비교")와 달리 초록 쪽만 떼서 반대 방향은 남았다. 지금 `src`에는 `ContentMeta.abstract`를 채우는 코드가 없어 실제 영향은 없다.

### 2.4 hardening L3 (테스트 공백)

`test_reload_user_matches_full_reindex_rankings`(시드 전체, `reindex_all` 상태 = `reload_user` 상태), `test_refresh_detects_each_index_input_changed_in_place`(contents·snapshots·summaries·tags·detail_tags·embeddings 등 성분별 제자리 수정), `test_separate_worker_refusal_keeps_reduced_i2_content_searchable`(별도 워커에서 refusal → `needs_review`, 같은 API 서버에서 I2 키워드로 찾힘) 세 테스트가 추가돼 있고 1.1절 실행에서 통과했다. 검수 L3의 (a)(b)(c)를 모두 덮는다. **해소.**

### 2.5 hardening L5 (런타임 `assert`)

- `validation.py`: `_parse_json_object`가 `_ParsedObject | _ParseFailure`를 돌려주고 `isinstance`로 좁힌다. `assert` 없음.
- `recording.py`: `complete_json` 재생은 `LLMRawResponse`가 아니면 `None`→`LLMCacheMiss`, 다른 타입→`LLMProviderError`. `count_tokens`는 `int`가 아니거나 `bool`이면 `LLMProviderError`. `assert` 없음.
- `uv run python -O`로 L4 지문 실험 스크립트(아래)를 돌려 정상 동작 확인. **해소.**

### 2.6 (범위 밖, 안전 확인만) hardening L4 스키마 지문

`python -O`로 직접 만든 모델 쌍을 비교했다: docstring·description·title·default만 바뀌면 같은 지문, `ge` 제약·enum 값·Optional 여부가 바뀌면 다른 지문, 필드 이름이 `title`·`description`인 모델의 타입 변경도 다른 지문(`properties` 아래 이름은 지우지 않음). `data/recordings`에는 임베딩·리랭커 녹화만 있고 LLM 녹화는 없어 이 변경으로 무효화되는 녹화는 없다. 채점하지 않았다.

## 3. 설계 대조 (`specs/design_local_analyzer.md` 9절 T25a 완료 조건)

| 조건 | 판정 |
|---|---|
| `pytest`, `ruff check`, `mypy src` 통과 | 충족 (1.1) |
| `eval ingest --mode mock --split dev\|test\|all` PASS, 두 번 실행 바이트 동일 | 충족 (1.2) |
| 바뀌는 수치는 N1·L-1로 인한 항목별 `unsupported_sentence_rate`뿐, 보고서에 전후 | 충족. 보고서 3.1절 전후 표, 1.2절에서 overall 동일 확인 |
| 검색 eval 4종 수치 동일, `src/jupjup/search`·`src/jupjup/query` diff 0 | 충족 (1.3) |
| N1 단위 테스트 4종 + v1 mock all `unsupported_sentences` 0건 회귀 단언 | 충족. `test_sentence_splitter_preserves_internal_periods_and_real_boundaries` 4 param, `tests/eval/test_ingest_regression.py:27`. 테스트 param은 dev·test 두 split이지만 합치면 all 80건과 같은 항목이고, all은 1.2절에서 직접 0/80 확인 |
| L-1 위치 기준, L-2 불용어 8개·대소문자 무시, L-5 상대 경로·`None` 게이트 실패 | 충족 (2.1, 1.2) |

## 4. 피드백 (심각도 순)

중간 이상 결함은 찾지 못했다.

### L-a. [낮음] 약어 목록이 진짜 문장 끝을 삼켜 두 문장을 하나로 합친다 — `src/jupjup/eval/judge.py:16-34`, `:141-154`
- **재현:** `split_sentences("He said no. Then left.")` → `['He said no. Then left.']`, `"결과는 no. 다음."` → 1문장. `no.`, `st.`가 무조건 내부 마침표로 처리되고, `_DOTTED_ABBREVIATION`도 `"… in the U.S. Then …"`처럼 문장 끝에 온 약어를 끝으로 보지 않는다.
- **영향:** 이번 N1의 반대 방향(덜 자름)이다. 근거 없는 문장이 근거 있는 문장과 합쳐지면 분모가 줄고, 합쳐진 문장 하나가 통째로 후보가 되어 비율이 왜곡된다. 지금 mock 요약은 한국어라 드러나지 않고 T25 요약도 한국어 위주라 빈도는 낮다. T25g 판정기가 문장 단위로 판정하므로 그 전에 정리하면 된다. 정확성 -1.
- **개선:** `no.`는 뒤에 공백+숫자가 올 때만(`No. 3`), `st.`는 뒤에 대문자 고유명사가 올 때만 내부로 본다. 테스트에 "진짜 끝인데 합치면 안 되는" 음성 사례(`He said no. Then left.`)를 추가한다.

### L-b. [낮음] 초록 경계: 반대 방향 구두점 차이와 줄바꿈 1개가 남았다 — `src/jupjup/ingest/chunking.py:190-217`
- **재현:** 2.3절 아래 세 줄. 초록 끝 종결부호만 떼고 본문 쪽 종결부호는 보지 않아, "초록에는 마침표가 없고 본문에는 있는" 경우 중복된다. 본문이 마침표 없이 줄바꿈 1개로 이어져도 중복된다.
- **영향:** `ContentMeta.abstract`를 채우는 코드가 아직 없어 실제 입력에는 영향이 없다. 설계 9절도 L2를 이번 범위 밖으로 두었는데 구현자가 앞서 처리했으므로 감점은 작게 둔다. 정확성 -1.
- **개선:** 초록 단어열이 본문 접두로 맞으면(`_prefix_words(text, core)`), 뒤가 종결부호·빈 줄·줄바꿈·텍스트 끝 중 하나일 때 경계로 인정한다. 초록 쪽 끝 구두점 유무와 관계없이 같은 규칙을 쓰면 된다. 파라미터 테스트에 세 줄을 추가한다.

### L-c. [낮음] 분리기 규칙이 문서화되지 않았고 음성 경계 테스트가 없다 — `src/jupjup/eval/judge.py:111`, `tests/unit/test_ingest_judge.py`
- `split_sentences`는 T25 설계상 비충실 비율 분모·분자, 판정기 문장 단위, 맵 단계 문장 번호가 모두 쓰는 공용 규칙인데 docstring이 없다. 숫자 사이·영문자 사이·약어 목록·점 약어·줄바꿈·종결부호 연속을 어떻게 다루는지 한 단락으로 적어 둬야 T25e/g 구현자가 같은 규칙을 가정할 수 있다.
- 테스트는 "자르지 말아야 할 곳"(소수점·약어)만 고정하고 "잘라야 할 곳에서 합치지 않음"(L-a), 목록 표기(`1. 서울시 발표\n2. 37곳 참여` → `['1.', '서울시 발표', '2.', '37곳 참여']`, `2.`가 근거 없는 후보가 되어 비율 0.25), 닫는 따옴표(`“This is it.” 서울시.` → `['“This is it.', '” 서울시.']`)는 없다. 마지막 두 가지는 이번 변경 전부터 있던 동작이고 N1 범위 밖이라 결함으로 세지 않았다. T25 요약 프롬프트가 목록을 금지하지 않으면 T25g에서 같이 다룬다. 유지보수성 -1.

### L-d. [낮음] 빈 주입 집합 경로가 `_gate` 단위로만 고정돼 있다 — `tests/unit/test_ingest_metrics.py:48-55`
- `_gate`에 `None`을 직접 넣는 테스트뿐이다. `run()`이 주입 0건 split에서 `injection_resistance=None`을 만들고 Markdown이 `해당 없음`으로 그리며 CLI가 종료 1을 내는 경로는 고정돼 있지 않다. 지금은 골든 검증기가 test ≥ 2건, dev ≥ 1건을 강제해 실제로 도달하지 않으므로 하네스 테스트(주입 사례를 뺀 임시 골든 + 검증기 우회 또는 `IngestEvalHarness` 단위 하위 경로)로 한 건 더 고정해 두면 충분하다. 유지보수성 -1.

### 참고 (감점 없음)

- **트리거 쓰기 증폭:** 임베딩 1행마다 revision 행을 한 번 갱신한다(recorded 첫 검색 백필에서 u_alice 320회). dev 규모에서는 무시할 수준이고, 보수적으로 다시 읽을 뿐 놓치지는 않는다. 수만 건 규모가 되면 문장 단위 트리거 대신 저장소 쓰기 함수에서 한 번 올리는 방식을 검토한다.
- **`contents.user_id` 변경:** UPDATE 트리거는 `NEW.user_id`만 올린다. 지금 콘텐츠 소유자를 바꾸는 경로는 없고, 옛 사용자 쪽은 행 수 요약값이 바뀌어 잡힌다.
- **남은 `assert`:** `src/jupjup/ingest/analyzer.py:153`, `:155`, `ingest/fetch.py:78`, `:145` 등. hardening L5 지적 범위 밖이고, `analyzer.py`는 T25e에서 다시 쓰이니 그때 같은 방식으로 좁힌다.
- **보고서 정확성:** 보고서 3.2절 검색 수치, 3.1절 지표 전후, 4절 명령 결과를 모두 같은 값으로 재현했다. 보고서 5절의 "전체 포맷 검사 9개 파일 실패"도 사실이고 모두 이번 diff 밖이다.
- **L4를 이번에 처리한 것:** 사용자 지시에서는 검수 범위 밖이지만 설계 9절은 T25a 필수로 두었다. 구현자는 설계를 따랐고 기존 녹화를 무효화하지 않음(2.6절)만 확인했다.

## 5. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 38 / 40 | N1·T24 L-1·L-2·L-5, hardening L1·L2(원 재현)·L3를 원래 재현 절차로 직접 해소 확인. 정상 골든 거짓 후보 5 → 0, overall·기준선·검색 eval 무변화, 검색 경계값 13종 정상. 감점: 약어가 진짜 문장 끝을 합침(-1, L-a), 초록 반대 방향 구두점·줄바꿈 1개 경계 잔존(-1, L-b) |
| 안전성 | 30 / 30 | hardening 때 감점 사유였던 런타임 `assert`(L5)와 스키마 지문 취약성(L4) 모두 해소. 녹화 재생 타입 오류가 명시적 `LLMProviderError`, 빈 주입 집합은 게이트 실패, 트리거는 상수 테이블명만 쓰는 고정 SQL, 옛 DB 자동 업그레이드, 사용자별 revision으로 격리 유지, 읽기 전용 검색은 쓰기 없음, 입력 검증(빈·긴·특수문자)·요청 잠금·사용자 격리 유지 |
| 유지보수성 | 28 / 30 | 구현 전 실패 테스트를 먼저 쓴 기록(11 failed → 통과, 6 failed → 70 passed), `_ParsedObject \| _ParseFailure` 타입 모델링, 변경 파일 전부 포맷 통과, 결정과 비범위를 숨기지 않은 보고서. 감점: 공용 분리기 규칙 미문서화·음성 경계 테스트 부재(-1, L-c), 빈 주입 경로가 `_gate` 단위로만 고정(-1, L-d) |
| **합계** | **96 / 100** | **PASS** |

## 6. 다음 단계 권고

- T25d(제공자·설정)로 진행해도 된다. T25a의 선행 조건은 모두 충족됐다.
- L-a·L-c는 T25g(판정기) 첫 커밋에서 분리기 docstring과 음성 테스트로 같이 정리하기를 권한다. 판정기의 문장 번호가 이 규칙에 묶인다.
- L-b는 T25e에서 논문 메타 초록을 채우게 될 때 같이 고친다.
