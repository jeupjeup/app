# 완화 정책 v2 설계

- 상태: Phase 1 설계안
- 대상: 검색 완화, 관련도 게이트, 교정 증거, human-reviewed 제품 게이트
- 기준일: 2026-10-30
- 근거 문서: `phase4_review_loop2.md`, `phase4_review_loop3.md`, `phase2_embedding_report.md`, `known_issues.md`
- 다음 단계: 본 문서 확정 후 Codex-Primary가 T0부터 순서대로 구현

## 1. 결론

완화 정책 v2는 “필터를 푼 검색의 점수가 더 높아 보이는가”를 비교하지 않는다. 최초 질의 해석을
고정한 뒤 모든 문서를 같은 특징과 같은 식으로 평가하는 문맥 독립 관련도 점수 `R(q₀, d)`를 하나만
사용한다.

- 요청에서 전달된 플랫폼·유형·기간은 모든 검색 계획에 적용되는 **절대 잠금**이다.
- 질의 문장에서 추출한 플랫폼·유형·기간은 관련도 점수에 섞지 않고, 위반 시 차감되는 **기억 facet
  비용**이다.
- 완화 후보는 원래 후보보다 관련도가 높다는 이유만으로 채택하지 않는다. 관련도 향상분이 새로
  발생한 facet 위반 비용과 최소 개선폭을 합친 값 이상일 때만 채택한다.
- 관련도 게이트도 `R(q₀, d)`의 절대 문턱만 사용한다. 키워드, 벡터, n-gram 중 하나만 통과하면 되는
  누적 OR 규칙과 검색 문맥별 `final_score` 비율은 제거한다.
- 완화 단계는 가변 상태를 순서대로 바꾸지 않는다. 원본에서 파생한 불변의 `RelaxationPlan`들을
  독립 평가하며, 실제 채택된 결과가 위반한 facet만 기록한다.

이 설계는 Loop 2의 과잉 완화와 Loop 3의 과소 완화를 같은 축에서 해결한다. bge-m3로 challenge
positive Recall@10이 0.6591에서 0.9091로 오른 실제 의미 신호는 관련도 모델의 주 신호로 사용하되,
`ch_0011`처럼 낮은 의미 유사도와 교정 확장만으로 생긴 오탐은 동일 점수의 절대 게이트에서 제거한다.

## 2. 목표와 범위

### 2.1 목표

1. 완화 전후 후보를 동일한 원 질의 기준으로 비교한다.
2. 요청 facet 잠금을 절대 보존하면서, 질의 유래 facet은 비용을 지불할 만큼 명백한 관련도 향상이
   있을 때 풀 수 있게 한다.
3. bge-m3 의미 신호와 원형 어휘 증거를 결합한 하나의 관련도 모델로 순위, 완화, 빈 결과 판정을
   일관되게 만든다.
4. 실제로 적용된 facet과 응답에 기록된 완화 내역을 정확히 일치시킨다.
5. 오교정이 원형 질의를 덮어쓰거나 단독으로 관련성 증거가 되지 않게 한다.
6. human-reviewed 제품 게이트가 분모 0 또는 전역/split 메타데이터 혼용으로 거짓 PASS를 내지 않게
   한다.
7. 알려진 실패 사례를 결과 ID, 순위, 완화 내역, 빈 결과까지 고정 회귀 테스트로 만든다.

### 2.2 하지 않는 것

- bge-m3 모델 교체, 추가 LLM 도입, 생성형 재순위는 하지 않는다.
- 인제스트, 저장소 스키마, 사용자 격리, 데모 바인딩 정책은 바꾸지 않는다.
- filter-only browse를 관련도 검색으로 합치지 않는다. browse는 기존처럼 정확한 필터와 최신순을
  사용한다.
- test split을 보며 계수나 문턱을 조정하지 않는다.
- 사람 검수 자체를 이번 구현 범위에 포함하지 않는다. 검수 데이터가 들어왔을 때 올바르게 판정하는
  구조까지만 구현한다.

## 3. 시소 현상의 근본 원인

### 3.1 서로 다른 문맥의 점수 비교

Loop 2는 완화 전후 `final_score`를 사실상 비교했지만, 이 점수에는 후보 집합의 최대 RRF로 정규화한
`rrf_norm`, 현재 필터 상태에서만 생기는 `facet_soft`, 현재 완화 창에 따른 `time_score`, 후보 집합과
순위에 좌우되는 값이 들어 있었다. 따라서 같은 문서도 필터를 hard에서 soft로 바꾸는 순간 점수가
올랐다.

`다리 운동 영상`에서 1위가 같은 `c_alice_0050`인데도 유형을 soft로 만든 뒤 점수가 올라 완화가
기록된 것은 문서의 관련도가 개선된 것이 아니라 좌표계가 바뀐 결과였다. 서로 다른 좌표계의 수치를
비교한 것이 Loop 2 과잉 완화의 직접 원인이다.

### 3.2 절대 veto

Loop 3는 위 문제를 막기 위해 원래 hard facet 위반 수가 하나라도 늘면 후보를 무조건 거부했다.
원래 검색을 통과한 incumbent의 위반 수는 구조상 0이므로, 후보가 한 건이라도 있으면 질의 유래
플랫폼·유형 완화가 사실상 불가능해졌다.

- `경주 맛집 인스타`: `경주`가 없는 인스타 맛집이 남아 정확한 blog 문서 `c_alice_0153`을 막았다.
- `하체 운동 유튜브`: 키워드 일부만 맞는 유튜브 홈트가 정확한 인스타 하체 루틴
  `c_alice_0040`을 막았다.

요청 facet과 기억에서 나온 facet을 같은 “hard”로 표현하고, 위반 증가를 비용이 아니라 금지로
처리한 것이 Loop 3 과소 완화의 직접 원인이다.

### 3.3 규칙 누적과 상태 변이

현재 완화 정책은 하나의 `current` 필터를 순서대로 변이한다. 플랫폼과 유형을 모두 soft로 만든 뒤
동일한 상태를 서로 다른 이름으로 두 번 내보내므로 첫 yield에서 결과가 나오면 실제로는 두 facet을
풀었어도 하나만 기록된다. 또한 `applied` 목록에는 채택된 변화가 아니라 지나오며 시도한 단계가
누적된다.

이 구조에서는 다음 세 값이 분리되지 않는다.

1. 시도한 완화
2. 검색 계획이 허용한 완화
3. 반환된 문서가 실제로 위반한 facet

`경주 맛집 카톡 논문`에서 blog/article 결과를 반환하고도 `platform_filter_dropped`만 기록한 것은
이 상태 모델의 필연적 결과다.

### 3.4 보조 원인

- RelevanceGate가 키워드, 벡터, n-gram, 목적 중 하나만 맞으면 통과시키는 OR 규칙이라 약한 단일
  신호가 관련성으로 승격됐다.
- top score 비율인 `tail_ratio`도 후보 집합과 검색 문맥에 따라 문턱이 달라졌다.
- 교정어가 원형을 대체하고 의미 질의에도 덧붙으면서, 낮은 신뢰도의 교정이 검색·게이트·완화의
  여러 단계에서 반복 가산됐다.
- RRF와 recency는 후보 생성·표시 순서에는 유용하지만 “원 질의와 문서가 관련 있는가”라는 절대
  판단에 쓰기에는 문맥 의존적이다.

## 4. 핵심 개념과 데이터 모델

### 4.1 최초 질의 해석 `q₀`

`q₀`는 한 요청 안에서 불변이다. 다음 값을 보존한다.

| 항목 | 의미 |
|---|---|
| `original_terms` | 교정 전 원형 키워드. facet과 불용 표현은 제외하되 표면형은 보존 |
| `canonical_terms` | 사전 동의어와 신뢰도 높은 교정으로 얻은 정규형 |
| `purpose_terms` | 과제, 선물, 업무참고 등 목적 |
| `semantic_text_original` | 교정어를 덧붙이지 않은 원문 기반 의미 질의 |
| `semantic_text_augmented` | 채택 가능한 교정·동의어 확장본. 보조 신호에만 사용 |
| `query_facets` | 질의에서 추출한 플랫폼, 유형, 기간 |
| `request_locks` | API/CLI 요청 필터에서 온 플랫폼, 유형, 기간 |
| `query_signal_profile` | normal 또는 low-signal. 문서와 무관한 질의 자체의 신호 상태 |

현재 `raw_keywords`는 `original_terms`의 출발점으로 재사용하되, 원형 의미 질의를 별도 필드로
보존해야 한다. `ParsedQuery.keywords`만으로 원형을 복원해서는 안 된다.

### 4.2 후보 관련도 평가

각 후보는 어느 검색 계획에서 발견됐는지와 무관하게 한 번만 `CandidateEvidence`로 평가한다.

| 특징 | 범위 | 정의 |
|---|---:|---|
| `semantic` | 0..1 | bge-m3 cosine을 model id별 calibration으로 변환한 값 |
| `original_lexical` | 0..1 | 원형 키워드의 필드 가중 coverage |
| `canonical_lexical` | 0..1 | 원형에 없던 정규형의 추가 coverage. 교정 신뢰도를 곱함 |
| `phrase` | 0..1 | 원형 residual의 n-gram/구문 coverage. 순위는 사용하지 않음 |
| `purpose` | 0..1 | 목적어의 detail/user_note 일치 또는 검증된 사전 동의어 일치 |
| `corroboration` | 0..1 | 독립 신호 둘 이상이 동시에 유효할 때의 제한된 상호작용 |
| `evidence_profile` | enum | 문서별 corroborated, semantic-only, lexical-only 중 하나 |
| `query_facet_violations` | set | platform, content_type, time_exact/time_window 위반 |
| `request_lock_violations` | set | 요청 잠금 위반. 하나라도 있으면 후보 자격 없음 |

필드 가중 coverage의 문서 필드 신뢰도 시작값은 title/user tag/AI tag `1.0`, detail/user_note
`0.8`, summary/body `0.6`, OCR `0.4`로 둔다. 문서 빈도나 후보 내 순위로 이 값을 바꾸지 않는다.

### 4.3 문맥 독립 관련도 점수 `R(q₀, d)`

`R`은 0..1 범위의 단조 점수다. 입력은 위 표의 의미·어휘 증거뿐이며 다음 값은 넣지 않는다.

- 현재 완화 계획, hard/soft 상태
- RRF 또는 검색기별 rank
- 후보 집합의 최댓값·최솟값
- 현재 시각 기준 recency
- 플랫폼·유형·기간 일치 보너스
- 요청 필터 일치 보너스

v2의 결합기는 고정된 특징의 로지스틱 모델을 사용한다.

`R(q₀,d) = sigmoid(b + βs·semantic + βo·original_lexical + βc·canonical_lexical +
βp·phrase + βu·purpose + βx·corroboration)`

계수와 bge-m3 calibration 구간은 recorded dev에서만 정한다. 모든 계수는 음수가 아니어야 하며,
`βo > βc`를 강제해 원형 증거가 교정 증거보다 강하게 남도록 한다. 의미 점수 calibration은 model id와
버전을 키로 가지며 `bge-m3`와 `hashing-v1` 값을 공유하지 않는다.

구현 시작값은 다음과 같다. 이는 PM 권고 초기값이며 T9에서 recorded dev 결과와 함께 최종값을
문서화한다.

| 설정 | 시작값 |
|---|---:|
| `βs` | 4.0 |
| `βo` | 2.4 |
| `βc` | 0.8 |
| `βp` | 0.8 |
| `βu` | 1.0 |
| `βx` | 0.6 |
| `b` | -2.0 |

RRF는 후보를 넓게 모으는 용도로만 남긴다. 최종 순위와 완화 비교는 `R` 및 아래 facet 비용으로
계산한 효용만 사용한다. 동일 점수의 결정적 tie-break는 `R` 내림차순, facet 비용 오름차순,
`saved_at` 내림차순, `content_id` 오름차순이다.

## 5. facet 비용과 요청 잠금

### 5.1 요청 facet: 절대 잠금

`SearchRequest.filters`에서 온 플랫폼, 유형, 기간은 비용 항목이 아니다. 모든 `RelaxationPlan`의 hard
filter에 포함하고, 후보 합집합을 만든 뒤에도 postcondition으로 다시 검사한다. 한 항목이라도 위반한
문서는 점수와 관계없이 제거한다.

질의 표현과 요청 필터가 충돌하면 기존처럼 요청 필터가 이긴다. `overridden_by_request`는 유지한다.

### 5.2 질의 유래 facet: 위반 비용

질의에서 추출한 facet은 사용자의 기억일 수 있으므로 풀 수 있지만, 관련도와 분리된 비용을 낸다.
비용은 후보 문서가 실제로 위반한 facet에서만 발생한다.

| 위반 | 시작 비용 | 비고 |
|---|---:|---|
| 기간 exact 밖, 확장 window 안 | 0.06 | `time_window_expanded` |
| 확장 window도 벗어나 기간 제거 필요 | 0.14 | `time_filter_dropped`; 0.06과 중복 합산하지 않음 |
| 플랫폼 불일치 | 0.12 | `platform_filter_dropped` |
| 유형 불일치 | 0.10 | lexicon의 확장 유형 집합 기준 |

총 비용 `C(q₀,d)`는 실제 위반별 비용의 합이다. 기간 비용은 서로 배타적이고 플랫폼·유형과는 합산한다.
비용도 0..1 관련도 점수와 같은 척도이며 T9에서 recorded dev만으로 조정한다.

### 5.3 후보 효용과 채택 규칙

문서 효용은 `U(q₀,d) = R(q₀,d) - C(q₀,d)`다. strict 계획의 1위 문서를 incumbent `i`, 완화 계획의
1위 문서를 challenger `c`라 한다.

완화 후보는 다음 조건을 모두 만족할 때만 채택한다.

1. 요청 잠금을 모두 만족한다.
2. RelevanceGate의 해당 신호 프로필 절대 문턱을 통과한다.
3. `c.content_id != i.content_id`다. 같은 1위면 점수나 표시 특징이 달라져도 완화를 채택하지 않는다.
4. `R(c) - R(i) > [C(c) - C(i)] + Δmin + epsilon`이다.
5. 비교 차이가 epsilon 이내면 facet을 덜 위반한 후보를 선택한다.

초기 `Δmin`은 0.05, 부동소수점 epsilon은 `1e-6`이다. strict 후보가 없으면 해당 게이트 문턱을
점수로 갖고 비용 0인 가상 incumbent를 사용한다. 즉 빈 strict 결과도 `R(c) > τprofile + C(c) +
Δmin + epsilon`을 만족해야 자동 완화로 채택된다. 단, strict 검색에서 후보는 있었지만 게이트만 실패한 경우도
동일하게 가상 incumbent를 사용해 약한 노이즈가 완화의 발판이 되지 않게 한다.

이 식은 두 방향을 동시에 보장한다.

- q_0173처럼 facet을 만족하는 충분히 관련 있는 후보가 있으면 약한 facet 위반 후보가 밀어내지 못한다.
- `경주 맛집 인스타`처럼 facet 위반 비용보다 핵심 의미·원형 증거 향상이 크면 정확한 문서를 채택한다.

## 6. 검색과 완화 실행 구조

### 6.1 불변 계획 집합

`RelaxationPolicy`는 mutable filter 상태의 iterator 대신 원본 `ResolvedFilters`에서 독립적인 계획을
생성한다. 각 계획은 다음 값을 가진다.

| 필드 | 의미 |
|---|---|
| `plan_id` | 결정적 식별자 |
| `allowed_query_relaxations` | 이 계획이 허용한 질의 facet 변화의 집합 |
| `hard_filter` | 요청 잠금 + 아직 유지하는 질의 facet |
| `retrieval_query` | 원형 또는 검증된 확장 의미 질의 |
| `parent` | 원본 계획. 실행 중 상태 상속에는 사용하지 않음 |

필수 계획은 strict, time-expanded, time-dropped, platform-dropped, content-type-dropped,
platform+content-type-dropped와 필요한 기간 조합이다. 조합 폭발을 막기 위해 facet은 기간·플랫폼·유형
세 종류로 제한하고, 동일 hard filter와 동일 retrieval query를 가진 계획은 하나로 정규화한다.

spelling expansion은 facet 완화가 아니라 검색어 확장 plan이다. 7절의 신뢰도 조건을 만족할 때만
생성하며, facet plan과 조합할 수 있으나 원형 증거와 원형 semantic 점수는 변하지 않는다.

### 6.2 후보 합집합과 재평가

1. 각 계획은 요청 잠금을 항상 포함한 채 후보 생성만 수행한다.
2. morph, n-gram, vector 결과를 계획별로 넓게 수집한다.
3. `content_id`로 합집합·중복 제거한다.
4. 모든 문서를 `q₀`와 문서 자체만으로 `CandidateEvidence` 및 `R`로 한 번 평가한다.
5. 각 문서의 실제 질의 facet 위반에서 `C`와 relaxation 기록을 계산한다.
6. 계획별 허용 집합에 맞는 후보를 `U`로 정렬하고 1위를 비교한다.
7. 5.3절을 통과한 최소 계획 하나를 선택하고 그 계획의 결과를 반환한다.

계획 선택 tie-break는 높은 1위 `U`, 높은 1위 `R`, 적은 실제 위반 수, 낮은 총 비용, 고정된 plan id
순이다. strict 계획의 1위가 전체 1위와 같으면 strict를 선택한다.

### 6.3 모듈 책임과 인터페이스

| 모듈 | 책임 | 설계 인터페이스 |
|---|---|---|
| `query/understanding.py` | 원형·정규형·두 의미 질의 보존 | `ParsedQuery`에 original/canonical evidence와 signal profile 제공 |
| `query/spell.py` | 교정 후보와 신뢰도 산출 | `propose(term, context, vocabulary) -> CorrectionCandidate[]` |
| `search/relevance.py` 신규 | 문맥 독립 특징, calibration, `R` 계산 | `score(q0, document, index) -> CandidateEvidence` |
| `search/relaxation.py` | 독립 계획 생성, 실제 위반 기록 변환 | `plans(original_filters, q0, vocabulary) -> RelaxationPlan[]` |
| `search/gate.py` | `R` 기반 절대 판정과 반환 tail 절단 | `evaluate(q0, evidence) -> GateDecision` |
| `search/service.py` | 후보 합집합, 계획 비교, 결과 조립 | `select_plan(strict, plans, evidence) -> RelaxationDecision` |
| `search/types.py` | evidence/plan/decision/응답 타입 | 아래 계약 준수 |
| `eval/harness.py` | 분모 보존 지표와 split 제품 게이트 | `MetricObservation`, split metadata 사용 |

필수 타입 계약은 다음과 같다.

- `CandidateEvidence`: `content_id`, `relevance`, 원자 특징, 실제 query facet 위반, request lock 위반,
  correction contribution, model/calibration version
- `GateDecision`: `accepted`, `threshold`, `signal_profile`, `reason`
- `RelaxationPlan`: 허용 변화 집합과 독립 hard filter
- `RelaxationDecision`: incumbent/challenger ID, `R`, `C`, `U`, `delta_relevance`, `delta_cost`,
  `minimum_gain`, 실제 적용 기록

`explain=true`에는 위 값을 노출하되 일반 응답의 `score`는 기존 `final_score`가 아니라 `R`을 반올림해
표시한다. 내부 검색기 점수와 RRF는 debug의 retrieval 진단으로만 남긴다.

## 7. RelevanceGate v2

### 7.1 단일 점수에 대한 절대 게이트

기존의 `keyword_ok or vector_ok or ngram_ok or purpose_ok`와 `top_score * tail_ratio`를 제거한다.
게이트는 후보의 `R`과 문서별 evidence profile에 대응하는 절대 문턱을 비교한다. 질의 자체가
low-signal이면 해당 문서 프로필 문턱과 low-signal 문턱 중 큰 값을 사용한다.

| 프로필 | 정의 | 시작 문턱 |
|---|---|---:|
| normal/corroborated | 독립 증거 두 종류 이상 | 0.45 |
| semantic-only | 원형 어휘 일치 없이 의미 신호만 유효 | 0.55 |
| lexical-only | 의미 신호가 calibration 하한 미만 | 0.52 |
| low-signal 보정 | 질의에 유효 원형 토큰이 없거나 모두 OOV/저신뢰 교정 | 0.58 |

semantic-only와 low-signal은 calibration된 semantic 자체도 각 프로필의 별도 semantic floor를
통과해야 한다. 시작 floor는 0.60이다. 최종 문턱은 T9에서 recorded dev로만 확정한다.

선택된 계획 안에서 반환할 문서는 각자 절대 문턱을 통과해야 한다. 관련 없는 꼬리 제거가 더 필요하면
비율이 아니라 고정 `return_tail_margin`을 사용해 `U(d) >= U(top) - margin`을 요구한다. 시작 margin은
0.18이다.

### 7.2 negative 질의

런타임에는 골든셋의 `negative` 라벨을 알 수 없다. 따라서 별도 “negative 규칙”을 만들지 않는다.
모든 후보가 자신의 절대 게이트를 통과하지 못하면 결과는 빈 배열이다. 완화 계획에서도 동일한
게이트를 사용하고, spelling/canonical 증거만으로는 통과할 수 없다.

`ch_0011`의 기대 흐름은 다음과 같다.

1. `mars migration documentary` 원형을 보존한다.
2. 낮은 신뢰도의 Latin corpus 교정을 만들지 않는다.
3. `c_alice_0154`의 원형 lexical evidence는 0이고 bge 의미 신호도 semantic-only 문턱보다 낮다.
4. 모든 계획이 게이트에서 탈락하고 빈 결과를 반환한다.
5. 채택된 계획이 없으므로 `applied_relaxations=[]`이다.

dev recorded의 true_empty_rate 0.733은 개별 OR 규칙을 추가해서 맞추지 않는다. negative 실패 사례별
`R`, 증거 프로필, 문턱을 출력해 하나의 calibration과 게이트를 조정한다.

### 7.3 저신호 및 교차 언어 질의

저신호는 입력 오류와 다르다. 반복 문자열 같은 `low_information`은 기존처럼 요청 자체를 거부하지만,
영어·혼합 언어이거나 개인 어휘에 없는 정상 질의는 검색한다.

`ch_0003`은 원형 lexical 신호가 약해도 bge-m3의 교차 언어 의미 신호와 paper 요청, 과제 목적을
사용할 수 있다. paper는 질의 유래 facet이지만 관련 paper 후보가 이를 만족하므로 비용은 0이다.
관련 문서가 semantic-only/low-signal 절대 문턱을 통과하면 유형을 풀지 않고 반환해야 한다. mock은
교차 언어 의미 품질을 대표하지 않으므로 관련 문서를 만들기 위한 임의 번역 규칙을 추가하지 않는다.

## 8. 이중 facet 완화 기록

### 8.1 실제 변화에서 기록 생성

완화 이름은 plan 생성 시 문자열로 누적하지 않는다. 선택된 결과와 `q₀.query_facets`를 비교해 실제
위반에서 계산한다. canonical order는 다음과 같다.

1. `time_window_expanded`
2. `time_filter_dropped`
3. `platform_filter_dropped`
4. `content_type_filter_dropped`
5. `spelling_expanded`

기간 expanded와 dropped는 동시에 기록하지 않는다. 플랫폼과 유형은 독립 원자 변화이므로 둘 다
위반하면 둘 다 기록한다.

### 8.2 응답 계약

- `applied_relaxations`: 채택된 1위 결과를 가능하게 만든 실제 원자 변화만 canonical order로 기록
- `attempted_relaxations`: 일반 응답에는 추가하지 않는다. `explain=true` debug에서만 계획별 시도와
  거부 사유를 제공
- 결과별 `relaxed`: 해당 결과의 실제 위반 집합이 비어 있지 않을 때만 true
- 결과별 `relaxed_facets` 신규 필드: 실제 위반 이름 목록. API 호환성을 위해 additive optional field

선택된 넓은 계획 안에서도 원래 facet을 만족하는 문서는 `relaxed=false`다. 빈 결과에서 실제 채택된
계획은 없으므로 `applied_relaxations=[]`이며, 사용자 제안은 기존 `EmptyState.suggestions`로 설명한다.

`경주 맛집 카톡 논문`의 1위 `c_alice_0153`은 플랫폼과 유형을 모두 위반하므로 응답에는 정확히
`["platform_filter_dropped", "content_type_filter_dropped"]`가 남아야 한다.

## 9. 오교정 방지

### 9.1 원형 증거 우선

교정은 대체가 아니라 확장이다.

- `original_terms`와 `semantic_text_original`은 끝까지 불변이다.
- `canonical_terms`는 원형과 나란히 보존한다.
- bge-m3 주 semantic 점수는 원형 의미 질의로 계산한다.
- augmented 의미 질의 점수는 교정 신뢰도를 곱한 제한된 보조 특징으로만 쓴다.
- 교정 일치만으로 RelevanceGate를 통과할 수 없다.

### 9.2 교정 신뢰도

각 `CorrectionCandidate`는 0..1 confidence와 근거를 가진다.

| 근거 | 설명 |
|---|---|
| edit quality | 길이로 정규화한 자모/문자 편집 거리 |
| frequency margin | 1위 후보와 2위 후보의 문서 빈도 차이. 고빈도 하나만으로 충분하지 않음 |
| context support | 다른 원형 용어와 같은 문서/필드에 공기하는 정도 |
| semantic consistency | 원형 의미 embedding과 교정 확장 embedding의 방향 일치 |
| curated evidence | 보호어, 별칭, 명시적 오타 사전 |

사전 동의어는 confidence 1.0으로 canonicalization할 수 있다. 자동 spelling은 confidence 0.90 이상에서만
정규형 증거로 사용하고, 0.75~0.90은 검색 recall용 expansion으로만 사용한다. 0.75 미만은 버린다.

PM 기본 정책은 다음과 같다.

- 2음절 한국어 정상어는 vocabulary에 없다는 이유만으로 자동 대체하지 않는다. 명시적 오타 사전 또는
  강한 context+semantic 근거가 함께 있어야 한다.
- Latin corpus spelling은 기본 비활성화하고, curated alias/synonym만 허용한다. 교차 언어는 bge-m3가
  담당한다.
- `다리→자리`는 confidence 부족으로 거부하고 `다리`를 원형으로 유지한다.
- 어떤 교정도 원형 lexical coverage를 올리지 못하며 `canonical_lexical`에만 기여한다.

## 10. human-reviewed 제품 게이트 수정

### 10.1 분모를 가진 지표

각 지표는 숫자 하나가 아니라 `MetricObservation(value, numerator, denominator, minimum_denominator,
eligible)`로 집계한다. denominator가 0이면 value는 1.0이 아니라 null이며 `eligible=false`다. 보고서에는
`not_evaluated`로 표시하고 제품 PASS에서는 실패 조건으로 취급한다.

PM 권고 최소 분모는 다음과 같다. 한 질의가 여러 범주에 동시에 기여할 수 있다.

| 지표군 | test human-reviewed 최소 유효 표본 |
|---|---:|
| positive ranked | 10 |
| negative / true_empty | 5 |
| filter-only browse | 5 |
| 기간 이해 | 5 |
| 플랫폼 이해 | 5 |
| 유형 이해 | 5 |
| 키워드 포함 | 10 |

`false_empty_rate`의 분모는 positive ranked, `true_empty_rate`의 분모는 negative, browse 세 지표의
분모는 filter-only다. 기간·플랫폼·유형·키워드 지표는 각 expected 필드가 실제 채점되는 사례 수를
분모로 쓴다. category minimum도 유효 ranked 표본이 있는 카테고리만 계산하되, 필수 카테고리의
분모 부족은 별도 eligibility 실패로 남긴다.

### 10.2 split 메타데이터

`review_metadata.json`은 전역 값과 split 값을 분리한다.

- `reviewed_query_count_total`
- `reviewed_query_count_by_split.dev`
- `reviewed_query_count_by_split.test`
- `reviewer_count`
- `weighted_kappa_overall`
- `weighted_kappa_by_split.dev/test`

validator는 전역 count를 전체 human-reviewed 수와, split count를 각 split의 수와 각각 비교한다.
평가가 dev이면 dev count, test이면 test count만 제품 증거의 `metadata_count_matches`에 사용한다.
`split=all`은 진단 보고만 허용하고 제품 PASS를 선언하지 않는다.

### 10.3 제품 PASS 조건

test의 human-reviewed 제품 PASS는 아래를 모두 만족해야 한다.

1. test human-reviewed 총 20건 이상
2. 위 표의 모든 필수 지표 분모 충족
3. 독립 검수자 2명 이상
4. test weighted kappa 0.70 이상
5. human-reviewed 절대 게이트 통과
6. 동일 mode·동일 review status의 test 회귀 기준선 존재 및 통과
7. 메타데이터 total과 split count 모두 실제 데이터와 일치

분모가 부족한 지표는 기준선에 1.0으로 저장하지 않는다. human 기준선 생성·갱신은 제품 evidence가
eligible일 때만 허용한다.

## 11. 테스트로 고정할 불변식

아래 각 항목은 적어도 하나의 단위 테스트와 필요한 경우 통합 테스트로 고정한다.

| ID | 불변식 | 테스트 오라클 |
|---|---|---|
| INV-01 | 요청 facet은 절대 풀리지 않는다 | 모든 plan hard filter와 최종 결과가 요청 플랫폼·유형·기간을 만족 |
| INV-02 | 같은 문서는 계획과 후보 집합이 달라도 같은 `R`을 갖는다 | strict/relaxed에서 동일 ID의 `R` 차이 ≤ `1e-6` |
| INV-03 | 같은 1위면 완화를 기록하지 않는다 | 결과 ID가 같으면 strict 선택, `applied_relaxations=[]` |
| INV-04 | tie는 완화하지 않는다 | 향상분이 비용+최소폭보다 작거나 같으면 strict 선택 |
| INV-05 | 원래 facet을 만족하는 강한 후보는 밀려나지 않는다 | challenger의 순향상이 부족하면 incumbent ID·순위 유지 |
| INV-06 | 명백히 더 관련 있는 facet 위반 후보는 채택된다 | `ΔR > ΔC+Δmin+epsilon`이면 challenger 1위와 정확한 완화 기록 |
| INV-07 | 두 facet 위반은 두 기록을 남긴다 | 플랫폼+유형 위반 1위는 두 이름을 canonical order로 포함 |
| INV-08 | 계획이 허용했지만 문서가 위반하지 않은 facet은 기록하지 않는다 | actual violation과 기록 집합이 정확히 같음 |
| INV-09 | 시도만 한 완화는 applied가 아니다 | 모두 거부된 빈 결과의 `applied_relaxations=[]` |
| INV-10 | 원형 키워드는 교정 후에도 보존된다 | `다리`가 original/semantic original에 남고 `자리`로 대체되지 않음 |
| INV-11 | 교정 단독 증거는 게이트를 못 넘는다 | original=0, semantic 미달, canonical>0 후보 거부 |
| INV-12 | 낮은 의미 유사도의 semantic-only 후보는 거부된다 | `R < τsemantic-only`이면 다른 순위와 무관하게 empty |
| INV-13 | 강한 bge 의미 신호는 어휘 불일치에도 통과 가능하다 | `ch_0003` recorded 관련 paper 통과 |
| INV-14 | RRF/recency는 `R`을 바꾸지 않는다 | 검색 rank·현재 시각만 바꿔도 동일 q/doc의 `R` 불변 |
| INV-15 | 결과별 relaxed는 실제 위반과 일치한다 | `relaxed == bool(relaxed_facets)` |
| INV-16 | 기간 비용은 expanded와 dropped가 중복되지 않는다 | 후보당 기간 기록·비용 정확히 하나 |
| INV-17 | 게이트 분모 0은 PASS가 아니다 | value=null, eligible=false, product evidence false |
| INV-18 | 전역과 split 메타데이터를 혼용하지 않는다 | total 및 dev/test count를 각각 독립 검증 |
| INV-19 | mode가 다른 기준선은 비교·갱신할 수 없다 | 기존 파일 바이트 불변과 명시적 실패 유지 |
| INV-20 | 결정성이 유지된다 | recorded 동일 실행의 비결정 필드 제외 리포트 byte-equivalent |

## 12. 고정 회귀 사례

모든 사례는 limit 1/2/10/50에서 1위와 완화 결정이 같아야 한다. 표의 “공통”은 mock과 recorded
모두에 적용한다. ch_0003만 embedding 능력 차이를 명시한다.

| 사례 | 기대 1위/결과 | 기대 완화 | 추가 오라클 |
|---|---|---|---|
| S7 / q_0083 `지난주 카톡으로 받은 회의 장소` | `c_alice_0136` 1위 | `time_window_expanded`만 | 1위 `relaxed=true`, `time_near`, 카톡 유지 |
| q_0173 `레스토랑 추천 블로그` | `c_alice_0153` 1위 | 없음 | 반환 상위는 blog, 카톡 `0145`가 앞서지 않음 |
| `다리 운동 영상` / q_0167 | `c_alice_0040` 1위 | 없음 | `다리` 원형 보존, `자리` 교정 없음, video 확장 유형 만족 |
| `경주 맛집 인스타` | `c_alice_0153` 1위 | `platform_filter_dropped`만 | `0019/0020`보다 앞섬 |
| `하체 운동 유튜브` | `c_alice_0040` 1위 | `platform_filter_dropped`만 | generic `0050/0051`보다 앞섬 |
| `경주 맛집 카톡 논문` | `c_alice_0153` 1위 | platform, content_type 순서로 정확히 2개 | 1위 `relaxed_facets`도 두 항목 |
| ch_0003 `assignment에 쓸 climate crisis paper` | recorded: `c_alice_0096` 1위, 관련 ID 중 하나 이상 top 3; mock: 관련성을 만들 수 없으면 안전한 empty 허용 | 없음 | recorded는 paper facet 유지, content type 완화 금지 |
| ch_0011 `mars migration documentary 저장한 거` | 빈 결과 | 없음 | `c_alice_0154` 미반환, spelling expansion 미채택 |

q_0173은 기존 구현의 `0152` 1위를 보존하지 않는다. `0152`는 “추천”만, `0153`은 “맛집”과 더 강한
bge 의미 신호를 가지므로 문맥 독립 관련도 모델에서는 골든의 grade 3 문서 `0153`이 1위여야 한다.

고정 사례는 이미 알려진 결함이므로 별도 regression fixture로 관리한다. held-out test 집계의 계수
튜닝 입력으로 사용하지 않으며, test aggregate는 13절의 최종 확인 전까지 실행하지 않는다.

## 13. 튜닝과 평가 절차

### 13.1 데이터 사용 규칙

1. T0에서 현재 recorded/mock 기준선과 고정 회귀 결과를 스냅샷한다.
2. 모델 계수, bge calibration, facet 비용, `Δmin`, 게이트 문턱은 **recorded dev만** 사용해 튜닝한다.
3. 알려진 고정 회귀 사례는 불변식 확인에만 쓰고 평균 지표를 최적화하는 loss에는 넣지 않는다.
4. mock dev는 결정성, 구조 호환, 기본 안전성 확인용이다. 실제 의미 품질 계수를 mock에 맞추지 않는다.
5. 파라미터 후보를 동결하고 변경 이유·탐색 범위·dev 결과를 보고서에 남긴 뒤에만 test를 한 번 실행한다.
6. test 실패 후 다시 계수를 바꾸려면 그 test 결과는 더 이상 blind final이 아니다. 새 dev 이슈로
   등록하고 별도 test v2를 마련하기 전에는 제품 PASS를 선언하지 않는다.

### 13.2 recorded dev 최적화 순서

1. 원형 보존과 교정 신뢰도부터 고정한다.
2. bge-m3 calibration과 관련도 계수를 맞춘다.
3. RelevanceGate 문턱으로 true empty와 false empty를 조정한다.
4. 관련도 계수를 동결한 뒤 facet 비용과 `Δmin`을 맞춘다.
5. 마지막으로 반환 tail margin만 조정한다.

이 순서를 바꾸지 않는다. facet 비용으로 negative 오탐을 숨기거나 gate 문턱으로 과소 완화를 보정하면
다시 규칙 간 시소가 생긴다.

### 13.3 합격 기준

기존 절대 기준과 mode별 기준선 회귀를 모두 적용한다.

| 지표 | mock 최소/최대 | recorded 최소/최대 |
|---|---:|---:|
| Recall@10 | ≥ 0.75 | ≥ 0.90 |
| Recall@5 | ≥ 0.65 | ≥ 0.85 |
| MRR@10 | ≥ 0.60 | ≥ 0.75 |
| nDCG@10 | ≥ 0.65 | ≥ 0.80 |
| Success@1 | ≥ 0.50 | ≥ 0.65 |
| category Recall@10 최저 | ≥ 0.55 | ≥ 0.80 |
| time exact | ≥ 0.95 | ≥ 0.95 |
| platform F1 | ≥ 0.97 | ≥ 0.97 |
| content type F1 | ≥ 0.95 | ≥ 0.95 |
| keyword inclusion | ≥ 0.90 | ≥ 0.90 |
| true empty | ≥ 0.70 | ≥ 0.80 |
| false empty | ≤ 0.05 | ≤ 0.03 |
| isolation/filter violations | 0 | 0 |
| browse precision@10 | ≥ 0.95 | ≥ 0.95 |
| browse sort/filter compliance | 1.0 | 1.0 |

추가 v2 기준은 다음과 같다.

- recorded dev true_empty_rate가 현재 0.7333에서 0.80 이상으로 오른다.
- recorded challenge positive Recall@10은 현재 0.9091보다 낮아지지 않는다.
- recorded challenge negative 2건은 모두 empty여서 true empty 1.0이다.
- 12절 고정 회귀표가 mode별 기대대로 전부 통과한다.
- mock과 recorded 모두 자신의 기존 baseline에서 Recall@10, MRR@10, nDCG@10, time exact,
  platform F1이 허용치 0.01을 넘게 하락하지 않는다.
- recorded test는 최종 확인에서 절대 기준, 회귀 기준, 고정 회귀를 모두 통과한다.
- human-reviewed 제품 PASS는 10절의 분모·메타데이터 조건까지 통과해야 하며, 데이터가 아직 0건이면
  기술 PASS와 별개로 `eligible=false`가 정상 결과다.

## 14. 구현 작업 분할

### T0. 회귀 잠금과 진단 출력

- 범위: 고정 회귀 fixture, 현재 결과 스냅샷, plan/evidence 진단 포맷
- 의존성: 없음
- 인수 기준: 12절 사례가 현재 실패 상태까지 재현되고, 각 후보의 원자 특징·`R/C/U`·게이트 사유를
  비교 가능한 포맷으로 출력할 수 있다. test aggregate는 실행하지 않는다.

### T1. v2 타입과 설정

- 범위: `CandidateEvidence`, `GateDecision`, `RelaxationPlan`, `RelaxationDecision`, calibration/version,
  response additive field
- 의존성: T0
- 인수 기준: Pydantic 검증, canonical relaxation order, unknown 설정 거부, request/query facet origin을
  타입 수준에서 구분한다.

### T2. 문맥 독립 관련도 모델

- 범위: 신규 `search/relevance.py`, 원자 특징 추출, bge/hash calibration, `R` 계산
- 의존성: T1
- 인수 기준: INV-02, INV-14 통과. 후보 순서·계획·현재 시각을 바꿔도 동일 q/doc 점수가 같다.

### T3. 원형 보존과 교정 신뢰도

- 범위: 두 의미 질의, correction confidence/evidence, Latin 기본 비활성, short Korean 보호
- 의존성: T1; T2와 병행 가능하나 통합은 T2 이후
- 인수 기준: INV-10, INV-11 및 `다리 운동 영상`, ch_0011 이해 스냅샷 통과.

### T4. 불변 RelaxationPlan 생성기

- 범위: 원본에서 독립 계획 생성, 중복 계획 제거, 요청 잠금의 모든 계획 상속
- 의존성: T1
- 인수 기준: INV-01, INV-07, INV-08, INV-16 단위 테스트 통과. 플랫폼과 유형 단일/복합 계획의
  hard filter가 서로 다르다.

### T5. 후보 합집합과 비용 기반 선택

- 범위: plan별 retrieval, content ID 합집합, 실제 위반 비용, adoption rule, 결정적 tie-break
- 의존성: T2, T3, T4
- 인수 기준: INV-03~INV-06 통과. q_0173, 경주 맛집 인스타, 하체 운동 유튜브의 ID·완화 내역 통과.

### T6. RelevanceGate v2

- 범위: 신호 프로필, 절대 문턱, semantic floor, 고정 tail margin, 거부 사유
- 의존성: T2, T3
- 인수 기준: INV-12, INV-13 통과. ch_0003 recorded non-empty, ch_0011 empty. 기존 OR 조건과
  `tail_ratio` 사용이 검색 경로에서 제거된다.

### T7. 응답과 완화 기록 정합성

- 범위: actual violation 기반 applied 기록, 결과별 `relaxed_facets`, debug attempted plans
- 의존성: T5, T6
- 인수 기준: INV-07~INV-09, INV-15 통과. `경주 맛집 카톡 논문`이 정확히 두 항목을 기록하고 빈
  결과는 applied를 기록하지 않는다.

### T8. human gate와 split 메타데이터

- 범위: `MetricObservation`, 필수 분모, null/not_evaluated, metadata v2 및 호환 migration,
  baseline eligibility
- 의존성: T1; 검색 작업과 병행 가능
- 인수 기준: INV-17~INV-19 통과. positive 20건·negative 0건 합성 데이터가 제품 PASS를 내지 않으며,
  dev/test에 정상 분산된 count는 각 split에서 일치한다.

### T9. recorded dev 튜닝

- 범위: calibration, 관련도 계수, gate, facet 비용, 최소 개선폭, tail margin 순차 튜닝
- 의존성: T5, T6, T7
- 인수 기준: 13.3 recorded dev 및 challenge 기준 통과. 변경한 값, 탐색 범위, 실패 후보별 evidence를
  별도 Phase 2 보고서에 기록한다.

### T10. mock·전체 정적 검증

- 범위: mock dev, 전체 단위/통합 테스트, ruff, mypy, 결정성
- 의존성: T8, T9
- 인수 기준: mock 합격 기준, 고정 회귀의 mode별 기대, 전체 테스트, lint/type check, recorded 재생
  결정성 통과. test aggregate는 아직 실행하지 않는다.

### T11. 최종 test 확인

- 범위: 동결된 설정으로 mock test와 recorded test 각 1회, 기준선 비교
- 의존성: T10, 설정 동결 승인
- 인수 기준: 13.3의 test 조건 전부 통과하고 설정·코드 재수정이 없다. 실패 시 결과를 숨기거나 같은
  test로 재튜닝하지 않고 새 이슈와 새 held-out split 필요성을 보고한다.

### 14.1 의존성 트리

```text
T0 → T1 ─┬→ T2 ─┬→ T5 ─→ T7 ─→ T9 ─→ T10 ─→ T11
         │      └→ T6 ─────┘
         ├→ T3 ─────→ T5/T6
         ├→ T4 ─────→ T5
         └→ T8 ─────────────────────→ T10
```

T2/T3/T4/T8은 파일 소유권이 겹치지 않는 범위에서만 병렬화할 수 있다. `service.py` 통합은 T5 한
작업자가 맡아 동시 수정을 피한다.

## 15. 전체 인수 기준

1. 11절 불변식이 모두 자동 테스트로 존재한다.
2. 12절 고정 회귀 사례가 mode별 기대대로 통과한다.
3. 요청 잠금 위반, 사용자 격리 위반은 0이다.
4. 같은 q/doc의 `R`이 계획, limit, 후보 수, 실행 순서에 무관하다.
5. recorded dev true empty ≥ 0.80, challenge positive Recall@10 ≥ 0.9091, challenge negative true empty
   = 1.0이다.
6. mock·recorded의 기존 절대/회귀 기준을 모두 통과한다.
7. test는 설정 동결 뒤 최종 확인에만 사용하고 실행 이력을 보고서에 남긴다.
8. human-reviewed 분모가 부족하거나 메타데이터가 불일치하면 제품 evidence가 반드시
   `eligible=false`다.
9. 공개 응답의 완화 기록과 결과별 실제 위반이 일치한다.
10. 구현 보고서에 최종 계수, calibration, facet 비용, gate 문턱, dev 탐색 범위와 선택 근거가
    기록된다.

## 16. 열린 질문과 PM 추천 기본값

사용자 확인이 없더라도 아래 추천값으로 구현을 시작할 수 있다.

### Q1. 결과별 `relaxed_facets`를 공개 응답에 추가할 것인가?

- **PM 추천 기본값:** 추가한다. optional additive field라 기존 소비자를 깨지 않으며, 전역
  `applied_relaxations`와 결과별 실제 완화를 검증할 수 있다. `attempted_relaxations`는 debug에만 둔다.

### Q2. 이미 여러 번 본 현재 test split을 계속 최종 test로 부를 것인가?

- **PM 추천 기본값:** 이번 v2에서는 기존 계약의 최종 회귀 확인용으로만 유지한다. 계수 튜닝에는
  recorded dev만 사용하고, 제품 품질을 최종 주장하기 전에는 별도의 human-reviewed test v2를 새로
  동결한다. 알려진 S7/q_0173은 별도 regression fixture로 취급한다.

### Q3. human-reviewed test의 범주별 최소 분모를 이번 구조 변경에서 강제할 것인가?

- **PM 추천 기본값:** 10.1절의 10/5/5/5/5/5/10을 강제한다. 표본이 부족하면 FAIL이 아니라
  `not_evaluated`로 보고하되 제품 PASS 자격은 주지 않는다. 실제 사용자 데이터 수집 후 숫자만 별도
  승인으로 조정할 수 있다.

## 17. 다음 워커에게 넘길 핵심 사항

Codex-Primary는 기존 `_comparison_features`에 bge 점수나 비용을 덧붙이는 국소 수정으로 시작하면 안
된다. 먼저 T0의 실패 테스트와 T1/T2의 단일 점수 경계를 세운 뒤, mutable relaxation loop를 T4/T5로
교체해야 한다. 관련도, gate, facet 비용을 한 번에 튜닝하지 말고 13.2절 순서를 지킨다. 특히 요청
잠금은 계획 생성과 최종 postcondition 두 곳에서 검증하고, test aggregate는 T11 전까지 실행하지
않는다.
