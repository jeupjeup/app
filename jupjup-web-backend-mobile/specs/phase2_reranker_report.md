# Phase 2 리랭커 사이클 Loop 1 — 크로스 인코더 리랭커(단계 1) 구현 보고서

- 작성: Codex-Primary. Codex가 사용 한도에 걸려 중단된 뒤 Claude가 같은 지침으로 이어서 완료했다.
- 기준일: 2026-10-30
- 브랜치: `ultra-penguin/phase-2-reranker` (기준 커밋 `c7da005`, Loop 3 병합 이후)
- 설계: `specs/design_reranker_query_assist.md` 단계 1 (T30~T36). Q-RA1~9는 PM 추천 기본값을 따른다.
- **결론: 구현은 끝났고 채택 판정은 `REJECT`다.** 리랭커 기본값은 꺼 둔 채(`cross_rerank.enabled=false`)
  구현만 남긴다. recorded dev에서 A1이 A0보다 나빠지고(Recall@10 −0.0315, nDCG 1승 9패), 개선 요건을
  만족하는 경로가 없다. 지연(mps)과 운영 기준은 통과했다.

---

## 1. 선행 작업 (Phase 4 cycle 2 Loop 3 후속)

| 항목 | 처리 |
|---|---|
| F1 anchored tail 비단조 | `service.py`에서 `utility <= anchor` 버리기 조건을 없앴다. 꼬리 후보는 primary 결과 뒤에서만 정렬된다(버리지 않고 순위만 제한). mock `q_0176` 회귀(`test_q0176_stronger_lexical_tail_is_rank_limited_not_discarded`)와 recorded 단조성 테스트(`test_anchored_tail_acceptance_is_monotonic_in_relevance`)를 추가했다 |
| F1~F6 이관 | `specs/known_issues.md` 6절에 상태별로 기록했다. 이번 결과는 7절에 새로 추가했다 |

## 2. T번호별 구현

| T | 내용 | 파일 |
|---|---|---|
| T30 기준 고정과 A/B 러너 | 실제 A0 = 현재 구현 HEAD + `cross_rerank.enabled=false`(기준선 파일은 바꾸지 않음). `c7da005` 바이트 정본이 아니므로, F1 수정이 들어간 HEAD와 리랭커만 비교한다. 쌍 부트스트랩(seed 20261030, 1,000회)과 정확 부호 검정, `ABComparison`(전체·challenge 부분집합·카테고리 차이·1위 변경·리랭크 상태), `decide_reranker`(10.1절 1~7번), `LatencyReport`, `jupjup eval ab` | `eval/ab.py`, `cli.py` |
| T31 지연 스파이크 | `BgeCrossEncoderReranker`(지연 import, mps/cpu, mps fp16, torch 없이 호출 가능한 제네릭 항등 함수로 원 로짓 유지), `jupjup bench rerank` | `providers/rerank_bge.py`, `eval/rerank_tools.py` |
| T32 제공자와 설정 | `Reranker` Protocol(`score_logits`, `model_id`, `revision`), `MockReranker(delay_ms, fail_on)`, `RecordingReranker`, `RecordedReranker`, 에러 계층 `RerankerError/RerankerUnavailable/RerankCacheMiss`, `RerankModelSettings`(revision 고정 `953dc6f…`), extra `[rerank]`, `[local-models]`, pytest 마커 `rerank`, 컨테이너 조립 | `providers/rerank.py`, `domain/errors.py`, `config.py`, `container.py`, `pyproject.toml` |
| T33 입력 텍스트와 녹화 | `build_rerank_query`(`residual_text` = 기간·플랫폼·유형 span을 뺀 q₀, 비면 `original_terms`), `build_rerank_text`(제목·대표 태그·요약·세부 태그 핵심·메모·본문, 600자, 플랫폼·유형·시각·작성자·OCR 제외), `jupjup rerank record`, 녹화본 커밋 | `search/cross_rerank.py`, `eval/rerank_tools.py`, `data/recordings/` |
| T34 통합과 게이트 v3 | 창 선택(전역 `N_global` + 계획별 `k_plan`, `N_max` 절단), 단일 비행 실행기(busy/timeout/error → v2 폴백, 캐시 미스는 그대로 올림), `RelevanceScorer.apply_cross`(v3 R, 의미 계열 semantic·cross는 한 계열), 게이트 v3(프로필별 cross floor, low-signal floor, 창 밖 문서는 corroborated + `R_unscored ≥ τ_unscored`만, 창 안 문서 뒤 정렬), `degraded_reasons: reranker_skipped:<사유>`, 응답 `rerank_status`, `timing_ms.cross_rerank`, explain `rerank` 블록 | `search/cross_rerank.py`, `search/relevance.py`, `search/gate.py`, `search/service.py`, `search/types.py`, `index/registry.py`(`documents`) |
| T35 calibration과 튜닝 | recorded dev만 사용. 4절 참고 | `config.py`(`CrossRelevanceSettings` v3-cross.2) |
| T36 A/B와 판정 | live 검색 벤치(`jupjup bench search`), recorded dev 판정, 설정 동결 뒤 test 1회 확인 | `specs/data/phase2_reranker_*.json` |

### 2.1 설계와 달라진 점 (이유)

1. **calibration.** 항등 함수로 시작했지만 확률 척도가 극단적으로 치우쳐(무관 후보 90%가 0.003 이하,
   정답 g3 하위 25%가 0.26 이하) floor를 둘 수 없었다. 원 로짓 −9/−7/−5/−3/0/+3을 0/0.10/0.30/0.50/0.75/0.95로
   펴는 단조 구간 선형(`bge-reranker-v2-m3-logit-pw.1`)으로 정했다.
2. **v3 계수와 floor (Q-RA2 안 A의 결정 근거 이전을 부분 철회).** 설계 시작값(β_semantic 0.55, β_cross 1.8,
   semantic floor 0.50, low-signal 0.60)은 dev에서 33개 질의를 잃었다. 탐색 결과 β_semantic은 v2 값 1.40을
   유지하고 cross는 약한 가산 증거(β_cross 0.30)로 두었으며, cross floor는 lexical-only(0.20)와 corroborated
   veto(0.05)에만 남겼다. semantic-only·low-signal의 결정 근거는 cross floor로 옮기지 못했다 (floor 0.2 이상에서
   동의어 정답이 거부됨, 4절).
3. **`cross_signal_floor` 추가.** cross가 의미 계열 증거로 인정되는 문턱을 따로 두었다(0.80). 설계 4.2절 2항의
   "유효할 때"를 설정값으로 명시한 것이다. semantic 신호 여부는 v2의 model별 증거 floor 판정을 그대로 쓴다.
4. **live 경로는 녹화하지 않는다.** Codex 초안은 live 컨테이너가 `RecordingReranker`로 감쌌다. 설계 15절 7항
   ("live 서비스 경로에서는 실제 사용자 질의를 녹화하지 않는다")에 맞춰 녹화는 `jupjup rerank record`로만 한다.
5. **A/B 표본.** 전체 지표는 하네스 게이트와 같은 `ai_draft_unreviewed` 질의로 계산하고, challenge는 별도
   부분집합(`subset_deltas.challenge`)으로 낸다. 10.1절 8번(사용자 승인)은 함수 밖에서 PM이 받는다.
6. **`enabled_on_cpu=false` 기본.** T31 cpu 측정이 예산을 크게 넘었다 (3절).

### 2.2 A0 정본 대비 변화 (보고 누락 정정)

A/B의 A0는 `c7da005` 자체가 아니라 F1 수정이 들어간 구현 HEAD에서 리랭커만 끈 경로다.
`c7da005` 대비 질의 단위 변화는 다음 두 건이고 악화는 0건이다.

- mock dev q_0176 `주식 공부 영상`: `[0063]` → `[0063, 0052]`, Recall@10 0 → 1, nDCG 0 → 0.63.
- recorded dev q_0127 `유튜브에서 본 기후 강의`: `0047`이 3위에 진입, Recall@5 0.5 → 1.0,
  nDCG 0.964 → 0.983. challenge ch_0001은 지표 변화가 없다.

## 3. 지연 측정 (live, Apple M5 24GB, warm, 단일 프로세스)

### 3.1 T31 리랭크 단계 단독 (dev 150질의의 실제 창 구성, 3회 반복 = 450호출)

| 장치 | max_length | 창 | p50 ms | p95 ms | max ms |
|---|---:|---:|---:|---:|---:|
| mps fp16 | 256 | 12 | 69.4 | 85.1 | 256.6 |
| mps fp16 | 256 | 20 | 116.0 | 144.5 | 241.8 |
| mps fp16 | 256 | 32 | 194.3 | 227.9 | 272.6 |
| mps fp16 | 384 | 12 | 70.7 | 87.5 | 102.9 |
| mps fp16 | 384 | 20 | 118.6 | **144.3** | 178.3 |
| mps fp16 | 384 | 32 | 188.1 | **218.9** | 317.8 |
| cpu fp32 | 256 | 12 | 541.3 | 723.0 | 794.6 |
| cpu fp32 | 256 | 20 | 934.8 | 1211.6 | 1289.1 |
| cpu fp32 | 256 | 32 | 1539.4 | 1799.1 | 1950.4 |
| cpu fp32 | 384 | 12 | 542.0 | 713.5 | 838.7 |
| cpu fp32 | 384 | 20 | 920.5 | **1168.0** | 1317.3 |
| cpu fp32 | 384 | 32 | 1528.5 | 1793.8 | 2061.2 |

- **go/no-go: mps go.** 창 20쌍 p95 144.3ms ≤ 150ms, 32쌍 218.9ms ≤ 220ms (둘 다 여유가 작다). max_length
  256은 이득이 없다 (질의·문서가 짧아 패딩 길이가 같다).
- **cpu는 no-go** (20쌍 p95 1168ms > 400ms). `enabled_on_cpu=false`를 기본으로 했다.
- 메모리: 첫 모델 적재의 최대 RSS 증가가 약 765MB(mps)·749MB(cpu)다. `ru_maxrss` 최댓값 차이라 같은 프로세스의
  두 번째 적재는 작게 나온다(84MB, 122MB). 참고값으로만 쓴다.
- 원자료: `specs/data/phase2_reranker_bench_t31.json`

### 3.2 T36 검색 전체 (`jupjup bench search --device mps --repeat 3`, dev 158질의 × 3)

| 항목 | 값 | 예산 |
|---|---:|---:|
| 리랭크 단계 p50 / p95 / max | 118.6 / **147.8** / 164.4 ms | p95 ≤ 150 |
| 검색 전체 A1 p50 / p95 / max | 142.8 / **174.4** / 286.4 ms | p95 ≤ 300 |
| 검색 전체 A0 p95 (같은 프로세스) | 27.2 ms | — |
| skip 비율 (timeout·error·busy) | 0.0% | ≤ 2% |
| RSS 증가 (리랭커 적재) | 295.7 MB | ≤ 1.5GB |

- live 경로는 bge-m3 live + 리랭커 live다. 리랭커가 검색 지연을 약 6배로 늘린다 (p95 27ms → 174ms).
- 원자료: `specs/data/phase2_reranker_bench_search_mps.json`

## 4. T35 recorded dev calibration과 튜닝 (test 미사용)

### 4.1 녹화 (T33)

- `jupjup rerank record --force --device mps`: 질의 265개(golden dev+test, challenge, probe), 창 구성 예정 쌍
  12,383개(중복 포함) → 고유 11,414행, 4.12MB, 84초. 원문 없음, Git LFS 기준(10MB) 이하.
- 녹화 범위: 합집합 `R_base` 상위 50 + 계획별 상위 5, `τ_pre=0`. T35 탐색 동안 캐시 미스는 없었다
  (녹화 갱신 0회). 빈 질의로 건너뛴 경우 0건.

### 4.2 cross 분포 (dev 창 안 3,040쌍, 원 로짓 분위수 1/5/10/25/50/75/90/95/99%)

| 집합 | 로짓 분위수 |
|---|---|
| 정답 g3 (161) | −7.16, −5.26, −3.64, −1.03, **1.31**, 3.00, 4.29, 5.49, 6.52 |
| 정답 g2 (57) | −8.99, −7.14, −5.95, −3.86, −2.31, −0.75, 0.87, 1.93, 3.79 |
| 정답 g1 (20) | −9.95, −9.95, −8.82, −7.37, −3.60, −2.12, 3.00, 3.21, 3.21 |
| positive 질의의 무관 후보 (2,462) | −11.04, −11.04, −11.03, −10.93, −9.87, −7.83, −5.89, −4.37, −1.23 |
| negative 질의 후보 (340) | −11.05, −11.04, −11.04, −11.02, −10.77, −9.58, −8.55, −7.89, −6.26 |

- 분리는 평균적으로 좋다. 하지만 정답 g3의 약 10%가 −3.6 이하이고, 그 구간에 무관 후보 상위가 겹친다.
  질의 150개 중 10개는 무관 후보 최고 로짓이 정답 최고 로짓보다 높다 (q_0082, q_0124, q_0129, q_0130, q_0162,
  q_0169, q_0170, q_0185, ch_0001, ch_0004).
- 낮은 정답 로짓의 대표 사례: `스파게티 만드는 법`→토마토 파스타 레시피 −6.3, `다리 운동 영상`→하체 루틴 −6.0,
  `언젠가 저장한 선크림`→선크림 문서 −6.1 (질의에 `언젠가`가 남는다. `선크림` 단독이면 +0.63).
  대표 오탐: `북극곰 다큐`→환경 다큐 문서 −6.3. 정답과 오탐이 cross에서도 **같은 좌표**에 있다.

### 4.3 탐색 범위와 선택

목적 함수: A0 대비 질의 단위 승/패(positive는 nDCG@10, negative는 empty 여부). 패배 수 최소 → 승리 수 최대 →
Recall@10 순. dev 158질의 전체(challenge dev 포함). 평가 1회 0.5초.

| 단계 | 범위 | 조합 수 | 최선 결과 |
|---|---|---:|---|
| 1 | β_cross {0.8,1.4,2.0} × β_semantic {0.55,1.0,1.4} × corroborated veto {0,0.1} × semantic floor {0.4,0.5,0.6} × lexical floor {0.2,0.35,0.5} × low-signal floor {0.5,0.6} × cross 신호 floor {0.5,0.6} | 648 | 12패 3~4승 |
| 2 | β_semantic 1.4 고정, β_cross {0,0.3,0.6,1.0} × veto {0,0.05} × semantic {0,0.2,0.4} × lexical {0,0.1,0.2} × low-signal {0,0.3,0.5} × 보조 cosine floor {0.45,0.61} × 신호 floor {0.6,0.8} × lexical-only 문턱 {0.44,0.58} | 5,184 | **β_cross=0(cross 무시)에서도 2패 0승**. β_cross>0 최소 7패 |
| 3 | β_cross {0.3,0.6,1.0} 근방, `τ_unscored` {0.50,0.65} | 144 | 7패 2승 (단, TE 0.933: `북극곰 다큐` 오탐) |
| 4 | 설계 시작값 근방 후보 9개 직접 비교 | 9 | 아래 |

| 후보 | Recall@10 | nDCG@10 | S@1 | TE | FE | 승/패 |
|---|---:|---:|---:|---:|---:|---|
| A0 (v2) | 0.9712 | 0.9860 | 1.000 | 1.000 | 0.000 | — |
| 설계 시작값 (항등 calibration) | 0.8274 | 0.8659 | 0.899 | 1.000 | 0.084 | 2/33 |
| 시작 floor + 구간 calibration, β_cross 0.3 | 0.9313 | 0.9570 | 0.975 | 1.000 | 0.017 | 2/12 |
| **채택 S7: β_cross 0.3, veto 0.05, lexical floor 0.20, semantic·low-signal floor 0** | **0.9397** | **0.9593** | **0.975** | **1.000** | **0.017** | **2/10** |
| S7에서 lexical floor 0 | 0.9712 | 0.9855 | 1.000 | 0.933 | 0.000 | 2/7 |

- **S7을 고른 이유:** TE 1.0(negative 안전)을 지키는 설정 중 패배가 가장 적다. lexical floor를 0으로 내리면
  `북극곰 다큐`가 `다큐` 한 단어 일치 문서(cross 0.134)를 반환한다. 0.20으로 올리면 그 오탐은 막지만
  cross 0.13~0.16의 동의어 정답(`스파게티`, `선크림`, `다리 운동`)도 함께 거부된다. **완화 정책 v2의 시소가
  cross floor에서 그대로 재현됐다.**
- facet 비용과 `Δmin`은 바꾸지 않았다. 창 크기(`N_global` 20, `k_plan` 3, `N_max` 32, `τ_pre` 0.15)와
  `τ_unscored` 0.50은 시작값을 유지했다. dev에서 창 밖 문서가 결과를 바꾼 사례가 없어 근거 없이 바꾸지 않았다.
- 동결 설정: `config.py` `CrossRelevanceSettings` `relevance-v3-cross.2`. 모든 값은 `search_overrides`로 바꿀 수 있다.

## 5. A/B 결과와 채택 판정 (T36)

### 5.1 recorded dev (판정 근거, 질의 119 positive / 15 negative)

| 지표 | A0 | A1 | Δ | 95% CI | 승/패/무 | 부호 검정 p |
|---|---:|---:|---:|---|---|---:|
| Recall@10 | 0.9712 | 0.9397 | −0.0315 | [−0.0651, −0.0063] | 0/5/114 | 0.0625 |
| MRR@10 | 1.0000 | 0.9748 | −0.0252 | [−0.0588, 0.0000] | 0/3/116 | 0.250 |
| nDCG@10 | 0.9860 | 0.9593 | −0.0266 | [−0.0602, −0.0014] | 1/9/109 | 0.0215 |
| Success@1 | 1.0000 | 0.9748 | −0.0252 | [−0.0588, 0.0000] | 0/3/116 | 0.250 |
| true empty | 1.000 | 1.000 | 0 | [0, 0] | 0/0/15 | 1.0 |
| false empty | 0.000 | 0.017 | +0.0168 | [0, +0.0420] | (2건 증가) | 0.5 |
| challenge dev positive Recall@10 | 0.9405 | 0.9405 | 0 | [0, 0] | 0/0/14 | 1.0 |

- 카테고리별 Recall@10 하락: semantic −0.161, ambiguous −0.115, multi −0.04, content_type −0.030, colloquial −0.014.
  A1의 dev 기술 게이트도 `category_recall@10_min 0.7798 < 0.80`으로 실패한다.
- 악화 질의: q_0021 `그 영화 예매했던 거`(g1 탈락), q_0026 `언젠가 저장한 선크림`(empty), q_0064·q_0072·q_0160·
  q_0166·q_0186(g3↔g2 순서 뒤바뀜), q_0162 `스파게티 만드는 법`(empty), q_0167 `다리 운동 영상`(1위가 무관 문서로),
  ch_0001(1위 정답 → 2위). 개선 질의: q_0061, ch_0004.

| 10.1절 규칙 | 결과 | 근거 |
|---|---|---|
| 1 절대 기준 | **FAIL** | A1 dev 게이트 실패(category min 0.7798). challenge positive 0.9405 ≥ 0.9091, challenge negative TE 1.0, 안전 0 |
| 2 허용 하락 | **FAIL** | Recall −0.0315, MRR −0.0252, nDCG −0.0266 (허용 −0.01), FE +0.0168 (허용 +0.01), category −0.161 (허용 −0.02) |
| 3 개선 요건 | **FAIL** | nDCG·S@1·challenge·시소 해소 경로 모두 해당 없음. A0 dev가 포화(S@1 1.0, TE 1.0, FE 0)라 개선 여지 자체가 작다 |
| 4 신뢰도 | **FAIL** | Recall CI 하한 −0.0651, nDCG −0.0602 |
| 5 지연 (mps) | PASS | 리랭크 p95 147.8/150ms, 검색 p95 174.4/300ms |
| 6 운영 | PASS | skip 0%, RSS +296MB |
| 7 test 확인 | FAIL | 5.2절 |
| 8 사용자 승인 | 해당 없음 | 기본값 변경을 제안하지 않는다 |

**판정: `REJECT`.** `cross_rerank.enabled=false`(기본)와 recorded 기준선은 그대로 둔다.

### 5.2 test 확인 (설정 동결 뒤 1회, A0·A1)

| 지표 | A0 | A1 | Δ | 95% CI | 승/패/무 |
|---|---:|---:|---:|---|---|
| Recall@10 | 0.9720 | 0.9620 | −0.0100 | [−0.0267, 0] | 0/2/73 |
| MRR@10 | — | — | +0.0022 | [0, +0.0067] | 1/0/74 |
| nDCG@10 | 0.9801 | 0.9807 | +0.0007 | [−0.0017, +0.0038] | 2/3/70 |
| Success@1 | 0.9867 | 0.9867 | 0 | [0, 0] | 0/0/75 |
| true / false empty | 1.0 / 0.0 | 1.0 / 0.0 | 0 / 0 | [0, 0] | — |
| challenge test positive Recall@10 | — | 0.875 | −0.0625 | [−0.1875, 0] | 0/1/7 |

- test에서도 개선 요건을 만족하는 경로가 없고, purpose 카테고리 Recall −0.083으로 허용치를 넘는다.
  A1 test 기술 게이트는 PASS다. test로 재튜닝하지 않았다.
- **test 사용 이력 (숨기지 않음):** 이번 사이클에서 recorded test는 (1) 동결 설정 A/B 1회(A0, A1)와
  (2) 완료 조건 확인용 `eval run --mode recorded --split test`(A0 기본 설정 = 기존 기준선과 같은 설정) 1회
  돌았다. mock test 게이트 1회. 기존 test는 이미 여러 번 소비되어 blind가 아니다 (Q-RA1, test v2 미구축).

### 5.3 9.2절 가설 사례

| 사례 | split | A0 | A1 | 가설 |
|---|---|---|---|---|
| ch_0017 `coffee cardiovascular health paper` | test | 정답 1위 | 정답 1위 | 해당 없음 (A0이 이미 통과) |
| ch_0023 `retrieval augmented generation survey paper` | test | 정답 1위 | 정답 1위 | 해당 없음 |
| ch_0001/0003/0009/0015 교차 언어 dev | dev | 통과 | ch_0003 `0096` 1위 유지. ch_0001 정답 1위 → 2위 | **일부 틀림** (ch_0001 MRR 하락) |
| q_0207 `낚시 포인트 추천` | test | empty | empty | 유지 (A0이 이미 empty) |
| q_0199/0203/0206/0211, ch_0011/0012 negative dev | dev | empty | empty | 맞음 (단 lexical floor 0.20 필요) |
| q_0180 `환경 다큐` | test | 정답 1위 | 정답 1위 | 유지 |
| q_0057, q_0071 부분 일치 g1 | dev | g1 거부 | g1 거부 | **틀림** (g1 회복 0건) |
| ch_0010 `유툭 십분 전신 홈트 그거` | dev | 정답 1위 | 정답 1위 | 영향 없음 (가설과 같음) |
| q_0045 `카톡으로 받은 회이 장소` | test | g1 1위, Recall 1.0 | g1 1위, MRR 개선, Recall 0.75 | 혼재 |
| q_0167 `다리 운동 영상` (사전 그대로) | dev | 정답 1위 | 1위가 무관 `0051` | **틀림** (사전이 있어도 악화) |

### 5.4 9.1절 고정 회귀

- A1 recorded에서 고정 negative(`북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `낚시 포인트 추천`, ch_0011)는
  모두 empty, ch_0003 1위 유지 (`test_recorded_a1_*`). 하지만 `다리 운동 영상`의 1위가 바뀌어 9.1절 "1위 불변"
  조건을 A1이 어긴다. 기대값은 바꾸지 않았다. 원인: 정답 `0040` 하체 루틴의 cross 0.155(로짓 −6.0)가
  lexical floor 0.20보다 낮다.

## 6. 불변식과 테스트

| ID | 테스트 |
|---|---|
| INV-R1 | `test_cross_and_relevance_are_computed_once_per_request` (요청당 리랭크 1회, 문서당 `apply_cross` 1회) |
| INV-R2 | 부분: `test_window_ignores_limit`에서 limit만 다른 요청의 창 동일. `now`·요청 잠금 변화에 대한 별도 테스트는 없다 (6.1절) |
| INV-R3 | `test_window_ignores_limit` (limit 1/2/10/50) |
| INV-R4 | `test_rerank_query_has_no_facet_spans`(facet 추출기 재실행 검출 0), `test_rerank_text_excludes_platform_type_time_and_author` |
| INV-R5 | `test_skipped_rerank_equals_v2` (6질의 × timeout·error 주입, 결과·완화 동일, `degraded_reasons` 기록) |
| INV-R6 | `test_v3_profile_thresholds_must_be_reachable` (튜닝 중 실제로 걸린 β_cross 0.15 조합 포함) |
| INV-R7 | `test_scored_responses_use_one_scale` |
| INV-R8 | `test_recording_has_no_raw_text_and_replay_misses_raise`, `test_recorded_miss_is_not_swallowed_by_stage` |
| INV-R9 | `test_gate_v3_unscored_tail_requires_corroboration`, `test_scored_responses_use_one_scale`(창 밖 문서 뒤 정렬) |
| 기타 | 실행기 busy/timeout, 단계 skip 사유 6종, calibration 단조성, bge 출력 검증과 revision 필수, **기본 설치로 mock/recorded 컨테이너가 torch·sentence-transformers를 import하지 않음**(서브프로세스), `decide_reranker` 경계(허용치 정확히 −0.01 통과, −0.0101 실패, CI 하한 0 실패, 시소 경로, 지연 1ms 초과, cpu 제한), A/B 결정성(A0 대 A0 Δ=0, 두 번 실행 동일), recorded A1 재생 결정성, 실제 모델 마커 2건(원 로짓 순서, 녹화본과 live cpu fp32 로짓 일치) |

### 6.1 검증 결과 (모두 이 워크트리에서 직접 실행)

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본, embed·rerank 마커 제외) | **602 passed**, 3 deselected |
| `uv run pytest -m "embed or rerank"` (실제 bge-m3·bge-reranker-v2-m3) | **3 passed** |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 56 source files |
| `jupjup eval validate` | 통과 (seeds 200, queries 259: dev 158, test 101) |
| `jupjup eval run --mode mock --split dev/test --baseline data/baselines/mock.json` | PASS / PASS |
| `jupjup eval run --mode recorded --split dev/test --baseline data/baselines/recorded.json` | PASS / PASS (리랭커 끔 기본 설정) |

## 7. 남은 문제

1. **리랭커 미채택 (known_issues 7절).** 근본 원인은 포화된 dev와, 사전 동의어·구어 질의에서 크로스 인코더가
   오탐과 같은 구간 점수를 준다는 점이다. 후보 대응: (a) 리랭커 질의에 사전 정규형을 함께 넣는 변형
   (설계 4.4절 원칙 범위 안), (b) 포화되지 않은 dev v2 사례 보강, (c) 다른 리랭커 비교(예: 한국어 특화 모델).
2. **리랭커 질의 상투어.** `언젠가 저장한 선크림` → `언젠가 선크림`처럼 `residual_text`에 상투어가 남는다.
   `선크림` 단독이면 로짓이 −6.1에서 +0.63으로 오른다. 질의 해석 쪽 개선 과제다.
3. **Q-RA2 결정 근거 이전 미완.** dev 근거로 semantic-only·low-signal floor를 0에 두었다. 설계가 의도한
   "cosine floor → cross floor" 이전은 데이터가 지지하지 않았다.
4. **INV-R2의 `now`·요청 잠금 축 테스트 없음.** limit 축만 자동 테스트가 있다.
5. **지연 여유가 작다.** mps 리랭크 p95가 예산의 98.5%(147.8/150ms)다. 창 32쌍이면 p95 219ms다.
6. **단계 2 기준.** 설계 10.2절에 따라 단계 1 미채택이므로 단계 2는 A2 대 A0으로, 트리거 부분집합 TE 하락 0의
   엄격한 조건으로 판단해야 한다.
7. F2~F6 잔여 상태는 `known_issues.md` 6절 그대로다.

## 8. 재현 명령

```bash
uv sync --extra embed --extra rerank
export JUPJUP_RERANK_CACHE_DIR=/Users/minjun/orca/workspaces/dc2/phase-2-real-embedding/var/models
uv run jupjup bench rerank --repeat 3                       # T31
uv run jupjup rerank record --force --device mps            # T33 (녹화본 갱신)
uv run jupjup bench search --device mps --repeat 3 --cache-dir $JUPJUP_RERANK_CACHE_DIR --out reports/bench_search_mps.json
uv run jupjup eval ab --mode recorded --split dev --arms A0,A1 --latency reports/bench_search_mps.json
```
