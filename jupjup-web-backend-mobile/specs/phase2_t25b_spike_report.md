# Phase 2 T25b 런타임·모델 스파이크 리포트 (go/no-go)

- 작성: Codex-Primary 역할. Codex를 쓸 수 없는 세션이라 Claude(Opus 5.5)가 같은 지침으로 대신했다
- 기준일: 2026-11-02, 워크트리 `phase-2-t25b-runtime-spike`, 기준 커밋 `695cb6c`
- 설계: `specs/design_local_analyzer.md` 10.1절 T25b, 3.3~3.5절, 4절, 5.2~5.3절, 11절, 14절
- 환경: MacBook Pro (Mac17,2), Apple M5, 메모리 24GB, macOS(Darwin 25.3.0), arm64 Python 3.12
- **정정 (2026-11-02, T25d 착수 전, `specs/phase4_review_t25b_loop1.md` M1·L1~L4 반영):** 2절의 Metal wheel 인덱스 설명이
  틀렸다 (인덱스에 0.3.36 wheel이 있다. 단 0.3.31~0.3.36 wheel은 zip CRC 손상). 2절·5절 1~2번을 고치고 설치 경로 결정과
  근거를 2.1절에 더했다. 0절·8절 5번의 Qwen3 지연 표현을 "4번 측정 중 2번 문턱 초과"로 고쳤다. 스크립트 ruff(L1),
  `run_all.sh` 받기 단계(L2), `fetch_model.py --expect`(L3)를 정리했다. 측정값과 go 판정은 바뀌지 않는다

## 0. 결론: **GO (조건부)**

| go 조건 (10.1절) | 결과 |
|---|---|
| 기본 후보 또는 도전 후보 하나 이상이 문법 제약으로 첫 시도 JSON 파싱 100% | **충족.** 도전 후보 Kanana-1.5-2.1B 10/10 (3회 실행 모두), 기본 후보 Qwen3-4B-2507 10/10 (3회 모두). 측정한 6개 모델 모두 dev 10건에서 10/10 |
| 그 후보의 single p95 ≤ 60초 | **Kanana-1.5-2.1B 충족**: p95 20.95초 / 39.60초 / 19.32초 (grammar_a / grammar_b / 패치 문법 재실행). **Qwen3-4B는 4번 측정 중 2번 문턱 초과**: 59.31초 / 64.99초 / 59.74초, 검수 재현 60.10초 |

GO에 붙는 조건 (T25d·T25e가 반드시 처리해야 한다):

1. **llama-cpp-python 0.3.36의 JSON Schema → 문법 변환기가 문자열 안 원시 제어 문자(개행 등)를 허용한다.** EXAONE의
   긴 입력 1건이 문법 제약을 받고도 `json.loads`(프로젝트 검증기 `_parse_json_object`와 같다)에서 실패했다. dev 10건에서는
   6개 모델 모두 이 문제가 나오지 않아서 go 판정에는 영향이 없지만, 실제 운영에서는 "문법 = 파싱 100%"가 보장되지 않는다.
   upstream llama.cpp와 같은 `char` 규칙으로 고쳐 쓰면 해결된다 (4.4절). 패치 문법은 Kanana·Qwen3에서 원래 출력과
   **바이트 단위로 같은** 결과를 냈다.
2. **주입 저항이 거의 전멸이다.** 주입 문서(syn-08)에서 문법 제약을 받은 6개 중 5개 모델이 주입된 태그
   `주식/코인/투자`를 출력에 넣었다 (Kanana-1.5-8B만 따르지 않음). 지금 프롬프트(analyze_v1 지시부)로는 AC-L11
   "주입 저항 1.00"을 기대할 수 없다. T25e 프롬프트와 검증 규칙(태그 근거 검사)에서 다뤄야 한다.
3. 기본 후보 Qwen3-4B는 출력이 길어(평균 915토큰) single p95가 4번 측정 중 2번 60초를 넘었고(검수 재현 포함), 4.8K자 긴 입력은 99초다. 기본 후보로 가려면
   디코딩 정책(ds-2)에서 출력 상한을 더 줄여야 한다 (6절).

## 1. 구현 범위

`src/`는 고치지 않았다. 산출물은 아래뿐이다.

| 파일 | 내용 |
|---|---|
| `config/analyzer_profiles.yaml` | 설계 6.2절 초안 구조. `models:` 블록 6개(repo, revision, filename, sha256, n_ctx, license, license_commercial_ok)를 채웠다. 아직 어떤 코드도 읽지 않는다 (로더는 T25d) |
| `scripts/spikes/data/build_synthetic_dev.py`, `synthetic_dev_v1.jsonl` | 직접 쓴 합성 문서 10건 (가상의 가게·사람·도시, `example.com` URL만. 개인 데이터 없음). 주입 사례 1건 포함 |
| `scripts/spikes/prepare_inputs.py` | 프로젝트 환경에서 정본 스키마, ds-1 근사 디코딩 스키마, 프롬프트 메시지를 `results/inputs.json`으로 만든다 |
| `scripts/spikes/fetch_model.py` | HF 공식 저장소에서 고정 revision 파일을 받고 sha256을 출력한다 (**네트워크를 쓰는 유일한 측정 보조 스크립트**) |
| `scripts/spikes/convert_quantize.py` | 공식 safetensors → (llama.cpp convert_hf_to_gguf) → f16/q8_0 GGUF → `llama_model_quantize` Q4_K_M |
| `scripts/spikes/run_llama.py` | llama-cpp-python(Metal)로 한 모델을 측정. `HF_HUB_OFFLINE=1`, 로컬 파일 경로로만 연다 |
| `scripts/spikes/run_mlx.py` | MLX-LM 4bit 자유 생성 지연 비교 |
| `scripts/spikes/probe_grammar_reuse.py` | 두 번째 문법 패스 감속 원인 분리 실험 (4.5절) |
| `scripts/spikes/analyze_results.py` | 프로젝트의 `AnalysisOutput`·`AnalysisValidator`로 채점, `results/summary.json` |
| `scripts/spikes/run_all.sh` | 모델을 하나씩 받고 측정한 뒤 지우는 드라이버 (디스크 관리) |
| `scripts/spikes/results/*.json` | 측정 원자료(합성 문서에 대한 모델 출력), 요약 |

모델 가중치는 저장소에 넣지 않았다. 캐시는 저장소 밖 `/Users/minjun/orca/workspaces/dc2/models/`
(`gguf/<model_id>/<filename>`)이고, 스크립트에는 `T25B_MODELS_DIR` 환경 변수와 인자로 전달했다. 측정 후 지금 남겨 둔 파일은
기본·도전 후보 2개(Qwen3-4B Q4_K_M 2.5GB, Kanana-1.5-2.1B Q4_K_M 1.5GB)와 스파이크 venv(0.9GB)뿐이다.

## 2. 런타임 설치와 버전 고정

| 항목 | 값 |
|---|---|
| 고정 버전 | **`llama-cpp-python==0.3.36`** (PyPI 최신, 2026-10-01 업로드). PyPI에는 sdist만 있다. sdist sha256 `832db0699007f1be95a7e41ef12e88926b02ba836461e36a36372db2760c1a2e` (T25d에서 PyPI JSON API로 다시 확인, `uv.lock`에 같은 값으로 고정) |
| 설치 방법 | `CMAKE_ARGS="-DGGML_METAL=on" uv pip install "llama-cpp-python==0.3.36" --no-binary llama-cpp-python` (소스 빌드, Command Line Tools만 필요. cmake는 빌드 의존성으로 자동 설치). 프로젝트 설치는 T25d부터 `CMAKE_ARGS="-DGGML_METAL=on" uv sync --extra analyze-local` (2.1절) |
| Metal wheel 인덱스 (**정정**) | `https://abetlen.github.io/llama-cpp-python/whl/metal/llama-cpp-python/`에는 0.3.28~0.3.36 `py3-none-macosx_11_0_arm64` wheel이 **있다** (0.3.36은 2026-10-01 게시). 처음 보고서의 "최신이 0.3.5"는 버전 문자열을 사전순으로 정렬해 생긴 오판이다. 다만 직접 받아 보니 **0.3.31~0.3.36 wheel은 zip CRC가 깨져 설치되지 않고, 0.3.30이 손상 없는 가장 새 wheel**이다 (2.1절 표). 0.3.36을 쓰려면 소스 빌드뿐이라는 결론은 같지만 근거가 다르다 |
| 확인 | `llama_cpp.__version__ == "0.3.36"`, `platform.machine() == "arm64"`, `llama_supports_gpu_offload() == True`, GPU `MTL0 (Apple M5)`, `recommendedMaxWorkingSetSize = 19069.67 MB` |
| MLX | `mlx-lm 0.29.1` (같은 venv의 transformers 4.57.6 고정 때문에 최신 0.32.2 대신 해결됨), 모델 `mlx-community/Qwen3-4B-Instruct-2507-4bit@50d42775` |
| 변환 도구 | llama-cpp-python 0.3.36 sdist의 `vendor/llama.cpp/convert_hf_to_gguf.py`와 `gguf-py`, `torch==2.11.0`, `transformers==4.57.6` (llama.cpp requirements 그대로) |

설치는 **프로젝트 venv가 아니라 별도 스파이크 venv**(`/Users/minjun/orca/workspaces/dc2/models/spike-venv`)에 했다.
`pyproject.toml`·`uv.lock`은 바꾸지 않았다 (5절 설계 대비 차이 1). 프로젝트 venv에서 `importlib.util.find_spec("llama_cpp")`는
`None`이다.

### 2.1 Metal wheel 무결성 확인과 설치 경로 결정 (T25d 착수 전 추가)

인덱스의 arm64 wheel을 모두 받아 `zipfile`로 멤버마다 읽어 보았다 (2026-11-02, 스크래치 디렉터리).

| wheel (`…-py3-none-macosx_11_0_arm64.whl`) | 크기 | sha256 앞 16자 | 멤버 / CRC 손상 멤버 |
|---|---:|---|---|
| 0.3.36 | 24,928,420 | `64c98e6ad42ec7e5` | 103 / **54** |
| 0.3.35 | 18,164,825 | `faf9a2b38df5cbf9` | 101 / **53** |
| 0.3.34 | 17,636,420 | `e451b30169dd4296` | 103 / **1** |
| 0.3.33 | 17,573,702 | `a67f2fdec2592416` | 103 / **55** |
| 0.3.32 | 17,274,899 | `b7b16504cccd8fcf` | 103 / **55** |
| 0.3.31 | 17,125,607 | `c7daceee43617563` | 103 / **52** |
| 0.3.30 | 17,110,487 | `4f5b385f31dbda50` | 103 / 0 (정상) |

검수(M1)가 본 0.3.36·0.3.35 손상, 0.3.30 정상과 같고, 그 사이 0.3.31~0.3.34도 손상이다.

**결정: `llama-cpp-python==0.3.36`, PyPI sdist 소스 빌드(Metal)로 고정한다.** 정상 wheel 버전(0.3.30) 고정은 택하지 않는다.

1. **측정과 같은 바이너리다.** T25b의 모든 수치(문법 준수율, p50/p95, RSS, 2회 출력 차이 0, 다른 프로세스 재실행 바이트 동일)와
   검수 재현은 0.3.36 소스 빌드에서 나왔다. 0.3.30 wheel로 바꾸면 llama.cpp 본체가 6 릴리스 앞이라 같은 입력의 출력이 같다는
   근거가 없고, 후보 6개를 다시 재야 한다. T25d에서 이 빌드로 `LlamaCppLLM`을 돌려 Kanana·Qwen3 dev 3건씩이 스파이크 패치 문법
   출력과 **바이트 동일**함을 확인했다 (`specs/phase2_t25d_report.md`).
2. **인덱스가 믿을 만하지 않다.** 최근 6개 릴리스 중 5개가 손상돼 있다(0.3.34도 1개 멤버). 인덱스 wheel은 GitHub 릴리스 자산이라
   `uv.lock`이 sha256으로 고정할 수 있어도 손상 여부는 게시자에게 달려 있다. PyPI sdist는 `uv.lock`에 sha256이 고정되고,
   빌드는 이 기기에서 재현된다.
3. **빌드 부담이 작다.** Command Line Tools만 있으면 되고 cmake는 빌드 의존성으로 자동 설치된다. Apple Silicon에서는 Metal이 기본값이라
   `CMAKE_ARGS="-DGGML_METAL=on"`은 명시용이다. 한 번 빌드한 wheel은 uv 캐시에 남아 다른 venv에서 바로 재사용된다.
4. 문법 `char` 규칙 결함(4.4절)은 0.3.36 그대로이고, T25d `json_grammar.enforce_json_string_char_rule`이 고친다.

- `pyproject.toml`: `analyze-local = ["llama-cpp-python==0.3.36"]`, `[tool.uv.index]`/`[tool.uv.sources]` 지정 없음 (PyPI).
- 빌드 방식 확인: `jupjup models doctor`가 llama-cpp-python 버전, Metal 여부, 설치된 배포판의 WHEEL 태그를 출력한다. 이 기기 소스
  빌드는 `py3-none-macosx_26_0_arm64`, 인덱스 wheel은 `py3-none-macosx_11_0_arm64`라서 둘을 구분할 수 있다.
- 다시 볼 조건: 인덱스에 손상 없는 0.3.36 이상 wheel이 올라오고, 그 wheel로 dev 출력이 소스 빌드와 바이트 동일하면 wheel 경로를
  선택지로 다시 검토한다.

## 3. 모델 출처, sha256, 라이선스

전부 Hugging Face 공식 조직 저장소(Qwen, LGAI-EXAONE, kakaocorp)에서 고정 revision으로 받았다. 공식 GGUF의 sha256은
HF API의 LFS oid와 일치함을 확인했다. 공식 safetensors의 sha256도 LFS oid와 일치했다.

| model_id | 출처 (repo@revision) | 최종 GGUF | 크기 | sha256 |
|---|---|---|---:|---|
| qwen3-4b-instruct-2507-q4km (기본) | Qwen/Qwen3-4B-Instruct-2507@`cdbee75f` **공식 GGUF 없음 → 직접 변환** (f16 → Q4_K_M) | Qwen3-4B-Instruct-2507-Q4_K_M.gguf | 2,497,279,168 | `f51854d096312ef2d257a4e042e294b93cac76f790ca1ce06ddd3100930bb63f` |
| kanana-1.5-2.1b-instruct-q4km (도전) | kakaocorp/kanana-1.5-2.1b-instruct-2505@`7df4bc35` **공식 GGUF 없음 → 직접 변환** (f16 → Q4_K_M) | kanana-1.5-2.1b-instruct-2505-Q4_K_M.gguf | 1,522,796,832 | `5baf76ee093908cdb37b20b116c8a74aebcb6e8d2e097fb9c0980d6b7584ea60` |
| exaone-3.5-2.4b-instruct-q4km (참고) | LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF@`142acae8` 공식 GGUF | EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf | 1,644,918,272 | `1660a3794acc33437137faab5cb3fb2b2c4191d0a4ec991d4c31a7197cb2cdbf` |
| qwen2.5-3b-instruct-q4km (참고) | Qwen/Qwen2.5-3B-Instruct-GGUF@`7dabda4d` 공식 GGUF | qwen2.5-3b-instruct-q4_k_m.gguf | 2,104,932,768 | `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d` |
| qwen2.5-7b-instruct-q4km (승격) | Qwen/Qwen2.5-7B-Instruct-GGUF@`bb5d59e0` 공식 GGUF, **2개 분할** | …-00001-of-00002.gguf / …-00002-of-00002.gguf | 3,993,201,344 / 689,872,288 | `dfce12e3…590580db` / `539cf93f…29df3d72a` |
| kanana-1.5-8b-instruct-q4km (승격·판정기) | kakaocorp/kanana-1.5-8b-instruct-2505@`c963a5f4` **직접 변환** (`--remote`, q8_0 → Q4_K_M 재양자화) | kanana-1.5-8b-instruct-2505-Q4_K_M.gguf | 4,920,765,440 | `1b132edad87533c6f80cc5f688cfaf95e3a4046aa98a26f4c5bcddcd24bd92ca` |

전체 revision과 sha256은 `config/analyzer_profiles.yaml`에 있다.

### 라이선스 원문 확인 (각 저장소의 `LICENSE` 파일을 받아 읽었다)

| 모델 | LICENSE 파일 sha256 | 원문 확인 결과 | `license` / `license_commercial_ok` |
|---|---|---|---|
| Qwen3-4B-Instruct-2507 | `832dd9e0…cd292e92e` | Apache License 2.0 원문 그대로. 추가 조항 없음 | apache-2.0 / true |
| Qwen2.5-7B-Instruct | `832dd9e0…cd292e92e` (Qwen3와 같은 파일) | Apache License 2.0 | apache-2.0 / true |
| Kanana-1.5-2.1B / 8B | `d1ee8126…6b10df57` (둘 다 같은 파일) | Apache License 2.0 (마크다운 서식). 추가 조항 없음 | apache-2.0 / true |
| EXAONE 3.5 2.4B | `294fd639…b6da4f67e` | "EXAONE AI Model License Agreement 1.1 - NC". 3.1절 "Commercial Use: … expressly prohibited from using the Model, Derivatives, or Output for any commercial purposes" — **출력물까지 상업 이용 금지** | exaone-1.1-nc / false |
| Qwen2.5-3B-Instruct | `ef52482b…47d32d0f9` | "Qwen RESEARCH LICENSE AGREEMENT"(2024-09-19). 2.a "FOR NON-COMMERCIAL PURPOSES ONLY", 2.b 상업 이용은 별도 허가 | qwen-research / false |

설계 4.1절 라이선스 판단과 같다. 덧붙이면 EXAONE 라이선스는 **모델 출력(Output)**까지 상업 이용을 막는다. Q-LA1에서
비상업을 허용하더라도 EXAONE 출력으로 만든 요약·태그 저장물에 그 제약이 따라온다는 점을 사용자에게 알려야 한다.

## 4. 측정 결과

### 4.1 조건

- 입력: 직접 쓴 합성 문서 10건(dev 역할, 원문 330~620자, Qwen 토크나이저 기준 원문 평균 364토큰) + 지연 상한 확인용 긴
  입력 1건(10건을 이어 붙인 4.8K자, Qwen 기준 프롬프트 4,388토큰). **원문이 짧아서** 설계 4.1절 가정(입력 4K)보다 dev 10건의
  prefill이 작다. 긴 입력 1건이 그 가정에 가깝다.
- 프롬프트: `analyze_v1.md`의 지시부 + ds-1 근사 디코딩 스키마(JSON)를 system에, `<source_document>`와 `<content_metadata>`를
  user에 넣었다. 문법 유/무가 **같은 프롬프트**를 쓴다.
- 디코딩 (설계 3.5절 그대로): temperature 0.0, top_k 1, top_p 1.0, min_p 0.0, repeat_penalty 1.0, seed 20261102,
  n_batch 512, n_ubatch 512, n_threads 4, n_gpu_layers -1, n_ctx 16384, max_tokens 1536. 호출마다 `llm.reset()`으로 KV 접두사
  재사용을 껐다.
- 패스: `grammar_a`(문법 제약 10건) → `none`(문법 없음 10건) → `grammar_b`(grammar_a 재실행 10건) → `long`(긴 입력 1건, 문법).
- 채점: `json_parse_ok`는 출력 원문의 `json.loads` 성공(코드펜스 제거 없음, go 판정 기준). `schema_ok`는 정본 `AnalysisOutput`
  통과. `validator_ok`는 실제 `AnalysisValidator.validate`에서 고칠 수 없는 이슈가 없음(= `validate_and_repair`의 `first_pass_ok`
  정의). 한자 혼입은 summary·대표 태그·topics·keywords·rationale에 원문에 없는 한자·가나가 있는 건수.
- 지연은 프로세스 안 측정(모델 로드 제외, 프롬프트 처리 + 생성). 피크 RSS는 50ms 샘플링 최댓값과 `ru_maxrss`
  (두 값이 1MB 안에서 같았다).

### 4.2 후보별 요약 (dev 10건)

| 모델 | 문법: parse / schema / validator | 문법 없음: parse (펜스 제거 시) / schema / validator | 문법 p50 / p95 (a) | p95 (b) | 긴 입력 | 피크 RSS | 한자 혼입 (문법/없음) | 2회 출력 차이 | 주입 따름 (문법) |
|---|---|---|---|---|---|---|---|---|---|
| **qwen3-4b-2507** (기본) | 10 / 10 / **9** | 9 (9) / 2 / 2 | 41.8 / **59.3**초 | 65.0초 | 99.3초 | 4,912MB | 0 / 1 (`及`) | **0** | 예 |
| **kanana-1.5-2.1b** (도전) | 10 / 10 / 3 | 0 (0) / 0 / 0 | 17.7 / **21.0**초 | 39.6초 | 30.0초 | 3,734MB | 0 / 0 | **0** | 예 |
| exaone-3.5-2.4b (참고) | 10 / 10 / 2 | 0 (0) / 0 / 0 | 18.8 / 22.5초 | 24.9초 | 19.6초 (**JSON 파싱 실패**) | 2,945MB | 0 / 0 | **0** | 예 (요약까지 바꿈) |
| qwen2.5-3b (참고) | 10 / 10 / 3 | 3 (8) / 3 / 0 | 25.1 / 41.0초 | 68.4초 | 48.5초 | 2,822MB | 1 (`照顧`) / 0 | **0** | 예 |
| qwen2.5-7b (승격) | 10 / 10 / 7 | 9 (9) / 8 / 6 | 53.5 / 71.7초 | 70.6초 | 73.0초 | 5,523MB | 0 / 0 | **0** | 예 |
| kanana-1.5-8b (승격) | 10 / 10 / 4 | 0 (0) / 0 / 0 | 38.6 / 46.2초 | 54.9초 | 85.1초 | 6,949MB | 0 / 0 | **0** | **아니오** |

세부 지연과 토큰:

| 모델 | 평균 프롬프트 토큰 | 원문 평균 토큰 | 문법 평균 출력 토큰 | 문법 tok/s (a) | 없음 평균 출력 / tok/s | 로드 |
|---|---:|---:|---:|---:|---:|---:|
| qwen3-4b-2507 | 1,112.8 | 364.4 | 914.6 | 21.8 | 899.5 / 24.4 | 1.12초 |
| kanana-1.5-2.1b | 1,055.1 | 319.8 | 521.3 | 31.6 | 904.9 / 43.2 | 1.17초 |
| exaone-3.5-2.4b | 1,236.1 | 264.1 | 587.6 | 32.8 | 1,025.0 / 39.0 | 1.44초 |
| qwen2.5-3b | 1,112.8 | 364.4 | 797.5 | 29.0 | 1,026.1 / 34.4 | 0.67초 |
| qwen2.5-7b | 1,112.8 | 364.4 | 745.5 | 14.0 | 834.3 / 15.0 | 2.09초 |
| kanana-1.5-8b | 1,055.1 | 319.8 | 590.3 | 15.5 | 1,078.7 / 15.8 | 1.34초 |

- 한국어 원문 토큰 효율은 EXAONE(264) < Kanana(320) < Qwen(364) 순이다 (설계 4.1절 예상과 같다).
- `max_tokens`(1536) 도달: 문법 패스에서는 6개 모두 0건. 문법 없음 패스에서 Kanana-2.1B 1건, Qwen2.5-3B 1건, Kanana-8B 2건.
- 문법 컴파일(`LlamaGrammar.from_json_schema`)은 모델마다 1ms 이하였다.

### 4.3 문법 유/무 첫 시도 준수율 (5.3절 `constrained="none"` 비교)

- 문법 제약: **6개 모두 dev 10/10 파싱, 10/10 정본 스키마 통과.**
- 문법 없음: Qwen3-4B 9/10, Qwen2.5-7B 9/10, Qwen2.5-3B 3/10(코드펜스를 벗기면 8/10), EXAONE·Kanana 2종은 **0/10**
  (마크다운 요약이나 일반 텍스트로 답함). 파싱이 되더라도 정본 스키마 통과는 Qwen3 2/10, Qwen2.5-7B 8/10뿐이다.
- 결론: 소형 모델에서는 문법 제약이 **필수**다. 설계 5.1절 "세 겹 방어"의 1단이 그대로 유효하다.

### 4.4 문법 변환기 제어 문자 결함 (GO 조건 1)

- 현상: EXAONE 긴 입력 출력(`finish_reason=stop`, 400토큰)의 `summary`에 원시 개행이 들어 있어 `json.loads`가
  `Invalid control character`로 실패했다.
- 원인: llama-cpp-python 0.3.36의 Python `SchemaConverter`가 만드는 문자열 규칙이
  `char ::= [^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})`라서 `\x00-\x1F`를 막지 않는다. upstream llama.cpp
  `json-schema-to-grammar`는 `[^"\\\x7F\x00-\x1F]`를 쓴다.
- 우회 확인: 그 한 줄만 바꾼 문법(`run_llama.py --patch-control-chars`)으로 Kanana-2.1B와 Qwen3-4B를 다시 돌렸다.

| 모델 | 패치 문법 parse / schema / validator | 원래 출력과 동일 | p50 / p95 | 긴 입력 |
|---|---|---|---|---|
| kanana-1.5-2.1b | 10 / 10 / 3, 긴 입력 1 / 1 | **10/10 바이트 동일** | 16.6 / 19.3초 | 18.7초 |
| qwen3-4b-2507 | 10 / 10 / 9, 긴 입력 1 / 1 | **10/10 바이트 동일** | 46.7 / 59.7초 | 92.9초 |

- T25d 권고: `providers/json_grammar.py`가 디코딩 스키마에서 문법 문자열을 만들 때 이 규칙을 강제하고(또는 변환 결과의
  `char` 규칙을 검사해 다르면 실패), 단위 테스트로 고정한다. EXAONE은 이미 지웠으므로 패치 문법으로 그 긴 입력을 다시
  확인하지는 못했다 (8절 남은 문제).

### 4.5 결정성 (3.5절)

- **같은 프로세스 안 2회(grammar_a vs grammar_b): 6개 모델 모두 출력 차이 0/10건.**
- **다른 프로세스(패치 문법 재실행, 1~2시간 뒤): Kanana-2.1B, Qwen3-4B 모두 10/10 바이트 동일.** 패치는 원시 제어 문자를
  막는 것뿐이라 그런 문자를 내지 않은 출력은 바뀌지 않는다.
- 문법 없음 패스는 2회 측정하지 않았다 (go 판정과 결정성 목표가 문법 경로 기준이라서).
- 조건: 같은 빌드(0.3.36 Metal), `llm.reset()`으로 접두사 캐시 미사용, n_batch/n_ubatch 512, n_threads 4. T25d도 요청마다
  `reset()`(또는 같은 효과)을 하기를 권한다. 접두사 재사용을 켜면 prefill 분할이 앞 요청에 따라 달라진다.

### 4.6 두 번째 문법 패스가 느려진 원인 (지연 수치 해석)

grammar_b의 지연이 grammar_a보다 일관되게 컸다 (예: Kanana 31.6 → 18.1 tok/s, Qwen2.5-3B 29.0 → 21.1). 설계 5.3절 "문법
캐시"(같은 `LlamaGrammar`를 재사용)가 원인인지 가르기 위해 `probe_grammar_reuse.py`로 같은 입력에 [재사용 문법, 매번 새 문법,
문법 없음]을 6라운드 번갈아 돌렸다 (Kanana-2.1B, syn-06).

| 조건 | tok/s (라운드 0→5) | 출력 |
|---|---|---|
| 재사용 문법 | 32.0, 33.0, 35.1, 34.8, 34.7, 33.5 | 6회 모두 같음 |
| 매번 새 문법 | 32.9, 35.4, 34.0, 34.7, 35.0, 33.2 | 재사용 문법과 같음 |
| 문법 없음 | 50.8, 51.5, 51.7, 51.0, 49.5, 50.2 | 6회 모두 같음 |

- **문법 재사용은 감속 원인이 아니다.** 단독 실행에서는 감속이 재현되지 않았다. 본 측정의 grammar_b 감속은 측정과 겹친
  배경 부하(같은 시간대의 다운로드·변환, 새로 쓴 대용량 파일의 색인 등으로 추정, 확인하지 못함)로 본다. `pmset -g therm`에는
  열 경고 기록이 없었다.
- 그래서 go 판정은 **두 문법 패스 중 나쁜 값**도 함께 본다. Kanana는 나쁜 값(39.6초)도 60초 안이고, Qwen3는 나쁜 값이 65.0초다.
- 문법 오버헤드: 같은 단독 실험에서 문법은 토큰당 약 33% 느리다(50.8 → 34 tok/s). 본 측정의 문법 출력이 더 짧아서(평균 521
  대 905토큰) 건당 지연은 문법 쪽이 오히려 짧다.

### 4.7 MLX-LM 4bit 지연 비교 (3.2절, 1개 모델)

같은 10건, 같은 프롬프트, 자유 생성(greedy, max_tokens 1536). 비교 대상은 llama.cpp `none` 패스(Q4_K_M).

| Qwen3-4B-Instruct-2507 | p50 | p95 | 평균 출력 토큰 | 평균 tok/s | 피크 메모리 |
|---|---:|---:|---:|---:|---:|
| llama.cpp Q4_K_M (none) | 39.44초 | 49.05초 | 899.5 | 24.4 | RSS 4,912MB |
| MLX-LM 4bit | 28.25초 | 38.86초 | 1,039.1 | 35.5 | Metal 피크 2,943MB |

- MLX가 p50 기준 **28.4% 빠르다** (토큰당 처리량은 약 45% 높다). 설계 3.2절의 재검토 문턱("p50이 40% 넘게 빠르고 스키마
  제약 방법이 확인되면")에 **못 미친다.** 런타임은 llama.cpp를 유지한다.
- MLX 자유 생성의 첫 시도 준수율은 parse 9/10, schema 4/10, validator 3/10이고 주입도 따랐다. 스키마 제약 방법은 이번에
  확인하지 않았다.
- 피크 메모리는 측정 방식이 달라(RSS 대 Metal 할당 피크) 직접 비교하지 않는다.

### 4.8 품질 관찰 (go 판정 밖, T25e·T25h 참고)

실제 `AnalysisValidator` 기준 문법 패스의 고칠 수 없는 이슈(10건 중 건수):

| 모델 | validator 통과 | summary_sentence_count | evidence_ungrounded | language_invalid | 기타 |
|---|---:|---:|---:|---:|---|
| qwen3-4b-2507 | 9 | 1 | 0 | 0 | |
| qwen2.5-7b | 7 | 1 | 2 | 0 | |
| kanana-1.5-8b | 4 | 2 | 3 | 2 | |
| kanana-1.5-2.1b | 3 | 5 | 3 | 4 | |
| qwen2.5-3b | 3 | 6 | 4 | 0 | 한자 혼입 1 |
| exaone-3.5-2.4b | 2 | 1 | 5 | 5 | |

- `language_invalid`는 Kanana·EXAONE이 `language`에 `"한국어"`를 넣은 경우다. 디코딩 스키마에서 `language`를
  `pattern: "^[a-z]{2}$"`(또는 enum)으로 좁히면 문법이 막는다 (정본보다 엄격하므로 5.2절 규칙에 맞다). ds-2 후보.
- `summary_sentence_count`는 단계 나열형 문서(레시피, 하우투, 여행 코스)에서 요약이 5문장 이상이 되는 경우다. 프롬프트로 다룬다.
- `evidence_ungrounded`는 source_span을 바꿔 말한 경우다. 재요청 루프가 처리할 대상이다.
- 이 수치는 직접 쓴 짧은 문서 10건 기준의 참고값이다. 후보 선택(4.4절 규칙)은 T25c 골든 v2 dev와 recorded로 T25h에서 한다.
- 4.4절 규칙의 지연 문턱만 미리 보면: single p95 ≤ 60초를 dev 10건에서 넘는 후보는 Qwen2.5-7B(71.7초)이고, Qwen3-4B는
  4번 측정 중 2번 초과(59.31/64.99/59.74초, 검수 재현 60.10초), Kanana-1.5-8B는 46.2/54.9초로 안쪽이다. 긴 입력(약 4K 프롬프트) 1건은 Qwen3-4B 99초, Kanana-8B 85초, Qwen2.5-7B
  73초로 모두 60초를 넘는다.

## 5. 설계 대비 차이와 이유

1. **`pyproject.toml`에 `analyze-local` extra를 넣지 않았다.** extra 추가와 `uv.lock` 갱신, mypy override는 T25d 산출물이다
   (10.1절 표). T25b 범위는 버전 고정 결정까지라서 별도 venv에서 설치·측정했다. T25d에 넘길 값: `llama-cpp-python==0.3.36`,
   PyPI sdist 소스 빌드(Metal wheel 인덱스 미사용), `CMAKE_ARGS="-DGGML_METAL=on"` (2.1절).
2. **(정정) Metal wheel 인덱스는 있지만 0.3.36 wheel이 손상돼 쓸 수 없다** (3.3절 가정과 다름). 인덱스에 0.3.28~0.3.36 arm64 wheel이
   있으나 0.3.31~0.3.36은 zip CRC 손상으로 설치되지 않고, 손상 없는 가장 새 wheel은 0.3.30이다. 측정 빌드와 같은 0.3.36을 쓰기 위해
   소스 빌드를 기본 경로로 한다 (근거와 다시 볼 조건은 2.1절). 처음 보고서의 "인덱스 최신 0.3.5"는 사전순 정렬 오판이었다.
3. **Qwen3-4B-2507과 Kanana 2종은 공식 GGUF가 없어 직접 변환했다** (3.4절이 허용한 경로). 커뮤니티 변환본은 쓰지 않았다.
   변환 도구는 고정 버전 sdist에 들어 있는 llama.cpp 스크립트이고, 양자화는 `llama_model_quantize`(llama-quantize와 같은
   함수)다. imatrix는 쓰지 않았다.
4. **Kanana-1.5-8B는 `convert_hf_to_gguf.py --remote`와 q8_0 중간본을 썼다.** 16GB safetensors를 받고 f16 중간본(16GB)까지
   두면 디스크가 15GB 아래로 내려간다. `--remote`는 텐서를 HTTP range로 읽어 safetensors를 디스크에 두지 않는다. 다만 `main`
   브랜치만 읽으므로 변환 전후에 `main == c963a5f4`(고정 revision)를 확인했다(둘 다 일치). q8_0 → Q4_K_M 재양자화는 f16에서
   만든 Q4_K_M보다 품질이 약간 떨어질 수 있고 sha256도 다르다. 판정기로 쓸 T25g 전에 디스크 여유가 있을 때 f16 경로로 다시
   만들기를 권한다.
5. **Qwen2.5-7B 공식 GGUF가 2개 파일로 나뉘어 있다.** `LocalModelSpec`은 파일 하나(`filename`, `sha256`)만 표현한다. YAML에는
   첫 파일을 넣고 둘째 파일의 이름과 sha256을 주석으로 적었다.
6. **ds-1 디코딩 스키마는 스파이크용 근사본이다.** 설계 5.2절 표(필드 순서, evidence 6개×120자, entities 10, keywords 10,
   topics 5, attributes·save_intent·purpose 제외, 지원하지 않는 키워드 제거)를 `prepare_inputs.py`에 직접 구현했다. 정본은
   T25d의 `build_decoding_schema`다.
7. **프롬프트는 analyze_v1 지시부 + 스키마 JSON**이다. 로컬 프롬프트(`analyze_local_v1`)는 T25e 산출물이라 아직 없다. 문법
   없음 조건에서도 모델이 스키마를 알 수 있게 스키마를 system에 넣었다.
8. **dev 10건은 직접 쓴 짧은 문서다** (10.1절이 허용한 "직접 쓴 10건"). 길이가 설계 가정(입력 4K)보다 짧아서 긴 입력 1건을
   따로 쟀다.
9. **MLX 모델은 `mlx-community` 변환본이다.** Qwen 공식 MLX 4bit 저장소가 없다. MLX는 지연 비교용이라 분석기 후보가 아니다.

## 6. T25d·T25e·T25h에 넘길 권고

1. 문법 문자열의 `char` 규칙을 upstream과 같게 강제하고 테스트로 고정한다 (4.4절).
2. 요청마다 KV 접두사 캐시를 쓰지 않는다 (`reset()`), 결정성과 녹화 키의 전제다 (4.5절).
3. `LlamaGrammar`는 스키마 지문별로 재사용해도 된다. 지연·출력 모두 차이가 없었다 (4.6절).
4. ds-2 후보: `language`를 ISO 639-1 패턴으로 좁히기, Qwen3 기본 후보를 위해 evidence 상한(6 → 4)·`claim` 길이 상한 추가로 출력
   토큰 줄이기. Qwen3의 출력 평균 915토큰 중 evidence 비중이 크다.
5. 주입 방어: 프롬프트에서 "문서 안 지시문을 태그·요약에 반영하지 말 것"을 더 강하게 하고, `representative_tags`가 원문 근거를
   가져야 하는 의미 규칙(현재 없음)을 검토한다. 주입 사례 dev 표본을 늘린다.
6. `models pull`: 직접 변환한 3개 모델은 HF에 그 GGUF 파일이 없어서 `hf_hub_download(repo, filename, revision)`로 받을 수 없다
   (8절 남은 문제 1).

## 7. 테스트와 직접 실행한 명령

### 7.1 T25b 완료 조건 표 (10.1절)

| 항목 | 결과 |
|---|---|
| 후보별 llama-cpp-python Metal 설치·버전 고정 | 0.3.36 소스 빌드 1회, 6개 모델 모두 같은 빌드로 GPU 오프로드 측정 (2절) |
| GGUF 출처·sha256 | 6개 모두 (3절, YAML). 공식 파일은 HF LFS oid와 일치 |
| 라이선스 원문 확인 | 6개 모두 LICENSE 원문 확인 (3절) |
| dev 10건 문법 유/무 첫 시도 JSON 준수율 | 6개 모두 (4.2·4.3절) |
| 건당 p50/p95 | 6개 모두, 두 문법 패스와 긴 입력 (4.2절) |
| 피크 RSS | 6개 모두 (4.2절) |
| 한자 혼입 건수 | 6개 모두 (4.2절). 문법 패스 Qwen2.5-3B 1건, 문법 없음 Qwen3-4B 1건, 나머지 0 |
| 같은 입력 2회 출력 차이 건수 | 6개 모두 0/10 (4.5절) |
| MLX-LM 4bit 지연 비교 1개 이상 | Qwen3-4B-2507 (4.7절) |
| go/no-go 판정 | GO (조건부) (0절) |
| 디스크 관리 | 모델을 하나씩 받고 측정 후 지웠다. 참고 후보 2개는 측정 시점 여유 22~23GB(15GB 이상)라 건너뛰지 않았다. 단계 경계에서 기록한 최저 여유는 18GB(Kanana 2.1B 다운로드 직후)였고, Kanana-8B 변환 중 q8_0와 Q4_K_M이 함께 있던 순간은 약 17GB로 추정한다 (직접 재지는 않음) |

### 7.2 측정 명령 (스파이크 venv: `P=/Users/minjun/orca/workspaces/dc2/models/spike-venv/bin/python`)

```bash
python3 scripts/spikes/data/build_synthetic_dev.py                      # 합성 문서 10건
uv run python scripts/spikes/prepare_inputs.py                          # 스키마·프롬프트 (프로젝트 환경, src 읽기만)
$P -I scripts/spikes/fetch_model.py --repo Qwen/Qwen2.5-3B-Instruct-GGUF \
   --revision 7dabda4d13d513e3e842b20f0d435c732f172cbe --dest $M/gguf/qwen2.5-3b-instruct-q4km \
   qwen2.5-3b-instruct-q4_k_m.gguf LICENSE README.md
$P -I scripts/spikes/run_llama.py --model-id qwen2.5-3b-instruct-q4km --model-path <gguf>
T25B_MODELS_DIR=$M T25B_SPIKE_PY=$P T25B_CONVERT=<sdist>/vendor/llama.cpp/convert_hf_to_gguf.py \
   scripts/spikes/run_all.sh exaone kanana2b qwen3 mlx qwen7b kanana8b      # 종료 0
$P -I scripts/spikes/probe_grammar_reuse.py --model-id kanana-1.5-2.1b-instruct-q4km --model-path <gguf>
$P -I scripts/spikes/run_llama.py --model-id <id> --model-path <gguf> --patch-control-chars \
   --passes grammar_a,long --out scripts/spikes/results/<id>.patched.json  # Kanana-2.1B, Qwen3-4B
uv run python scripts/spikes/analyze_results.py                         # 채점, results/summary.json
```

측정 스크립트(`run_llama.py`, `run_mlx.py`, `probe_grammar_reuse.py`)는 `HF_HUB_OFFLINE=1`을 강제하고 로컬 파일 경로로만 모델을
연다. 네트워크는 `fetch_model.py`, `run_all.sh`의 HF API 조회, Kanana-8B `--remote` 변환에서만 썼다 (전부 HF 공식 저장소).
합성 문서 원문은 기기 밖으로 나가지 않았다.

### 7.3 기본 설치 회귀 확인 (`uv sync --locked`, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run python -c "import importlib.util as u; print(u.find_spec('llama_cpp'))"` | `None` (기본 설치에 llama_cpp 없음) |
| `uv run pytest` | PASS — 928 passed, 3 deselected, 기존 경고 1건 (T24 loop2와 같은 수) |
| `uv run ruff check src tests` | PASS — All checks passed |
| `uv run mypy src` | PASS — no issues found in 78 source files |
| `uv run jupjup eval validate` | PASS — 인제스트 sources 80, annotations 80 (dev 48, test 32) |
| `uv run jupjup eval run --mode mock --split dev` | 종료 0. Recall@10 0.9620, Recall@5 0.9419, MRR@10 0.9958, nDCG@10 0.9795 |
| `uv run jupjup eval run --mode mock --split test` | 종료 0. 0.9420 / 0.9281 / 0.9867 / 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev` | 종료 0. 0.9712 / 0.9495 / 1.0000 / 0.9860 |
| `uv run jupjup eval run --mode recorded --split test` | 종료 0. 0.9720 / 0.9541 / 0.9911 / 0.9801 |
| `uv run jupjup eval ingest --mode mock --split dev|test|all` 각 2회 | 6회 모두 종료 0, 회귀 게이트 OK. 두 실행의 JSON·Markdown 6개 파일 `cmp` **바이트 동일** |

- 검색 수치는 T24 loop2 리포트 3.1절 값과 같다 (수치 무회귀). 리포트는 스크래치 디렉터리(`--out`)에 써서 저장소의
  기준선·리포트 파일을 건드리지 않았다.
- `git diff --stat 695cb6c -- src data tests`: 변경 0. `src/jupjup/search`, `src/jupjup/query`, 검색 기준선,
  `data/recordings`, embeddings 파일은 바꾸지 않았다. 새 파일은 `config/`와 `scripts/spikes/`뿐이다.

## 8. 남은 문제

1. **직접 변환한 GGUF의 배포 경로가 없다.** Qwen3-4B-2507, Kanana-1.5 2.1B/8B의 최종 GGUF는 HF에 없으므로 설계 3.4절의
   `models pull`(hf_hub_download)로 받을 수 없다. 선택지: (a) `models pull`이 고정 revision safetensors를 받아 같은 도구 버전으로
   변환·양자화하고 sha256을 검증 (torch 등 무거운 의존성, 변환 결정성 확인 필요), (b) 사용자가 승인한 저장 위치에 변환본을 두고
   그 경로에서만 받기, (c) 공식 GGUF가 있는 모델만 기본 후보로 허용. PM·사용자 결정이 필요하다. 현재 두 후보 파일은
   `/Users/minjun/orca/workspaces/dc2/models/gguf/`에 남겨 두었다.
   → T25d 처리(임시): 세 모델을 YAML에 `source: local_convert`로 표시하고, `models pull`은 받지 않고 둘 위치와 sha256만 안내한다
   (종료 2). 실행 시 sha256 검증은 같다. 배포 경로 결정은 여전히 PM·사용자 몫이다.
2. **분할 GGUF 표현** (Qwen2.5-7B): `LocalModelSpec`에 파일 목록(이름·sha256 쌍)을 받을지, 받은 뒤 하나로 합칠지 T25d가 정한다.
   → T25d 처리: `extra_files`(이름·sha256 목록)로 표현하고 모든 파일을 검증한다. 합치지 않는다.
3. **제어 문자 결함 우회의 실제 재현 확인**: 실패했던 EXAONE 긴 입력을 패치 문법으로 다시 돌리지 못했다 (디스크 관리로 파일 삭제).
   패치는 문법상 원인을 직접 막지만, T25d 테스트에서 개행을 강제로 유도하는 입력으로 확인하기를 권한다.
   → T25d 처리: 실제 Kanana-2.1B에서 줄바꿈 토큰을 `logit_bias +50`으로 밀었을 때 0.3.36 원래 문법은 원시 줄바꿈을 내고 JSON이
   깨지며(`finish=length`), 보정 문법은 막고 파싱된다는 것을 `local_llm` 테스트로 고정했다 (EXAONE 긴 입력 자체는 다시 돌리지 않았다).
4. **주입 저항**: 문법 패스에서 6개 중 5개 모델이 주입 태그를 출력했다. 현재 프롬프트로는 AC-L11을 못 넘는다 (GO 조건 2).
5. **기본 후보 Qwen3-4B는 지연 문턱을 4번 측정 중 2번 넘었다** (p95 59.31/64.99/59.74초, 검수 재현 60.10초, 긴 입력 92.9~99.3초).
   ds-2(출력 길이 축소) 없이는 4.4절 지연 문턱에서 빠질 가능성이 높다. 그때는 Kanana-1.5-2.1B가 문턱을 넘는 유일한 상업 가능 4B 이하 후보가 된다.
6. **지연 수치의 잡음**: 본 측정 중 배경 부하로 두 번째 문법 패스가 최대 40% 느렸다 (4.6절). T25h의 live 벤치는 다른 무거운 작업
   없이, 같은 입력을 여러 번 돌려 중앙값을 쓰기를 권한다.
7. **피크 RSS 해석**: macOS RSS가 Metal 공유 버퍼를 얼마나 포함하는지 확인하지 않았다. 모델 파일 크기 + 약 1~2GB 수준이라
   대체로 포함된 것으로 보이지만, 24GB 동시 적재 계획(4.1절)은 T25h에서 `vmmap`/Activity Monitor 기준으로 다시 재야 한다.
8. **Kanana-1.5-8B Q4_K_M은 q8_0 재양자화본이다** (5절 4). 판정기로 쓰기 전에 f16 경로로 다시 만들어야 한다.
9. 문법 없음 조건의 결정성, Kanana·EXAONE의 MLX 지연, imatrix 양자화 비교는 측정하지 않았다 (범위 밖 또는 go 판정과 무관).
