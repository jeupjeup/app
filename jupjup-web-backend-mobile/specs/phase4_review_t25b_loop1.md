# Phase 4 최종 검수: T25b 런타임·모델 스파이크 (go/no-go), Loop 1/3

- **점수:** 95 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 30 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 M1은 **T25d 착수 전에** 보고서 2절·5절 2번을 정정하고 설치 경로를 다시 정하는 것을 조건으로 권한다 (PM이 T25d 브리프에 넣으면 된다). L1~L4는 T25d 때 같이 정리해도 된다.
- **검수 대상:** `PM` 병합 커밋 `344034b` (구현 `0e706fb spike: T25b local runtime and model go/no-go measurements`), 직전 검수 대상 `0b80f1e`
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드는 고치지 않았다. 재현 실험은 스크래치 디렉터리(스크립트 사본, 별도 venv), `var/review.db`에서만 했다.
- **범위 밖:** `src/` 수정, T25c~T25h. 사람 검수 미완료(`ai_draft_unreviewed`)는 감점하지 않았다. 주입 저항·제어 문자 결함은 스파이크가 **찾아서 보고한 것**이라 결함이 아니라 성과로 본다 (해결은 T25d·T25e).

## 0. 한 줄 판정

10.1절 T25b 완료 조건을 **직접 재현했다.** 남아 있는 두 후보(Kanana-1.5-2.1B, Qwen3-4B-2507)를 같은 스파이크 venv로 다시 돌린 결과, 커밋된 원자료와 **출력 31건이 모두 바이트 단위로 같았고**(다른 프로세스, 몇 시간 뒤), Kanana의 문법 제약 첫 시도 JSON 파싱은 10/10, single p95는 18.13초로 go 조건(파싱 100%, p95 ≤ 60초)을 충족한다. GGUF sha256(로컬 2개 직접 해시, 공식 4개 파일은 HF LFS oid), 6개 저장소 LICENSE 원문 sha256과 핵심 조항, 원자료 재채점(`summary.json` 바이트 동일), 0.3.36 변환기의 `char` 규칙 결함과 EXAONE 긴 입력의 실제 파싱 실패까지 보고서와 일치한다. `src`·`data`·`tests`·`pyproject.toml`·`uv.lock` diff는 0줄이고, 기본 설치에는 `llama_cpp`가 없으며, 게이트·eval·인제스트 결정성은 직전 검수와 같다.
**감점 사유는 하나가 크다:** 보고서는 "Metal wheel 인덱스 최신이 0.3.5라서 쓸 수 없다"고 했지만 **사실이 아니다.** 인덱스에는 2026-10-01부터 0.3.36 arm64 wheel이 있다. 다만 직접 받아 보니 0.3.36·0.3.35 wheel은 zip CRC가 깨져 설치되지 않고, 0.3.30 wheel은 멀쩡하다. "0.3.36은 소스 빌드" 결론은 우연히 맞지만 근거가 틀렸고, T25d의 설치 경로 결정에 필요한 대안(정상 wheel이 있는 버전)이 빠졌다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | 종료 0. `pytest --co` 기준 **944/947 collected (3 deselected)**. 경고 1건(기존 Starlette/httpx). 보고서 7.3절의 928은 스파이크 기준 커밋 `695cb6c`(T25a 이전) 수치라 병합 상태 944와 다른 것이 맞다 |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 78 source files |
| `uv run ruff check scripts --exclude scripts/spikes` | All checks passed! (기존 스크립트) |
| `uv run ruff check scripts/spikes` | **10 errors** (E501 9건, RUF100 1건) → L1 |
| `uv run python -c "importlib.util.find_spec('llama_cpp'), find_spec('mlx_lm')"` | `None None` (기본 설치에 없음) |
| `grep -rn "llama_cpp\|mlx" src` | 0건 |
| `git diff --stat 0b80f1e 344034b -- src data tests pyproject.toml uv.lock` | **0줄**. `git diff --stat 695cb6c 0e706fb -- 같은 경로`도 0줄 |
| `pyproject.toml` optional-dependencies / `uv.lock`의 `llama` | `embed, rerank, local-models` (변경 없음) / 0건 |
| `config/analyzer_profiles.yaml` 구조 검사 (스크래치 스크립트) | 모델 6개, 키 = model_id, sha256 64hex, revision 40hex, 키 집합이 설계 6.2절 `LocalModelSpec`과 같음, 프로필·판정기 참조 무결, `default_profile: mock` |
| `grep -rn analyzer_profiles src` | 0건 (아직 어떤 코드도 읽지 않는다는 주석과 같다) |

### 1.2 T25b 완료 조건 재현

| 완료 조건 (10.1절) | 직접 확인 | 판정 |
|---|---|---|
| llama-cpp-python Metal 설치·버전 고정 | 스파이크 venv `python -I -c "import llama_cpp"` → `0.3.36 arm64 True`, `MTL0 (Apple M5)`, `recommendedMaxWorkingSetSize = 19069.67 MB` | 충족. 단 설치 경로 근거 오류 → **M1** |
| GGUF 출처·sha256 | 로컬 `shasum -a 256`: Kanana-2.1B `5baf76ee…ea60`, Qwen3-4B `f51854d0…b63f` (YAML과 일치). HF `paths-info` API LFS oid: EXAONE `1660a379…cdbf`, Qwen2.5-3B `626b4a66…5c62d`, Qwen2.5-7B 00001 `dfce12e3…80db`·00002 `539cf93f…d72a` (YAML·주석과 일치, 크기도 일치). Qwen3·Kanana 2종의 고정 revision이 HF에 실제로 있고 safetensors 파일 목록이 보고서와 같음 | 충족. Kanana-8B 변환본은 지워져 해시 재현 불가 (보고서에 명시) |
| 라이선스 원문 확인 | 6개 저장소 고정 revision의 `LICENSE`를 받아 sha256: Qwen3·Qwen2.5-7B `832dd9e0…e92e`, Kanana 2종 `d1ee8126…df57`, EXAONE `294fd639…f67e`, Qwen2.5-3B `ef52482b…f0d9`. EXAONE 3.1절 "Model, Derivatives, or **Output** … any commercial purposes" 금지, Qwen2.5-3B 2.a "FOR NON-COMMERCIAL PURPOSES ONLY" 확인 | 충족. `license_commercial_ok` 값 모두 맞음 |
| dev 10건 문법 유/무 첫 시도 JSON 준수율 | 재현 실행 Kanana `grammar_a` parse 10/10, `none` 0/10 (보고서와 같음). 커밋 원자료 재채점(`analyze_results.py` 사본) 6개 모델 표가 4.2절과 같음 | 충족 |
| 건당 p50/p95 | 재현: Kanana 문법 **14.71 / 18.13초**, 없음 18.93 / 27.10초, 긴 입력 18.12초. Qwen3 문법 **45.28 / 60.10초** | 충족. Qwen3는 보고서 말대로 경계선(이번엔 60.10초로 문턱 0.1초 초과) |
| 피크 RSS | 재현: Kanana 3,728MB, Qwen3 4,886MB (보고서 3,734 / 4,912MB와 1% 이내) | 충족 |
| 한자 혼입 건수 | 재채점 결과 문법 패스 Qwen2.5-3B 1건, 없음 Qwen3 1건, 나머지 0 (보고서와 같음) | 충족 |
| 같은 입력 2회 출력 차이 건수 | 커밋 원자료 grammar_a vs grammar_b 6개 모델 모두 0/10. **재현 실행(다른 프로세스·몇 시간 뒤) vs 커밋 원자료: Kanana grammar_a 10/10, none 10/10, long 1/1, Qwen3 grammar_a 10/10 바이트 동일** | 충족 (보고서 주장보다 강한 증거) |
| MLX-LM 4bit 지연 비교 1개 이상 | `summary.json` `_mlx`: mlx-lm 0.29.1, p50 28.25 / p95 38.86초, parse 9 / schema 4 / validator 3. 스파이크 venv에 `mlx_lm-0.29.1` 설치 확인 | 충족 (재실행은 모델을 지워서 하지 않음) |
| go/no-go 판정 | 위 재현으로 Kanana-1.5-2.1B가 go 조건 충족. "조건부 GO"와 조건 3개(제어 문자, 주입 저항, Qwen3 지연)는 근거와 맞다 | 충족 |

### 1.3 보고서 주장 교차 확인

| 주장 | 확인 방법 | 결과 |
|---|---|---|
| 0.3.36 `SchemaConverter`의 `char` 규칙이 제어 문자를 허용 | 스파이크 venv에서 `SchemaConverter` 문자열 스키마 변환 출력 | `char ::= [^"\\] \| "\\" (…)` — `\x00-\x1F` 미차단 확인 |
| EXAONE 긴 입력이 문법을 받고도 파싱 실패 | 원자료 `json.loads` | `finish=stop`, 400토큰, `Invalid control character at: line 1 column 142`. 원시 `\n\n`이 summary 안에 있음 (주입 지시까지 따른 출력) |
| 패치 문법 출력이 원래 출력과 바이트 동일 | `*.patched.json` vs `*.llama.json` | Kanana·Qwen3 grammar_a 10/10, long 1/1 동일 |
| 주입: 문법 6개 중 5개가 따름 | `summary.json` `injection_followed` | Kanana-8B만 False, 나머지 True |
| `max_tokens` 도달 (없음 패스 Kanana-2.1B 1, Qwen2.5-3B 1, Kanana-8B 2) | `summary.json` `finish_length` | 같음 |
| grammar_b 감속 (Kanana 31.6 → 18.1 tok/s 등) | `summary.json` | 같음 |
| `summary.json`, `inputs.json`, `synthetic_dev_v1.jsonl`이 스크립트로 재생성됨 | `scripts/spikes` 사본에서 세 스크립트 재실행 후 `cmp` | **3개 모두 바이트 동일** (`prepare_inputs.py`는 사본 위치 때문에 프롬프트 경로만 바꿔 실행) |
| **Metal wheel 인덱스 최신이 0.3.5** | 인덱스 HTML, `gh api releases/tags/v0.3.36-metal`, wheel 다운로드 후 `zipfile` 검사 | **틀림.** 0.3.30~0.3.36 `py3-none-macosx_11_0_arm64` wheel이 있고 0.3.36은 2026-10-01 05:50Z 게시. 단 0.3.36(sha256 `64c98e6a…7023`)·0.3.35는 `Bad CRC-32`(0.3.36은 54개 멤버 손상), `uv pip install` 실패. 0.3.30은 `testzip()` 정상 → M1 |
| 합성 dev에 개인 데이터 없음 | 10건 원문 훑기, URL·전화·주민번호 패턴 grep | 가상 인물·가게·도시, 패턴 0건 |
| 커밋 파일에 로컬 절대 경로 | `grep -rn /Users/ scripts/spikes config` | `run_all.sh` 주석 예시 1곳뿐 (무해) |

### 1.4 검색·인제스트 무회귀

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval validate` | 종료 0. 인제스트 sources/annotations 80/80 (dev 48, test 32), 플랫폼군 분포 이전과 같음 |
| `eval run --mode mock --split dev` | PASS. R@10 0.9620, R@5 0.9419, MRR 0.9958, nDCG 0.9795, cat min 0.8838 |
| `eval run --mode mock --split test` | PASS. 0.9420 / 0.9281 / 0.9867 / 0.9589 / 0.7812 |
| `eval run --mode recorded --split dev` | PASS. 0.9712 / 0.9495 / 1.0000 / 0.9860 / 0.8894 |
| `eval run --mode recorded --split test` | PASS. 0.9720 / 0.9541 / 0.9911 / 0.9801 / 0.8900 |
| `eval ingest --mode mock --split dev\|test\|all` 2회 (`--out` 스크래치) | 6회 종료 0, 게이트 통과. **6개 파일 `cmp` 바이트 동일**. all: first 0.925, final 1.0, injection 1.0 |

검색 수치는 T25a 검수 1.3절과 소수점 4자리까지 같다. `src/`가 직전 검수 대상과 같으므로 서비스 경로의 네트워크 부재(AC-L8 전제)·mock 결과 불변도 그대로다.

### 1.5 CLI 경계값 (`seed load --db var/review.db` → u_alice 160, u_bob 30, u_carol 10. `search --db var/review.db --now 2026-10-15T12:00+09:00 --json`)

| 질의 | mock | recorded | 비고 |
|---|---|---|---|
| `성수동 카페` (회귀) | 블로그·지도 캡처·유튜브 성수 카페 상위 10건 | 지도 캡처·블로그·카톡 성수 상위 10건 | 정상 |
| `성슈동 카페` (오타) | 성수 카페 상위, 익선동 한옥 카페 2위 (약한 과잉 완화, 기존) | `EMBEDDING_CACHE_MISS`, 종료 2 | 녹화본 밖 질의 미스는 기존 동작 |
| `''` (빈 문자열) | `INVALID_QUERY` 1~200자, 종료 2 | 같음 | 정상 |
| `!!!@@@###` | `INVALID_QUERY` 검색할 단어 없음, 종료 2 | 같음 | 정상 |
| 200자 초과 | `INVALID_QUERY`, 종료 2 | 같음 | 정상 |
| `React hooks 정리` (영어 혼합) | 0건 | 캐시 미스 | 기존 동작 |
| `인스타 --platform instagram` (필터 전용) | instagram만 10건 | 같음 | 요청 잠금 정상 |
| `유튜브 영상 --platform blog` (충돌) | 0건 | 0건 | 요청 필터가 이김. 과소 완화 없음 |
| `화성 우주정거장 레시피` (없는 대상) | 0건 | 캐시 미스 | 거짓 결과 없음 |
| `작년 여름 제주 여행` | 제주 관련 8건 | 캐시 미스 | 정상 |
| `u_carol` `성수동 카페` | u_carol 저장물 1건만 | 같음 | 사용자 격리 정상 |
| 없는 사용자 `u_nobody` | 안내 문구 + 빈 결과 JSON, 종료 0 | 같음 | 기존 동작 |

모두 T25a 검수와 같은 동작이다 (`src/` 변경 0줄과 일치).

## 2. 피드백 (심각도 순)

### 중간

**M1. Metal wheel 인덱스에 대한 사실 오류와 빠진 대안** — `specs/phase2_t25b_spike_report.md:56`, `:234-235`, `:233` (T25d에 넘길 값)
- 현상: "인덱스의 최신 wheel은 0.3.5(2024-12)라서 Qwen3를 모른다. 3.3절의 인덱스 지정은 쓸 수 없고 소스 빌드가 기본 경로다." 실제 인덱스(`…/whl/metal/llama-cpp-python/`)에는 0.3.30~0.3.36 arm64 `py3-none` wheel이 있고, 0.3.36은 2026-10-01 게시라 스파이크 당시에도 있었다. 버전 문자열을 사전순으로 정렬하면 `0.3.5`가 `0.3.36`보다 뒤에 와서 생긴 오판으로 보인다.
- 직접 확인한 사실: 0.3.36·0.3.35 wheel은 zip CRC 손상으로 설치되지 않는다 (`uv pip install` → `Invalid zip file structure`). 0.3.30 wheel은 정상이다.
- 영향: 결론(0.3.36은 소스 빌드)은 맞지만 근거가 틀렸다. T25d가 이 문장을 그대로 `data/models/README.md`에 옮기면 사용자는 Command Line Tools·cmake 빌드를 필수로 알게 된다. "버전 고정"은 T25b 완료 조건의 첫 항목이고, 빌드 방식(소스 vs wheel)은 바이너리가 달라 결정성·녹화 지문(`recording_model_id`, llama-cpp-python 버전 기록, AC-L15)과도 이어진다.
- 조치 (T25d 착수 전): 보고서 2절과 5절 2번을 "인덱스에 0.3.36 wheel이 있으나 손상(CRC)되어 설치 불가, 0.3.30은 정상"으로 고치고, (a) 0.3.36 소스 빌드 유지, (b) 정상 wheel이 있는 버전(예: 0.3.30)으로 고정하고 Kanana·Qwen3 dev 10건 출력·지연을 다시 확인하는 것 중 하나를 PM·사용자가 정하게 한다. 어느 쪽이든 T25d `models doctor`가 빌드 방식(wheel/소스)을 출력하게 하기를 권한다.

### 낮음

**L1. 스파이크 스크립트 ruff 미통과** — `scripts/spikes/run_llama.py:30` (RUF100 쓰지 않는 `noqa`), `scripts/spikes/convert_quantize.py:38`, `scripts/spikes/probe_grammar_reuse.py:8`, `scripts/spikes/data/build_synthetic_dev.py:33,67,69,70,84,87,165` (E501)
- 공식 게이트(`src tests`) 밖이라 크게 감점하지 않았지만, 같은 저장소의 다른 `scripts/`는 통과한다. 커밋한 스크립트라면 같은 규칙을 지키거나 `pyproject.toml`에서 `scripts/spikes`를 명시적으로 제외하는 편이 낫다.

**L2. 측정 드라이버가 자기 완결적이지 않다** — `scripts/spikes/run_all.sh:39-55`
- `exaone`, `kanana2b`, `qwen3` 단계는 GGUF나 safetensors가 `$M/gguf`·`$M/hf`에 이미 있다고 가정하고, Qwen2.5-3B는 단계 자체가 없다. 이 파일들을 받은 명령은 보고서 7.2절에 Qwen2.5-3B 한 줄 예시만 있고 나머지는 저장소 밖 로그(`$M/logs/fetch.jsonl`)에만 남는다. T25h에서 측정을 다시 하려면 이 받기 단계가 스크립트에 있어야 한다.

**L3. `fetch_model.py`가 기대 sha256과 비교하지 않는다** — `scripts/spikes/fetch_model.py:36-38`
- 받은 파일의 sha256을 출력만 한다 (처음 고정하는 스파이크 용도로는 맞고, 공식 파일은 LFS oid와 대조돼 있다). T25d의 `models pull`은 설계 3.4절대로 YAML sha256과 비교하고 다르면 지워야 한다. 이 스크립트를 그대로 옮기지 않도록 T25d 브리프에 적어 둔다.

**L4. Qwen3 기본 후보 지연이 재현에서도 문턱을 넘었다** — `specs/phase2_t25b_spike_report.md:13`, `:337`
- 재현 p95 60.10초 (보고서 59.31 / 64.99 / 59.74초). go 판정은 Kanana로 충족하므로 판정은 바뀌지 않지만, 보고서의 "경계선" 표현보다 "4번 측정 중 2번 문턱 초과"가 더 정확하다. T25e의 ds-2(출력 길이 축소) 없이는 4.4절 지연 문턱에서 빠질 가능성이 높다는 점을 PM이 사용자에게 알려 두기를 권한다.

### 참고 (감점 없음)

- **주입 저항(GO 조건 2)과 제어 문자 결함(GO 조건 1)**: 보고서가 재현 가능한 근거와 함께 짚었고, T25d(`json_grammar.py`의 `char` 규칙 강제·테스트)와 T25e(프롬프트, 태그 근거 규칙)에 넘긴 권고가 구체적이다. EXAONE 긴 입력 실패 출력은 주입 지시도 따른 것이라 두 문제가 함께 나타났다.
- **직접 변환 GGUF의 배포 경로 부재**(보고서 8절 1)와 **분할 GGUF 표현**(8절 2)은 설계가 정하지 않은 부분이라 결함이 아니라 PM·사용자 결정 사항이다. Q-LA 목록에 추가하기를 권한다.
- 승격 후보 Kanana-8B는 q8_0 재양자화본이라는 점을 YAML 주석과 보고서 양쪽에 적어 두었다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 완료 조건 10개 모두 산출, 핵심 수치(파싱률, p95, RSS, 결정성, sha256, 라이선스)를 직접 재현해 일치, go 판정 근거 타당. M1 사실 오류(설치 경로 근거와 대안 누락) −3 |
| 안전성 | 30 / 30 | `src`·의존성 변경 0, 기본 설치에 `llama_cpp` 없음, 측정 스크립트는 `HF_HUB_OFFLINE=1`과 로컬 경로만 사용, 네트워크는 HF 공식 저장소 받기와 고정 revision 확인에만 사용, Kanana-8B `--remote`는 변환 전후 `main == 고정 revision` 검사, 모델 가중치 미커밋, 합성 데이터에 개인 정보 없음, 라이선스의 출력물 제약(EXAONE)까지 짚음. L3은 스파이크 범위에서 정당 |
| 유지보수성 | 28 / 30 | 스크립트 역할 분리가 분명하고 결과 재생성이 바이트 동일, 설계 대비 차이 9개를 이유와 함께 기록, YAML이 설계 6.2절 구조와 일치. L1 ruff −1, L2 측정 받기 단계 누락 −1 |
| **합계** | **95 / 100** | **PASS** |

## 4. 재검수 조건

PASS라 재검수는 필요 없다. 다만 T25d 브리프에 아래를 넣는다.
1. M1: 보고서 2절·5절 2번 정정, 그리고 0.3.36 소스 빌드 대 정상 wheel 버전 중 고정 방식을 PM·사용자가 확정.
2. L3: `models pull`은 YAML sha256과 비교해 다르면 파일을 지우고 실패.
3. 보고서 6절 1~3번 권고(`char` 규칙 강제, 요청마다 `reset()`, 문법 캐시 허용)를 테스트로 고정.
