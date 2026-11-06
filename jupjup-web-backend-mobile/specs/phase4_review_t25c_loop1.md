# Phase 4 최종 검수: T25c 인제스트 골든 v2, Loop 1/3

- **점수:** 93 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 28 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). M1은 독립 교차 검수(Codex)·사용자 표본 검수를 반영해 `data_*.py`를 고칠 때 같이 고치고, 검사기 규칙 추가는 T25g가 `eval/`을 만질 때 넣길 권한다. L1~L5는 T25h 전에 정리하면 된다.
- **검수 대상:** `1de1231 feat: T25c natural-language ingest golden v2 with template checker and test seal` (기준 `b5aea9d`)
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드와 데이터는 고치지 않았다. 재현 실험은 스크래치 디렉터리(`git archive b5aea9d` 사본과 그 venv, 변조용 골든 사본, 소켓 차단 실행기, 점검 스크립트)와 `var/review.db`에서만 했다.
- **범위 밖:** 사용자 표본 검수 자체, Codex 독립 교차 검수, T25g 이후. 완료 조건 중 "교차 검수 불일치 해소"와 "사용자 표본 검수 20건 이상 반영"은 이번 범위 밖이라 감점하지 않았다. `ai_draft_unreviewed` 상태도 감점하지 않았다.

## 0. 한 줄 판정

이번 범위의 T25c 완료 조건 다섯 개를 **모두 직접 재현했다**: `eval validate-ingest` 통과(템플릿 검사·봉인 포함, 종료 0), 80건·플랫폼 분포·어려운 사례 수·split 60/40 충족, v2 mock 기준선 생성(dev/test/all 통과, 두 번 실행 바이트 동일), v1 mock 기준선 파일 무변경(v1 mock 리포트는 경로 두 줄 말고 기준 커밋 사본과 바이트 동일, md는 완전 동일), test 봉인 해시 일치(변조 3종은 모두 잡힘). 기본 게이트(pytest 1177 passed skip 0, ruff, mypy), 검색 eval 4종(기준 커밋 사본과 수치 동일), CLI 검색 회귀·경계값 27건(사본과 정규화 출력 동일)도 통과했다. 소켓을 막고 돌린 `validate-ingest`·`eval ingest`에서 네트워크 시도는 0건이었고 `llama_cpp`는 import되지 않았다.

원문은 플랫폼별 문체가 살아 있는 자연문이고, 요일·날짜 17건이 모두 2026-11~2027 달력과 맞았다. 감점은 gold 한 건의 자기모순(M1)과, 이 모순을 못 잡는 검사기 빈틈, 봉인·기준선 정체성이 도구로 강제되지 않는 점(L1~L3), `기타`를 허용 의도로 넓게 둔 점(L4), 긴 글 내부 반복(L5)에서 나왔다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run python -c "importlib.util.find_spec('llama_cpp')"` | `None` |
| `uv run pytest` (`-o addopts=""`와 같은 마커 제외로 요약 줄 확인) | **1177 passed, 4 deselected**, 경고 2 (기존 Starlette 1, 테스트가 의도한 `RuntimeWarning` 1). skip 0 (AC-L1) |
| `uv run ruff check src tests scripts` | All checks passed! (`scripts/golden_ingest_v2` 포함) |
| `uv run mypy src` | Success: no issues found in 87 source files |
| `uv run jupjup eval validate` | 종료 0. 인제스트 구조 검사가 v2 80건(dev 48 / test 32, 7개 군)으로 돈다 |
| `git diff --stat b5aea9d HEAD -- src` | `cli.py`, `eval/ingest_golden_checks.py`(신규), `eval/ingest_harness.py` 세 파일뿐 |
| `git diff --stat b5aea9d HEAD -- src/jupjup/search src/jupjup/query data/baselines/{mock,recorded,ingest.mock}.json data/recordings data/golden/seeds* data/golden/queries*` | **0줄** |
| `jupjup.cli`·`eval.ingest_golden_checks`·`eval.ingest_harness` import 뒤 `sys.modules` | `llama_cpp` False, `jupjup.providers.llm_local` False |

### 1.2 T25c 완료 조건 재현 (설계 10.1절 T25c 행)

| 완료 조건 | 직접 확인 | 판정 |
|---|---|---|
| `eval validate-ingest` 통과 (템플릿 검사 포함) | `uv run jupjup eval validate-ingest` → "인제스트 골든 검증 통과 (템플릿 검사·test 봉인 포함)", 종료 0. 군별 최대 8-gram 중복률 blog_web 0.000, image 0.011, instagram 0.000, kakaotalk 0.000, news 0.007, paper 0.025, youtube 0.013 (상한 0.15). 경고 0 | 충족 |
| v1이 템플릿 검사에서 거부되는지 | `--golden-dir data/golden/ingest_v1` → 종료 1 (instagram 쌍 0.69~0.72 등). `--legacy` → 종료 0 | 충족 |
| 80건·분포·어려운 사례 수 | 내 스크립트로 집계: instagram 15 / youtube 15 / news 15 / paper 10 / kakaotalk 10 / blog_web 10 / image 5, 군마다 60/40. 긴 글 5, 광고·해시태그 5, 영어 중심 5, 숫자·날짜 5 (각 dev 3 / test 2), 주입 3 (dev 1 / test 2). REVIEW_GUIDE 분포표와 군별 어려운 사례 배치까지 일치. category 13종 전부 사용 | 충족 |
| v2 mock 기준선 생성 | `eval ingest --mode mock --golden v2 --split dev\|test\|all` 각 2회 → 모두 PASS(회귀 검사 포함), 1회·2회 6개 파일 `cmp` **바이트 동일**. `data/baselines/ingest_v2.mock.json` 스키마 최종 준수율 1.0, 주입 저항 1.0 | 충족 |
| v1 mock 기준선 무변화 | `ingest.mock.json` diff 0. `eval ingest --mode mock --split dev\|test\|all` 2회 + `git archive b5aea9d` 사본(별도 venv, `jupjup.__file__`이 사본 `src`)에서 1회. 1회 대 2회 바이트 동일. 사본 대비 JSON은 `sources_path`/`annotations_path` 두 줄(`ingest_v1/`)만 다르고 치환하면 동일, **md 3개는 완전 동일** | 충족 (경로 두 줄은 설계 8.1절 이동의 직접 결과, 보고서 2절에 명시) |
| test 봉인 해시 | `test.sha256` = `764aaf76…a2d68c`, 32건. 사본 골든에서 ① test key_fact 한 줄 변경 ② test 긴 글 fixture에 공백 1바이트 추가 → 둘 다 "test split 봉인 불일치", 종료 1. ③ test 한 건을 dev로 옮김 → split 60/40 구조 오류로 거부 | 충족 |
| 생성기 결정성 | `build.py --check`를 `PYTHONHASHSEED` 0, 12345로 → 둘 다 "golden v2 files match the generator" | 충족 |

### 1.3 검색 무회귀 (AC-L2)

| 명령 | 결과 |
|---|---|
| `eval run --mode mock --split dev` | PASS. R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat min 0.8838 |
| `eval run --mode mock --split test` | PASS. 0.9420 / 0.9867 / 0.9589 / 0.7812 |
| `eval run --mode recorded --split dev` | PASS. 0.9712 / 1.0000 / 0.9860 / 0.8894 |
| `eval run --mode recorded --split test` | PASS. 0.9720 / 0.9911 / 0.9801 / 0.8900 (네 줄 모두 T25f 검수 값과 같음) |
| 위 4개를 기준 커밋 사본에서도 실행해 JSON 비교 | `created_at`·`git_sha`·`perf`·`config`의 절대 경로(사본 위치) 말고 모든 키 동일. md는 생성 시각·git·지연 줄만 다름 |

### 1.4 CLI 검색 회귀·경계값 (`seed load --db var/review.db`, `--now 2026-10-15T12:00+09:00`, 사본과 비교)

`query_id`·`timing_ms`를 지운 JSON 출력 해시를 HEAD와 사본에서 비교했다. **27건 모두 SAME.**

| 분류 | 질의 | 결과 (HEAD) |
|---|---|---|
| 회귀 (과소 완화) | `경주 맛집 인스타` (mock·recorded) | `c_alice_0153`, `platform_filter_dropped` |
| 회귀 (과소 완화) | `하체 운동 유튜브` (mock·recorded) | `c_alice_0040` 1위, `platform_filter_dropped` |
| 회귀 (이중 완화 기록) | `경주 맛집 카톡 논문` | `platform_filter_dropped`, `content_type_filter_dropped` 둘 다 기록 |
| 회귀 (오교정) | `다리 운동 영상` (mock·recorded) | `c_alice_0040` 1위, 완화 없음 |
| 오타 | `성수동 카패` | mock 5건 / recorded `EMBEDDING_CACHE_MISS` (사본과 동일, 기존 동작) |
| 빈 문자열·공백 | `""`, `" "` | `[INVALID_QUERY] 질의는 1~200자여야 해요`, 종료 2 |
| 특수문자 | `!!!@@@###` | `[INVALID_QUERY] 검색할 단어가 없어요`, 종료 2 |
| 긴 질의 | 70자 구어 질의 | 결과 0, 오류 없음 |
| 영어 혼합 | `pasta recipe 파스타` | 결과 0 |
| 필터 전용 | `지난주에 저장한 거`, `이번 달 유튜브` | 각각 5건, 2건 |
| 요청 잠금 | `맛집 --platform youtube` | youtube만 1건, 완화 없음 |
| 요청 잠금 | `경주 맛집 --platform instagram` | 0건 (잠근 플랫폼을 풀지 않음, 과잉 완화 없음) |
| 요청 잠금 | `운동 --type video` | video 계열만, 완화 없음 |
| 시간대 없는 날짜 | `카페 --from 2026-09-01 --to 2026-10-01` | `[INVALID_FILTER] --from에는 시간대가 있어야 합니다` |
| 없는 대상 | `화성 우주정거장 레시피` | 0건 |
| 사용자 격리 | u_bob `경주 맛집`, u_bob·u_carol `카페 디저트`, `u_nobody` | 다른 사용자 문서 0건, 자기 문서만. `u_nobody`는 안내 문구 + 빈 결과 |

### 1.5 네트워크·import (AC-L8, 14절 1·2)

소켓 `connect`/`create_connection`을 막는 실행기로 `jupjup.cli.app`을 불렀다.

| 명령 | 네트워크 시도 | `llama_cpp` / `llm_local` import |
|---|---|---|
| `eval validate-ingest` | 0 | False / False |
| `eval ingest --mode mock --golden v2 --split all` | 0 | False / False |
| `eval ingest --mode recorded --profile local-qwen3-4b --split dev` | 0 ("LLM 녹화본 파일이 없습니다", 종료 2) | False / False |
| `eval ingest --mode recorded ... --split test` (해시 없음) | 0 (동결 해시 요구로 거부) | False / False |
| `eval ingest --golden v3` | 종료 2, "--golden은 v1\|v2" | — |

### 1.6 gold 품질 기계 점검 (내 스크립트, dev 위주 + 전 건 기계 검사)

| 점검 | 결과 |
|---|---|
| 요일 표기(`M월 D일(요)`, `M월 D일 X요일`) 17건을 2026-11~2027 달력과 대조 | 불일치 0 |
| forbidden_claim이 공백 제거 원문에 있는지 | 0 |
| forbidden_claim이 같은 건의 key_facts·대표/허용 태그·엔티티·허용 의도에 들어 있는지 | **1건: `ing2_0038` `입장료` ⊂ key_fact `입장료는 없다`** (M1) |
| 숫자형 forbidden_claim(`5도`, `2도`, `4주`, `10kg`)이 원문의 더 긴 숫자 뒤에 붙는지 | 0 |
| dev 표본 10건(0001, 0011, 0016, 0021, 0038, 0040, 0055, 0059, 0069, 0076) 원문·gold 대조 | key_facts는 원문 근거가 있고 바꿔 쓰기다. 주관 판단 지점(0016 `김치찌개`를 product 엔티티로, 0040 category `tech`)은 사람 검수 논점으로 남김 |
| 긴 글 5건 고유 문장 비율 (내 문장 분리 기준) | 0031 0.81, 0033 0.74, 0046 0.65, 0032 0.59, **0066 0.19** (L5) |

## 2. 피드백 (심각도 순, `파일:줄`)

### M1. gold 자기모순: 핵심 사실을 그대로 담은 요약이 "비충실 1.0"이 된다 (중간)

- **위치:** `scripts/golden_ingest_v2/data_*.py`의 `ing2_0038` 레코드 → `data/golden/ingest/annotations.jsonl` (`ing2_0038`, dev, 사용자 표본 포함). 검사기 `src/jupjup/eval/ingest_golden_checks.py:176-178`.
- **현상:** key_facts에 `입장료는 없다`가 있고 forbidden_claims에 `입장료`가 있다. 충실도 결합 규칙은 `normalize_text(claim) in normalize_text(summary)`면 그 건을 바로 1.0으로 만든다 (`src/jupjup/eval/judge.py:164`). 원문은 "입장은 무료"라서 검사기의 "forbidden_claim이 원문에 없음" 규칙은 통과한다. 그래서 key_fact 재현율을 올리려고 "입장료는 없다"라고 쓴 **가장 충실한 요약이 비충실 1.0**을 받는다. 핵심 사실 재현율과 비충실 비율이 서로 반대로 움직이는 gold다.
- **왜 중간인가:** dev 1건이지만 T25h 프롬프트 조정이 dev만 보고 하므로(8.2절), 이 건이 "입장료"라는 단어를 피하라는 잘못된 신호가 된다. 같은 모양의 오류를 검사기가 구조적으로 못 잡는다.
- **고칠 방향:** ① `ing2_0038`의 forbidden_claim을 `입장료 N원`·`유료 입장`처럼 원문과 반대되는 주장으로 바꾼다. ② `check_ingest_templates`에 "forbidden_claim이 같은 건의 key_facts·representative/acceptable_tags·entity 이름의 부분 문자열이면 오류" 규칙을 더하고 `test_template_checker_flags_each_rule`에 사례를 넣는다. ③ 한 글자 forbidden_claim(`ing2_0069` `굴`)은 `얼굴`·`동굴`처럼 무관한 단어에도 걸리므로 최소 길이(예: 2자 이상, 또는 `굴을 넣`처럼 서술형)를 REVIEW_GUIDE 규칙과 검사기에 둔다.

### L1. test 봉인이 생성기 실행만으로 조용히 다시 찍힌다 (낮음)

- **위치:** `scripts/golden_ingest_v2/build.py:172-173`, `src/jupjup/eval/ingest_golden_checks.py:273-277`.
- **현상:** `build.py`(인자 없음)는 매번 `compute_test_seal`로 `test.sha256`을 새로 쓴다. 그래서 `data_*.py`에서 test gold를 고치고 재생성하면 봉인이 자동으로 맞춰지고 `validate-ingest`는 통과한다. 불일치 메시지가 요구하는 "이유를 기록하고 다시 봉인"은 도구로 강제되지 않는다. 남는 방어선은 git diff에서 `test.sha256` 변경을 사람이 보는 것뿐이다. 하네스도 실행 시점에 봉인을 확인하지 않는다 (보고서 7.4에 명시).
- **고칠 방향:** `build.py`가 기존 `test.sha256`과 다른 봉인을 만들 때 `--reseal --reason "<이유>"` 없이는 쓰지 않게 하고, 이유를 `manifest.json`(또는 `review_metadata.json`)의 봉인 이력에 남긴다. T25h 전에 recorded/live test 실행 때 봉인 확인을 하네스에 넣을지 정하고, 넣는다면 리포트 `config`에 봉인 해시를 남긴다.

### L2. mock 기준선과 리포트 파일이 골든 버전을 모른다 (낮음)

- **위치:** `src/jupjup/eval/ingest_harness.py:354`, `src/jupjup/eval/ingest_harness.py:988-993`, `src/jupjup/eval/ingest_report.py:191`, `src/jupjup/cli.py:937-939`.
- **현상:** ① `eval ingest --mode mock --golden v2 --baseline data/baselines/ingest.mock.json`(v1 기준선)도, 그 반대 조합도 PASS로 돈다. 기준선은 mode·profile만 대조하고 골든 정체성(경로, 건수, 봉인)은 대조하지 않는다. 지금은 두 기준선 지표가 같아서 결과가 같지만, 기준선에 다른 지표가 생기면 엉뚱한 골든과 비교된다. ② v1과 v2 mock 리포트가 같은 이름 `eval_ingest_mock_<split>.json`으로 써져 `reports/`에서 서로 덮어쓴다. ③ `IngestEvalConfig(mode="mock", sources_path=<v2>)`처럼 코드에서 경로만 바꾸면 `baseline_path` 기본값은 여전히 v1 기준선이다.
- **고칠 방향:** 기준선에 `golden`(버전 또는 sources 상대 경로)을 넣고 `_finish_gate`에서 대조한다. 리포트 stem에 골든 버전을 넣거나(v1은 기존 이름 유지, v2만 `eval_ingest_mock_v2_<split>` 등) CLI 출력에 덮어쓰기 위험을 적는다. `baseline_path` 기본값도 `_default_golden_by_mode`에서 같이 고른다.

### L3. 검사기 빈틈: forbidden_claim·key_fact 관계와 locations `level` 누락 (낮음)

- **위치:** `src/jupjup/eval/ingest_golden_checks.py:163-183`.
- **현상:** M1의 근본 원인이다. 검사기는 forbidden_claim을 원문과만 대조하고 같은 gold와는 대조하지 않는다. 또 `ing2_0039`(경기 북부, 강원, 철원), `ing2_0057`(부산) 네 장소에 `level`이 없다. 스키마상 선택값(`ingest_harness.py:153`)이라 오류는 아니지만, REVIEW_GUIDE가 장소 수준을 정하라고 하므로 일관성 검사가 있으면 좋다.
- **고칠 방향:** M1의 ② 규칙 추가. `level` 누락은 경고로 띄운다.

### L4. `기타`를 허용 저장 의도로 18건(22%)에 넣었다 (낮음, 사람 검수 논점)

- **위치:** `data/golden/ingest/annotations.jsonl` (`save_intent.acceptable`의 `기타` 18건), 계산 `src/jupjup/eval/ingest_harness.py:896-897`.
- **현상:** `save_intent_correct`는 예측 라벨 하나라도 `labels`나 `acceptable`에 있으면 정답이다. 그 밖 범주인 `기타`를 18건에서 허용하면, 확신이 없을 때 `기타`를 섞어 내는 분석기가 저장 의도 정확도(합격선 0.70)를 쉽게 얻는다. 의도 라벨이 0~3개라서 실제로 섞어 낼 수 있다.
- **고칠 방향:** 교차 검수 때 `기타`를 허용 의도에서 빼고, 정말 다른 의도가 없는 건만 `labels`에 `기타`를 둔다. REVIEW_GUIDE에 규칙으로 적는다.

### L5. 긴 글 fixture의 내부 반복이 크다 (낮음, 보고서 7.2에 이미 명시)

- **위치:** `scripts/golden_ingest_v2/long_docs.py` (특히 `long_tongyeong_diary` 생성부, `ing2_0066` test).
- **현상:** 내 문장 분리 기준 고유 문장 비율이 `ing2_0066` 0.19, `ing2_0032` 0.59다 (`그날의 작은 기록 #.` 144회, `이날 찍은 사진은 #장이다.` 123회 등). 템플릿 검사 (a)는 **다른 원문 사이** 중복만 재고 한 원문 안의 반복은 재지 않아 통과한다. 청킹·사실 위치 분산 시험에는 쓸 수 있지만, map_reduce 부분 요약이 반복 틀을 사실처럼 옮기는지 볼 때 실제 긴 글보다 쉬운 입력이다. 설계 8.1절이 v1 fixture 재사용까지 허용했으므로 큰 감점은 아니다.
- **고칠 방향:** 검사기에 "긴 글 내부 고유 문장 비율 하한(예: 0.5)" 경고를 더하고, 교차 검수에서 부족하다고 보면 `ing2_0066`부터 다시 쓴다. test 건이므로 다시 쓰면 봉인을 다시 하고 이유를 남긴다 (L1).

### 참고 (감점 없음)

- v1 mock 리포트 경로 두 줄 변경은 설계 8.1절 "v1을 `ingest_v1/`로 옮긴다"의 직접 결과이고, 기준선 파일과 md 리포트는 바이트 동일하다. AC-L2 위반으로 보지 않았다.
- `sample_for_user.jsonl` 24건 중 test가 11건이다. 사용자는 분석기·프롬프트 작업자가 아니라 봉인 원칙과 충돌하지 않지만, 보고서 7.6 제안대로 사용자가 T25h 조정에 참여한다면 test 표본을 dev로 바꿔 다시 뽑는 편이 안전하다. PM이 사용자에게 확인할 항목이다.
- 동결 해시(`frozen_config_sha256`)에는 골든 정체성이 없다. 8.2절이 요구하지 않으므로 감점하지 않았지만, T25h 리포트에 `test.sha256` 값을 같이 남기길 권한다 (L1과 같이 처리).
- 이전 검수 T25f M1(recorded 연결 지표의 임베딩 미스 미검출)은 T25c 범위 밖이고 그대로 남아 있다. T25h 전에 고쳐야 한다는 판단은 유지한다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 범위 안 완료 조건 전부 직접 재현, 테스트·eval·검색 무회귀 확인 (+). M1 gold 자기모순 −2, L4 `기타` 허용으로 의도 정확도 부풀림 위험 −1 |
| 안전성 | 28 / 30 | 네트워크 0, `llama_cpp` 미로드, 봉인이 test gold·fixture 바이트 변조를 잡음, 잘못된 `--golden` 종료 2 (+). L1 봉인 재생성 무마찰 −1, L2 기준선·리포트의 골든 정체성 부재 −1 |
| 유지보수성 | 28 / 30 | 결정적 생성기와 `--check`, 13개 테스트, REVIEW_GUIDE·README·보고서가 실제와 일치 (+). L3 검사기 빈틈 −1, L5 긴 글 내부 반복을 재는 검사 없음 −1 |
| **합계** | **93 / 100** | **PASS** |

## 4. 다음 단계 제안

1. 남은 T25c 완료 조건(Codex 독립 교차 검수 → 불일치 목록 → 사용자 판정 + 표본 24건 → `data_*.py` 반영 → 재봉인 → `review_metadata.json`)을 진행할 때 M1·L4를 교차 검수 항목에 넣는다.
2. 검사기 보강(M1 ②③, L3, L5 경고)과 L1·L2는 T25g가 `src/jupjup/eval/`을 만질 때 짧은 커밋으로 묶는다.
