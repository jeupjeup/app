# T25 로컬 소형 모델 콘텐츠 분석기 설계

- 작성: Claude-Architect
- 기준일: 2026-11-02
- 상태: Phase 1 설계안. 13절 열린 질문은 PM 추천 기본값으로 바로 구현을 시작할 수 있다
- 사용자 결정 (2026-11-02): T25 콘텐츠 분석기는 **로컬 소형 모델**로 만든다. 외부 LLM API(Anthropic 등)는
  쓰지 않는다. 개인 데이터가 기기 밖으로 나가지 않는 것이 원칙이다. 예외는 **모델 가중치를 처음 내려받을 때**
  하나뿐이다 (bge-m3와 같은 방식).
- 환경: Apple M5, 메모리 24GB, macOS, Python 3.12 + uv. bge-m3는 optional extra(`--extra embed`)와
  `JUPJUP_BGE_CACHE_DIR` 캐시를 쓴다.
- 근거 문서: `prd_and_design.md`(3.5절, 4.3절, 5.8.1절, 5.10절, 7.3절), `design_reranker_query_assist.md`
  (4.8~4.11절, 5.6절, 5.8절, 10.3절, 16절), `phase4_review_ingest-hardening_loop1.md`(D1, L1~L5),
  `phase4_review_ingest-t24_loop2.md`(N1, L-1~L-5)
- 기준 코드: PM `6554b6e`. `src/jupjup/ingest/`, `providers/llm.py`, `providers/recording.py`,
  `eval/ingest_*.py`, `eval/judge.py`

---

## 1. 결론

| 항목 | 결정 (추천) | 근거 요약 |
|---|---|---|
| 런타임 | **llama.cpp (`llama-cpp-python`, Metal)**, GGUF Q4_K_M | JSON Schema를 문법(GBNF)으로 바꿔 디코딩을 제약할 수 있다. 프로세스 안에서 로컬 파일로만 로드한다. 질의 보조 설계(5.6절)와 런타임이 같다. MLX-LM은 T25b에서 지연 비교용으로만 잰다 |
| 설치 | optional extra `analyze-local = ["llama-cpp-python==<T25b에서 고정>"]` | 기본 설치는 llama_cpp를 import하지 않는다 |
| 기본 분석 모델 후보 | **Qwen3-4B-Instruct-2507 (Apache-2.0)** | 상업 이용이 가능한 라이선스 중 구조화 출력과 다국어에 가장 강할 것으로 본다. non-thinking 전용이라 `<think>` 출력이 없다 |
| 한국어 특화 경량 후보 | **Kanana-1.5-2.1B-Instruct (Apache-2.0)** | 한국어 특화, 가장 빠르다. 품질이 기준을 넘으면 기본값이 된다 (4.4절 선택 규칙) |
| 사용자 지정 후보 | EXAONE 3.5 2.4B, Qwen2.5 3B | **둘 다 비상업 라이선스**다 (EXAONE AI Model License 1.1 - NC, qwen-research). 참고 측정만 하고, 13절 Q-LA1이 "비상업 허용"으로 정해질 때만 기본 후보가 될 수 있다 |
| 한 단계 큰 후보 | Qwen2.5-7B-Instruct Q4 (Apache-2.0), Kanana-1.5-8B-Instruct Q4 (Apache-2.0) | 4B급이 3.5.4절 기준에 못 미칠 때 올라갈 자리. 충실도 판정기 후보도 겸한다 |
| 충실도 판정기 | **로컬 Kanana-1.5-8B-Instruct Q4** (분석기와 다른 계열, 더 큰 모델) | PRD 3.5.3절 "분석기와 같거나 높은 등급, 다른 프롬프트"를 로컬로 지킨다. κ ≥ 0.7 보정 전에는 합격 판단에 쓰지 않는다 |
| 녹화 | 기존 `RecordingLLM`/`RecordedLLM` v2를 그대로 쓴다. `model_id`에 모델 파일 해시와 디코딩 설정 지문을 넣는다. 파일은 `data/recordings/llm/` 아래로 분리 | 녹화 형식은 바꾸지 않고, 키가 모델 파일과 디코딩 설정 변경을 놓치지 않게 한다 |
| 평가 | 인제스트 골든셋 **v2(자연문, 사람 검수)**를 먼저 만든다. dev에서만 조정하고, 설정을 동결한 뒤 test는 프로필마다 1회만 돈다 | **현재 골든셋 80건은 템플릿 문장이라** 실제 모델 품질을 잴 수 없다 (2.2절) |

핵심 원칙 다섯 가지를 문서 전체에 적용한다.

1. **원문은 기기 밖으로 나가지 않는다.** 런타임은 로컬 파일 경로로만 모델을 연다. 가중치 다운로드는
   `jupjup models pull` 명령 하나에서만 하고, sha256을 검증한다. 서비스 경로와 워커 경로는 네트워크를 쓰지 않는다.
2. **출력은 믿지 않고 검증한다.** 문법 제약 디코딩으로 JSON 형태는 보장하지만, 의미 규칙은 기존
   `validate_and_repair`가 그대로 검사한다. 재요청 루프와 partial/failed 규칙도 바꾸지 않는다.
3. **판단은 recorded 결과로만 한다.** live 출력은 Metal 연산 순서 때문에 실행마다 다를 수 있다. 첫 녹화가 정본이다.
4. **mock 결과는 바뀌지 않는다.** 기본 설치, mock 모드, 검색 경로는 이번 작업으로 한 바이트도 바뀌지 않는다
   (선행 정리 N1처럼 의도한 변경은 예외로 하고 보고서에 적는다).
5. **모델이 없으면 가짜 분석을 저장하지 않는다.** live에서 분석기가 없을 때 mock 출력으로 대체하지 않는다.

---

## 2. 배경과 현재 상태

### 2.1 이미 있는 것 (재사용)

| 구성 | 위치 | 상태 |
|---|---|---|
| `LLMClient` Protocol (`complete_json(system, user, schema, timeout_s, max_tokens, effort) -> LLMRawResponse`, `count_tokens`) | `providers/llm.py` | 있음. 파싱·검증은 호출자 몫 |
| `RecordingLLM` / `RecordedLLM` v2 (`request_hash(system, user, schema 지문, max_tokens, effort)`, `count_tokens` 행, 원문 미저장, 미스는 `LLMCacheMiss`) | `providers/recording.py` | 있음. 녹화 파일은 아직 없음 |
| `ContentAnalyzer` Protocol, `AnalysisRunMeta`, `MockAnalyzer`, `prompt_path` | `ingest/analyzer.py` | 있음. `LLMContentAnalyzer`는 없음 |
| `AnalysisOutput`, `analysis_output_json_schema()` | `ingest/schemas.py` | 있음. `ChunkNotes`는 **없음** |
| `AnalysisValidator`, `validate_and_repair(call, validator, source_text, max_repairs=2)`, `RepairContext(reason, max_tokens_multiplier)` | `ingest/validation.py` | 있음. `stop_reason == "max_tokens"`면 2배로 1회 재시도, `"refusal"`이면 `LLMRefusalError` |
| 프롬프트 `analyze_v1.md`, `chunk_notes_v1.md`, `repair_v1.md` | `ingest/prompts/` | 있음. 아직 아무 코드도 렌더링하지 않는다 |
| `chunk_for_analysis` (single/map_reduce, `ChunkSettings`) | `ingest/chunking.py` | 있음. `IngestStageRunners(chunk_settings=...)`로 주입 가능 |
| 재시도 분류 `is_retryable_error` (`details["retryable"]`로 덮어쓰기 가능) | `ingest/worker.py:105` | 있음 |
| 인제스트 하네스 (mock만), `DeterministicFaithfulnessChecker`, `FaithfulnessJudge` Protocol | `eval/ingest_harness.py`, `eval/judge.py` | 있음. recorded/live, LLM 판정기, `compare_profiles`는 `NotImplementedError` |
| 조립 | `container.build_ingest_service` | 모든 모드에서 `ExtractiveMockAnalyzer`를 쓴다 |

### 2.2 막히는 것 (이번 설계가 해결)

1. **골든셋이 템플릿 문장이다.** 80건 원문이 `"<엔티티>의 <주제> 핵심 정보 N 소개. <X> 관련 <Y> 자료 N 저장. 대표
   주제는 …이며 작성자가 직접 만든 평가용 원문입니다."` 꼴이다. gold `key_facts`도 이 문장 조각을 그대로 옮겼다.
   전부 `annotator: "ai"`, `ai_draft_unreviewed`다. 실제 모델이 이 원문을 요약하면 F1과 핵심 사실 재현율은
   모델 품질이 아니라 템플릿을 얼마나 그대로 베끼는지를 재게 된다. 이미지 사례 일부는 원문에 없는 장소(`서울`)가
   gold에 있다. → **T25c 골든셋 v2**를 선행 조건으로 둔다 (8.1절).
2. **핵심 사실 재현율이 부분 문자열 일치다** (`ingest_harness.py` `_item_metrics`의
   `normalize_text(fact) in normalized_summary`). 실제 모델은 바꿔 말하므로 거의 0이 나온다. → 결정적 매처와
   로컬 판정기를 둔다 (8.4절).
3. **문장 분리기가 소수점에서 자른다** (N1). 비충실 비율의 분모·분자가 틀린다. → T25a.
4. **녹화 키의 스키마 지문이 pydantic 출력 전체에 묶여 있다** (L4). 녹화본을 커밋한 뒤 description 문구만 바꿔도
   전부 미스가 난다. 녹화를 시작하기 **전에** 고쳐야 한다. → T25a.
5. **검색 연결 지표**를 recorded bge-m3로 재려면, 분석기가 만든 새 요약·태그 텍스트의 임베딩이 녹화본에 없다
   (`RecordedEmbedder`는 `text_hash` 키). → 연결 지표용 임베딩 녹화를 따로 둔다 (7.4절).

---

## 3. 런타임 선택

### 3.1 비교

| 기준 | llama.cpp (`llama-cpp-python`) | MLX-LM (`mlx-lm`) | transformers + MPS |
|---|---|---|---|
| Apple Silicon 가속 | Metal. 사전 빌드 wheel(macOS 11+, Python 3.10~3.12) 또는 `CMAKE_ARGS="-DGGML_METAL=on"` 빌드 | Metal 전용. 가장 빠를 가능성이 높다 | MPS. 양자화 지원이 약하다 (bitsandbytes 미지원) |
| 양자화와 메모리 | GGUF Q4_K_M 등. 4B ≈ 2.5GB, 7~8B ≈ 4.7~5GB | MLX 4bit. 비슷한 크기 | 사실상 fp16/bf16. 4B ≈ 8GB, 7B ≈ 15GB. bge-m3·리랭커와 함께 24GB에서 빠듯하다 |
| 구조화 출력 | **JSON Schema → GBNF 문법 제약을 기본 제공** (`response_format={"type":"json_object","schema":…}`, `LlamaGrammar.from_json_schema`) | 기본 제공 없음. `logits_processors` 훅에 outlines 같은 별도 라이브러리를 붙여야 한다 | outlines·lm-format-enforcer 같은 별도 라이브러리 필요 |
| 오프라인 로드 | 파일 경로 하나로 연다 (`Llama(model_path=…)`). 허브 접근이 없다 | 로컬 디렉터리 경로로 가능. 기본 사용법은 허브 id | 로컬 경로 + `HF_HUB_OFFLINE=1` |
| 결정성 | greedy(temperature 0, top_k 1) + 고정 seed. 같은 빌드·같은 `n_batch`·같은 스레드 수면 대부분 같지만 Metal에서 bit 동일은 보장하지 않는다 | greedy 가능. 같은 한계 | MPS 비결정 연산이 더 많다 |
| 이식성 | macOS·Linux·CPU 공통 | Apple 전용 | 공통이지만 느리다 |
| 모델 지원 | Qwen2.5/Qwen3, EXAONE, Llama 계열(Kanana) 지원 | 대부분 지원 | 전부 지원 |
| 라이선스 | MIT | MIT | Apache-2.0 |
| 위험 | 파이썬 바인딩 릴리스가 llama.cpp 본체보다 늦을 때가 있다. 열린 이슈가 많다 | 구조화 출력을 직접 붙여야 해서 검증 범위가 늘어난다 | 속도·메모리 |

### 3.2 추천: llama.cpp (`llama-cpp-python`)

- 판단 이유: **구조화 출력이 이 작업의 핵심 위험**이다 (3.5.4절 첫 시도 준수율 ≥ 0.97). 소형 모델은 자유 생성으로는
  중첩 스키마를 자주 깨뜨린다. llama.cpp는 스키마 제약을 별도 라이브러리 없이 제공하고, 질의 보조 설계(5.6절)와
  런타임을 공유해 extra와 어댑터를 하나로 유지할 수 있다.
- MLX-LM은 T25b 스파이크에서 같은 모델(4bit)의 **자유 생성 지연만** 비교해 기록한다. llama.cpp보다 p50이
  40% 넘게 빠르고 스키마 제약 방법이 확인되면 별도 설계로 다시 다룬다 (이번 범위 밖).
- transformers + MPS는 메모리와 속도 때문에 제외한다.

### 3.3 설치 (optional extra)

```toml
[project.optional-dependencies]
analyze-local = ["llama-cpp-python==0.3.<n>"]   # 정확한 버전은 T25b에서 Metal wheel 설치 확인 후 고정
assist-local  = ["jupjup[analyze-local]"]       # 질의 보조 설계 4.10절의 assist-local과 같은 패키지
local-models  = ["jupjup[embed,rerank,analyze-local]"]
```

- 설치: `uv sync --extra analyze-local`. Metal wheel 인덱스가 필요하면 `pyproject.toml`의 `[tool.uv.sources]`나
  `[[tool.uv.index]]`에 `https://abetlen.github.io/llama-cpp-python/whl/metal`을 **이 패키지에만** 지정한다.
  wheel이 없으면 소스 빌드(`CMAKE_ARGS="-DGGML_METAL=on"`)로 대체하는 방법을 `data/models/README.md`에 적는다.
- arm64 Python인지 확인한다 (x86 Python이면 10배 느리다). `jupjup models doctor`가 `platform.machine()`,
  llama_cpp 버전, Metal 사용 여부(`llama_supports_gpu_offload()`)를 출력한다.
- mypy: `[[tool.mypy.overrides]] module = ["llama_cpp.*"] ignore_missing_imports = true`.
- `providers/llm_local.py`는 llama_cpp를 **함수 안에서** 지연 import한다. 기본 설치의 mock·recorded 경로와
  테스트는 llama_cpp 없이 돈다.

### 3.4 모델 파일, 캐시 경로, 오프라인 실행

- 캐시: 설정 `analyzer_cache_dir`(환경 변수 `JUPJUP_ANALYZER_CACHE_DIR`), 기본 `var/models/`. bge-m3·리랭커와
  같은 디렉터리를 쓰고, 그 아래 `gguf/<model_id>/<filename>`에 둔다. `var/`는 git에 넣지 않는다.
- 모델 명세는 `config/analyzer_profiles.yaml`의 `models:`에 고정한다: `repo`, `revision`(HF commit hash),
  `filename`, `sha256`, `n_ctx`, `license`, `license_commercial_ok`.
- **다운로드는 한 명령에서만**: `jupjup models pull <model_id> [--cache-dir D]`. `huggingface_hub`가 있으면
  `hf_hub_download(repo, filename, revision)`를 쓰고(`embed` extra에 이미 들어 있다), 없으면 안내 메시지를 내고
  끝낸다. 내려받은 뒤 sha256을 검증하고, 다르면 파일을 지우고 실패한다.
- **실행 시에는 허브를 부르지 않는다.** `LlamaCppLLM`은 `cache_dir/gguf/<model_id>/<filename>` 경로만 받는다.
  파일이 없으면 `AnalyzerUnavailableError`를 낸다 (6.8절). 첫 로드 때 sha256을 한 번 검증하고(약 1~3초) 결과를
  프로세스 안에서 기억한다.
- 공식 GGUF가 있으면 그것을, 없으면 공식 safetensors(고정 revision)를 llama.cpp `convert_hf_to_gguf.py` +
  `llama-quantize Q4_K_M`으로 직접 변환한다. 어느 쪽이든 최종 GGUF의 sha256을 명세에 고정한다. 출처는 T25b에서
  모델마다 정한다. 커뮤니티 변환본을 쓰면 리포트에 출처를 적는다.
- 텔레메트리: llama.cpp는 네트워크를 쓰지 않는다. 테스트(T25d)에서 소켓을 막은 채 가짜 llama 모듈로 로드·생성
  경로를 돌려 네트워크 호출이 없음을 확인한다.

### 3.5 결정성

| 설정 | 값 | 비고 |
|---|---|---|
| `temperature` | 0.0 | greedy |
| `top_k` / `top_p` / `min_p` | 1 / 1.0 / 0.0 | greedy를 명시적으로 고정 |
| `repeat_penalty` | 1.0 | 반복 억제는 JSON 문법을 흔든다. dev에서 반복이 문제면 프롬프트 버전으로 다룬다 |
| `seed` | 20261102 | greedy에서는 영향이 없지만 고정한다 |
| `n_batch` / `n_ubatch` | 512 / 512 | prefill 분할이 바뀌면 부동소수 누적 순서가 바뀐다. 고정 |
| `n_threads` | 4 | CPU 경로 결정성 |
| `n_gpu_layers` | -1 (전부 Metal) | 설정으로 0(CPU)도 가능 |
| `n_ctx` | 16,384 (모델 명세 값) | 6.6절 입력 상한과 맞춘다 |
| 동시 실행 | 모델 인스턴스당 1건 (`threading.Lock`) | llama 객체는 스레드 안전하지 않다 |

- 이 값들을 `DecodingParams`로 묶고 지문(`fingerprint()`)을 녹화 키에 넣는다 (7.2절).
- live 결정성 목표는 "같은 머신·같은 빌드에서 두 번 돌리면 대부분 같다"까지다. T25b에서 dev 10건을 두 번 돌려
  **출력이 다른 건수**를 리포트에 적는다. 평가와 회귀 판단은 recorded로만 한다 (원칙 3).

---

## 4. 모델 후보

### 4.1 비교표

메모리는 GGUF Q4_K_M 파일 크기와 KV 캐시(16K 컨텍스트, fp16) 추정치다. 속도는 **추정**이다. M5 기본형
메모리 대역폭(약 150GB/s)에서 디코딩은 대략 `0.6~0.7 × 대역폭 ÷ 모델 크기`로, prefill은 수백~천여 토큰/초로
가정했다. T25b에서 실측해 이 표를 갱신한다.

| 후보 | 크기 | 라이선스 (상업 이용) | 컨텍스트 | 한국어 품질 (예상) | 모델 메모리 / KV 16K | 디코딩 추정 | 건당 지연 추정 (입력 4K, 출력 700토큰) |
|---|---|---|---|---|---|---|---|
| EXAONE 3.5 2.4B Instruct | 2.4B | EXAONE AI Model License 1.1 **- NC** (**상업 불가**) | 32K | 높음. 한국어 중심 학습 | ≈ 1.6GB / ≈ 0.6~1GB | ≈ 55~65 tok/s | ≈ 15초 |
| Qwen2.5 3B Instruct | 3B | **qwen-research** (**상업 불가**, 연구 목적) | 32K (생성 8K) | 중간. 한국어 출력에 한자가 섞이는 사례가 알려져 있다 | ≈ 2.0GB / ≈ 0.6GB | ≈ 45~55 tok/s | ≈ 18초 |
| **Qwen3-4B-Instruct-2507** | 4B | **Apache-2.0 (가능)** | 256K (16K로 제한해 씀) | 중상. 다국어 확대. 한자 혼입은 검증 대상 | ≈ 2.5GB / ≈ 2.3GB | ≈ 35~45 tok/s | ≈ 22초 |
| **Kanana-1.5-2.1B-Instruct-2505** | 2.1B | **Apache-2.0 (가능)** | 32K | 높음. 한국어 특화 (자체 보고 KoMT-Bench 6.54) | ≈ 1.4GB / ≈ 0.5~1GB | ≈ 60~70 tok/s | ≈ 13초 |
| Qwen2.5-7B-Instruct | 7B | **Apache-2.0 (가능)** | 32K (YaRN 시 128K) | 중상 | ≈ 4.7GB / ≈ 0.9GB | ≈ 20~25 tok/s | ≈ 40초 |
| Kanana-1.5-8B-Instruct-2505 | 8B | **Apache-2.0 (가능)** | 32K | 높음. 한국어 특화 | ≈ 4.9GB / ≈ 2GB | ≈ 18~23 tok/s | ≈ 45초 |

- 라이선스는 2026-11-02에 각 Hugging Face 모델 카드의 라이선스 표기로 확인했다. 정식 채택 전 T25b에서 라이선스
  원문을 다시 읽고 `license`, `license_commercial_ok`를 명세에 적는다. Kanana·Qwen3의 Apache-2.0은 사용 범위
  제약이 없다. EXAONE의 NC는 연구·비상업 목적만 허용한다.
- 동시 메모리: 워커 프로세스에 분석 모델(최대 ≈ 5GB + KV 2GB), bge-m3(≈ 2.2GB), 판정기(평가 때만, ≈ 7GB)가
  올라간다. 판정기와 분석기를 **같은 프로세스에 동시에 올리지 않는다** (평가는 분석 → 녹화 → 판정 순서로 따로 돈다).
  24GB에서 여유가 있다.
- 지연 예산: PRD 4.3절 ① "건당 p95 ≤ 60초"를 single 모드에 그대로 쓴다. map_reduce 건은 별도 예산 ≤ 300초
  (Q-LA4). 4B급까지는 single 예산 안에 들어올 것으로 추정한다.
- 한국어 토큰 효율: EXAONE·Kanana 토크나이저가 Qwen보다 한국어를 적은 토큰으로 자른다. 같은 원문이라도
  prefill 시간이 달라지므로 T25b에서 `count_tokens`로 골든 dev 평균 입력 토큰을 모델별로 잰다.

### 4.2 기본 후보

- **기본 후보: Qwen3-4B-Instruct-2507 Q4_K_M.** 상업 이용이 가능하고, 구조화 출력과 긴 입력에 가장 안정적일 것으로
  본다. 대표 태그·엔티티·카테고리처럼 분류 성격이 강한 필드가 많아서, 한국어 문장력보다 지시 수행과 스키마 준수가
  더 중요하다고 판단했다.
- **도전 후보: Kanana-1.5-2.1B Q4_K_M.** 한국어 요약 품질과 속도에서 앞설 수 있다. 4.4절 규칙으로 기본 후보와 겨룬다.
- **참고 후보: EXAONE 3.5 2.4B, Qwen2.5 3B.** 사용자가 지목한 후보라 dev에서 같은 조건으로 측정해 표에 넣는다.
  비상업 라이선스라서 Q-LA1 결정 전에는 기본값으로 고르지 않는다.
- **승격 후보: Qwen2.5-7B-Instruct, Kanana-1.5-8B.** 4B급이 dev에서 3.5.4절 절대 기준을 못 넘을 때만 분석기로
  비교한다. Kanana-1.5-8B는 판정기 기본 후보다 (8.3절).

### 4.3 한자·가나 혼입 대응

Qwen 계열은 한국어 출력에 한자가 섞이는 사례가 있다. `AnalysisValidator`의 의미 규칙에 하나를 더한다.
- `summary`, `representative_tags`, `detail_tags.topics/keywords`, `save_intent.rationale`에 **원문에 없는 한자(CJK
  Unified Ideographs)·가나**가 있으면 `code="foreign_script"`, `fixable=False` 이슈 → 재요청.
- 기존 mock 출력에는 한자가 없으므로 mock 결과는 바뀌지 않는다 (T25e에서 단언).

### 4.4 후보 선택 규칙 (dev, recorded)

질의 보조 설계 10.3절과 같은 구조다.

1. 라이선스: `license_commercial_ok=false`인 후보는 Q-LA1이 "비상업 허용"이 아니면 기본값에서 제외한다 (측정은 한다).
2. 출력 품질 문턱: 스키마 첫 시도 준수율 ≥ 0.97, 최종 준수율 = 1.00, 주입 저항 = 1.00을 dev에서 못 넘으면 제외.
3. 지연 문턱: single 건 p95 ≤ 60초, map_reduce 건 p95 ≤ 300초 (live 벤치마크, 4.1절 조건).
4. 남은 후보 중 **3.5.4절 기본 분석기 열을 더 많이 충족**하는 쪽. 같으면 아래 주요 지표의 합(비충실 비율은 `1 − 값`)이
   큰 쪽: 요약 비충실 문장 비율, 핵심 사실 재현율, 엔티티 F1, 대표 태그 F1.
5. 4번 합계 차이가 0.02 이내면 single p95 지연이 낮은 쪽, 그다음 피크 메모리가 낮은 쪽.
6. 모두 3.5.4절 절대 기준을 못 넘으면 승격 후보(7~8B)로 같은 절차를 반복한다. 그래도 못 넘으면 **기준을 낮추지 않고**
   PM을 거쳐 사용자에게 보고한다 (Q-LA6).

---

## 5. 구조화 출력

### 5.1 세 겹 방어

```
[1] 문법 제약 디코딩   — JSON 형태, 필드 이름, enum, 배열 길이 상한, 문자열 길이 상한을 생성 단계에서 강제
[2] validate_and_repair — 파싱 → Pydantic/JSON Schema → 의미 규칙 → evidence 근거 (기존 그대로)
[3] 재요청 루프         — 고칠 수 없는 이슈만 최대 2회, 소진 시 partial/failed (기존 그대로)
```

### 5.2 디코딩 스키마 `build_decoding_schema`

`AnalysisOutput.model_json_schema()`를 그대로 문법으로 바꾸면 두 가지가 문제다. (a) llama.cpp의 스키마 → 문법
변환기가 지원하지 않는 키워드가 섞여 있다 (`maxProperties`, `$schema`, `$id`, 숫자 `minimum/maximum` 일부).
(b) 상한이 넉넉해서(evidence 20개 × 200자) 출력이 길어지고 느려진다. 그래서 **디코딩 전용 스키마**를 따로 만든다.
검증 스키마(정본)는 바꾸지 않는다.

```python
# providers/json_grammar.py (신규, 순수 함수, llama_cpp import 없음)
DECODING_SCHEMA_VERSION = "ds-1"

class DecodingSchemaPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = DECODING_SCHEMA_VERSION
    property_order: dict[str, list[str]] = {}     # JSON 포인터 → 필드 순서
    drop_paths: list[str] = []                    # 디코딩에서 아예 빼는 필드 (예: "/properties/detail_tags/properties/attributes")
    max_items: dict[str, int] = {}                # 경로 → 더 엄격한 maxItems
    max_length: dict[str, int] = {}               # 경로 → 더 엄격한 maxLength

def build_decoding_schema(schema: type[BaseModel], policy: DecodingSchemaPolicy) -> dict[str, Any]
    # 1) model_json_schema()를 deep copy  2) $ref를 로컬 $defs 기준으로 인라인
    # 3) 지원하지 않는 키워드 제거: $schema, $id, title, description, maxProperties, format
    # 4) drop_paths 제거(required에서도 빠지는지 확인: required 필드는 drop 불가 → ValueError)
    # 5) max_items/max_length 적용(정본보다 느슨하게 바꾸면 ValueError)
    # 6) property_order대로 properties 재배열 (llama.cpp 문법은 스키마 순서대로 필드를 낸다)
    # 결과는 sort 없이 결정적. 같은 입력이면 같은 dict
def decoding_schema_fingerprint(decoding_schema: dict[str, Any]) -> str   # 정규 JSON sha256
```

`ANALYSIS_DECODING_POLICY_DS1` (기본값, dev에서 버전을 올리며 조정한다):

| 항목 | 정본 | ds-1 | 이유 |
|---|---|---|---|
| 필드 순서 | 임의 | `language → title_suggestion → evidence → summary → representative_tags → detail_tags → save_intent` | **근거 구절을 먼저 뽑고 요약을 쓰게** 해 충실도를 높인다. 검증은 이름으로 하므로 순서와 무관 |
| `evidence` maxItems | 20 | 6 | 출력 길이와 지연 |
| `evidence[].source_span` maxLength | 200 | 120 | 같은 이유 |
| `detail_tags.entities` maxItems | 20 | 10 | |
| `detail_tags.keywords` / `topics` maxItems | 20 / 10 | 10 / 5 | |
| `detail_tags.attributes`, `detail_tags.save_intent`, `detail_tags.purpose` | 있음 | 디코딩에서 제외 | `save_intent`·`purpose`는 I6 `materialized_detail_tags()`가 채운다. `attributes`는 소형 모델이 잡음을 많이 낸다 |
| `detail_tags.schema_version` | `const: 1` | 그대로 (문법이 강제) | |
| `summary` minLength/maxLength | 20/400 | 그대로 | 문법이 길이를 강제한다 |

- **필수 필드는 빼지 않는다.** 디코딩 스키마로 만든 출력은 항상 정본 스키마를 통과할 수 있는 모양이어야 한다
  (T25d 속성 테스트: 디코딩 스키마의 모든 필드·제약이 정본보다 같거나 엄격한지 검사).
- 디코딩 정책과 버전은 프로필의 일부다. 정책을 바꾸면 `decoding_schema_version`을 올리고 녹화 키가 바뀐다 (7.2절).

### 5.3 문법 제약의 한계와 대응

| 한계 | 대응 |
|---|---|
| 문법은 `max_tokens`에서 멈추면 JSON이 잘린다 | `finish_reason == "length"` → `stop_reason="max_tokens"`. 기존 경로대로 `max_tokens` 2배로 1회 재시도 |
| 문법이 의미(원문 근거, 요약 문장 수, 한국어 여부)는 못 지킨다 | `validate_and_repair`의 의미 규칙과 재요청 |
| 문법 안에서 같은 토큰을 반복하는 퇴화(예: 같은 태그 반복) | 배열 길이 상한으로 끝이 있다. 중복 태그는 기존 auto_fix가 지운다. dev에서 빈도를 리포트 |
| 문법 컴파일 비용 | 스키마 지문별로 `LlamaGrammar`를 프로세스 안에 캐시한다 |
| 스키마 → 문법 변환 실패 (지원하지 않는 구조) | `LlamaCppLLM` 생성 시점(warm-up)에 분석·청크·판정 스키마 문법을 미리 컴파일해 바로 실패시킨다 |
| `constrained="none"` 비교 | T25b에서 같은 dev 10건을 문법 없이도 돌려 첫 시도 준수율 차이를 기록한다 (근거 확보용) |

### 5.4 `validate_and_repair`와의 연결

- 로컬 분석기는 기존 `validate_and_repair(call, validator, source_text, max_repairs)`를 그대로 부른다.
  `call(context)` 콜백 안에서만 프롬프트를 고른다.
  - `context is None` → 분석 프롬프트 (`prompt_version`)
  - `context.reason == "max_tokens"` → **잘린 요청과 같은 프롬프트**(첫 응답이 잘렸으면 분석 프롬프트, 재요청 응답이 잘렸으면 그 재요청), `max_tokens × context.max_tokens_multiplier` (T25e 검수 L1, T25f에서 반영)
  - `context.reason == "validation"` → 재요청 프롬프트 (`repair_prompt_version`). `previous_output`과 `issues`를
    렌더링한다. 이전 출력은 `<previous_output>` 데이터 블록에 넣는다 (주입 방어)
- 재요청 프롬프트의 이슈 목록은 `path`, `code`, `message`만 넣는다. `message`에는 원문이 들어가지 않는다는 기존
  규칙을 지킨다.
- 로컬 모델은 거절 `stop_reason`이 없다. 거절 문장을 내면 문법 때문에 JSON 안의 이상한 값으로 나오고, 의미 규칙
  실패 → 재요청 → 소진 시 partial/failed가 된다. `LLMRefusalError`·`needs_review` 경로는 로컬 엔진에서는 쓰이지 않는다.
- `first_pass_ok`, `attempts`, `repairs`, `partial`은 기존대로 `AnalysisRunMeta`에 담는다.

---

## 6. LocalLLMContentAnalyzer 인터페이스

### 6.1 구성 관계

```
ContentAnalyzer (Protocol, 기존)
 └─ LLMContentAnalyzer (신규, 엔진 중립)           ← 프롬프트 렌더링, single/map_reduce, validate_and_repair
       ├─ llm: LLMClient                            ← 분석·리듀스·재요청
       ├─ chunk_llm: LLMClient | None               ← 맵 단계 (None이면 llm)
       ├─ prompts: PromptStore                      ← 버전 파일
       ├─ validator: AnalysisValidator              ← 기존
       └─ profile: AnalyzerProfile

LLMClient (Protocol, 기존)
 ├─ MockLLM (기존)                ← 단위 테스트
 ├─ LlamaCppLLM (신규, extra)     ← live
 ├─ RecordingLLM(LlamaCppLLM)     ← 평가 live 녹화 (기존 v2)
 └─ RecordedLLM (기존 v2)         ← recorded 재생
```

- 사용자 요청서의 이름 `LocalLLMContentAnalyzer`는 **`LLMContentAnalyzer`에 로컬 `LLMClient`를 꽂은 조립**을
  가리킨다. 분석기 클래스는 엔진을 모른다. 그래서 같은 분석기 코드가 MockLLM(테스트), LlamaCppLLM(live),
  RecordedLLM(recorded)으로 돈다. 조립 함수 이름은 `build_local_content_analyzer`다 (6.9절).
- PRD 5.10.8절 시그니처 `LLMContentAnalyzer(llm, chunk_llm, profile, prompts, validator)`를 그대로 따른다.

### 6.2 설정과 프로필

```python
# config.py (확장)
class AnalyzerSettings(BaseModel):                # Settings.analyzer
    model_config = ConfigDict(extra="forbid")
    engine: Literal["mock", "local"] = "mock"     # mock = 기존 ExtractiveMockAnalyzer 경로 (기본, 변경 없음)
    required: bool = False                        # live에서 모델이 없을 때 시작을 막을지 (6.8절)
    profile: str | None = None                    # None이면 analyzer_profiles.yaml의 default_profile
    profiles_path: Path = REPO_ROOT / "config" / "analyzer_profiles.yaml"
    recordings_dir: Path = REPO_ROOT / "data" / "recordings" / "llm"
    n_gpu_layers: int = -1

class Settings(BaseSettings):
    ...
    analyzer: AnalyzerSettings = Field(default_factory=AnalyzerSettings)
    analyzer_cache_dir: Path = REPO_ROOT / "var" / "models"     # JUPJUP_ANALYZER_CACHE_DIR
```

```python
# ingest/profiles.py (신규)
class LocalModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: str                                 # "qwen3-4b-instruct-2507-q4km" (영숫자, 점, 밑줄, 하이픈)
    repo: str; revision: str; filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    n_ctx: int = Field(default=16_384, ge=2_048)
    chat_template: Literal["gguf"] = "gguf"       # GGUF 내장 템플릿만 쓴다
    license: str; license_commercial_ok: bool

class DecodingParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    temperature: float = 0.0; top_k: int = 1; top_p: float = 1.0; min_p: float = 0.0
    repeat_penalty: float = 1.0; seed: int = 20261102
    n_batch: int = 512; n_ubatch: int = 512; n_threads: int = 4
    constrained: Literal["json_schema", "none"] = "json_schema"
    decoding_schema_version: str = "ds-1"
    def fingerprint(self) -> str                  # 정규 JSON sha256 앞 8자

class ProfileTimeouts(BaseModel):
    analyze_s: float = 120.0; chunk_s: float = 45.0; repair_s: float = 120.0

class ChunkOverrides(BaseModel):                  # ChunkSettings 필드와 같은 이름
    single_max_tokens: int = 8_000; chunk_target_tokens: int = 4_000
    overlap_tokens: int = 200; max_chunks: int = 12

class AnalyzerProfile(BaseModel):                 # PRD 5.10.8절 정의를 로컬용으로 바꾼다
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    engine: Literal["mock", "local"]
    model: str | None = None                      # models: 키. engine="local"이면 필수
    chunk_model: str | None = None                # None이면 model
    prompt_version: str = "analyze_local_v1"
    chunk_prompt_version: str = "chunk_notes_local_v1"
    repair_prompt_version: str = "repair_local_v1"
    reduce_prompt_version: str = "reduce_local_v1"
    max_output_tokens: int = 1_536
    chunk_max_output_tokens: int = 512
    max_repairs: int = 2
    timeouts: ProfileTimeouts = ProfileTimeouts()
    chunk: ChunkOverrides = ChunkOverrides()
    decoding: DecodingParams = DecodingParams()
    routes: list[ProfileRoute] = []               # 3.5.5절 7번 플랫폼 라우팅 (이번 범위는 스키마만)
    effort: None = None                           # 로컬 엔진은 effort가 없다. 녹화 키에는 None으로 들어간다

class JudgeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str; model: str
    faithfulness_prompt_version: str = "judge_faithfulness_v1"
    keyfact_prompt_version: str = "judge_keyfact_v1"
    max_output_tokens: int = 1_024; timeout_s: float = 120.0
    decoding: DecodingParams = DecodingParams()

class AnalyzerProfiles(BaseModel):
    version: Literal[1]
    default_profile: str
    models: dict[str, LocalModelSpec]
    profiles: dict[str, AnalyzerProfile]
    judges: dict[str, JudgeProfile] = {}
    @classmethod
    def load(cls, path: Path) -> AnalyzerProfiles    # 참조 무결성 검사: 없는 model 키, model_id 불일치 → ValueError
```

`config/analyzer_profiles.yaml` (초안. sha256·revision은 T25b가 채운다):

```yaml
version: 1
default_profile: mock            # T25h 채택과 사용자 승인 뒤에 local-<선택>으로 바꾼다
models:
  qwen3-4b-instruct-2507-q4km:
    model_id: qwen3-4b-instruct-2507-q4km
    repo: <T25b>
    revision: <hf-commit>
    filename: <file>.gguf
    sha256: <64 hex>
    n_ctx: 16384
    license: apache-2.0
    license_commercial_ok: true
  kanana-1.5-2.1b-instruct-q4km: {...,  license: apache-2.0, license_commercial_ok: true}
  exaone-3.5-2.4b-instruct-q4km: {..., license: exaone-1.1-nc, license_commercial_ok: false}
  qwen2.5-3b-instruct-q4km:      {..., license: qwen-research, license_commercial_ok: false}
  qwen2.5-7b-instruct-q4km:      {..., license: apache-2.0, license_commercial_ok: true}
  kanana-1.5-8b-instruct-q4km:   {..., license: apache-2.0, license_commercial_ok: true}
profiles:
  mock: {name: mock, engine: mock}
  local-qwen3-4b: {name: local-qwen3-4b, engine: local, model: qwen3-4b-instruct-2507-q4km}
  local-kanana-2b: {name: local-kanana-2b, engine: local, model: kanana-1.5-2.1b-instruct-q4km}
  local-exaone-2b: {name: local-exaone-2b, engine: local, model: exaone-3.5-2.4b-instruct-q4km}
  local-qwen25-3b: {name: local-qwen25-3b, engine: local, model: qwen2.5-3b-instruct-q4km}
  local-qwen25-7b: {name: local-qwen25-7b, engine: local, model: qwen2.5-7b-instruct-q4km}
  local-kanana-8b: {name: local-kanana-8b, engine: local, model: kanana-1.5-8b-instruct-q4km}
judges:
  judge-kanana-8b: {name: judge-kanana-8b, model: kanana-1.5-8b-instruct-q4km}
  judge-qwen25-7b: {name: judge-qwen25-7b, model: qwen2.5-7b-instruct-q4km}
```

- 모델 id와 경로는 설정에만 있다 (AC-34). 코드 상수는 설정 기본값뿐이다.
- 프로필의 `chunk`는 I4 `ChunkSettings`로 들어간다. 로컬 프로필은 기본값보다 작다(single 8,000, 청크 4,000,
  최대 12개). 소형 모델은 긴 입력에서 품질이 떨어지고 prefill 시간이 늘어나기 때문이다. 값은 dev에서 조정한다.
  청킹은 지금처럼 **문자 기반 추정**(`len × 1.0`)을 쓴다. 로컬 토크나이저의 `count_tokens`로 청킹을 정하면
  recorded 모드가 `count_tokens` 녹화에 묶이고 프로필마다 청킹이 달라져 후보 비교가 어려워진다.

### 6.3 로컬 LLM 제공자

```python
# providers/llm_local.py (신규, extra [analyze-local]. llama_cpp는 함수 안에서 import)
class LlamaCppLLM:                                # LLMClient 구현
    model_id: str                                 # recording_model_id(spec, decoding) (7.2절)

    def __init__(self, spec: LocalModelSpec, decoding: DecodingParams, cache_dir: Path, *,
                 n_gpu_layers: int = -1, policies: Mapping[str, DecodingSchemaPolicy] | None = None,
                 loader: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic): ...
        # loader: 테스트용 가짜 Llama 생성자 주입. None이면 llama_cpp.Llama
        # 생성자는 파일 존재만 확인하고 모델을 열지 않는다 (지연 로드)
    def warm_up(self, schemas: Sequence[type[BaseModel]] = ()) -> None
        # 모델 로드 + sha256 검증 + 스키마 문법 미리 컴파일 + 짧은 더미 생성 1회
    def complete_json(self, system: str, user: str, schema: type[BaseModel], timeout_s: float,
                      max_tokens: int = 4000, effort: str | None = None) -> LLMRawResponse
        # effort는 무시한다 (None이 아니면 경고 없이 무시. 녹화 키에는 호출자가 준 값이 그대로 들어간다)
        # chat 템플릿: GGUF 내장 템플릿으로 [system, user] 메시지를 렌더링 (create_chat_completion)
        # 문법: build_decoding_schema(schema, policies.get(schema.__name__, 기본)) → LlamaGrammar (캐시)
        # 반환 stop_reason 매핑: finish_reason "stop" → "end_turn", "length" → "max_tokens"
        # 토큰: usage.prompt_tokens / completion_tokens. latency_ms: 벽시계 (참고값)
    def count_tokens(self, system: str, user: str) -> int
        # 같은 chat 템플릿으로 렌더링한 전체 프롬프트의 정확한 토큰 수
    def close(self) -> None
```

- **입력 상한 검사**: `count_tokens(system, user) + max_tokens > spec.n_ctx`이면 생성하지 않고
  `LLMContextOverflowError`(영구)를 낸다. I4 청킹 설정이 맞으면 생기지 않아야 하는 방어선이다.
- **타임아웃**: llama-cpp-python은 생성 중에 끊는 공식 타임아웃이 없다. 토큰마다 불리는 `stopping_criteria`로
  `clock() > deadline`이면 멈추고 `LLMTimeoutError`를 낸다. prefill은 중간에 못 끊으므로 입력 상한(6.6절)으로 묶는다.
- **동시성**: 인스턴스마다 `threading.Lock` 하나. 워커 스레드가 2개여도 분석 호출은 한 번에 하나다. 기다리는 시간은
  타임아웃에 넣지 않는다 (잠금을 잡은 뒤부터 잰다). 잠금 대기 시간은 `AnalysisRunMeta`에 넣지 않고 잡 이벤트 로그에만
  남긴다.
- **로드 시점**: 첫 `complete_json` 또는 `warm_up`에서 로드한다. `build_container`나 API 프로세스는 모델을 로드하지
  않는다. `jupjup worker run`은 시작 때 `warm_up()`을 불러 첫 잡의 지연과 설치 오류를 미리 드러낸다.
- 로그: 프롬프트와 출력 원문을 로그에 남기지 않는다 (AC-16). 길이와 토큰 수만 남긴다.

### 6.4 분석기

```python
# ingest/analyzer.py (확장)
class PromptStore:
    def __init__(self, root: Path | None = None): ...              # 기본 ingest/prompts/
    def load(self, name: str) -> PromptTemplate                    # prompt_path()로 경로 탈출 차단
class PromptTemplate(BaseModel):
    name: str; system: str; user: str; sha256: str                 # 파일을 "---user---" 줄로 system/user로 나눈다
    def render(self, **blocks: str) -> tuple[str, str]
        # {{name}} 자리만 바꾼다. 값 안의 "{{"는 이스케이프하지 않고 그대로 넣되, 렌더링은 한 번만 한다 (재귀 치환 금지)
        # 없는 자리나 남는 값이 있으면 ValueError

class LLMContentAnalyzer:                                          # ContentAnalyzer 구현
    def __init__(self, llm: LLMClient, chunk_llm: LLMClient | None, profile: AnalyzerProfile,
                 prompts: PromptStore, validator: AnalysisValidator, *,
                 chunk_validator: ChunkNotesValidator | None = None): ...
    profile_name: str                                              # profile.name
    def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]
        # single: _analyze_single(inp.text, inp.meta)
        # map_reduce: notes = [_extract_notes(chunk) for chunk in inp.chunks] → _reduce(inp, notes)
        # 오류: AnalysisSchemaError, LLMProviderError(LLMTimeoutError, LLMContextOverflowError 포함),
        #       LLMCacheMiss(recorded), AnalyzerUnavailableError
```

- `AnalysisRunMeta`는 그대로 쓴다. `model`에는 `llm.model_id`(지문 포함), `prompt_version`에는
  `"<prompt_version>+<repair_prompt_version>"`처럼 실제로 쓴 버전을 넣는다. map_reduce면 맵·리듀스 호출의 토큰과 지연을
  모두 더한다. `cost_usd`는 로컬이므로 0.0이다.
- 프롬프트 렌더링 결과(system, user)는 바이트 단위로 결정적이어야 한다. 메타데이터는 `json.dumps(…, sort_keys=True,
  ensure_ascii=False)`로 넣는다. 날짜·시각처럼 실행마다 바뀌는 값을 넣지 않는다 (녹화 키가 흔들린다).
- `source_text`(검증 근거)는 single이면 분석 입력 본문, map_reduce면 모든 청크 원문을 이은 것이다. MockAnalyzer와 같다.

### 6.5 프롬프트 버전 파일

| 파일 | 용도 | 데이터 블록 |
|---|---|---|
| `prompts/analyze_local_v1.md` | single 분석 | `<source_document>`, `<content_metadata>`, `<user_note>` |
| `prompts/repair_local_v1.md` | 재요청 | `<source_document>`, `<previous_output>`, `<validation_issues>` |
| `prompts/chunk_notes_local_v1.md` | 맵 | `<source_chunk>` (문장마다 `[s12]` 번호를 붙여 넣는다) |
| `prompts/reduce_local_v1.md` | 리듀스 | `<content_metadata>`, `<source_head>`(첫 청크 앞 1,500자), `<chunk_notes>` |
| `prompts/judge_faithfulness_v1.md` | 판정기 문장 판정 | `<source_document>`, `<summary_sentences>` |
| `prompts/judge_keyfact_v1.md` | 판정기 핵심 사실 포함 판정 | `<summary>`, `<key_facts>` |

- 기존 `analyze_v1.md` 등은 지우지 않는다 (API 엔진용 자리, `analysis_runs`에 남은 기록과의 호환).
- 로컬 프롬프트 작성 규칙: **한국어 지시문**으로 쓴다. 출력 언어가 한국어임을 첫 문단에서 못 박는다. 필드별 규칙을
  짧은 목록으로 둔다(요약 2~4문장, 원문에 없는 숫자·이름 금지, 대표 태그 3~7개 명사형, 카테고리 enum 설명 한 줄씩,
  저장 의도 라벨 설명 한 줄씩). 소형 모델은 긴 일반 지시보다 **짧은 예시 1개**가 낫다. 예시는 골든셋과 겹치지 않는
  직접 작성본을 쓴다 (dev 누수 금지).
- 주입 방어 문구(5.10.6절 7번)를 그대로 넣는다. 원문 블록의 닫는 태그 문자열(`</source_document>`)이 원문에 있으면
  렌더링 전에 `<\/source_document>`로 바꿔 블록 탈출을 막는다 (T25e 테스트).
- 프롬프트 파일의 sha256을 `analysis_runs.repairs`가 아니라 리포트의 `config`에 남긴다. 파일 내용이 바뀌었는데
  버전 이름이 같으면 녹화 미스로 드러난다 (system/user가 녹화 키에 들어가므로).

### 6.6 맵-리듀스 경로

```python
# ingest/schemas.py (확장)
class ChunkFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    text: str = Field(min_length=1, max_length=160)
    evidence_ids: list[str] = Field(min_length=1, max_length=4)    # "s12" 형식
class ChunkEntity(BaseModel):
    type: EntityType; name: str = Field(min_length=1, max_length=60)
class ChunkNotes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    facts: list[ChunkFact] = Field(max_length=8)
    entities: list[ChunkEntity] = Field(max_length=10)
    locations: list[str] = Field(max_length=5)
    keywords: list[str] = Field(max_length=8)
    quotes: list[str] = Field(max_length=3)                        # 각 ≤ 120자

# ingest/validation.py (확장)
class ChunkNotesValidator:
    def __init__(self, lexicon: Lexicon): ...
    def validate(self, raw_json: str, chunk: NumberedChunk) -> tuple[ChunkNotes | None, list[ValidationIssue]]
        # evidence_ids가 청크에 실제로 있는 번호인지, entities/locations/quotes가 청크 원문에 근거가 있는지
        # (AnalysisValidator와 같은 _grounded 규칙). 근거 없는 항목은 지우고(fixable) 기록한다

# ingest/chunk_notes.py (신규)
class NumberedChunk(BaseModel):
    chunk_index: int; sentences: list[tuple[str, str]]             # [("s1", "…"), …]
def number_sentences(chunk: AnalysisChunk) -> NumberedChunk        # T25a에서 고친 split_sentences 규칙을 공유
class LLMChunkNoteExtractor:                                       # ChunkNoteExtractor 구현
    def __init__(self, llm: LLMClient, profile: AnalyzerProfile, prompts: PromptStore,
                 validator: ChunkNotesValidator): ...
    def extract(self, chunk: AnalysisChunk) -> ChunkNotesResult    # notes + attempts + tokens + latency
```

- 맵 단계 재요청은 **1회**만 한다(`max_repairs=1`). 그래도 실패하면 그 청크를 빈 노트로 두고 `repairs`에
  `chunk[i]: notes_failed`를 남긴다. 청크 절반 넘게 실패하면 `AnalysisSchemaError`로 잡을 실패시킨다.
- 리듀스는 `AnalysisOutput`을 만든다. `validate_and_repair`의 `source_text`는 **전체 원문**(모든 청크)이라서 리듀스가
  노트에서 지어낸 엔티티는 근거 검사에서 걸린다.
- 리듀스 입력 크기: 메타 + 원문 앞 1,500자 + 노트(청크 12개 × 약 300토큰) ≈ 6,000토큰 이하. `n_ctx` 16,384 안에 든다.
- 논문 초록, 유튜브 설명란 우선 규칙은 기존 I4 청킹이 이미 처리한다 (변경 없음).

### 6.7 타임아웃과 실패 분류

추가 에러 (`domain/errors.py`, 5.8.1절에 더함):

```python
class LLMTimeoutError(LLMProviderError):       code = "LLM_TIMEOUT"           # details: {"retryable": True, "timeout_s": …}
class LLMContextOverflowError(LLMProviderError): code = "LLM_CONTEXT_OVERFLOW" # details: {"retryable": False, "input_tokens": …, "n_ctx": …}
class AnalyzerUnavailableError(ProviderError): code = "ANALYZER_UNAVAILABLE"   # details: {"retryable": False, "reason": "extra_missing|model_missing|sha_mismatch|load_failed"}
```

| 상황 | 에러 | 재시도 (`is_retryable_error`) | 잡 결과 |
|---|---|---|---|
| 생성이 프로필 타임아웃 초과 | `LLMTimeoutError` | 가능. 단 analyze 단계 timeout 재시도는 **1회로 제한** (`details["timeout_retries"]`로 셈) | 소진 시 `failed(analyze)`. 스냅샷 축약 인덱스로 검색은 계속된다 |
| 입력이 `n_ctx` 초과 | `LLMContextOverflowError` | 불가 | `failed(analyze)` |
| extra 없음, 모델 파일 없음, sha256 불일치, 로드 실패 | `AnalyzerUnavailableError` | 불가 | `failed(analyze)`. 설치 뒤 `jupjup ingest reanalyze`로 다시 돈다 |
| Metal 메모리 부족 등 llama 런타임 예외 | `LLMProviderError` | 가능 (기존 analyze 3회) | 소진 시 `failed` |
| JSON·스키마·의미 규칙 실패, 재요청 소진, 요약 실패 | `AnalysisSchemaError` | 불가 (기존) | `failed` |
| 재요청 소진, 요약은 통과 | (에러 아님) | — | `succeeded`, `partial=true` (기존) |
| recorded 녹화 미스 | `LLMCacheMiss` | 불가 (`LLMProviderError`가 아님, 기존) | 평가 오류. 하네스는 그 건을 `failed`로 기록하고 리포트에 미스 목록을 낸다 |

- 결정적 모델이 같은 입력에서 또 타임아웃될 가능성이 높아서 timeout 재시도를 1회로 묶는다. 두 번째 시도는
  기존 백오프를 따른다.
- 프로필 타임아웃 기본값: single 120초, 청크 45초, 재요청 120초. single p95 예산(60초)의 2배다.

### 6.8 모델 미설치 시 동작 (required / optional)

| 모드 | `engine` | 상황 | `required=false` (기본) | `required=true` |
|---|---|---|---|---|
| mock | 무엇이든 | — | 지금처럼 `ExtractiveMockAnalyzer`. 로컬 설정은 읽기만 하고 무시한다 | 같음 |
| recorded | `local` | 녹화 파일 없음 | 시작 시 `LLMProviderError`(기존 `RecordedLLM` 동작) | 같음 |
| live | `mock` | — | 지금처럼 `ExtractiveMockAnalyzer` (변경 없음) | 같음 |
| live | `local` | extra 없음 / 모델 파일 없음 / sha 불일치 | **워커는 뜬다.** `RuntimeWarning` 1회 + `healthz`에 `analyzer: "unavailable"`. analyze 단계에 온 잡은 `AnalyzerUnavailableError`로 `failed`. 축약 인덱스로 검색은 된다 | 워커 시작 시 `AnalyzerUnavailableError`로 즉시 종료 (종료 코드 2, 한 줄 안내: `uv sync --extra analyze-local && uv run jupjup models pull <id>`) |

- **live에서 로컬 분석기가 없을 때 mock 분석기로 대체하지 않는다** (원칙 5). 가짜 요약·태그가 사용자 DB에 저장되면
  사용자 수정값 규칙과 재분석 규칙이 꼬인다. 리랭커(없으면 v2 검색으로 계속)와 다른 점이다.
- `jupjup models doctor`: extra, 모델 파일, sha256, Metal 여부, 프로필 참조 무결성을 한 번에 점검하고 표로 낸다.

### 6.9 조립

```python
# container.py (확장)
def build_content_analyzer(settings: Settings, lexicon: Lexicon, tokenizer: KiwiTokenizer, *,
                           recording: bool = False) -> tuple[ContentAnalyzer, ChunkSettings]
    # mock 모드 또는 engine="mock" → (ExtractiveMockAnalyzer, ChunkSettings())   ← 기존과 바이트 동일
    # recorded + local → RecordedLLM(analyze 녹화 경로, recording_model_id) 로 LLMContentAnalyzer
    # live + local     → LlamaCppLLM (recording=True면 RecordingLLM으로 감쌈. 평가·녹화 명령에서만 True)
    # 반환 ChunkSettings는 프로필 chunk 값
def build_local_content_analyzer(profile: AnalyzerProfile, llm: LLMClient, chunk_llm: LLMClient | None,
                                 lexicon: Lexicon) -> LLMContentAnalyzer

def build_ingest_service(container, *, clock=None, worker_id=None, concurrency=None,
                         analyzer: ContentAnalyzer | None = None,       # 하네스 주입용 (신규, 키워드 전용)
                         chunk_settings: ChunkSettings | None = None) -> IngestService
```

- **live 서비스 경로는 녹화하지 않는다.** 실제 사용자 원문에서 나온 출력이 녹화 파일에 들어가지 않게 한다.
  `recording=True`는 `jupjup eval ingest --mode live`와 `jupjup analyze record`에서만 켠다.
- 검색 경로(`build_container`의 검색 쪽)는 바뀌지 않는다. `search/`, `query/` diff 0이 인수 기준이다.

---

## 7. 녹화와 재생

### 7.1 무엇을 녹화하나

| 대상 | 파일 | 키 |
|---|---|---|
| 분석기 호출 (single, 재요청, max_tokens 재시도, 맵, 리듀스) | `data/recordings/llm/analyze.<recording_model_id>.jsonl` | 기존 v2 `request_hash` + `model_id` |
| 판정기 호출 (문장 판정, 핵심 사실 판정) | `data/recordings/llm/judge.<recording_model_id>.jsonl` | 같음 |
| 분석기 `count_tokens` | 같은 analyze 파일의 `kind="count_tokens"` 행 | 기존 v2 |
| 검색 연결용 임베딩 (분석기 출력으로 만든 문서 텍스트) | `data/recordings/linkage/embeddings.bge-m3.<analyzer_profile>.jsonl` | 기존 임베딩 녹화 형식 (`model_id, kind, text_hash`) |

- 기존 `data/recordings/embeddings.bge-m3.jsonl`, `rerank.bge-reranker-v2-m3.jsonl`과 **디렉터리를 나눈다.**
  분석기를 바꿀 때마다 검색 기준선용 녹화가 흔들리지 않게 하기 위해서다.
- 분석·판정 녹화의 `response.text`에는 모델 원 출력이 들어간다. 원문 프롬프트는 넣지 않는다 (기존 v2 규칙). 골든셋은
  직접 작성한 합성 원문이므로 출력에 원문 일부(evidence 구절)가 들어가도 된다. 실제 사용자 원문은 녹화 대상이 아니다.
- **원 출력을 저장하므로** 검증 규칙을 바꿔도 같은 녹화본으로 다시 평가할 수 있다. 단, 검증 결과가 바뀌어 재요청
  여부가 달라지면 녹화에 없는 재요청이 생겨 미스가 난다. 그때는 녹화를 이어 붙인다 (`--append`).

### 7.2 녹화 키와 `recording_model_id`

기존 v2 행 키는 `(kind, model_id, request_hash)`이고, `request_hash`에는 system, user, 스키마 지문, max_tokens, effort가
들어간다. 로컬 모델에서는 **모델 파일과 디코딩 설정**이 응답을 바꾸는데 지금 키에는 없다. 녹화 형식(v2)을 바꾸지 않고
`model_id`에 넣는다.

```python
def recording_model_id(spec: LocalModelSpec, decoding: DecodingParams) -> str
    # f"{spec.model_id}@{spec.sha256[:12]}~{decoding.fingerprint()}"
    # 예: "qwen3-4b-instruct-2507-q4km@3f9a0c1d2e4b~a1b2c3d4"
```

- `decoding.fingerprint()`는 `DecodingParams` 전 필드(+ `decoding_schema_version`)의 정규 JSON 해시다. 디코딩 정책을
  바꾸면 `decoding_schema_version`을 올려야 한다. T25d에서 "정책 내용 해시 ≠ 버전에 등록된 해시"면 시작 시 실패하게 해,
  버전을 안 올리고 정책만 바꾸는 실수를 막는다 (`DECODING_POLICY_HASHES = {"ds-1": "<sha>"}`).
- 녹화 파일 이름은 `analyze.<recording_model_id>.jsonl`이다. `@`와 `~`는 파일 이름에 쓸 수 있지만, 안전하게
  파일 이름에서는 `@` → `_at_`, `~` → `_dec_`으로 바꾼다 (`recording_file_stem()`).
- llama.cpp 빌드 버전은 키에 넣지 않는다. 바뀌어도 recorded 재생은 그대로 된다(녹화가 정본). 대신 녹화 행을 쓸 때
  리포트 `config.runtime`에 `llama_cpp_python` 버전과 Metal 여부를 남긴다.
- **L4 정리 먼저** (T25a): `schema_fingerprint`가 description·title을 뺀 구조(필드 이름, 타입, 필수 여부, enum,
  const, 길이·개수 제약)만 해시하도록 바꾼다. 녹화 파일이 아직 하나도 없으므로 지금 바꾸면 무효화되는 녹화가 없다.

### 7.3 녹화 명령과 재생

- `jupjup analyze record --profile <P> --split dev|test|all [--append] [--confirm-run]`
  - 골든셋 v2 원문을 인제스트 파이프라인(I1~I5)으로 돌리고 `RecordingLLM`으로 분석기 호출을 녹화한다.
  - 시작 전에 **예상 소요 시간**(건수 × 모델별 T25b 실측 건당 p50)과 비용 0 USD를 출력한다. `--confirm-run` 없이는
    실행하지 않는다 (AC-33의 로컬판. 기존 `--confirm-cost`도 같은 뜻의 별칭으로 받는다).
  - 같은 요청이 이미 녹화돼 있으면 덧붙이지 않는다 (기존 `RecordingLLM._seen`).
  - **test split 녹화는 설정 동결 뒤에만** 허용한다. `--split test|all`은 `--frozen-config <sha256>`을 함께 요구하고,
  현재 프로필·프롬프트·디코딩 정책의 결합 해시가 같아야 실행한다 (8.6절).
- `jupjup eval ingest --mode recorded --profile <P>`는 `RecordedLLM`으로만 돈다. 미스가 나면 그 건을 실패로 기록하고
  종료 코드 2로 끝낸다 (조용히 넘어가지 않는다).
- 녹화 크기 추정: 80건 × 평균 1.3호출 × 약 3KB ≈ 0.3MB/프로필. 후보 6개와 판정기 녹화, 연결 지표(시드 200건)를 다
  합쳐도 10MB 안쪽이다. 커밋한다 (PRD Q9 규칙).

### 7.4 검색 연결 지표의 녹화

- `seed load --analyze`로 시드 200건을 분석기로 다시 분석하면, 검색 인덱스 문서 텍스트가 사람 분석과 달라져
  recorded bge-m3 임베딩이 없다.
- 두 단계로 잰다.
  1. **mock 연결 지표 (필수)**: `HashingEmbedder`로 사람 분석 인덱스와 분석기 인덱스의 검색 Recall@10, nDCG@10을 비교한다.
     녹화 없이 결정적이다. 분석기 출력은 recorded 분석 녹화(시드 200건 분)에서 읽는다.
  2. **recorded 연결 지표 (채택 판단용)**: `jupjup analyze record-linkage --profile P`가 분석기 출력으로 만든 문서·청크
     텍스트를 live bge-m3로 임베딩해 `data/recordings/linkage/…`에 녹화한다. 질의 임베딩은 기존 녹화를 쓴다.
     리랭커는 현재 recorded 기준선 설정과 같게 둔다.
- 3.5.4절 "검색 연결 Recall@10 하락 ≤ 0.03"은 2번(recorded) 값으로 판정한다. 1번은 회귀 감시와 디버깅용이다.
- 시드 분석 녹화는 분석 녹화 파일에 함께 들어간다(같은 `recording_model_id`). 시드는 검색 골든셋이라 **split 구분이 없다.**
  연결 지표는 설정 동결 뒤에 한 번만 녹화한다 (dev 튜닝 목적 함수에 넣지 않는다).

---

## 8. 평가 계획

### 8.1 인제스트 골든셋 v2 (T25c, 선행 조건)

- 규모와 분포는 PRD 3.5.1절 그대로다 (80건, 플랫폼별 분포, 어려운 사례 5종: 긴 글 5, 광고·해시태그 5, 영어 중심 5,
  숫자·날짜 5, 주입 3). split도 dev 48 / test 32를 유지한다.
- **원문을 자연문으로 새로 쓴다.** 실제 게시물을 옮기지 않고 직접 쓴다 (저작권, PRD Q18). 플랫폼별 문체를 살린다
  (인스타 구어체·해시태그, 카톡 대화 줄, 뉴스 기사체, 논문 초록, 유튜브 자막 구간). 긴 글 5건은 기존 HTML fixture를
  다시 써도 된다.
- **템플릿 검사기**를 `jupjup eval validate-ingest`에 더한다: (a) 원문 사이 8-gram 중복률 상한(같은 플랫폼 안 0.15),
  (b) 금지 문구(`핵심 정보 \d+`, `평가용 원문`, `자료 \d+ 저장`), (c) gold `key_facts`가 원문 문장의 **완전 복사**가 아닐 것
  (자연스러운 바꿔 쓰기. 정규화 후 원문 부분 문자열이면 경고), (d) gold의 엔티티·장소가 원문에 근거가 있을 것.
- gold 작성: AI 초안(작성 워커) → **다른 엔진 워커의 독립 검수**(Claude ↔ Codex) → 불일치만 사람이 판정. 사용자 표본
  검수 20~30건(PRD Q8 방식). `annotator`, `review_status`를 REVIEW_GUIDE대로 갱신한다.
- **test 봉인**: test 32건은 작성·검수 뒤 `data/golden/ingest/test.sha256`에 원문·gold 결합 해시를 남기고, T25h 동결 전까지
  분석기·프롬프트 작업자가 열어 보지 않는다 (워커 브리프에 명시. 하네스는 `--split test`를 동결 해시 없이 거부).
- 기존 v1 골든셋은 `data/golden/ingest_v1/`로 옮겨 mock 회귀 기준선(`ingest.mock.json`)용으로 남긴다. mock 배선 회귀는
  v1로 계속 돈다 (기준선 재생성 없음). v2에는 새 mock 기준선 `ingest_v2.mock.json`을 따로 만든다.

### 8.2 데이터 사용 규칙

1. 프롬프트, 디코딩 정책, 청킹 값, 후보 선택은 **recorded dev(48건)만** 보고 정한다.
2. 동결: 프로필 YAML 블록 + 프롬프트 파일 + 디코딩 정책 + `ChunkOverrides` + 모델 sha256의 결합 해시
   (`frozen_config_sha256`)를 리포트와 `specs/phase2_t25h_report.md`에 적고 커밋한다.
3. 동결 뒤 test를 **프로필마다 한 번** 녹화·평가한다. test 결과를 보고 설정을 바꾸면 그 프로필은 기각한다
   (다시 하려면 test v3가 필요하다는 사실을 보고한다).
4. 판정기 보정용 사람 판정은 dev에서만 단다.
5. dev가 48건이라 구간이 넓다. 리포트에 건별 표와 부트스트랩 구간을 함께 낸다.

### 8.3 충실도 판정기 (로컬)

- **1차 결정적 검사 (항상)**: 기존 `DeterministicFaithfulnessChecker` (T25a로 N1·L-1·L-2를 고친 판). 요약 문장의 숫자·날짜·
  고유명사가 원문에 없으면 "근거 없음 후보". `forbidden_claims`가 나오면 그 건은 1.0.
- **2차 로컬 판정기 (recorded/live)**: `LocalFaithfulnessJudge`가 `split_sentences(summary)`의 문장마다
  `supported | partially | unsupported`를 받는다. 문법 제약 스키마로 받는다.

```python
# eval/judge.py (확장)
class JudgeVerdicts(BaseModel):                    # 판정기 출력 스키마 (문법 제약)
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    judgments: list[JudgeItem] = Field(max_length=8)
class JudgeItem(BaseModel):
    index: int = Field(ge=0); verdict: Literal["supported", "partially", "unsupported"]
    evidence: str = Field(max_length=120)          # 원문 인용 (판정 근거, 리포트용)

class LocalFaithfulnessJudge:                      # FaithfulnessJudge 구현
    def __init__(self, llm: LLMClient, profile: JudgeProfile, prompts: PromptStore): ...
    profile_name: str
    def judge(self, source_text: str, sentences: Sequence[str]) -> list[SentenceJudgment]
        # index가 빠지거나 중복이면 1회 재요청, 그래도 실패하면 그 문장은 "unsupported"가 아니라
        # "judge_failed"로 리포트에 따로 센다 (판정기 실패를 분석기 탓으로 돌리지 않는다)

class CombinedFaithfulness:                         # 1차 + 2차 결합 규칙
    def unsupported_sentences(self, det: DeterministicCheckResult, judged: Sequence[SentenceJudgment] | None,
                              forbidden_hit: bool) -> tuple[list[str], float]
```

- **결합 규칙**: 판정기가 보정을 통과했으면(κ ≥ 0.7) 문장이 비충실인 조건은 `판정 == unsupported` **또는** (1차 후보이면서
  `판정 != supported`)이다. `partially`는 비충실로 세지 않지만 리포트에 따로 센다. 보정 전이거나 실패했으면 1차 결과만 쓰고,
  리포트 게이트의 비충실 행에 "판정기 미보정"을 표시한다.
- **판정기 등급**: 분석기보다 크거나 같은 모델, 다른 계열을 우선한다. 기본 `judge-kanana-8b`. 분석기가 Kanana 계열로
  정해지면 `judge-qwen25-7b`로 바꾼다 (자기 계열 선호 편향을 피한다). 판정기 프롬프트는 분석기 프롬프트와 다르다.
- **긴 원문**: 판정기 입력이 `n_ctx`를 넘으면 원문을 문장 번호로 나눠, 각 요약 문장마다 BM25로 고른 상위 12개 원문 문장만
  넣는다 (결정적 선택, `judge_context="retrieved"`로 리포트에 표시).
- **κ 보정 (T25g)**: dev 요약 문장 ≥ 100개(여러 후보 출력에서 고르게 표집, seed 고정)에 사람이 3분류 판정을 단다.
  도구: `jupjup eval judge-sample --out data/golden/ingest/judge_labels.dev.jsonl`이 문장·원문 발췌·빈 라벨을 내고,
  `jupjup eval judge-calibrate`가 Cohen's κ(3분류)와 이진(unsupported 대 나머지) κ를 낸다. **이진 κ ≥ 0.7**을 통과
  기준으로 둔다 (합격 판단이 이진이므로). 미달이면 판정기 프롬프트 버전을 올려 다시 잰다(최대 3회). 그래도 미달이면
  판정기 후보를 바꾸거나 Q-LA3 기본값대로 간다.

### 8.4 핵심 사실 재현율

부분 문자열 일치를 두 단계로 바꾼다.

1. **결정적 매처 (항상)** `keyfact_covered_deterministic(fact, summary, tokenizer)`: 사실의 내용 형태소(Kiwi 명사·동사·
   형용사·숫자 lemma, 동의어 정규형) 중 요약에 있는 비율 ≥ 0.6 **이고** 사실의 숫자·날짜가 요약에 모두 있으면 포함.
   mock과 v1 골든에서는 기존 부분 문자열 일치와 결과가 같아야 한다 (T25g에서 v1 mock all로 단언).
2. **로컬 판정기 (recorded/live, 보정 통과 시)** `LocalKeyFactJudge`: 사실마다 `covered | partial | missing`.
   `covered`만 포함으로 센다. κ 보정은 8.3절과 함께, 핵심 사실 쌍 ≥ 60개로 한다.
- 리포트에는 두 값을 다 낸다. 판정기가 보정을 통과했으면 3.5.4절 판정에 판정기 값을 쓰고, 아니면 결정적 값을 쓴다.

### 8.5 지표와 합격 기준

- 3.5.2절 전 지표를 그대로 낸다. 로컬 프로필은 `cost_usd = 0`이므로 리포트에 **건당 p50/p95 지연(single, map_reduce 따로),
  피크 RSS, 출력 토큰/초**를 비용 자리에 함께 낸다.
- 합격 기준은 3.5.4절 "기본 분석기" 열을 바꾸지 않는다. T25 완료 조건은 **recorded test(v2)가 그 열을 모두 충족**하는 것이다.
- 지연은 recorded가 아니라 live 벤치마크(`jupjup bench analyze --profile P --split dev`)로만 판단한다.

### 8.6 후보 비교 절차와 SwapDecision

1. **스파이크 (T25b)**: 후보 6개를 dev 10건으로 live 측정(첫 시도 준수율, 지연, 메모리, 한자 혼입, 문법 유무 차이).
   라이선스 원문 확인. 결과로 dev 전체 비교 대상을 줄인다 (기본: Qwen3-4B, Kanana-2.1B + 참고 EXAONE, Qwen2.5-3B).
2. **dev 녹화와 비교 (T25h)**: 남은 후보를 dev 48건 녹화 → recorded 평가 → 4.4절 선택 규칙으로 1개를 고른다.
   프롬프트 조정은 선택된 후보와 차점 후보에만 하고, 조정 이력(바꾼 것, 전후 지표)을 리포트에 남긴다.
3. **동결 → test 1회 → 3.5.4절 판정**.
4. **승격 판단 (선택)**: 기본 후보가 test를 통과했더라도 7~8B 후보가 dev에서 주요 지표를 크게 올리면(아래 업그레이드
   규칙) 사용자에게 선택지로 보고한다.

`compare_profiles`(T26a)는 PRD 3.5.5절 규칙을 구현하되 로컬 엔진에 맞게 두 방향을 둔다.

```python
# eval/ingest_compare.py (신규)
class DeltaCI(BaseModel): metric: str; delta: float; ci_low: float; ci_high: float; tolerance: float | None
class SwapDecision(BaseModel):
    direction: Literal["downgrade", "upgrade"]
    eligible: bool; reasons: list[str]; deltas: dict[str, DeltaCI]
    resource_gain: dict[str, float]                 # p95 지연, 피크 RSS, 비용의 상대 개선 (양수 = 후보가 좋음)
def compare_profiles(candidate: IngestEvalReport, incumbent: IngestEvalReport, *,
                     direction: Literal["downgrade", "upgrade"], bench: BenchPair | None = None,
                     n_boot: int = 1000, seed: int = 20261102) -> SwapDecision
```

- **downgrade** (더 작은 모델로): 3.5.5절 4번 그대로. 절대 기준 전부 + 하락 허용치(태그·엔티티·장소 F1 ≤ 0.03, 비충실 증가
  ≤ 0.01, 검색 연결 Recall@10 하락 ≤ 0.02) + 95% 구간 하한이 허용치보다 나쁘지 않음 + **자원 30% 이상 개선**. 로컬은
  비용이 0이므로 자원은 "single p95 지연 또는 피크 RSS"로 본다.
- **upgrade** (더 큰 모델로): 절대 기준 전부 + 주요 지표(비충실 비율, 핵심 사실 재현율, 엔티티 F1, 대표 태그 F1) 중 하나
  이상 개선이고 그 지표의 구간 하한 > 0 + 나머지 지표는 downgrade 허용치 안 + 지연 예산(single p95 ≤ 60초) 준수.
- 두 리포트의 `split`, 골든셋 해시, 판정기 프로필이 다르면 비교를 거부한다.
- 부트스트랩은 건 단위 쌍 재표집, seed 고정. 표본이 작다는 경고(건수 < 40)를 리포트에 낸다.

### 8.7 채택·기각 규칙

| 결과 | 조치 |
|---|---|
| 선택 후보가 recorded test(v2)에서 3.5.4절 기본 분석기 열 전부 충족 + κ 통과 + 검색 연결 하락 ≤ 0.03 + live 지연 예산 충족 | 채택 후보. 비교 리포트를 PM을 거쳐 사용자에게 올린다. 승인되면 `default_profile`을 바꾸고 `data/baselines/ingest.<profile>.recorded.json`을 커밋한다 |
| test에서 일부 기준 미달 | 기각. 설정을 test에 맞춰 고치지 않는다. 미달 지표와 원인 분석을 보고하고 Q-LA6에 따라 사용자 판단을 받는다 |
| κ 미달 | 비충실 비율·핵심 사실 재현율은 결정적 값으로 판정하되 "판정기 미보정"을 리포트 첫 줄에 적는다. 채택 여부는 사용자에게 묻는다 |
| dev에서 모든 후보가 절대 기준 미달 | 승격 후보로 반복. 그래도 미달이면 test를 쓰지 않고 멈춘 뒤 보고 (test를 아낀다) |
| 채택 뒤 프롬프트·모델 변경 | 3.5.5절 절차 (dev → 동결 → test 확인 → 승인)로만 |

---

## 9. 선행 정리 작업 (T25a)

| ID | 출처 | 내용 | T25 관련성 | 이번 처리 |
|---|---|---|---|---|
| **N1** | t24 loop2 | `eval/judge.py` `_SENTENCE`가 `6.5%`, `3.14`, `2026.10.06`, `v2.1`에서 문장을 자른다 | 비충실 비율 분모·분자, 판정기 문장 단위, 맵 단계 문장 번호가 모두 이 분리기를 쓴다 | **T25a 필수.** 마침표 앞뒤가 숫자거나 영숫자 버전 표기면 끝으로 보지 않는다. 단위 테스트 4종 + v1 골든 mock all에서 `unsupported_sentences` 0건 회귀 단언 |
| L-1 | t24 loop2 | 비충실 비율 분자는 집합, 분모는 중복 포함 | 3.5.4절 비충실 ≤ 0.03 판정값 | **T25a 필수.** 분자·분모를 문장 위치 기준으로 맞추고 테스트 기대값을 고친다 |
| L-2 | t24 loop2 | 영어 문장 첫 대문자 단어를 고유명사 후보로 잡는다 | 영어 중심 사례 거짓 양성 | **T25a 필수.** 문장 첫 단어는 원문 대소문자 무시 비교, 불용어(This, The, It, We, In, A, An, Our) 제외 |
| L-5(t24) | t24 loop2 | 리포트 `config` 경로가 절대 경로, `accuracy([])`가 1.0 | recorded 기준선을 커밋·비교하려면 경로가 상대여야 한다. 주입 사례 0건 공허 통과 | **T25a 필수.** 저장소 기준 상대 경로 직렬화, 빈 집합은 `None`(게이트 실패) |
| **D1** | hardening loop1 | 설계서 5.7절 `recording.py` 설명이 `prompt_hash 기반`으로 남아 있다. 3.5.1절 녹화 파일 설명도 같다. I2 직후 검색 노출의 dev API 해석이 없다 | 녹화 키 설명이 이 문서 7.2절과 맞아야 한다 | **이번 Architect 작업에서 처리** (PRD 최소 수정, 변경 이력 v1.2) |
| L1 | hardening loop1 | 인덱스 요약값이 제자리 수정을 놓친다 | 재분석(reanalyze)은 워커 I8이 `updated_at`을 갱신하므로 T25 경로에서는 생기지 않는다 | 이번 범위 밖. 사용자 수정 API 때 처리 |
| L2 | hardening loop1 | 초록 중복 검사 구두점 경계 | `ContentMeta.abstract`를 채우는 코드가 아직 없어 실제 분석 입력에 영향 없음 | 이번 범위 밖 (골든 v2에 논문 메타 초록을 넣게 되면 T25e에서 같이 고친다) |
| L3 | hardening loop1 | `reload_user` 동등성·성분별 테스트 없음 | 분석기와 무관 (검색 인덱스 다시 읽기) | 이번 범위 밖. Phase 3 정리 |
| **L4** | hardening loop1 | 녹화 키 스키마 지문이 pydantic JSON Schema 전체에 묶임 | **녹화 시작 전에 고쳐야** 커밋한 녹화가 문구 수정으로 무효화되지 않는다 | **T25a 필수.** 구조만 해시. 모듈 docstring에 "구조가 바뀌면 다시 녹화" 명시. 녹화 파일이 아직 없으므로 무효화 없음 |
| **L5** | hardening loop1 | `recording.py:205, 216`, `validation.py:327` 런타임 `assert` | T25에서 `recording.py`를 다시 쓰므로 같이 정리 | **T25a 포함.** 타입으로 좁히기 (`_parse_json_object` 반환형 정리) |
| L-3, L-4(t24) | t24 loop2 | 추출 빈 fixture가 run을 멈춤, 템플릿 조사 오류 | 골든 v2(T25c)가 대체한다. L-3 항목화는 T25f 하네스 확장 때 같이 처리 | T25c/T25f |

- T25a 완료 조건: `pytest`, `ruff check`, `mypy src` 통과. `eval ingest --mode mock --split dev|test|all` PASS, 두 번 실행 바이트
  동일. 바뀌는 수치는 N1·L-1로 인한 항목별 `unsupported_sentence_rate`뿐이며 보고서에 전후를 적는다. 검색 eval 4종 수치 동일,
  `src/jupjup/search`·`src/jupjup/query` diff 0.

---

## 10. 작업 분해와 의존성

### 10.1 작업 목록

| ID | 내용 | 주 산출물 | 담당 (기본) | 완료 조건 |
|---|---|---|---|---|
| **T25a** | 선행 정리 (9절 필수 항목) | `eval/judge.py`, `eval/ingest_harness.py`, `eval/ingest_metrics.py`, `providers/recording.py`, `ingest/validation.py`, 테스트 | Codex-Refactor (기능 수정 N1·L-1·L-2 포함이라 Codex-Primary도 가능) | 9절 완료 조건 |
| **T25b** | 런타임·모델 스파이크 (go/no-go). `src/`는 고치지 않는다 | `specs/phase2_t25b_spike_report.md`, `config/analyzer_profiles.yaml`의 `models:` 블록(repo, revision, filename, sha256, license) | Codex-Primary (측정 스크립트는 `scripts/spikes/`, 커밋하되 패키지 밖) | 후보 6개 각각: llama-cpp-python Metal 설치·버전 고정, GGUF 출처·sha256, 라이선스 원문 확인, dev 10건(템플릿 v1 대신 T25c 초안 또는 직접 쓴 10건)으로 문법 유/무 첫 시도 준수율, 건당 p50/p95, 피크 RSS, 한자 혼입 건수, 같은 입력 2회 출력 차이 건수. MLX-LM 4bit 자유 생성 지연 비교 1개 모델 이상. **go 조건**: 기본 후보 또는 도전 후보 하나 이상이 문법 제약으로 첫 시도 JSON 파싱 100%, single p95 ≤ 60초 |
| **T25c** | 인제스트 골든셋 v2 (8.1절) | `data/golden/ingest/` v2, `data/golden/ingest_v1/`, 템플릿 검사기, `test.sha256`, REVIEW_GUIDE 갱신 | 작성: Claude 워커, 독립 검수: Codex 워커, 표본 검수: 사용자 | `eval validate-ingest` 통과(템플릿 검사 포함), 80건·분포·어려운 사례 수 충족, 교차 검수 불일치 해소, 사용자 표본 검수 20건 이상 반영, v2 mock 기준선 생성, v1 mock 기준선 무변화 |
| **T25d** | 로컬 LLM 제공자와 설정 | `providers/llm_local.py`, `providers/json_grammar.py`, `ingest/profiles.py`, `config.py`, `domain/errors.py`, `pyproject.toml` extra, `jupjup models pull|doctor`, `config/analyzer_profiles.yaml` | Codex-Primary | 가짜 llama 모듈로: 지연 로드, sha 불일치·파일 없음 → `AnalyzerUnavailableError`, `finish_reason` 매핑, 타임아웃(`stopping_criteria`), 입력 상한, 잠금 직렬화, 문법 캐시, `recording_model_id` 결정성, 디코딩 정책 해시 검사. `build_decoding_schema` 속성 테스트(정본보다 같거나 엄격). 기본 설치에서 `import jupjup.providers.llm_local`이 llama_cpp를 import하지 않음. 소켓 차단 테스트. `@pytest.mark.local_llm` 실제 모델 테스트 1건(기본 제외) |
| **T25e** | 분석기 (single, 재요청, 맵-리듀스) | `ingest/analyzer.py`(`LLMContentAnalyzer`, `PromptStore`), `ingest/schemas.py`(`ChunkNotes`), `ingest/chunk_notes.py`, `ingest/validation.py`(`ChunkNotesValidator`, `foreign_script` 규칙), 프롬프트 4종, `container.build_content_analyzer`, `build_ingest_service(analyzer=…, chunk_settings=…)` | Codex-Primary | MockLLM fixture로: 프롬프트 렌더링 바이트 고정(골든 파일), 블록 탈출 방지, 재요청 프롬프트에 이전 출력·이슈 렌더링, `max_tokens` 재시도 시 같은 프롬프트·2배 토큰, 맵 재요청 1회·청크 실패 절반 규칙, 리듀스 근거 검사, `AnalysisRunMeta` 합산, 6.7절 실패 분류 표 전 행, 6.8절 required/optional 표 전 행. mock 모드 인제스트·검색 결과 바이트 동일 |
| **T25f** | 녹화·재생과 하네스 확장 | `jupjup analyze record|record-linkage`, `eval/ingest_harness.py` recorded/live 모드, 시간 추정·`--confirm-run`, 동결 해시 검사, 검색 연결 지표(mock·recorded), 미스 목록, L-3 항목화, `jupjup bench analyze` | Codex-Primary | MockLLM을 감싼 `RecordingLLM`으로 녹화 → `RecordedLLM` 재생이 같은 리포트(바이트 동일), 미스 시 종료 2와 미스 목록, test split 동결 해시 없으면 거부, live가 확인 플래그 없이 실행되지 않음, live 서비스 경로가 녹화하지 않음(테스트), 연결 지표 mock 경로 결정성 |
| **T25g** | 판정기와 보정 도구 | `eval/judge.py`(`LocalFaithfulnessJudge`, `LocalKeyFactJudge`, `CombinedFaithfulness`, 결정적 핵심 사실 매처), 판정 프롬프트 2종, `jupjup eval judge-sample|judge-calibrate`, κ 계산 | Codex-Primary | κ 계산 손계산 일치, 결합 규칙 표 테스트, 판정기 실패가 `judge_failed`로 따로 세짐, v1 mock all에서 결정적 매처 = 기존 부분 문자열 결과, 판정기 녹화·재생 |
| **T26a** | `compare_profiles`와 `compare-profiles` CLI (8.6절) | `eval/ingest_compare.py`, CLI | Codex-Primary | 두 방향 규칙, 부트스트랩 결정성(seed), 비교 거부 조건, 손으로 만든 리포트 쌍 테스트 (AC-29) |
| **T25h** | dev 튜닝, 후보 선택, 동결, test 1회, 기준선 | 녹화 파일(`data/recordings/llm/`, `linkage/`), 사람 판정 라벨, `specs/phase2_t25h_report.md`, `data/baselines/ingest.<profile>.recorded.json` | Codex-Primary(실행) + 사용자(판정 라벨 100문장·핵심 사실 60쌍) | 8.6~8.7절 절차대로 실행한 기록. recorded test v2가 3.5.4절 기본 분석기 열 충족(또는 미달 보고), κ 결과, 연결 지표, live 지연 벤치, `frozen_config_sha256`, 두 번 recorded 실행 바이트 동일 |
| T26b | (선택) 플랫폼 라우팅, 질의 보조와 런타임 공유 정리 | — | — | 이번 범위 밖 |

### 10.2 의존성 트리

```
T25a 선행 정리 ─────┬──▶ T25d 제공자·설정 ──▶ T25e 분석기 ──▶ T25f 녹화·하네스 ──┐
                    │                                                         │
                    └──▶ T26a compare_profiles ───────────────────────────────┤
T25b 스파이크 (src 미수정, 병렬) ──▶ (T25d의 models: 블록, 기본값 확정) ─────────┤
T25c 골든셋 v2 (data/golden, 병렬) ─────────────────────────────▶ T25g 판정기 ──┤
                                         (T25d 이후)  ─────────────▶ T25g      │
                                                                              ▼
                                                     T25h dev 튜닝 → 동결 → test 1회 → 사용자 승인
```

- `src/`를 고치는 작업(T25a, T25d, T25e, T25f, T25g, T26a)은 **한 번에 하나**씩, 위 순서로 한다 (CLAUDE.md 규칙).
  T25b(측정 보고서와 YAML 모델 블록)와 T25c(`data/golden/`, 검사기 스크립트)는 `src/`를 고치지 않으므로 병렬로 돌릴 수 있다.
  단, T25c의 템플릿 검사기를 `src/jupjup/eval/`에 넣는 부분은 T25a가 병합된 뒤 짧은 별도 커밋으로 한다.
- 권장 순서: T25a ∥ T25b ∥ T25c(원문 작성) → T25d → T25e → T25f → T25g → T26a → T25h.
- 각 작업은 Phase 2 → (필요 시 Phase 3) → Phase 4 검수 루프를 따른다.

---

## 11. 인수 기준 (Reviewer 채점용)

PRD 8장의 AC를 그대로 유지하고 아래를 더한다.

### 11.1 정확성
- AC-L1 기본 설치(extra 없음)에서 `uv run pytest`, `uv run ruff check src tests`, `uv run mypy src`가 통과한다. llama_cpp가
  설치되지 않은 환경에서 어떤 테스트도 skip이 아니라 통과로 끝난다 (실제 모델 테스트는 `local_llm` 마커로 기본 제외).
- AC-L2 mock 모드 인제스트(v1 골든) 리포트와 검색 eval 4종 수치가 T25a 이후 기준과 바이트 단위로 같다. `src/jupjup/search`,
  `src/jupjup/query` diff 0.
- AC-L3 `LLMContentAnalyzer`가 single·map_reduce·재요청·`max_tokens` 재시도를 PRD 5.10.6절과 이 문서 5.4절대로 처리한다
  (MockLLM 테스트).
- AC-L4 `eval ingest --mode recorded --profile <채택 후보> --split test`가 3.5.4절 기본 분석기 열을 충족한다. 두 번 실행 결과가
  바이트 단위로 같다.
- AC-L5 판정기 이진 κ ≥ 0.7(사람 판정 ≥ 100문장)이 리포트에 있고, 판정기 결합 규칙(8.3절)이 테스트로 고정돼 있다.
- AC-L6 검색 연결 Recall@10 하락(사람 분석 대비, recorded) ≤ 0.03.
- AC-L7 `compare_profiles`가 8.6절 두 방향 규칙을 구현하고 테스트된다.

### 11.2 안전성
- AC-L8 서비스·워커 경로에서 네트워크 호출이 없다. 모델은 로컬 파일 경로로만 열린다. 다운로드는 `models pull`에만 있고
  sha256을 검증한다 (소켓 차단 테스트와 코드 검사).
- AC-L9 live 서비스 경로는 녹화하지 않는다. 녹화 파일에 프롬프트 원문이 없다.
- AC-L10 live에서 로컬 분석기가 없을 때 mock 출력을 저장하지 않는다. 6.8절 표 전 행이 테스트로 있다.
- AC-L11 주입 사례에서 recorded 실제 출력이 스키마를 지키고 주입 지시를 따르지 않는다 (주입 저항 1.00). 원문 블록 탈출 방지
  테스트가 있다.
- AC-L12 test split은 동결 해시 없이 녹화·평가되지 않는다.
- AC-L13 로그와 `last_error`에 원문·프롬프트·출력 원문이 없다.

### 11.3 유지보수성
- AC-L14 모델 id, 파일, sha256, 디코딩 값, 청킹 값, 타임아웃이 `analyzer_profiles.yaml`과 설정에만 있다.
- AC-L15 프롬프트가 버전 파일로 분리돼 있고, 리포트 `config`에 프롬프트 sha256, `recording_model_id`, llama-cpp-python 버전,
  `frozen_config_sha256`이 남는다.
- AC-L16 `LLMContentAnalyzer`는 엔진을 모르고 `LLMClient`만 쓴다. llama_cpp import는 `providers/llm_local.py` 한 곳뿐이다.
- AC-L17 리포트 경로는 저장소 기준 상대 경로다.

---

## 12. 위험과 대응

| 위험 | 가능성 | 영향 | 대응 |
|---|---|---|---|
| 4B급 모델이 3.5.4절 기준(특히 엔티티 F1 ≥ 0.80, 핵심 사실 재현율 ≥ 0.85, 비충실 ≤ 0.03)에 못 미침 | 중~높음 | T25 미완료 | 문법 제약 + 근거 먼저 쓰는 필드 순서 + 한국어 짧은 예시. 승격 후보(7~8B). 그래도 미달이면 기준을 낮추지 않고 사용자 판단 (Q-LA6) |
| 골든 v2 작성이 오래 걸리고 품질이 들쭉날쭉 | 중 | 평가 신뢰도 | 템플릿 검사기, 교차 엔진 검수, 사용자 표본 검수. T25b·T25d와 병렬 진행 |
| llama-cpp-python 릴리스가 새 모델 구조를 늦게 지원 | 중 | 후보 탈락 | T25b에서 설치 가능한 버전으로 모델별 동작 확인. 안 되면 그 후보 제외 |
| Metal에서 live 출력이 실행마다 달라짐 | 중 | 재현성 | recorded가 정본. live는 지연 벤치에만 사용 |
| 문법 제약이 품질을 떨어뜨림 (모델이 원치 않는 토큰 강요) | 낮~중 | 품질 | T25b에서 문법 유/무 비교. 필드 순서·상한을 디코딩 정책 버전으로 조정 |
| 판정기 κ 미달 | 중 | 비충실 판정 신뢰도 | 프롬프트 개정 3회, 판정기 교체, 이진 κ 기준. 미달 시 결정적 값 + 표시 |
| 사람 판정 라벨(100문장 + 60쌍) 작업이 사용자에게 부담 | 중 | 일정 | 라벨 도구가 한 문장씩 원문 발췌와 함께 보여 주고 키 하나로 답하게 한다. 약 1시간 예상. Q-LA3 |
| 소형 모델이 한국어 요약에 한자·영어를 섞음 | 중 (Qwen) | 품질 | `foreign_script` 의미 규칙 → 재요청 |
| 워커가 분석 모델 + bge-m3를 함께 올려 메모리 압박 | 낮음 | 안정성 | 4.1절 추정 합계 ≈ 10GB 미만. T25b에서 피크 RSS 실측 |
| 긴 글 map_reduce 지연(최대 12청크) | 중 | 체감 없음(비동기)이나 큐 적체 | 별도 예산 300초, 우선순위(신규 > 재분석) 유지 |
| 비상업 모델을 무심코 기본값으로 채택 | 낮음 | 법적 | `license_commercial_ok`를 선택 규칙 1번과 `models doctor`에서 경고 |
| 녹화 키가 모델 파일·디코딩 변경을 놓침 | 낮음 | 잘못된 재생 | `recording_model_id`에 sha256·디코딩 지문, 정책 해시 검사 |

---

## 13. 열린 질문과 PM 추천 기본값

사용자 확인이 없어도 아래 추천값으로 구현을 시작할 수 있다.

### Q-LA1. 비상업 라이선스 모델(EXAONE 3.5, Qwen2.5 3B)을 기본 분석기로 써도 되나요?
지금은 개인 프로젝트지만 이후 서비스 가능성이 있습니다.
- **PM 추천 기본값:** 기본값 후보는 상업 이용이 가능한 모델(Apache-2.0: Qwen3-4B-2507, Kanana-1.5, Qwen2.5-7B)로만 고른다.
  EXAONE 3.5와 Qwen2.5 3B는 dev에서 참고 측정만 하고 표에 넣는다. 참고 후보가 압도적으로 좋으면(주요 지표 합 +0.05 이상)
  그 사실을 보고해 사용자가 고르게 한다.

### Q-LA2. 인제스트 골든셋을 v2(자연문)로 새로 만들어도 되나요? 누가 검수하나요?
현재 80건은 템플릿 문장이라 실제 모델 품질을 잴 수 없습니다.
- **PM 추천 기본값:** 만든다 (T25c). Claude 워커가 쓰고 Codex 워커가 독립 검수하며, 사용자는 20~30건 표본만 본다.
  v1은 mock 배선 회귀용으로 남긴다.

### Q-LA3. 판정기 보정용 사람 판정(문장 100개 + 핵심 사실 60쌍)은 누가 하나요?
- **PM 추천 기본값:** 사용자가 라벨 도구로 한다 (약 1시간). 사용자가 어렵다면 Claude·Codex 두 엔진의 독립 판정이 일치한
  것만 "준-사람 라벨"로 쓰되, 리포트에 "사람 판정 아님"을 표시하고 κ 기준 통과를 PRD 의미의 보정으로 주장하지 않는다.

### Q-LA4. map_reduce(긴 글) 건의 지연 예산을 single과 따로 300초로 둬도 되나요?
PRD 4.3절 ①은 건당 p95 ≤ 60초 하나만 있습니다. 긴 글 5건이 dev·test의 5%를 넘어 p95를 좌우합니다.
- **PM 추천 기본값:** single p95 ≤ 60초, map_reduce p95 ≤ 300초로 나눈다. 사용자는 기다리지 않는 비동기 경로다.

### Q-LA5. live에서 로컬 모델이 없을 때 워커를 띄울까요, 막을까요?
- **PM 추천 기본값:** `required=false`(띄움). 분석 잡은 `ANALYZER_UNAVAILABLE`로 실패시키고 축약 인덱스로 검색은 계속한다.
  mock 분석 결과로 대체하지 않는다. 운영 배포에서는 `required=true`를 권한다.

### Q-LA6. 로컬 모델이 3.5.4절 기준에 끝내 못 미치면 어떻게 할까요?
기준은 Opus 5.5급 API 모델을 가정하고 정한 값입니다.
- **PM 추천 기본값:** 기준을 자동으로 낮추지 않는다. 7~8B 승격까지 해 본 뒤 미달 지표와 사례를 보고하고, 사용자가 (a) 해당
  지표 기준 조정, (b) 더 큰 로컬 모델(예: 14B Q4, 메모리 약 9GB) 검토, (c) 현 상태로 채택하되 "기준 미달" 표시 중에서 고른다.
  외부 API는 사용자 결정(2026-11-02)에 따라 선택지에 넣지 않는다.

### Q-LA7. 분석기 출력 녹화와 연결 지표 임베딩 녹화를 git에 커밋해도 되나요?
- **PM 추천 기본값:** 커밋한다. 합성 골든셋에서 나온 출력이라 개인 데이터가 없다. 10MB를 넘으면 Git LFS (PRD Q9).

### Q-LA8. 질의 보조(설계서 5.6절)의 로컬 런타임도 같은 extra와 제공자를 쓰게 할까요?
- **PM 추천 기본값:** 그렇다. `assist-local`을 `analyze-local`의 별칭으로 두고 `LlamaCppLLM`을 공유한다. 질의 보조 작업(T39)
  착수 때 `n_ctx`, `max_tokens`만 다른 프로필로 쓴다.

### Q-LA9. 기본 분석기 채택 뒤 기존 저장물을 전부 재분석할까요?
- **PM 추천 기본값:** 채택 승인 시 `jupjup ingest reanalyze --all --profile <채택>`을 운영자가 한 번 돌린다(재분석 우선순위 1).
  사용자 수정값은 보존된다(AC-31). 건당 약 20~30초라 저장물 1,000건이면 약 7시간이므로 밤에 돌린다.

### Q-LA10. 판정기 κ 기준을 3분류가 아니라 이진(unsupported 대 나머지)으로 재도 되나요?
- **PM 추천 기본값:** 이진 κ ≥ 0.7로 판정한다. 합격 지표(비충실 비율)가 이진이기 때문이다. 3분류 κ도 리포트에 함께 낸다.

---

## 14. Codex-Primary에게 넘길 핵심 사항

1. **원문은 기기 밖으로 나가지 않는다.** 실행 경로에서 허브·네트워크를 부르지 않는다. 다운로드는 `models pull`만, sha256 검증.
2. **기본 설치는 그대로다.** llama_cpp는 `providers/llm_local.py` 안에서만 지연 import한다. mock 결과와 검색 결과는 한 바이트도
   바뀌지 않는다.
3. **분석기는 엔진을 모른다.** `LLMContentAnalyzer`는 `LLMClient`만 쓰고, 테스트는 MockLLM으로 한다.
4. **검증 루프는 바꾸지 않는다.** 문법 제약 디코딩은 앞단 방어일 뿐, `validate_and_repair`를 항상 거친다.
5. **녹화가 정본이다.** `recording_model_id`에 모델 sha256과 디코딩 지문을 넣는다. 녹화 형식 v2는 바꾸지 않는다. L4를 먼저 고친다.
6. **live에서 분석기가 없으면 mock으로 대체하지 않는다.** `ANALYZER_UNAVAILABLE`로 실패시키고 축약 인덱스로 검색을 유지한다.
7. **test는 봉인한다.** dev에서만 조정하고, 동결 해시 없이 test를 돌리지 않는다.
8. **한 번에 한 워커만 `src/`를 고친다.** 순서: T25a → T25d → T25e → T25f → T25g → T26a → T25h.
9. 설계와 다르게 구현해야 하면 보고서에 이유를 적는다.
