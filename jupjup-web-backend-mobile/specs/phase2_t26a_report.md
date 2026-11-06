# Phase 2 T26a 보고서: compare_profiles와 compare-profiles CLI

- 작성: Codex-Primary 역할 (Claude가 실행)
- 기준일: 2026-11-02
- 설계: `specs/design_local_analyzer.md` 8.6절, 10.1절 T26a, 11절(AC-L7), 14절 / PRD 3.5.4·3.5.5절, AC-29
- 기준 커밋: `8db3dee`

## 1. 구현 범위

| 항목 | 파일 | 내용 |
|---|---|---|
| 판정 본체 | `src/jupjup/eval/ingest_compare.py` (신규) | `DeltaCI`, `BenchPair`, `SwapDecision`, `CompareRefused`, `paired_bootstrap`, `compare_profiles`, `render_swap_markdown`, `load_report`, `load_bench` |
| 두 방향 규칙 | 같은 파일 | **downgrade**: 3.5.4절 절대 기준 전부(`LOCAL_GATE` + recorded 검색 연결 하락 ≤ 0.03) + 하락 허용치(태그·엔티티·장소 F1 ≤ 0.03, 비충실 증가 ≤ 0.01, 검색 연결 Recall@10 하락 ≤ 0.02) + 95% 구간의 나쁜 쪽 끝도 허용치 안 + 자원 30% 이상 개선(single p95, 피크 RSS, 비용 중 최댓값). **upgrade**: 절대 기준 전부 + 주요 지표(비충실, 핵심 사실 재현율, 엔티티 F1, 태그 F1) 중 하나 이상의 구간이 개선 쪽에 완전히 있음 + 허용치 지표 모두 downgrade 허용치 안 + live single p95 ≤ 60초 |
| 부트스트랩 | 같은 파일 | 건(source_id) 단위 쌍 재표집. `random.Random(seed)`로 고정, 한 번 뽑은 인덱스를 모든 지표에 같이 쓴다. 실패 건(지표 없음)은 리포트 `overall`처럼 평균에서 뺀다. 백분위는 선형 보간(numpy 기본과 같음). 기본값 `n_boot=1000`, `seed=20261102` |
| 비교 거부 | 같은 파일 | `CompareRefused(ValueError)`: split 불일치, `golden_sha256` 없음·불일치, mock 리포트(로컬 프로필 실행 아님), 녹화 미스 있음, 판정기 프로필 불일치, 판정기 블록이 한쪽에만 있음, 판정기 `recording_model_id`·프롬프트 불일치, 판정기 보정 상태 불일치, 건 목록 불일치·중복·빈 목록, 벤치의 프로필·모델이 리포트와 다름, 두 벤치의 split 불일치 |
| 경고 | 같은 파일 | 건수 < 40, 검색 연결은 점추정, mode가 서로 다름, 프로필이 같음, 판정기 미사용·미보정, 후보 map_reduce p95 예산 초과 |
| 골든셋 해시 | `src/jupjup/eval/ingest_golden_checks.py` | `compute_split_digest(golden, fixtures_root, split)`. test 봉인과 같은 형식(원문·fixture 바이트·gold·split)을 dev/test/all로 일반화했다. `compute_test_seal`은 이 함수의 test 분기를 그대로 호출한다(값 동일, 테스트로 확인) |
| 리포트 필드 | `src/jupjup/eval/ingest_harness.py` | `IngestEvalReport.golden_sha256`. **recorded/live에서만** 채우고, None이면 `deterministic_dict`에서 뺀다. 그래서 mock 리포트는 바이트가 같다. `IngestEvalHarness.compare_profiles`는 `NotImplementedError` 대신 새 함수에 위임한다 |
| CLI | `src/jupjup/cli.py` | `jupjup eval compare-profiles --candidate a.json --incumbent b.json --direction downgrade|upgrade [--bench-candidate x.json --bench-incumbent y.json] [--n-boot 1000] [--seed 20261102] [--out d.json]`. 판정 마크다운을 화면에 출력하고, `--out`을 주면 JSON과 같은 이름의 `.md`를 쓴다. 종료 코드는 0 교체 후보, 1 교체 불가, 2 비교 거부·입력 오류. 모델을 부르지 않고 네트워크도 쓰지 않는다 |

델타 부호는 언제나 `후보 − 현행`이다. 높을수록 좋은 지표는 음수가 나빠짐이고, 비충실 비율은 양수가 나빠짐이다. `eligible`은 `reasons`(미충족 사유)가 비어 있을 때만 참이다.

## 2. 설계 대비 차이 (이유)

1. **`golden_sha256` 리포트 필드 추가.** 8.6절은 "골든셋 해시가 다르면 거부"라고 정했지만, 기존 리포트에는 골든셋 해시가 없었다. 경로만 비교하면 gold를 고쳐도 알아챌 수 없다. 그래서 recorded/live 리포트에만 필드를 더했다. mock은 None이고 직렬화에서 빠지므로 mock 결과는 한 바이트도 바뀌지 않는다(확인함). recorded 리포트에는 키가 하나 늘어난다. 아직 커밋된 recorded 인제스트 기준선이 없어 무효화되는 파일은 없다.
2. **`SwapDecision`에 설명 필드 추가.** `candidate_profile`, `incumbent_profile`, `split`, `golden_sha256`, `n_items`, `n_boot`, `seed`, `warnings`를 더했다. 판정에는 쓰지 않는다. "건수 < 40 경고를 리포트에 낸다"는 요구를 `warnings`로 채웠다.
3. **검색 연결 Recall@10은 구간 없이 점추정으로 판정한다.** 리포트 `search_linkage`에 질의별 값이 없어 쌍 부트스트랩을 할 수 없다. `ci_low = ci_high = delta`로 두고 경고에 적었다. 질의별 값을 리포트에 넣으려면 T25f 연결 지표의 출력 형식을 바꿔야 하므로 이번 범위 밖으로 남겼다(3절).
4. **upgrade의 "나머지 지표는 downgrade 허용치 안"을 점추정과 구간 끝 둘 다로 본다.** downgrade와 같은 판정 함수를 쓴다. 엄격한 쪽을 택했다. 개선된 주요 지표는 구간이 0을 넘으므로 이 검사를 자동으로 통과한다.
5. **자원 개선은 live 벤치(`BenchPair`)로만 판정한다.** 리포트의 `latency_*`는 녹화 시점 값이라 쓰지 않는다(8.5절). 비용은 현행 비용이 0보다 클 때만 상대 개선을 계산한다. 로컬끼리 비교하면서 벤치를 주지 않으면 downgrade는 "자원 개선 판정 불가", upgrade는 "지연 예산 판정 불가"로 교체 불가가 된다.
6. **절대 기준에 recorded 검색 연결 지표가 꼭 있어야 한다.** 3.5.4절 기본 분석기 열에 포함되기 때문이다. `--linkage recorded`를 빼고 만든 후보 리포트는 교체 불가가 된다.
7. **거부 조건을 넓혔다.** 판정기 모델·프롬프트·보정 상태 불일치(지표 정의가 달라진다)와 녹화 미스가 있는 리포트도 거부한다.

## 3. 테스트

`tests/unit/test_ingest_compare.py` (신규, 39건, 손으로 만든 리포트 쌍. AC-29, AC-L7)

- 부트스트랩: 선형 보간 백분위 손계산, 건마다 같은 차이면 구간 폭 0, 결측 건을 평균에서 제외, seed 결정성(같은 seed면 같고 다른 seed면 구간만 달라짐), 잘못된 입력 거부, `compare_profiles` JSON 바이트 결정성
- downgrade: 허용치 안 + 자원 개선 → eligible, 4개 지표 각각 점추정 초과 → 거부(비충실은 증가가 나빠짐), 비충실 감소는 하락이 아님, 점추정은 허용치 안이지만 구간이 넘으면 거부, 검색 연결 하락 초과, 자원 개선 30% 경계(20%는 불가, 정확히 30%는 통과), 벤치 없으면 판정 불가, 비용 개선 경로
- 절대 기준: 두 방향 모두 차단, recorded 연결 지표 필요, 값 None은 미충족
- upgrade: 주요 지표 개선 + 예산 → eligible, 비충실 감소도 주요 개선으로 셈, 구간이 0을 포함하면 개선 없음(주요 지표가 아닌 카테고리 개선은 세지 않음), 다른 지표가 허용치를 넘으면 거부, single p95 61초·벤치 없음은 거부, map_reduce 초과는 경고만
- 경고: 32건 경고, 40건은 경고 없음, 판정기 미보정
- 비교 거부: split, 해시 불일치, 해시 없음, mock, 판정기 프로필, 건 목록, 녹화 미스, 판정기 프롬프트, 보정 상태, 판정기 블록 한쪽, 중복 건, 후보·현행 벤치 프로필 불일치, 잘못된 direction
- 하네스 메서드 위임, 마크다운 내용
- CLI: 종료 0(JSON·md 출력), 1(벤치 없음), 2(split 거부, 잘못된 direction, 벤치 한쪽만, 깨진 JSON)

`tests/integration/test_ingest_record_replay.py`에 1건 추가: 실제 recorded dev 리포트에 `golden_sha256`이 있고 `compute_split_digest(dev)`와 같음, `compute_split_digest(test)` = `compute_test_seal` = 커밋된 `test.sha256`, 파일로 쓴 리포트를 다시 읽어 자기 자신과 비교하면 델타 0, mock 리포트에는 키가 없고 비교가 거부됨

## 4. 직접 실행한 명령과 결과 (기본 설치, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | 종료 0, **1266 passed, 4 deselected**(기존 1226 + 신규 40). 실패 0, skip 0 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 90 source files |
| `uv run jupjup eval validate`, `eval validate-ingest` | 둘 다 종료 0 |
| `uv run jupjup eval run --mode mock|recorded --split dev|test` | 4개 모두 종료 0. 기준 커밋 `8db3dee`(`git archive`로 뽑은 사본) 결과와 비교하면 절대 경로(`config.*`), `created_at`, `git_sha`(사본에는 .git이 없음), `perf.latency_*`만 다르고 **지표는 모두 같다**. 검색 수치 무회귀 |
| `uv run jupjup eval ingest --mode mock --golden v1|v2 --split dev|test|all` | 6개 모두 종료 0(PASS). 두 번 실행하면 바이트 동일, 기준 커밋 결과와도 **바이트 동일**(`diff -r`) |
| `python -c "import jupjup.eval.ingest_compare, jupjup.cli; 'llama_cpp' in sys.modules"` | False |
| `git diff -- src/jupjup/search src/jupjup/query data/` | 변경 없음 (검색 기준선, 녹화·임베딩 파일 그대로) |

## 5. 남은 문제

- **실제 프로필 리포트 쌍으로 비교한 적은 없다.** T25h(녹화·튜닝) 범위다. 지금은 손으로 만든 리포트와 MockLLM recorded 리포트로만 확인했다.
- **검색 연결 Recall@10은 점추정이다**(2절 3번). 구간까지 내려면 연결 지표에 질의별 recall을 남겨야 한다. T25h 전에 짧은 후속 작업으로 해도 된다.
- PRD 3.5.5절 5번(test split 재확인)과 7번(플랫폼 라우팅 부분집합 ≥ 20건)은 이 함수가 강제하지 않는다. test 리포트 쌍을 같은 함수에 넣으면 된다. 라우팅은 T26b 범위다.
- recorded 리포트 JSON에 `golden_sha256` 키가 하나 늘었다. T25h에서 recorded 기준선을 처음 커밋할 때 이 형식으로 만들어진다.
