# Phase 4 최종 검수 — T25t dev 튜닝·승격 후보 Loop 1/3

- **점수:** 100 / 100
- **상태:** PASS
- **항목별 점수:** 정확성 40 / 40, 안전성 30 / 30, 유지보수성 30 / 30
- **판정 범위:** Loop 1 검수 PASS. 이는 Phase 2 dev 튜닝·기록 재현 작업에 대한 판정이며, 어떤 로컬 모델도 제품 기본 분석기로 승격하는 승인은 아니다.

## 요약

튜닝 변경 기록, dev 수치, frozen config와 모델 provenance가 추적 가능하다. Qwen2.5-7B·Kanana-8B recorded dev는 miss 0이며 각 모델의 두 리포트가 바이트 단위로 재현된다. 구현 보고서도 모델 품질 기준 미달과 test 평가 미실시를 명시하고 기본 프로필 `mock`을 유지한다. 실제 모델을 사용하는 ingest test split은 실행하지 않았다.

요청된 기준은 모두 확인했다. dev 후보가 제품 품질 문턱을 넘지 못한 것은 구현·보고 오류가 아니며, 보고서가 이를 승격 보류로 처리하므로 감점하지 않았다. 사람 검수 미완료도 감점하지 않았다.

## 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **1430 passed, 5 deselected**, 경고 3개, 143.43초 |
| `uv run ruff check src tests` | 통과 |
| `uv run mypy src` | `Success: no issues found in 106 source files` |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259(dev 158/test 101), ingest annotations 80(dev 48/test 32) 확인 |
| `uv run jupjup eval run --mode mock --split dev/test --baseline data/baselines/mock.json` (split별 실행) | dev/test 모두 PASS |
| `uv run jupjup eval run --mode recorded --split dev/test --baseline data/baselines/recorded.json` (split별 실행) | dev/test 모두 PASS |
| 위 mock/recorded 검색 평가의 동일 split 재실행 및 `results` 비교 | 네 조합 모두 결과 레코드가 동일. 전체 JSON 리포트는 `created_at`·실측 latency 필드가 달라 바이트 동일하지 않음 |
| `uv run jupjup eval ingest --mode mock --out /tmp/t25t-review-ingest-{1,2}` | 두 번 PASS. JSON SHA256 양쪽 `e3c79ef4cc82a0f54779035b1107cc89d693a50620928e41d3353ac6a38890aa`, Markdown `395256ed89be5ff3e416ac8f0edb511ffe10d855d1cd9a3dab4cc905c5897c75`로 동일 |
| `uv run jupjup analyze freeze --profile tuning-qwen25-7b` / `...tuning-kanana-8b` | 각각 frozen SHA256 `8d899e6a516997ce23ae5268ee186580228b5828131df3215eeef8e4b713f04b`, `c228aa98a94c89ac638ab715aa2573d96adb79560a753c12cfa9cf6703292e53` |
| `uv run jupjup eval ingest --mode recorded --profile tuning-qwen25-7b --split dev --linkage none --frozen-config 8d899e6a516997ce23ae5268ee186580228b5828131df3215eeef8e4b713f04b --out /tmp/t25t-qwen-run{1,2}` | 두 실행 모두 품질 미달로 exit 1(예상). 리포트 JSON·Markdown 각 SHA256이 두 실행 간 동일. `misses: []` |
| 기본 설치 import 확인: `uv run python -c 'import sys; import jupjup.cli; print("llama_cpp imported:", "llama_cpp" in sys.modules)'` | `False` |
| test split 실행 제한 코드 확인 | `src/jupjup/eval/ingest_harness.py`에서 frozen-config 확인이 분석기 평가 실행보다 먼저 수행됨. test split의 실제 모델 실행 명령은 Phase 2 manifest에 없음. 검색 recorded test는 로컬 모델 분석기 실행과 별개 |
| 네트워크 접근 코드·테스트 확인 | 로컬 LLM은 로컬 파일을 열고 네트워크 API를 호출하지 않음. `tests/unit/test_llm_local.py::test_no_network_on_load_and_generate`, `test_network_code_lives_only_in_models_pull`, fetch 및 ingest 파이프라인 네트워크 차단 테스트 포함. 전체 pytest 통과 |

보고서의 후보 provenance에는 고정 revision·SHA256·라이선스가 기록되어 있다. `specs/artifacts/t25t/model-provenance.json`에서 Qwen2.5-7B 두 GGUF 조각과 Kanana-8B GGUF의 SHA256 및 config 일치 여부를 대조했고, 모두 `matches_config: true`, Apache-2.0이다. `specs/artifacts/t25t/recorded-dev/`의 두 후보 보고서 모두 frozen config와 `misses: []`를 포함한다. 실제 재생은 Qwen2.5-7B 후보에 대해 직접 두 번 실행해 같은 결과를 확인했다.

## 피드백 (심각도 순)

- **정보:** [phase2_t25t_tuning_report.md](/Users/minjun/orca/workspaces/dc2/phase-4-review-t25t-loop1/specs/phase2_t25t_tuning_report.md:189)의 기준 표는 두 승격 후보의 스키마·태그·엔티티·장소·카테고리·사실·비충실 기준 미달을 투명하게 기록한다. 같은 보고서가 223행에서 기본값 유지와 승격 보류를 선언하므로 제품 채택으로 오해될 주장은 확인되지 않았다. 후속 루프에서도 이 미달 상태를 유지하고, test 실행은 동결·별도 승인 절차 이후에만 수행해야 한다.

## 결론

Loop 1 검수 **PASS**. dev 기록과 재현성이 확인됐고, mock 결정성과 안전 경계가 유지됐다. 모델 후보는 dev 품질 문턱을 충족하지 않으므로 승격 대상이 아니다. 이번 검수 범위에서 코드 변경은 없었다.
