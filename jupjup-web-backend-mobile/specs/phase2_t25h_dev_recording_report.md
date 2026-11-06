# Phase 2 T25h 보고서 — dev 로컬 분석기 녹화와 판정기 라벨 표본

- 작성: Orca Codex-Primary
- 기준일: 2026-11-03
- 기준 커밋: `e925a17`
- 설계: `specs/design_local_analyzer.md` 7.4절, 8.2~8.6절, 10.1절 T25h, 11절 인수 기준, 14절 핵심 사항
- 범위: `dev` 분석기·검색 연결 녹화와 사람 판정용 빈 라벨 표본. 프롬프트 튜닝, 실제 후보의 `test` split, 사람 라벨 작성은 하지 않았다.

## 1. 구현 범위와 산출물

| 항목 | 파일/결과 | 내용 |
|---|---|---|
| 이어 녹화 결함 수정 | `src/jupjup/providers/recording.py` | 기존 `--append`는 녹화 키를 알고도 live 모델을 먼저 호출하고 파일 쓰기만 생략했다. 로드한 응답·토큰 수를 키별 저장해 기존 요청은 live 호출 없이 깊은 복사로 즉시 재사용하게 했다. 녹화 형식 v2와 요청 키는 바꾸지 않았다 |
| 결함 재현 테스트 | `tests/unit/test_ingest_analyzer_providers.py` | 새 `RecordingLLM` 인스턴스로 기존 파일을 연 뒤 inner가 호출되면 실패하도록 고정했다. 응답·토큰 재사용과 파일 바이트 불변을 확인한다 |
| Kanana dev+seed 녹화 | `data/recordings/llm/analyze.kanana-1.5-2.1b-instruct-q4km_at_5baf76ee0939_dec_bbdbf37b.jsonl` | 682행, 약 2.0MB. dev 48건과 검색 시드 200건을 `--append`로 완성했다 |
| Qwen dev+seed 녹화 | `data/recordings/llm/analyze.qwen3-4b-instruct-2507-q4km_at_f51854d09631_dec_bbdbf37b.jsonl` | 558행, 약 984KB. dev 48건과 검색 시드 200건을 `--append`로 완성했다 |
| 검색 연결 녹화 | `data/recordings/linkage/embeddings.bge-m3.local-{kanana-2b,qwen3-4b}.jsonl` | Kanana 433벡터(약 3.0MB), Qwen 549벡터(약 3.1MB). BGE-M3 캐시를 오프라인 모드로 열어 생성했다 |
| 판정 라벨 표본 | `data/golden/ingest/judge_labels.dev.jsonl` | 160행: 문장 100, 핵심 사실 60. `sample_id` 160개가 모두 고유하고 `label`, `annotator` 160행 모두 `null`이다 |
| 판정기 모델 | `/Users/minjun/orca/workspaces/dc2/models/gguf/kanana-1.5-8b-instruct-q4km/…Q4_K_M.gguf` | 저장소 밖 모델 캐시에 f16 중간본에서 Q4_K_M으로 재생성했다. SHA256 `fbe5103bfe68ec23cb8ea2d3e90ff9f3979b933df4169ba05b348f2b818eed57` |
| 설정 | `config/analyzer_profiles.yaml` | Kanana-1.5-8B Q4_K_M의 f16 직행 변환 설명과 새 SHA256을 기록한다 |

모든 커밋 대상 녹화 파일은 10MB 미만이어서 Git LFS를 추가하지 않았다. 모델 가중치는 저장소에 넣지 않았다.

## 2. 실행 결과

### 2.1 recorded dev 품질

최종 리포트는 `--linkage recorded`로 후보별 세 번 만들었다. JSON과 Markdown은 각 후보에서 1·2·3회가 `cmp`로 바이트 동일했고 `misses`는 모두 0이었다. 판정 라벨은 아직 사람이 작성하지 않았으므로 런타임 표시는 설계대로 `deterministic_only`(판정기 미보정)이다.

| 지표 | Kanana-2B | Qwen3-4B | 기준 | 결과 |
|---|---:|---:|---:|---|
| dev 성공/전체 | 35/48 | 37/48 | 48/48 | 둘 다 미달 |
| schema first | 0.5208 | 0.4792 | ≥ 0.97 | 둘 다 미달 |
| schema final | 0.7292 | 0.7708 | = 1.00 | 둘 다 미달 |
| tag F1 | 0.3577 | 0.5179 | ≥ 0.70 | 둘 다 미달 |
| entity F1 | 0.2981 | 0.3175 | ≥ 0.80 | 둘 다 미달 |
| location F1 | 0.5857 | 0.7838 | ≥ 0.85 | 둘 다 미달 |
| category accuracy | 0.4571 | 0.4595 | ≥ 0.85 | 둘 다 미달 |
| save-intent accuracy | 0.6000 | 0.8649 | ≥ 0.70 | Qwen만 통과 |
| key-fact recall | 0.2595 | 0.2500 | ≥ 0.85 | 둘 다 미달 |
| unsupported sentence rate | 0.1738 | 0.1014 | ≤ 0.03 | 둘 다 미달 |
| injection resistance | 1.0000 | 1.0000 | = 1.00 | 둘 다 통과 |
| recorded linkage Recall@10 하락 | 0.059408 | 0.042770 | ≤ 0.03 | 둘 다 미달 |

따라서 두 후보의 dev 리포트 종료 코드는 품질 게이트 실패를 뜻하는 1이다. 녹화 미스나 실행 오류를 뜻하는 실패는 아니다. 기준을 낮추거나 프롬프트를 튜닝하지 않았다.

### 2.2 검색 시드와 linkage

| 후보 | 시드 성공 | 시드 실패 | linkage 벡터 | 사람 Recall@10 | 분석기 Recall@10 | 하락 |
|---|---:|---:|---:|---:|---:|---:|
| Kanana-2B | 33 | 167 | 433 | 0.971521 | 0.912113 | 0.059408 |
| Qwen3-4B | 149 | 51 | 549 | 0.971521 | 0.928751 | 0.042770 |

`record-linkage`는 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`과 중앙 캐시 경로를 명시해 실행했다. 기존 다른 작업 트리에 있던 고정 BGE-M3 스냅샷을 중앙 모델 캐시로 복사했고, 가중치 SHA256 `b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`이 원본과 복사본에서 같음을 확인했다. 서비스·워커 경로는 실행하지 않았으며 네트워크를 쓰지 않았다.

후보별 dev 평가 동결 해시는 Kanana-2B
`03506b0f62899f00a162e1ea60a5f1ee344135940f16bae4271c40a7c14e9144`, Qwen3-4B
`fd5a0a67493c23f8988fc78e616c240485d4ca83a47f541d23a14877135cd6e0`이다. 아래 명령 표의
`<sha>`는 각각 이 값을 뜻한다.

### 2.3 판정기 라벨 표본

`judge-sample --candidates local-qwen3-4b,local-kanana-2b --mode recorded` 결과는 다음 검사를 통과했다.

- 전체 160행, `sentence` 100행, `keyfact` 60행
- `sample_id` 160개 고유
- 문장 행은 `sentence`, `source_excerpt`, `summary`, 문장 인덱스를 포함
- 핵심 사실 행은 `fact`, `summary`, 사실 인덱스를 포함
- `label == null` 160행, `annotator == null` 160행
- dev 출력만 사용. 사람 판정은 하지 않음

## 3. 설계 대비 차이와 이유

1. **8B 변환의 모델 읽기에 `models pull` 대신 변환 도구의 `--remote` HTTP range 경로를 썼다.** 설계 14.1은 다운로드를 `models pull`로 한정하지만, 이 모델은 공식 GGUF를 받는 것이 아니라 공식 safetensors를 f16 GGUF로 변환해야 한다. T25b용 `convert_quantize.py`가 8B의 디스크 제약을 위해 제공한 경로를 그대로 사용했다. 실행 직전 `git ls-remote`로 `main == c963a5f4f6496c749f94064a20b33028b0db9f19`를 확인하고, 완료 뒤 다시 확인했다. 사용자 원문이나 서비스 데이터는 전송하지 않았다.
2. **BGE-M3를 새로 내려받지 않고 기존 로컬 캐시에서 중앙 캐시로 옮겼다.** 지정 중앙 캐시에 가중치가 없어 `record-linkage`가 오프라인 실패했기 때문이다. 같은 revision의 blob SHA256을 확인했고 이후 실행은 오프라인으로 강제했다. 복사 중 역참조돼 중복된 두 대형 스냅샷 파일은 동일 blob을 가리키는 Hugging Face 표준 상대 심볼릭 링크로 복구했다.
3. **`RecordingLLM --append`를 수정했다.** 설계와 T25f 보고서는 기존 요청을 건너뛰어 이어 쓰기가 안전하다고 전제했지만 실제 구현은 inner 모델 호출 뒤 쓰기만 생략했다. 장시간 녹화를 재개할 때 이미 끝난 요청을 다시 생성하는 결함이 이번 실제 녹화에서 드러나, 허용된 범위대로 재현 테스트와 함께 고쳤다.
4. **검색 연결 지표의 BGE 캐시 준비 때문에 평가 명령에서만 네트워크 없는 별도 캐시 경로를 지정했다.** 서비스·워커 설정과 검색 순위 코드는 건드리지 않았다.

그 밖에 프롬프트, 디코딩 정책, 검색 순위, 검색 기준선, 기존 `data/recordings/embeddings`는 설계대로 변경하지 않았다. 실제 후보의 test split은 실행하지 않았다.

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `…/jupjup analyze record --profile local-kanana-2b --split dev --target ingest --append --confirm-run` | 완료. 최종 recorded dev 성공 35/48, 미스 0 |
| `…/jupjup analyze record --profile local-qwen3-4b --split dev --target ingest --append --confirm-run` | 완료. 최종 recorded dev 성공 37/48, 미스 0 |
| `…/jupjup analyze record --profile <후보> --target seeds --append --frozen-config <sha> --confirm-run` | Kanana 33/200 성공, Qwen 149/200 성공. 실패도 녹화 종료 상태로 집계됨 |
| `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 … jupjup analyze record-linkage --profile <후보> --frozen-config <sha>` | 두 후보 종료 0. Kanana 433, Qwen 549 벡터 |
| `uv run jupjup eval ingest --mode recorded --profile <후보> --split dev --linkage recorded` 각 3회 | 두 후보 모두 종료 1(품질 미달), 미스 0. 각 후보 JSON·Markdown 3회 바이트 동일 |
| `uv run jupjup eval judge-sample --candidates local-qwen3-4b,local-kanana-2b --mode recorded` | 종료 0. 100문장+60핵심 사실, 빈 라벨 160행 |
| `…/python -I scripts/spikes/convert_quantize.py … --remote --intermediate f16` | T25r venv 첫 시도는 `requests` 미설치로 중간본 생성 전 종료 1. 의존성이 갖춰진 spike venv로 재실행해 종료 0. 변환 807.0초, 양자화 43.8초 |
| `…/jupjup models doctor --cache-dir /Users/minjun/orca/workspaces/dc2/models --json` | 종료 0, `kanana-1.5-8b-instruct-q4km` present/sha256_ok 모두 true, recording model id `…@fbe5103bfe68~bbdbf37b` |
| `uv run pytest` | 두 번 모두 **1320 passed, 5 deselected**, 경고 2, 실패 0 (최종 114.16초) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 90 source files |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259, ingest 80 |
| `uv run jupjup eval run --mode mock --split dev/test --baseline data/baselines/mock.json` | 둘 다 종료 0(PASS). dev Recall@10 0.9620/nDCG 0.9795, test 0.9420/0.9589 |
| `uv run jupjup eval run --mode recorded --split dev/test --baseline data/baselines/recorded.json` | 둘 다 종료 0(PASS). dev Recall@10 0.9712/nDCG 0.9860, test 0.9720/0.9801 |
| `uv run jupjup eval ingest --mode mock` 2회 | 둘 다 종료 0(PASS), 출력 디렉터리 `diff -rq` 동일. 기본 split은 test지만 실제 모델을 호출하지 않는 기존 mock 배선·회귀 검증이다 |
| `uv run python -I -c "import jupjup.cli …"` | 기본 설치에서 `llama_cpp`가 `sys.modules`에 없음을 확인 |
| `git diff --exit-code -- src/jupjup/search src/jupjup/query data/recordings/embeddings` | 종료 0, diff 없음 |
| 녹화 JSONL `jq` 검사 | LLM 1,240행 요청 키 전부 고유, `system`/`user`/`prompt` 원문 필드 0건. 판정 라벨 스키마·행 수 통과 |

### 4.1 판정기 최종 검증

- 변환 전 디스크 여유: 40GB(15GB 이상이므로 생략 조건 해당 없음)
- 입력 revision: `c963a5f4f6496c749f94064a20b33028b0db9f19`
- 경로: f16 GGUF → Q4_K_M 직접 양자화(`allow_requantize=false`)
- llama-cpp-python: `0.3.36`
- 파일 크기: `4,920,765,440`바이트(약 4.6GiB)
- SHA256: `fbe5103bfe68ec23cb8ea2d3e90ff9f3979b933df4169ba05b348f2b818eed57`
- 설정 SHA256과 실제 파일 SHA256: `shasum -a 256` 및 모델 doctor로 일치 확인
- 변환 시간: f16 생성 807.0초, Q4_K_M 양자화 43.8초
- 변환 후 디스크 여유: 36GB, f16 중간본 삭제 확인

## 5. 남은 문제와 인수 기준 상태

1. **두 후보 모두 dev 품질 게이트를 통과하지 못했다.** Qwen이 상대적으로 낫지만 schema final, 태그·엔티티·장소·카테고리, 핵심 사실, 비충실 비율이 미달이다. Kanana는 save-intent까지 미달이다. 범위 밖인 프롬프트 튜닝이나 기준 완화는 하지 않았다.
2. **AC-L6 linkage 하락 ≤ 0.03도 둘 다 미달이다.** Kanana 0.059408, Qwen 0.042770이다. 특히 Kanana 시드 분석 성공이 33/200에 불과하다.
3. **판정기는 아직 미보정이다.** 사람 라벨이 비어 있으므로 AC-L5 κ ≥ 0.7을 주장할 수 없다. 리포트는 결정적 검사만 사용하며 이를 숨기지 않고 `deterministic_only`로 표시한다.
4. **AC-L4 recorded test 평가는 범위상 실행하지 않았다.** 사용자가 test 봉인을 명시했고 이번 작업은 dev 준비다. 동결 해시는 생성·사용했지만 후보 test 품질을 주장하지 않는다.
5. **기본 설치·검색 회귀·안전 조건은 통과했다.** 전체 pytest/ruff/mypy, eval validate, 검색 eval 4종, mock ingest 결정성, `llama_cpp` 지연 import, 금지 영역 diff 0, 녹화 원문 필드 0을 확인했다.
6. **보고서의 dev latency는 live 녹화에 저장된 관측값이지 recorded 실행 시간은 아니다.** Kanana p50/p95 16.47/59.21초, Qwen 28.32/511.42초이며 Qwen의 긴 꼬리가 매우 크다. 이번 범위에는 별도 `bench analyze` 재측정이 없다.
