# Phase 2 리포트: T25c 인제스트 골든 v2

- 작업: `specs/design_local_analyzer.md` 10.1절 T25c (8.1·8.2절)
- 워크트리: `phase-2-t25c-ingest-golden-v2` (베이스 `b5aea9d`)
- 실행: Codex-Primary 역할을 Claude가 수행. 설계 10.1절의 T25c 담당은 "작성: Claude 워커, 독립 검수: Codex 워커"이므로
  이번 작성 주체는 설계와 맞다. 독립 검수는 아직 하지 않았다 (7절).
- 작성일: 2026-11-02

## 1. 구현 범위

| 항목 | 산출물 | 상태 |
|---|---|---|
| v1 보존 | `data/golden/ingest/` → `data/golden/ingest_v1/` (git mv, 내용 무변경). v1 생성기 `scripts/generate_ingest_golden.py`의 출력 경로를 `ingest_v1`로 바꿈 | 완료 |
| 자연문 골든 v2 80건 | `data/golden/ingest/` `sources.jsonl`, `annotations.jsonl`, `fixtures/html/long_*.html` 5, `fixtures/transcripts/yt_*.vtt` 5, `manifest.json` | 완료 (AI 초안) |
| 생성기 | `scripts/golden_ingest_v2/` (`data_<플랫폼>.py` 7개에 직접 쓴 레코드, `long_docs.py` 긴 글 5건, `build.py` 결정적 생성·`--check`) | 완료 |
| 템플릿 검사기 | `src/jupjup/eval/ingest_golden_checks.py`, CLI `jupjup eval validate-ingest [--golden-dir] [--legacy]` | 완료 |
| test 봉인 | `data/golden/ingest/test.sha256` (test 32건 원문 + fixture 바이트 + gold + split) | 완료 |
| REVIEW_GUIDE 갱신 | `data/golden/ingest/REVIEW_GUIDE.md` (v2 신규), `ingest_v1/REVIEW_GUIDE.md` 상단에 보존본 안내 | 완료 |
| 사용자 표본 목록 | `data/golden/ingest/sample_for_user.jsonl` 24건 | 완료 (검수 자체는 범위 밖) |
| v2 mock 기준선 | `data/baselines/ingest_v2.mock.json` (dev/test/all 스키마 최종 준수율 1.0, 주입 저항 1.0) | 완료 |
| v1 mock 기준선 | `data/baselines/ingest.mock.json` 무변경 | 완료 |
| 하네스·CLI | `IngestEvalConfig` 기본 골든을 mode로 고름(mock→v1, recorded/live→v2), `eval ingest --golden v1\|v2`, `INGEST_GOLDEN_V1`·`INGEST_V2_BASELINE` 상수 | 완료 |
| 문서 | `data/golden/README.md`, `data/baselines/README.md` 변경 이력 | 완료 |
| 자체 검수 패스 | 6절 | 완료 |

### 1.1 v2 골든 구성

- 80건, dev 48 / test 32. 플랫폼군 instagram 15, youtube 15, news 15, paper 10, kakaotalk 10, blog_web 10, image 5
  (각 군 60/40 고정 split).
- 어려운 사례: 긴 글 5, 광고·해시태그 5, 영어 중심 5, 숫자·날짜 5 (각 dev 3 / test 2), 주입 3 (dev 1 / test 2).
- category 13종을 모두 쓴다. 플랫폼군마다 category와 대표 save_intent가 2종 이상이다.
- gold: 대표 태그 3~5개, key_facts 298개(건당 2~5개, 대부분 4개), 엔티티 173개, forbidden_claims 건당 3개.
- mock 재요청 배선: `mock_failure` 6건(invalid_json 2, schema_violation, truncated_json, max_tokens, empty_response),
  dev 3 / test 3.
- 모든 annotation은 `annotator: "ai"`, `review_status: "ai_draft_unreviewed"`.
- 합성 데이터 원칙: 상호·인물·단체·상품·학술지 이름은 지어낸 것(누리시·해온시·가람시·한빛도 등)이다. 실제 지명(동네·
  도시)과 일반 기관명(기상청)만 실제 이름이다. 실존 개인정보는 없다. 날짜·요일은 2026-11~2027 달력에 맞췄다.
- 플랫폼별 문체: 인스타 구어체·이모지·해시태그, 유튜브 자막(VTT)·설명+자막 발췌, 기사체, 논문 초록+본문 발췌(국문·영문),
  카톡 대화 줄, 블로그 후기·웹 안내문, 이미지 OCR(포스터·영수증·공지·약봉투·메뉴판).

### 1.2 템플릿 검사기 (`eval validate-ingest`)

설계 8.1절 (a)~(d)에 더해, gold 품질을 기계적으로 잡을 수 있는 검사를 같이 넣었다.

| 검사 | 기준 | 결과(v2) |
|---|---|---|
| (a) 같은 플랫폼군 글자 8-gram 중복률 (공백 제거, `normalize_text`, 쌍별 `|A∩B|/min`) | ≤ 0.15 | 최대 0.025 (paper) |
| (b) 금지 문구 `핵심 정보 \d+`, `평가용 원문`, `자료 \d+ 저장` (원문·제목·key_facts) | 없음 | 0 |
| (c) key_fact가 원문 부분 문자열 | 경고 | 경고 0 |
| (d) 엔티티·장소 이름 원문 근거 | 오류 | 0 |
| (추가) key_fact 숫자가 원문에 있음 | 오류 | 0 |
| (추가) forbidden_claim이 원문에 없음 | 오류 | 0 |
| (추가) 어려운 사례 실질 검사: 긴 글 추출 본문 > 40,000자, 영어 비율 ≥ 0.6, 해시태그 ≥ 15, 숫자 밀집 + key_fact 숫자, 주입 문구 원문 포함·gold 미포함 | 오류 | 0 |
| (추가) 플랫폼군별 category·대표 save_intent 2종 이상 | 오류 | 0 |
| test 봉인 일치 | 오류 | 일치 |

v1 템플릿 골든에 같은 검사를 돌리면 오류 809건(8-gram 중복 0.70 안팎, 금지 문구 등)으로 거부된다. v1은 `--legacy`로
구조 검사만 통과한다.

## 2. 설계 대비 차이 (이유)

1. **v1 mock 리포트의 경로 필드 2개가 바뀐다.** 설계 8.1절이 v1을 `ingest_v1/`로 옮기라고 하므로
   `config.sources_path`/`annotations_path`가 `data/golden/ingest_v1/...`가 된다. 이 두 줄을 빼면 dev/test/all JSON은
   T25c 이전과 바이트 단위로 같고, Markdown 리포트는 완전히 같다 (5절에서 확인). 기준선 파일 `ingest.mock.json`은
   경로를 담지 않아 바뀌지 않았다. 기존 테스트 `test_ingest_written_reports_are_byte_identical`의 경로 단언만
   `ingest_v1`로 고쳤다.
2. **기본 골든을 mode로 고른다.** 설계는 "mock 배선 회귀는 v1로 계속 돈다"와 "data/golden/ingest/는 v2"를 함께 요구한다.
   `IngestEvalConfig`에 `model_validator(mode="before")`를 두어 경로를 주지 않으면 mock은 v1, recorded/live는 v2를 쓴다.
   그래서 `jupjup analyze record`·`bench analyze`(live)와 T25h의 recorded 평가는 자동으로 v2를 쓰고, `eval ingest --mode
   mock`은 기존과 같이 v1을 쓴다. CLI에는 `--golden v1|v2`를 더했고 mock 기준선도 골든에 맞춰 고른다
   (`v1→ingest.mock.json`, `v2→ingest_v2.mock.json`). CLI 첫 줄 출력은 그대로 두고 둘째 줄에 `골든 v1 (data/golden/ingest_v1)`를 찍는다.
3. **`eval validate-ingest`를 새 명령으로 만들었다.** 설계 문구는 "validate-ingest에 더한다"인데 이 명령이 없었다. 기존
   `eval validate`는 검색 골든과 인제스트 구조 검사(이제 v2)를 그대로 하고, 템플릿 검사·봉인은 `validate-ingest`에만 넣었다
   (검색 골든 검증 출력과 섞지 않기 위해).
4. **test 봉인은 `annotator`·`review_status`를 해시에 넣지 않는다.** 사용자·교차 검수로 상태만 바뀔 때 봉인이 깨지지 않게
   하려는 것이다. gold·원문·fixture 바이트가 바뀌면 깨진다 (테스트로 고정). 하네스 실행 시점에 `test.sha256`을 확인하는
   것은 넣지 않았다. 지금 test split 실행 차단은 T25f의 `frozen_config_sha256`이 맡는다. 실행 시점 봉인 확인을 하네스에
   넣을지는 T25h 전에 정하면 된다 (7절).
5. **jsonl을 직접 쓰지 않고 Python 데이터 모듈 + 생성기로 만들었다.** 긴 글 fixture를 결정적으로 만들어야 하고, 검수 반영을
   한 곳(`data_*.py`)에서 하게 하려는 것이다. `build.py --check`와 테스트가 커밋 파일과 생성 결과의 일치를 확인한다.
6. **긴 글 5건은 반구조 생성 본문이다.** 핵심 서술(도입·핵심 절·마무리, key_facts의 근거)은 직접 썼다. 4만 자를 채우는
   나머지(노선별 설명, 일자별 기록, 도서관별 현황, 오류 사례, 여행 메모 등)는 고정 seed의 데이터 표를 여러 문장 틀로 풀었다.
   본문의 수치 합계(온열질환자 87명, 쉼터 412곳·야간 38곳, 경비 680,000원 등)는 핵심 서술과 맞도록 만들었다. 설계는
   "기존 HTML fixture를 다시 써도 된다"고 했지만, v1 fixture는 금지 문구 반복이라 템플릿 검사를 통과할 수 없어 새로 만들었다.
   한계는 7절에 적었다.
7. **템플릿 검사에 설계에 없는 검사를 더했다** (1.2절 "추가"). 첫 작성본에서 이 검사들이 실제 gold 오류 15건을 잡았다 (6절).
8. **카카오톡 엔티티 규칙**: 대화에 이름이 나온 참여자는 모두 person 엔티티로 넣었다 (REVIEW_GUIDE에 규칙으로 적음).
   엔티티 정밀도가 이름 누락에 민감해서 한 가지 규칙으로 통일했다.

## 3. 테스트 목록

신규 `tests/unit/test_ingest_golden_v2.py` (13개 케이스):

| 테스트 | 확인 내용 |
|---|---|
| `test_v2_size_distribution_and_ai_draft_status` | 80건, 플랫폼군 분포, 어려운 사례 수, 48/32, 전부 ai 초안, mock 실패 배선 dev·test 각 3건 이상 |
| `test_v2_passes_template_checks_with_no_warnings` | v2 템플릿 검사 오류·경고 0, 중복률 ≤ 0.15, 긴 글 5건 > 40,000자 |
| `test_v1_template_golden_is_rejected_by_template_checks` | v1이 8-gram 중복과 금지 문구로 거부됨 |
| `test_ngram_overlap_detects_number_substitution_templates` | 번호만 바꾼 문장 쌍은 상한 초과, 자연문은 이하 |
| `test_template_checker_flags_each_rule` | 금지 문구, 근거 없는 엔티티, 원문에 있는 forbidden_claim, 틀린 숫자, 원문 복사 경고 |
| `test_test_seal_tracks_test_gold_but_not_review_status_or_dev` | 봉인 일치, 검수 상태·dev 변경은 무영향, test gold·fixture 바이트 변경과 파일 삭제는 실패 |
| `test_generator_reproduces_committed_files` | 생성기 결과 = 커밋 파일 (바이트) |
| `test_user_sample_covers_groups_difficult_cases_and_both_splits` | 20~30건, 7개 군, 어려운 사례 5종, dev·test, gold 일치, 판정 비어 있음 |
| `test_default_golden_follows_mode` | mock→v1, recorded/live→v2, 명시 경로 우선 |
| `test_validate_ingest_cli_exit_codes` | v2 종료 0, v1 종료 1, v1 `--legacy` 종료 0 |
| `test_v2_mock_gate_baseline_and_determinism[dev/test]` | v2 mock 게이트·회귀 검사 통과, 재요청 배선, 주입 저항 1.0, 두 번 실행 바이트 동일 |
| `test_eval_ingest_cli_golden_option` | `--golden v2` 경로·기준선, 잘못된 값 종료 2 |

수정: `tests/eval/test_ingest_regression.py`(v1 경로 상수·경로 단언), `tests/unit/test_ingest_golden_validator.py`
(v1 디렉터리로 지정). 다른 테스트는 바꾸지 않았다 (T25f record/replay 테스트는 이제 recorded/live 기본값으로 v2를 써서 통과).

## 4. 직접 실행한 명령과 결과

모두 기본 설치(extra 없음)에서 실행했다.

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **1177 passed, 4 deselected** (마커 제외분: embed/rerank/local_llm). skip 0 |
| `uv run ruff check src tests` | All checks passed (`scripts/golden_ingest_v2`도 통과) |
| `uv run mypy src` | Success: no issues found in 87 source files |
| `uv run jupjup eval validate` | 종료 0 (인제스트 v2 80건 구조 검사 포함) |
| `uv run jupjup eval validate-ingest` | 통과 (템플릿 검사·test 봉인 포함), 군별 최대 8-gram 중복률 blog_web 0.000, image 0.011, instagram 0.000, kakaotalk 0.000, news 0.007, paper 0.025, youtube 0.013 |
| `uv run jupjup eval validate-ingest --golden-dir data/golden/ingest_v1 [--legacy]` | 템플릿 검사 시 종료 1 (809건), `--legacy` 종료 0 |
| `uv run python scripts/golden_ingest_v2/build.py --check` | golden v2 files match the generator |
| `uv run jupjup eval run --mode mock\|recorded --split dev\|test` | 4개 모두 PASS. T25c 전 리포트와 비교해 다른 키는 `created_at`, `perf`(지연)뿐 → 수치 무회귀 |
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all` (v1) ×2 | 모두 PASS, 두 실행 리포트 동일. T25c 전 리포트와 경로 2줄 외 바이트 동일, md 완전 동일 |
| `uv run jupjup eval ingest --mode mock --golden v2 --split dev\|test\|all` ×2 | 모두 PASS(기준선 회귀 포함), 두 실행 리포트 동일. 첫 시도 준수율 dev 0.9375 / test 0.90625 (mock 실패 배선), 최종 1.0, 주입 저항 1.0 |
| `python -c "import jupjup.cli, ...; 'llama_cpp' in sys.modules"` | False |
| `git status -- src/jupjup/search src/jupjup/query data/recordings data/baselines/{mock,recorded,mock.human_reviewed,ingest.mock}.json` | 변경 0 |

test 봉인: `764aaf760ad049846311a498fe36ab2cdc214466b43c19b2e3836f8baca2d68c` (32건).

## 5. 무회귀 확인 방법

T25c 작업 전에 `eval ingest --mode mock`(dev/test/all)과 `eval run --mode mock|recorded`(dev/test) 리포트를 scratch에
저장하고, 작업 뒤 같은 명령 결과와 비교했다. 인제스트 v1은 `data/golden/ingest_v1/` → `data/golden/ingest/` 치환 후
`cmp` 일치, 검색은 `created_at`·`perf` 외 모든 키 일치.

## 6. 자체 검수 패스 (별도 체크리스트)

작성을 마친 뒤 아래 체크리스트로 한 번 더 봤다. 같은 작성자의 검수이므로 독립 검수를 대신하지 않는다.

| 체크 항목 | 방법 | 발견 | 조치 |
|---|---|---|---|
| A. gold 원문 근거 (엔티티·장소·숫자) | 템플릿 검사기 | 엔티티 원문 없음 1 (`모아랩`이 제목에만 있음), key_fact 숫자 형식 불일치 6 (`12.13` 날짜, `January 12`, `part two`, `66만 원` 대 `660,000원`, `11:00~20:30` 등) | 원문 보강 또는 바꿔 쓰기 |
| B. forbidden_claims가 원문에 없음 | 템플릿 검사기 | 원문에 있는 구절 7 (`버피`, `리그 1위`, `영어 영수증`, 주입 문구 3, `해산물` 등). 충실한 요약이 벌점을 받는 오류 | 교체 |
| C. 주입 문구가 gold에 없음 | 템플릿 검사기 | 1 (forbidden_claims에 주입 문구) | 제거 |
| D. 날짜·요일 일관성 | 스크립트로 명시 요일을 2026-11~2027 달력과 대조 | 12건 불일치 (2024/2025 달력 기준으로 씀). 이 중 2건은 문서 안에서 모순 (`2026 누리 하프마라톤 11월 24일 일요일`, `2027 전시 1월 11일(토)`). `부산 12월 14일`이 토요일 드론쇼와 안 맞음 | 날짜를 요일에 맞게 옮기고 key_facts도 같이 수정, 재검사 0건 |
| E. 정답 누락 (엔티티) | Kiwi NNP + 영문 고유명사 후보를 gold와 대조해 목록화한 뒤 하나씩 판단 | `강릉역`, `SQLite`, `카카오뱅크`, `아이패드` 누락. 카톡 참여자 이름 12개 누락(규칙 불일치). 영어 기사 장소가 영문 표기라 한국어 요약과 안 맞음 | 추가·규칙 통일·`대전`/`세종`으로 변경(원문 한국어 줄에 근거 추가) |
| F. 긴 글 key_facts 근거 | 각 fact의 핵심 구절을 fixture에서 grep, 생성 수치 합계 재계산 | 전부 있음. 일자별 온열질환자 합 87 일치 | — |
| G. 긴 글 내부 모순 | 문단 표본 읽기 | 폐지 노선에 시간표와 "저상버스로 바뀐다" 문장, 등대섬 도착 12:03(물길은 13:40부터), 메모가 임의 시각에 바람의 언덕에 있음, 섬에서 버스 이야기, 조사 오류(`누리대학교을`, `생선구이을`) | 폐지 노선 문장 분리, 등대섬 13:45 이후·바람의 언덕 30분 고정, 장소·시각 없는 메모 틀, 섬 전용 문장, 받침 맞춤 조사 포맷터 |
| H. 분포 | 군별 category·intent·어려운 사례 split 집계 | 기준 충족 (1.1절) | — |
| I. 결정적 충실도 검사와의 정합 | gold key_facts 298개를 요약 문장으로 넣어 `DeterministicFaithfulnessChecker` 실행 | 15건 19문장이 근거 없음 후보. 하나씩 보니 gold 오류는 0이고 검사기 한계였다: 단위가 붙은 숫자(`5km`, `200ml`, `10km`, `500m`, `40ms`, `20kg`, `K7`), 점·ISO 날짜와 한국어 날짜(`12.13`, `2026. 12. 6`, `2026-11-28`), Kiwi NNP 오탐(`게시물`, `층간소음`, `한국어`, `사진`, `월금`, `봉수`, `러`) | gold는 두고 T25g 입력으로 넘김 (7절) |

검수자 판단이 필요한 지점으로 남긴 것: 영어 사진전 게시물의 장소에 `Seoul`을 넣을지, 긴 글의 엔티티 범위(주제 기관만
넣음), 저장 의도(`save_intent`)의 주관적 선택, forbidden_claims의 적절성.

## 7. 남은 문제

1. **T25c 완료 조건 중 두 가지가 남았다.** "교차 검수 불일치 해소"와 "사용자 표본 검수 20건 이상 반영"이다. 이번 범위
   밖이라 하지 않았다. 다음 순서: Codex 워커 독립 검수 → 불일치 목록 → 사용자가 불일치 + `sample_for_user.jsonl` 24건
   판정 → `data_*.py` 반영 → 재생성(봉인 갱신) → `review_metadata.json` 작성. 그때까지 v2는 AI 초안이다.
2. **긴 글 5건의 생성 본문 품질**: 본문의 약 80~85%가 문장 틀 반복이다 (예: 응답 메모·오류 사례·현장 점검 메모가 수백 개).
   청킹 경로와 핵심 사실 위치 분산을 시험하기에는 충분하지만, 실제 긴 기사만큼 다양하지는 않다. 검수에서 부족하다고 보면
   긴 글만 따로 다시 써야 한다 (작업량이 커서 이번에는 하지 않음).
3. **결정적 충실도 검사기 한계** (6절 I): T25g의 결정적 매처·충실도 검사 개선 때 단위 숫자, 날짜 표기 정규화, NNP 오탐을
   함께 다뤄야 v2 recorded 평가의 비충실 비율이 부풀지 않는다.
4. **실행 시점 봉인 확인**: 하네스는 recorded/live test 실행 때 `test.sha256`을 확인하지 않는다 (`validate-ingest`만 확인).
   T25h 전에 하네스에 넣을지 정해야 한다.
5. **영어 원문 날짜**: 영어 원문의 날짜를 한국어 요약에 옮기면(`January 12` → `1월 12일`) 현 검사기는 `1`을 근거 없음으로
   본다. gold는 원문 표기(`January 12`)를 썼다. T25g에서 함께 다룬다.
6. 사용자 표본 24건 중 test가 11건이다. test gold를 사용자가 보는 것은 봉인 원칙(분석기·프롬프트 작업자 열람 금지)과
   충돌하지 않지만, 사용자가 T25h 프롬프트 조정에 직접 참여한다면 test 11건을 dev로 바꿔 다시 뽑는 편이 안전하다.
