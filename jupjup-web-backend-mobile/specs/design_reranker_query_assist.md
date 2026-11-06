# 크로스 인코더 리랭커와 소형 LLM 질의 보조 설계

- 작성: Claude-Architect
- 상태: Phase 1 설계안 (사용자 확정 전. 16절 열린 질문은 PM 추천 기본값으로 진행할 수 있다)
- 기준일: 2026-10-30
- 근거 문서: `prd_and_design.md`(3.3, 3.5.5, 4.3, 5.2, 5.4.2, 5.8.3~5.8.4절), `design_relaxation_v2.md`,
  `phase4_review_cycle2_loop1.md`, `phase4_review_cycle2_loop2.md`, `known_issues.md`
- 선행 조건: 완화 정책 v2 Loop 3 수정이 PM 브랜치에 병합된 뒤에 구현을 시작한다. 이 문서의 작업은
  Loop 3이 고치는 `search/relevance.py`, `search/gate.py`, `search/service.py`, `config.py`를 다시
  건드리므로, Loop 3과 동시에 진행하지 않는다.
- 다음 단계: 사용자 확정 → T30(기준 고정과 A/B 러너)부터 순서대로 구현

---

## 1. 결론

완화 정책 v2는 문서마다 `R(q₀, d)` 하나를 계산하고, 증거 프로필마다 절대 문턱 하나로 자른다.
Loop 1~2 검수에서 확인된 시소는 문턱 값이 아니라 **입력 특징의 표현력**에서 생긴다.

- `R`의 입력은 bi-encoder cosine(질의와 문서를 따로 임베딩)과 원형 어휘 coverage뿐이다.
- 이 두 신호로는 "부분 일치 + 약한 의미" 모양을 가진 정답(g1 부분 일치, 교차 언어 정답)과
  오탐(주제만 가까운 문서, 범용어 하나만 맞는 문서)이 **같은 좌표**에 놓인다.
- 그래서 문턱을 내리면 오탐이 돌아오고(N2 `낚시 포인트 추천`), 올리면 정답이 사라진다(N1 교차 언어,
  q_0057/q_0071 부분 일치 g1).

이 설계는 두 단계로 이 문제를 다룬다.

| 단계 | 무엇을 바꾸나 | 역할 | 기본값 |
|---|---|---|---|
| 1. 크로스 인코더 리랭커 | **판정**. 질의와 문서를 한 입력으로 읽는 `BAAI/bge-reranker-v2-m3`의 점수를 `R`의 근거 특징 `cross`로 넣고, semantic-only·low-signal·lexical-only 프로필의 결정 근거를 cosine floor에서 cross floor로 옮긴다 | 같은 좌표에 있던 정답과 오탐을 떼어 낸다 | A/B 채택 기준 통과 시 recorded/live에서 켬. mock은 끔 |
| 2. 소형 LLM 질의 보조 | **후보 수집**. 규칙이 저신호, 교차 언어, 모호로 분류한 질의에만 로컬 소형 LLM을 불러 검색어를 보강(재작성, 번역, 동의어)하고, 보강어로 별도 후보 수집 계획을 하나 더 돌린다 | 원 질의 어휘로는 후보에 들어오지 않던 정답을 후보 집합에 넣는다 | 채택 전까지 끔. 기본 엔진은 로컬. API는 사용자 동의 시에만 |

핵심 원칙 두 가지를 이 문서 전체에 적용한다.

1. **LLM은 후보를 넓히고, 판정은 원 질의로 한다.** 리랭커 입력 질의는 언제나 원 질의(`q₀`)에서
   만든다. LLM 보강어는 후보 수집과 보조 특징에만 쓰고, 보강어만으로는 게이트를 통과할 수 없다.
   그래서 LLM이 지어낸 동의어가 무관한 문서를 결과로 끌어올리지 못한다.
2. **모든 모델 출력은 녹화하고 재생한다.** recorded 모드는 리랭커 점수와 LLM 응답을 녹화본에서만
   읽고, 녹화본에 없으면 조용히 넘어가지 않고 에러를 낸다. A/B 판단은 recorded 결과로만 한다.

---

## 2. 배경: 문턱 하나로 해결되지 않는 이유

### 2.1 검수에서 확인된 사례

| 사례 | 증거 모양 (recorded) | 현재 결과 | 원인 |
|---|---|---|---|
| N1 ch_0017 `coffee cardiovascular health paper` | 원형 어휘 일치 0, cosine 중간, 전부 OOV라 low-signal | 정답 누락 | low-signal 문턱이 축소된 계수로 도달 불가. 문턱을 내리면 영어 오탐도 같이 통과할 위험 |
| N1 ch_0023 `retrieval augmented generation survey paper` | 같음 | 정답 누락 | 같음 |
| N2 q_0207 `낚시 포인트 추천` → `c_alice_0021` "가평 글램핑 추천" | 원형 일치 0, raw cosine 0.5135 (야외 활동 주제 근접) | 오탐 반환 | semantic-only 판정이 분포 중첩 구간 안의 cosine floor 하나에 걸려 있음 |
| N3 q_0180 `환경 다큐` → `c_alice_0113` "딥러닝 기반 음성 인식 개선" | `환경` 본문 일치, cosine 0.40 | 정답(sem 0.69)보다 위 | 단어 하나 일치가 coverage 전체가 됨 |
| q_0057, q_0071 (dev) | 세 어절 중 한 어절 일치, 의미 중간 | g1 정답 거부 | negative 오탐과 같은 증거 모양이라 함께 거부 |

dev 진단 기준으로 negative 최대 raw cosine은 0.484이고 정답 5분위는 0.458이다. 즉 **cosine 축
위에서는 두 분포가 겹친다.** 어떤 문턱을 골라도 한쪽을 잃는다.

### 2.2 크로스 인코더가 맞는 이유

bi-encoder는 질의와 문서를 독립적으로 벡터로 만들기 때문에 "주제가 가깝다"와 "이 질의가 찾는
것이다"를 구분하지 못한다. 크로스 인코더는 질의와 문서를 한 시퀀스로 넣고 토큰 간 상호작용을 직접
본다. 그래서 다음을 구분할 수 있다고 **가정한다** (12절 A/B로 검증한다).

- `낚시 포인트` 대 `글램핑`: 주제는 가깝지만 질의가 찾는 대상이 아니다 → 낮은 점수
- `coffee cardiovascular health` 대 한국어 "커피와 심혈관 건강" 논문: 다국어 쌍 판정 → 높은 점수
- `환경 다큐` 대 "딥러닝 음성 인식": `환경`이 본문에 있어도 질의 의도와 무관 → 낮은 점수

`bge-reranker-v2-m3`는 bge-m3와 같은 XLM-RoBERTa 계열 다국어 모델이라 한국어·영어 혼합 쌍을
다룰 수 있고, 로컬에서 돌아가 저장물 원문이 밖으로 나가지 않는다 (PRD Q6 원칙과 같다).

### 2.3 LLM 보조가 필요한 이유 (리랭커와 다른 문제)

리랭커는 **이미 후보에 들어온** 문서만 다시 판정한다. 원 질의 어휘와 cosine으로 후보에 오르지
못한 정답은 리랭커가 구할 수 없다. 이런 질의는 대개 다음 모양이다.

- 저신호: 원형 토큰이 비었거나 전부 OOV이고 교정도 실패 (`그때 그거 뭐였지`, `유툭 십분 홈트`)
- 교차 언어: 영어 핵심어인데 저장물은 한국어 (`ETF investment basics 영상`)
- 모호: 지시어 + 명사 1개 이하, 또는 범용어만 남음 (`그 다큐`, `추천 맛집`)

이 경우에만 LLM이 검색어를 보강해 후보 수집 범위를 넓힌다. 판정은 여전히 단계 1의 리랭커와
`R`이 원 질의 기준으로 한다.

---

## 3. 목표와 범위

### 3.1 목표

1. 크로스 인코더 점수를 문맥 독립 관련도 `R`의 근거로 넣어, 부분 일치·약한 의미 영역에서 정답과
   오탐을 떼어 낸다.
2. 리랭커를 상위 N개에만 적용해 지연 예산을 지키고, 실패하거나 시간이 지나면 v2 경로로 안전하게
   돌아간다.
3. 리랭커 점수와 LLM 응답을 녹화·재생해 recorded 모드 평가를 완전히 결정적으로 유지한다.
4. 소형 LLM은 규칙이 고른 질의에만 부르고, 검색어 보강만 하며, 필터를 바꾸지 못하게 구조로 막는다.
5. 두 단계 각각 켬/끔 A/B를 같은 하네스로 돌리고, PRD 3.5.5절 정신(절대 기준, 허용 하락, 신뢰구간,
   지연과 비용)의 채택 규칙으로만 기본값을 바꾼다.

### 3.2 하지 않는 것

- bge-m3 임베딩 모델 교체, 인덱스 구조 변경, 인제스트 경로 변경
- LLM 재순위(LLMReranker)와 생성형 답변. LLM은 질의 쪽만 다룬다.
- LLM이 기간·플랫폼·유형 필터나 의도(`lookup`/`browse`)를 바꾸는 것
- filter-only browse 경로에 리랭커나 LLM을 넣는 것
- 사용자 요청 잠금(`request_locks`)을 어떤 경우에도 푸는 것
- test split을 보며 계수, 문턱, 트리거 규칙을 조정하는 것
- 리랭커 파인튜닝. 사전학습 가중치를 그대로 쓰고 calibration만 한다.

---

## 4. 단계 1 — 크로스 인코더 리랭커

### 4.1 파이프라인 위치

완화 정책 v2의 6.2절 흐름에 단계 하나를 넣는다.

```
q₀ 고정 → 계획별 후보 수집 → content_id 합집합 (요청 잠금 postcondition)
   → [기존] CandidateEvidence 원자 특징 계산 → R_base (v2 로지스틱)
   → [신규] 리랭크 창 선택 (4.3절) → CrossEncoder 채점 (창 안 문서만, 요청당 1회)
   → [신규] cross 특징 calibration → R (v3 로지스틱, cross 포함)
   → [변경] RelevanceGate v3 (4.6절, 프로필별 cross floor)
   → [기존] 비용 C, 효용 U = R − C, 계획 선택, 완화 기록
```

- 리랭커는 **요청당 한 번, 합집합 위에서** 돈다. 계획마다 따로 돌리지 않는다. 그래서 한 요청 안에서
  같은 문서는 모든 계획에서 같은 `cross`와 같은 `R`을 갖는다 (INV-02 유지).
- 완화 비교식 `R(c) − R(i) > [C(c) − C(i)] + Δmin + ε`은 바꾸지 않는다. `R`이 좋아지면 완화 판단도
  같은 식 그대로 좋아진다.

### 4.2 게이트와의 관계 — 결정

세 가지 안을 비교했다.

| 안 | 내용 | 장점 | 단점 | 판정 |
|---|---|---|---|---|
| A. cross를 `R`의 근거 특징으로 넣고, 프로필 게이트의 결정 근거를 cross floor로 옮긴다 | `R = σ(… + βr·cross)`. semantic-only·low-signal은 cosine floor 대신 cross floor 통과 필수 | 완화 정책 v2의 단일 점수·효용 수식을 그대로 쓴다. 원형 어휘 증거와 함께 판단한다. 리랭커가 빠져도 v2로 돌아갈 수 있다 | 계수와 문턱을 다시 calibration해야 한다 | **채택** |
| B. 게이트를 cross 문턱 하나로 대체 | `cross ≥ τ`면 통과 | 단순하다 | 문턱 하나로 다시 시소가 생긴다. 크로스 인코더 점수도 질의 유형마다 보정 정도가 다르다. 원형 어휘 증거를 버린다. 리랭커 장애 시 게이트가 없다 | 기각 |
| C. 순위만 cross로 바꾸고 게이트는 v2 그대로 | 표시 순서만 개선 | 영향이 작다 | N1, N2는 게이트 문제라 해결되지 않는다 | 기각 |

**채택안 A의 세부 규칙**

1. `cross`는 `R`의 특징 중 하나다. 다른 특징처럼 음수가 아닌 계수를 갖는다. 기존 제약 `βo > βc`는
   유지한다.
2. 증거 신호 집합에 `cross`를 추가한다. 단, `semantic`과 `cross`는 둘 다 의미 계열이라 **둘만으로는
   corroborated가 되지 않는다.** corroborated는 {의미 계열(semantic 또는 cross), 원형 어휘, 목적} 중
   서로 다른 두 계열 이상이 유효할 때다.
3. 프로필별 게이트 결정 근거는 4.6절 표를 따른다. 요약하면 cosine floor는 남겨 두되 결정은 cross
   floor가 한다.
4. 리랭커가 실패, 타임아웃, 비활성인 요청은 **v2 설정 묶음**(v2 계수, v2 문턱)으로 계산한다. 한 응답
   안에서 두 척도를 섞지 않는다 (4.7절).

### 4.3 상위 N개 리랭크 창

리랭커 비용은 문서 수에 비례하므로 창을 제한한다. 창 선택 기준은 문맥 독립 값인 `R_base`다.

- **창** = 다음 두 집합의 합집합. 중복 제거 후 `R_base` 내림차순, 동점은 `content_id` 오름차순.
  1. 전체 합집합에서 `R_base ≥ τ_pre`인 문서 중 상위 `N_global`개
  2. 계획마다 그 계획이 허용하는 후보 중 `R_base` 상위 `k_plan`개 (strict 계획의 incumbent가
     창 밖에 남지 않게 한다)
- 창 크기 상한 `N_max`를 넘으면 `R_base` 순으로 자르고 `rerank_truncated`를 진단에 남긴다.
- 시작값 (T35에서 recorded dev로 확정)

| 설정 | 시작값 | 비고 |
|---|---:|---|
| `N_global` | 20 | PRD 4.3절 ⑥과 같다 |
| `k_plan` | 3 | |
| `N_max` | 32 | 지연 예산 상한 |
| `τ_pre` | 0.15 | `R_base` 척도. 확실한 잡음만 제외하는 낮은 값 |

**창 밖 문서 처리**

- 창 밖 문서는 `cross` 특징이 없다. `R` 계산에서 `cross = 0`으로 두지 않는다 (0은 "무관" 판정과
  구별되지 않는다). 대신 `rerank_scored = false`로 표시한다.
- 창 밖 문서는 **corroborated 프로필이고 v3 척도에서 `R_unscored ≥ τ_unscored`일 때만** 반환할 수
  있다. 여기서 `R_unscored`는 cross 항을 뺀 v3 로지스틱이다. 시작값 `τ_unscored`는 corroborated
  문턱 + 0.05.
- 창 밖 문서는 반환되더라도 창 안 문서 뒤에 `R_unscored` 순으로 붙는다. 이 규칙은 `limit`이 창
  크기보다 클 때(예: `limit=50`)의 꼬리에만 영향을 준다.

**문맥 독립성에 대한 정확한 계약**

- 크로스 인코더 점수 자체는 (리랭커 질의, 문서 텍스트) 쌍의 순수 함수다.
- 한 요청 안에서는 같은 문서의 `cross`와 `R`이 모든 계획에서 같다 (INV-R1).
- 요청 간에는 `limit`, `now`, 요청 잠금이 달라질 때 **창에 들어가는지 여부**가 달라질 수 있다.
  두 실행에서 모두 채점된 문서의 `R`은 같아야 한다 (INV-R2). 채점 여부만 다를 수 있다는 사실을
  INV-02의 개정으로 문서화한다.
- `limit`은 창 선택에 쓰지 않는다. 그래서 `limit`만 바뀐 두 요청은 창이 같다 (INV-R3).

### 4.4 리랭커 입력 텍스트

완화 정책 v2는 `R`에 facet 일치 보너스를 넣지 않는다. 리랭커 입력도 같은 원칙을 지킨다.

- **리랭커 질의** `rerank_query`: `q₀.semantic_text_original`에서 기간, 플랫폼, **유형** 표현 span을 모두
  지운 문장. 목적어는 남긴다. 비면 `original_terms`를 공백으로 이은 문자열. 그것도 비면 이 요청은
  리랭크를 건너뛴다 (`rerank_skipped: empty_query`).
  - 예: `assignment에 쓸 climate crisis paper` → `assignment에 쓸 climate crisis`
  - 유형 단어를 지우는 이유: 문서 텍스트에 유형이 들어가면 유형 일치가 cross 점수 보너스가 되어
    facet 비용 수식과 이중 계산된다.
  - LLM 보강어(단계 2)는 리랭커 질의에 넣지 않는다 (1절 원칙 1).
- **리랭커 문서 텍스트** `rerank_doc_text`: `title`, 유효 대표 태그(사용자 태그 우선, 숨긴 AI 태그 제외),
  최신 요약, 세부 태그 핵심(entities, locations, topics, purpose), user_note, 본문 앞부분 순으로 이어
  붙이고 토큰 예산 안에서 자른다. **플랫폼, 유형, 저장 시각, 작성자는 넣지 않는다.**
  - 문서 텍스트는 `build_rerank_text(doc: IndexDocument, max_chars: int) -> RerankText(text, text_hash)`로
    인덱싱 시점에 만들 수 있지만, MVP는 검색 시점에 `IndexDocument`에서 만든다 (결정적, 수 µs).
- 쌍 최대 길이 `max_length = 384` 토큰 (시작값). 문서 쪽은 문자 수 예산 `max_doc_chars = 600`으로 먼저
  자른다. 질의가 200자 상한이라 질의 쪽 잘림은 없다.

### 4.5 점수와 calibration

- 모델 원점수는 로짓이다. 녹화본에는 **원 로짓**을 저장한다.
- `cross_prob = sigmoid(logit)` (0..1).
- `cross = calibrate(cross_prob)`: model id와 revision을 키로 갖는 단조 구간 선형 함수. 시작값은
  항등 함수다. T35에서 recorded dev 쌍(정답 등급 ≥1 대 negative·무관 후보)의 분포를 보고 구간점을 정한다.
- calibration과 계수는 `RelevanceSettings`의 새 버전 `relevance-v3-cross`에 두고, v2 묶음
  `relevance-v2.x`와 나란히 보관한다.

### 4.6 RelevanceGate v3

v3 묶음에서 프로필 정의와 결정 근거는 다음과 같다. 숫자는 시작값이고 T35에서 recorded dev로만
정한다.

| 프로필 | 정의 | R 문턱 | 결정 근거 (추가 조건) |
|---|---|---:|---|
| corroborated | 서로 다른 증거 계열 둘 이상 (4.2절 2) | 0.45 | `cross ≥ 0.05` (거의 확실한 무관만 거부하는 약한 veto) |
| semantic-only | 원형 어휘 일치 없음, 의미 계열만 유효 | 0.45 | `cross ≥ cross_floor_semantic` (시작 0.50). cosine floor는 0.45로 낮춰 보조 조건으로만 둔다 |
| lexical-only | 의미 계열이 floor 미만, 원형 어휘만 유효 | 0.44 | `cross ≥ cross_floor_lexical` (시작 0.20). 단어 하나만 맞는 무관 문서를 거른다 (N3) |
| low-signal 질의 | 질의 자체가 저신호 (기존 정의) | 문서 프로필 문턱과 같음 | `cross ≥ cross_floor_low_signal` (시작 0.60). R 문턱을 따로 올리지 않는다 (N1의 교훈) |

**도달 가능성 불변식 (N1 재발 방지)**

- 각 프로필에 대해 "그 프로필이 가질 수 있는 특징 최대값으로 계산한 `R`이 문턱보다 0.05 이상 크다"를
  설정 로딩 시 검사한다. 어기면 설정 에러로 컨테이너 생성이 실패한다 (INV-R6).
- low-signal 보정은 R 문턱이 아니라 **증거 공간의 floor**(cross floor)로만 정의한다.

**리랭커를 쓸 수 없을 때**

- v2 묶음의 게이트(현재 Loop 3 결과)를 그대로 쓴다. 이때 응답에 `degraded_reasons: ["reranker_skipped:<사유>"]`를
  남긴다.

### 4.7 실패, 타임아웃, 성능 저하 처리

| 상황 | 동작 | 기록 |
|---|---|---|
| optional extra 미설치, 모델 로드 실패 | 컨테이너 생성 시 `rerank.enabled=true`면 시작을 실패시킨다 (`RerankerUnavailable`). `rerank.required=false`면 경고 로그 후 리랭커 없이 시작 | 시작 로그 |
| 요청 중 타임아웃 (`rerank.timeout_ms`, 시작 300) | 결과를 기다리지 않고 v2 묶음으로 계산 | `reranker_skipped:timeout` |
| 추론 예외 | 같음 | `reranker_skipped:error` |
| 실행기가 바쁨 (이전 요청 추론이 아직 진행 중) | 큐에 쌓지 않고 바로 v2 묶음 | `reranker_skipped:busy` |
| recorded 모드 녹화본 미스 | **에러** `RerankCacheMiss`. 평가 실행 실패 | 하네스 실패 |

- torch 추론은 중간에 취소할 수 없다. 그래서 단일 워커 실행기를 쓰고, 워커가 바쁘면 새 요청은
  기다리지 않고 건너뛴다. 타임아웃 난 추론은 끝까지 돌지만 결과는 버린다.
- 한 응답 안에서 v2와 v3 척도를 섞지 않는다. 리랭크가 일부 문서만 끝났어도 전부 버리고 v2로 간다.

### 4.8 장치(mps/cpu), 정밀도, 메모리

| 설정 | 값 | 비고 |
|---|---|---|
| `rerank.device` | `auto` (기본) / `mps` / `cpu` | `auto`는 `torch.backends.mps.is_available()`이면 mps, 아니면 cpu |
| 정밀도 | mps: fp16, cpu: fp32 | `rerank.dtype`으로 덮어쓸 수 있다 |
| 배치 | 창 전체를 한 배치 (최대 32쌍) | mps에서 배치 하나가 가장 빠르다고 가정. T31에서 확인 |
| warm-up | 컨테이너 생성 시 더미 쌍 4개로 1회 추론 | 첫 요청 지연 제거 |
| cpu 정책 | T31 벤치마크에서 cpu p95가 예산을 넘으면 `device=cpu`일 때 기본 비활성 (`rerank.enabled_on_cpu=false`) | 사용자가 명시하면 켤 수 있다 |

- 메모리: 모델(약 568M 파라미터) fp16 약 1.1GB, fp32 약 2.3GB. bge-m3와 함께 올려도 개발 장비
  (Apple M5, 24GB)에서 여유가 있다. T31에서 RSS 증가를 잰다.
- live 결정성: mps fp16은 실행마다 마지막 자리 값이 달라질 수 있다. live 결과는 평가 판정에 쓰지 않고,
  녹화본은 첫 녹화 값을 정본으로 삼는다.

### 4.9 지연 예산

PRD 4.3절 ⑥의 "상위 20개 p95 ≤ 120ms (CPU)"는 실측 근거가 없다. 이번 설계는 장치별 예산으로 바꾸고,
T31 벤치마크로 실현 가능성을 먼저 확인한다 (go/no-go).

| 항목 | mps 예산 | cpu 예산 |
|---|---:|---:|
| 리랭크 단계 p95 (창 20쌍, 384토큰) | ≤ 150ms | ≤ 400ms (넘으면 cpu 기본 비활성) |
| 리랭크 단계 p95 (창 32쌍) | ≤ 220ms | 해당 없음 |
| 검색 전체 p95 (LLM 보조 없음, live) | ≤ 300ms (PRD 4.3절과 같다) | ≤ 600ms |
| 타임아웃 | 300ms | 500ms |

- 측정 조건: warm 상태, 사용자 u_alice 시드 200건, dev 질의 전체를 3회 반복, 단일 프로세스.
- recorded 모드 지연은 재생 지연이라 채택 판단에 쓰지 않는다. 지연은 live 벤치마크(`jupjup bench search`)로만
  판단한다.
- T31에서 mps p95가 예산의 1.5배를 넘으면 `max_length`를 256으로, `N_global`을 12로 줄인 설정을 함께 재고,
  그래도 넘으면 단계 1을 보류하고 PM에 보고한다.

### 4.10 optional extra 분리

```toml
[project.optional-dependencies]
embed  = ["sentence-transformers>=5.1,<6"]          # 기존
rerank = ["sentence-transformers>=5.1,<6"]          # CrossEncoder. embed와 같은 패키지
local-models = ["jupjup[embed,rerank]"]
assist-local = ["llama-cpp-python>=0.3,<0.4"]       # 단계 2. 버전은 T39에서 확정
assist-api   = ["anthropic>=1,<2"]                  # 단계 2 API 선택 옵션
```

- `providers/rerank_bge.py`는 모듈 안에서 지연 import한다. mock과 recorded 경로는 torch,
  sentence-transformers를 import하지 않는다 (AC: 기본 설치로 mock/recorded 테스트 전부 통과).
- 모델 가중치 캐시는 기존 `var/models/`를 공유한다 (`JUPJUP_MODEL_CACHE_DIR`). 모델 revision(HF commit
  hash)을 설정에 고정한다.

### 4.11 녹화와 재생

임베딩 녹화(`data/recordings/embeddings.bge-m3.jsonl`)와 같은 방식이다.

- 파일: `data/recordings/rerank.bge-reranker-v2-m3.jsonl`
- 행 형식 (원문을 넣지 않는다)

```json
{"model_id":"bge-reranker-v2-m3","revision":"<hf-commit>","pair_hash":"<sha256>","query_hash":"<sha256>",
 "doc_hash":"<sha256>","max_length":384,"logit":-3.21875}
```

- `pair_hash = sha256(model_id \0 revision \0 max_length \0 rerank_query \0 rerank_doc_text)`.
  입력 텍스트 구성 규칙(4.4절)이나 `max_length`가 바뀌면 키가 바뀌어 캐시 미스로 드러난다.
- `RecordingReranker`: live 리랭커를 감싸 새 쌍만 덧붙인다. `RecordedReranker`: 녹화본만 읽고, 없으면
  `RerankCacheMiss`(쌍 해시와 질의 해시 포함).
- **녹화 범위**: `jupjup rerank record` 명령이 골든 queries(dev+test), challenge, recorded_probes 전체를
  돌면서, 각 질의의 합집합에서 `R_base` 상위 **50개**와 계획별 상위 5개를 녹화한다. 실제 창(최대 32)보다
  넓게 녹화해 T35에서 `N_global`, `k_plan`, `τ_pre`를 바꿔도 다시 녹화하지 않게 한다.
- `R_base`는 v2 계수에 의존하므로 v2 계수를 바꾸면 창 구성이 바뀔 수 있다. 녹화 범위를 넓게 잡은 이유가
  이것이다. 그래도 미스가 나면 녹화를 갱신하고, 갱신 사실과 추가된 쌍 수를 보고서에 남긴다.
- 녹화 크기 예상: 질의 약 300개 × 쌍 약 60개 = 약 18,000행, 행당 약 300바이트 → 약 5MB. 커밋한다
  (PRD Q9 규칙: 10MB를 넘으면 Git LFS).
- 녹화 명령은 녹화 전에 예상 쌍 수와 예상 시간을 출력한다 (네트워크 비용은 없다).

### 4.12 mock 모드

- mock 모드의 기본값은 **리랭커 끔**이다. `MockReranker`(문자 2-gram 자카드)는 실제 리랭커의 품질을
  대표하지 않고, mock 기준선을 흔들기만 한다.
- `MockReranker`는 배선 테스트(창 선택, 타임아웃 경로, v2 폴백, 녹화 키)에만 쓴다. 지연 주입과 예외
  주입 옵션을 추가한다 (`MockReranker(delay_ms=…, fail_on=…)`).

### 4.13 설정 스키마

```python
class RerankModelSettings(BaseModel):          # SearchSettings.cross_rerank
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False                      # 채택 결정 후 recorded/live 기본값을 True로 바꾼다
    required: bool = False                     # True면 로드 실패 시 시작 실패
    model_name: str = "BAAI/bge-reranker-v2-m3"
    model_id: str = "bge-reranker-v2-m3"
    revision: str = ""                         # 빈 값이면 live 시작 거부
    device: Literal["auto", "mps", "cpu"] = "auto"
    dtype: Literal["auto", "fp16", "fp32"] = "auto"
    enabled_on_cpu: bool = True                # T31 결과로 기본값 결정
    max_length: int = 384
    max_doc_chars: int = 600
    n_global: int = 20
    k_plan: int = 3
    n_max: int = 32
    pre_threshold: float = 0.15                # τ_pre (R_base 척도)
    timeout_ms: int = 300
    recording_path: Path = Path("data/recordings/rerank.bge-reranker-v2-m3.jsonl")
```

- `RelevanceSettings`에 `profiles: dict[str, RelevanceProfile]`를 두고 `"v2"`와 `"v3-cross"` 두 묶음을
  보관한다. `RelevanceProfile`은 계수, calibration, 게이트 문턱, floor를 함께 가진다. 기존 단일 필드는
  `"v2"` 묶음으로 옮긴다 (설정 마이그레이션은 T34 범위).
- `search_overrides`로 두 묶음 모두 덮어쓸 수 있다 (AC-20 유지).

### 4.14 인터페이스

```python
# providers/rerank.py (확장)
class Reranker(Protocol):
    model_id: str
    revision: str
    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]: ...
        # 원 로짓. 실패 시 RerankerError

class MockReranker(Reranker):              # 결정적. delay_ms, fail_on으로 지연·예외 주입
    def __init__(self, delay_ms: int = 0, fail_on: Collection[str] = ()) -> None: ...
class RecordingReranker(Reranker):
    def __init__(self, inner: Reranker, store_path: Path, max_length: int) -> None: ...
class RecordedReranker(Reranker):          # 미스면 RerankCacheMiss
    def __init__(self, store_path: Path, model_id: str, revision: str, max_length: int) -> None: ...

# providers/rerank_bge.py (신규, optional extra [rerank])
class BgeCrossEncoderReranker(Reranker):
    def __init__(self, settings: RerankModelSettings, cache_dir: Path | None = None) -> None: ...
    def warm_up(self) -> None: ...

# search/cross_rerank.py (신규)
class RerankText(BaseModel):
    text: str; text_hash: str
def build_rerank_query(q0: ParsedQuery) -> str | None
def build_rerank_text(doc: IndexDocument, max_chars: int) -> RerankText

class RerankWindow(BaseModel):
    content_ids: list[str]; truncated: bool; reasons: dict[str, str]   # id → "global" | "plan:<plan_id>"

class CrossRerankOutcome(BaseModel):
    status: Literal["scored", "skipped"]
    skip_reason: Literal["disabled", "timeout", "error", "busy", "empty_query", "cpu_disabled"] | None
    scores: dict[str, float]                 # content_id → calibrated cross (창 안 문서만)
    logits: dict[str, float]
    latency_ms: float; device: str; model_id: str; revision: str

class CrossRerankStage:
    def __init__(self, reranker: Reranker | None, settings: RerankModelSettings,
                 calibration: CrossCalibration, executor: SingleFlightExecutor): ...
    def select_window(self, base: Mapping[str, float], plan_members: Mapping[str, Sequence[str]]) -> RerankWindow
    def score(self, q0: ParsedQuery, window: RerankWindow, docs: Mapping[str, IndexDocument]) -> CrossRerankOutcome

# search/relevance.py (확장)
class RelevanceScorer:
    def score_base(self, q0, document, index) -> CandidateEvidence          # 기존 v2
    def apply_cross(self, evidence: CandidateEvidence, cross: float | None,
                    profile: RelevanceProfile) -> CandidateEvidence          # v3 R, signals, profile 갱신

# domain/errors.py
class RerankerError(ProviderError): ...
class RerankerUnavailable(RerankerError): ...
class RerankCacheMiss(RerankerError): ...
```

- `CandidateEvidence`에 추가: `cross: float | None`, `cross_logit: float | None`, `rerank_scored: bool`,
  `relevance_profile: Literal["v2", "v3-cross"]`, `relevance_base: float`.
- `explain=true` debug에 `rerank` 블록 추가: 창 구성과 사유, 상태, 건너뛴 사유, 지연, 장치, 문서별
  `logit/cross/R_base/R`.
- 검색 파이프라인은 구체 리랭커 클래스를 import하지 않는다. `AppContainer`가 모드에 따라
  `Mock/Recorded/Recording(Bge)`를 조립한다 (AC-19).

---

## 5. 단계 2 — 소형 LLM 질의 보조 (QueryAssistant v2)

### 5.1 호출 조건: 규칙 기반 트리거

LLM은 아래 세 분류 중 하나에 걸린 질의에만 부른다. 분류는 결정적 규칙이고, 결과는 `AssistTrigger`로
응답 debug와 평가 리포트에 남는다.

| 분류 | 규칙 (모두 q₀와 사용자 어휘만 사용) | 예 |
|---|---|---|
| `low_signal` | `q₀.query_signal_profile == "low-signal"`, 또는 `original_terms`가 비었는데 filter-only가 아님 | `그때 그거 뭐였지`, `유툭 십분 전신 홈트 그거` |
| `cross_lingual` | 잔여 내용 토큰 중 라틴 문자 토큰 비율 ≥ 0.5이고, 라틴 내용 토큰 중 하나 이상이 사용자 어휘와 curated 별칭에 없음 | `ETF investment basics 영상`, `coffee cardiovascular health paper` |
| `ambiguous` | (a) 지시어 + 내용 명사 ≤ 1개, 또는 (b) 원형 내용어가 모두 `weak_lexical_terms`(범용어), 또는 (c) 원형 내용어가 모두 OOV이고 신뢰도 ≥ 0.75 교정이 하나도 없음 | `그 다큐`, `추천 맛집 저장한 거` |

- 부르지 않는 경우: filter-only browse, 위 셋에 걸리지 않는 정상 질의, `qu_assist.enabled=false`,
  사용자 질의가 입력 검증에서 거부된 경우.
- 트리거 비율 목표: dev 전체 질의의 25% 이하. T37에서 dev 비율을 보고하고, 넘으면 규칙을 좁힌다.
- 기존 `QueryAssistant.is_ambiguous`는 이 분류기로 교체한다.

### 5.2 LLM이 할 수 있는 일과 없는 일

**할 수 있는 일 (검색어 보강만)**

- 재작성: 원 질의 뜻을 유지한 한국어 바꿔 쓰기 최대 2개
- 번역: 외국어 핵심어의 한국어 대응어 최대 5쌍
- 동의어: 원형 핵심어별 동의어·유사어 최대 3개, 전체 최대 8개

**할 수 없는 일 (구조로 막는다)**

- 기간, 플랫폼, 유형, 의도, 결과 수, 정렬을 바꾸는 것. 출력 스키마에 그런 필드가 아예 없다.
- 보강어 안에 facet 표현을 섞어 우회하는 것. 5.4절 facet 가드가 지운다.
- 판정에 끼어드는 것. 리랭커 질의와 `semantic_text_original`, `original_terms`는 바뀌지 않는다.

### 5.3 출력 스키마

```python
class AssistTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=40)     # 원 질의에 있는 표현
    ko: str = Field(min_length=1, max_length=20)

class AssistSynonym(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1, max_length=20)       # 원 질의에 있는 표현
    alternatives: list[str] = Field(max_length=3)

class AssistOutput(BaseModel):                           # schema_version "qa-1"
    model_config = ConfigDict(extra="forbid")
    rewrites: list[str] = Field(default_factory=list, max_length=2)      # 각 ≤ 60자
    translations: list[AssistTranslation] = Field(default_factory=list, max_length=5)
    synonyms: list[AssistSynonym] = Field(default_factory=list, max_length=5)
```

- 로컬 런타임은 이 스키마로 만든 JSON Schema 문법 제약(grammar-constrained decoding)으로 생성한다.
  API는 `output_config.format` 구조화 출력을 쓴다. 어느 쪽이든 결과는 아래 검증을 반드시 거친다.

### 5.4 검증과 폴백

`validate_assist(output_text, q0, lexicon, temporal, facets) -> AssistResult` 순서:

1. **JSON 파싱과 스키마 검증** (`extra=forbid`, 길이 제한). 실패 → 폴백.
2. **근거 검사**: `translations[].source`, `synonyms[].term`은 정규화한 원 질의 안에 실제로 있어야 한다.
   없는 항목은 버린다.
3. **facet 가드**: 모든 보강 문자열에 `TemporalParser.extract`와 `FacetExtractor.extract`를 돌린다.
   검출된 기간·플랫폼·유형 span은 지운다. 지운 뒤 비면 그 항목을 버린다. 가드가 지운 횟수를
   `facet_stripped`로 센다. (원 질의에 이미 있던 facet도 지운다. facet은 q₀가 이미 가지고 있다.)
4. **내용 검사**: 불용 표현, 기호만 있는 항목, 원형과 같은 항목, 200자를 넘는 항목을 버린다.
   한글·라틴·숫자 외 문자 비율이 30%를 넘는 항목을 버린다.
5. **개수 상한 재적용**과 결정적 정렬(입력 순서 유지, 중복 제거).
6. 남은 항목이 0개면 `status = "empty"`로 원래 경로를 탄다.

폴백 조건과 기록

| 상황 | 결과 | `assist.status` |
|---|---|---|
| 정상 | 보강 적용 | `applied` |
| 스키마 실패, JSON 깨짐 | 원래 경로 | `invalid_output` |
| 검증 후 남은 항목 0개 | 원래 경로 | `empty` |
| 타임아웃 | 원래 경로 | `timeout` |
| 런타임 오류, 모델 미로딩 | 원래 경로 | `error` |
| API 거절(`stop_reason == "refusal"`) | 원래 경로. Haiku 5.5는 서버 측 fallback이 없으므로 재시도하지 않는다 | `refused` |
| recorded 모드 녹화본 미스 | **에러** `AssistCacheMiss` | 하네스 실패 |

- 재요청하지 않는다. 검색 경로는 동기라 재시도할 시간이 없다.

### 5.5 보강어의 사용처

보강 결과는 `q₀`를 바꾸지 않고 `q₀.assist: AssistResult`로 **나란히** 붙는다. 요청 안에서 불변이다.

1. **후보 수집 (주 용도)**: 계획 집합에 `assist` 검색 계획을 하나 추가한다.
   - hard filter는 strict 계획과 같다 (요청 잠금 + 질의 facet). facet 완화는 하지 않는다. 즉 보강은
     후보를 넓힐 뿐 facet을 풀지 않는다. facet 완화가 필요하면 기존 완화 계획들이 그 일을 한다.
   - morph/ngram 검색어: `translations[].ko`, `synonyms[].alternatives`
   - 벡터 검색: `rewrites` 각각을 질의 임베딩해 최대값 사용 (최대 2회 추가 임베딩)
   - 이 계획의 후보는 합집합에 들어가 다른 후보와 똑같이 `R_base`, 리랭크 창, `R`, 게이트를 거친다.
   - 계획 선택과 완화 기록에서 `assist` 계획은 strict와 같은 facet 집합을 가지므로 완화로 기록되지 않는다.
     응답 `understanding`에 `assist_applied: true`와 보강어 목록을 남긴다 (사용자가 볼 수 있게).
2. **보조 특징 `assist_lexical`**: 보강어의 필드 가중 coverage. `canonical_lexical`과 같은 규칙으로
   제한한다.
   - 계수 `βa ≤ βc < βo`
   - 증거 계열로는 "보강 어휘"라는 별도 계열이지만, **원형 어휘나 의미 계열 없이 혼자서는 어떤
     프로필도 통과시키지 못한다** (INV-A3, INV-11과 같은 원칙)
3. **리랭커 질의에는 넣지 않는다** (4.4절). 단계 1이 켜져 있으면 판정은 원 질의 기준 cross가 한다.

### 5.6 모델 선택과 런타임

**기본값: 로컬 한국어 소형 모델**

| 후보 | 크기 | 장점 | 확인할 점 |
|---|---|---|---|
| EXAONE 3.5 2.4B Instruct | 2.4B | 한국어 지시 수행이 강함 | 라이선스(EXAONE AI Model License, 상업 이용 제한 여부)를 T39에서 확인 |
| Qwen2.5 3B Instruct | 3B | 다국어·JSON 출력 안정성 | 3B 체크포인트 라이선스(Qwen Research License 여부)를 T39에서 확인 |
| (라이선스 대안) Apache-2.0 계열 소형 모델 | 1.5~4B | 라이선스 제약 없음 | 위 두 후보가 라이선스 문제로 막힐 때만 같은 절차로 비교 |

- 비교는 T39 스파이크에서 같은 프롬프트, 같은 양자화(GGUF Q4_K_M), 같은 장비로 한다. 지표: 트리거된
  dev 질의의 스키마 첫 시도 통과율, facet 가드 발동률, 보강 후 트리거 부분집합 Recall@10, p50/p95 지연,
  메모리, 라이선스. 선택 규칙은 12.3절.

**런타임: llama.cpp (`llama-cpp-python`, Metal 가속) 기본**

| 안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| llama.cpp (`llama-cpp-python`) | macOS·Linux 공통, GGUF 양자화, JSON Schema 문법 제약 지원, 프로세스 내 실행 가능 | 빌드 옵션(Metal) 관리 | **기본** |
| MLX (`mlx-lm`) | Apple Silicon에서 빠를 수 있음 | Apple 전용, 구조화 출력 제약을 별도로 붙여야 함 | T39에서 지연만 비교 참고 |
| `llama-server` 별도 프로세스 | API 프로세스와 메모리·장애 분리 | 운영 대상 증가 | 설정 `assist.local.endpoint`로 선택 가능하게만 둔다 |

- 생성 설정: greedy(temperature 0), 고정 seed, `max_tokens = 160`, 컨텍스트 1024.
- 프롬프트는 버전 파일 `prompts/query_assist/qa-1.md`로 분리한다 (AC-35). 질의는 `<query>` 데이터 블록에
  넣고 지시로 취급하지 않도록 명시한다 (주입 저항).

**API 선택 옵션: `claude-haiku-5-5`**

- 아래 조건을 **모두** 만족할 때만 쓴다.
  1. 설정 `qu_assist.engine = "api"`
  2. 설정 `qu_assist.api_consent = true` (사용자가 "질의 문장이 Anthropic API로 전송된다"는 사실에 동의)
  3. 환경 변수나 `ant auth` 프로필로 자격 증명이 있음
- 전송 범위: 정규화된 질의 문장만 보낸다. 저장물 본문, 제목, 태그, 사용자 어휘는 보내지 않는다.
- 호출 설정: 공식 SDK `anthropic`, 모델 id `claude-haiku-5-5`(날짜 접미사 없음), `output_config.effort = "low"`,
  `output_config.format`에 `AssistOutput` JSON Schema, `max_tokens = 512`, 요청 타임아웃은 assist 타임아웃과
  같게, SDK 재시도 0회. sampling 파라미터(`temperature` 등)는 보내지 않는다 (Haiku 5.5는 기본값 외 값을
  거부한다).
- 단가: 입력 $0.10, 출력 $0.50 per MTok (2026-10 기준). 호출당 입력 약 400토큰, 출력 약 150토큰이면
  1,000회 호출에 약 $0.12다. 평가 live 실행은 PRD 3.5.5절처럼 비용 추정을 먼저 출력하고 `--confirm-cost`
  없이는 호출하지 않는다.
- 거절 응답은 서버 측 fallback이 없으므로 `refused`로 폴백한다.

### 5.7 실행 흐름과 지연 예산

```
parse(q) → q₀ (규칙) → trigger?
   ├─ 아니오 → 기존 경로 (LLM 호출 없음, 결과는 바이트 단위로 기존과 같아야 함)
   └─ 예 → [병렬] LLM 보강 시작 ─────────────────┐
           [병렬] 기존 계획들의 후보 수집 진행     │
                                                 ▼
           보강 도착(타임아웃 전) → assist 계획 후보 수집 → 합집합에 합류
           타임아웃 → assist 계획 생략 (status=timeout)
   → R_base → 리랭크 창 → cross → R → 게이트 → 계획 선택
```

- LLM 호출은 기존 후보 수집과 **병렬**로 돈다. 기다리는 시간은 LLM 시간에서 기존 수집 시간을 뺀 만큼이다.
- 리랭크 창 선택은 assist 후보까지 합친 뒤에 한다 (assist가 늦으면 assist 없이).

| 항목 | 로컬 (mps) 예산 | API 예산 |
|---|---:|---:|
| LLM 호출 p95 | ≤ 900ms | ≤ 900ms |
| 타임아웃 | 1,200ms | 1,200ms |
| 트리거된 질의의 검색 전체 p95 | ≤ 1,500ms | ≤ 1,500ms |
| 트리거되지 않은 질의 | 단계 1 예산과 같음 (추가 지연 0) | 같음 |

- PRD 4.3절의 "LLM 보조 포함 p95 ≤ 1.2초"는 리랭커 지연을 포함하지 않은 값이었다. 리랭커와 함께
  쓰므로 1.5초로 조정을 제안한다 (Q-RA6).
- 2~3B Q4 모델의 생성 속도로 보아 출력 160토큰 상한이 지연을 좌우한다고 가정한다. T39에서 실측하고,
  p95가 예산을 넘으면 출력 상한을 줄이거나(재작성 1개, 동의어 5개) 트리거를 좁힌다.
- 로컬 모델은 앱 시작 시 로드하고 warm-up 1회를 한다. 단일 워커이며, 바쁘면 기다리지 않고 `busy`로 폴백한다.

### 5.8 녹화와 재생

- 파일: `data/recordings/assist.<model_id>.jsonl` (예: `assist.exaone-3.5-2.4b-q4km.jsonl`,
  `assist.claude-haiku-5-5.jsonl`)
- 키: `sha256(engine \0 model_id \0 model_file_sha256_or_api_model \0 prompt_version \0 schema_version \0 decoding_params_json \0 normalized_query)`
- 행: `key`, `model_id`, `prompt_version`, `schema_version`, `raw_text`, `stop_reason`, `input_tokens`,
  `output_tokens`, `latency_ms`(참고용)
- **원 출력(raw_text)을 저장한다.** 검증 규칙(5.4절)을 바꿔도 같은 녹화본으로 다시 평가할 수 있다.
- 골든 질의는 합성 데이터라 질의에서 파생된 보강어를 녹화본에 남겨도 된다. 실제 사용자 질의는
  녹화하지 않는다 (live 서비스 경로에서 Recording 래퍼를 쓰지 않는다).
- `jupjup assist record --engine local|api [--confirm-cost]`: 트리거 규칙에 걸리는 골든·challenge·probe
  질의만 녹화한다. 트리거 규칙을 바꿔 새 질의가 걸리면 미스가 나고, 녹화를 갱신한다.
- recorded 모드에서 트리거 결정은 규칙이라 결정적이고, 그래서 LLM이 불리는 질의 집합도 고정이다.
- mock 모드: `MockLLM`에 트리거된 골든 질의별 고정 응답 fixture(`data/fixtures/assist_mock.jsonl`)를 두고,
  일부러 깨진 응답(스키마 위반, facet 섞인 보강, 빈 응답)을 섞어 검증·폴백 경로를 시험한다. mock 기본값은
  보조 끔이고, fixture는 배선 테스트에만 쓴다.

### 5.9 설정과 인터페이스

```python
class QueryAssistSettings(BaseModel):              # Settings.qu_assist (기존 qu_assist_enabled 대체)
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    engine: Literal["local", "api"] = "local"
    api_consent: bool = False                      # engine="api"이면 True여야 시작
    api_model: str = "claude-haiku-5-5"
    local_model_path: Path | None = None           # GGUF 파일
    local_model_id: str = ""                       # 녹화 키와 리포트용
    local_endpoint: str | None = None              # llama-server 사용 시
    prompt_version: str = "qa-1"
    timeout_ms: int = 1200
    max_output_tokens: int = 160
    trigger: AssistTriggerSettings = Field(default_factory=AssistTriggerSettings)
    recording_path: Path | None = None

class AssistTriggerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latin_ratio_min: float = 0.5
    deictic_max_nouns: int = 1
    enable_low_signal: bool = True
    enable_cross_lingual: bool = True
    enable_ambiguous: bool = True
```

```python
# query/assist.py (신규. 기존 understanding.py의 QueryAssistant를 옮긴다)
AssistTriggerKind = Literal["low_signal", "cross_lingual", "ambiguous"]

class AssistTrigger(BaseModel):
    kinds: list[AssistTriggerKind]; reasons: list[str]

class AssistResult(BaseModel):                     # 기존 AssistResult 대체
    status: Literal["applied", "empty", "invalid_output", "timeout", "error", "refused", "busy", "not_triggered"]
    trigger: AssistTrigger | None
    rewrites: list[str]; translations: list[AssistTranslation]; synonyms: list[AssistSynonym]
    terms: list[str]                               # translations.ko + synonyms.alternatives (정렬·중복 제거)
    facet_stripped: int; model_id: str; prompt_version: str; latency_ms: float

class AssistTriggerClassifier:
    def __init__(self, settings: AssistTriggerSettings, lexicon: Lexicon, intent: IntentClassifier): ...
    def classify(self, q0: ParsedQuery, vocabulary: Vocabulary | None) -> AssistTrigger | None

class QueryAssistant:
    def __init__(self, llm: LLMClient, settings: QueryAssistSettings, validator: AssistValidator,
                 executor: SingleFlightExecutor): ...
    def start(self, q0: ParsedQuery, trigger: AssistTrigger) -> AssistHandle   # 비동기 시작
    # AssistHandle.result(deadline) -> AssistResult (타임아웃이면 status="timeout")

class AssistValidator:
    def __init__(self, temporal: TemporalParser, facets: FacetExtractor, lexicon: Lexicon): ...
    def validate(self, raw_text: str, q0: ParsedQuery) -> AssistResult

# providers/llm_local.py (신규, extra [assist-local])
class LlamaCppLLM(LLMClient):
    def __init__(self, model_path: Path, model_id: str, n_ctx: int = 1024, seed: int = 0): ...
# providers/llm.py (확장, extra [assist-api])
class AnthropicLLM(LLMClient): ...                  # PRD T17 범위의 어댑터를 공유
class RecordingLLM(LLMClient): ...                  # PRD T21에 정의된 이름을 재사용 (없으면 신설)
class RecordedLLM(LLMClient): ...                   # 미스면 LLMCacheMiss (assist 경로에서는 AssistCacheMiss로 감쌈)
```

- `ParsedQuery`에 `assist: AssistResult | None` 필드를 추가한다. 기존 `llm_rewritten`은
  `assist is not None and assist.status == "applied"`로 계산하는 읽기 전용 속성으로 바꾼다.
- `QueryUnderstander.parse`는 트리거 판정까지만 하고 LLM을 직접 기다리지 않는다. 병렬 실행과 assist
  계획 조립은 `SearchService`가 맡는다. `parse_only`(`/v1/query:parse`)는 `assist=true` 옵션이 있을 때만
  보강을 기다린다.

---

## 6. 두 단계의 상호작용

| 조합 | 판정 | 후보 수집 | 기대 |
|---|---|---|---|
| 둘 다 끔 | v2 | 기존 계획 | 현재 Loop 3 결과 (기준) |
| 리랭커만 | v3-cross | 기존 계획 | 오탐 감소, 교차 언어·부분 일치 정답 통과 |
| 보조만 | v2 + `assist_lexical` | 기존 + assist | 후보 누락 정답 일부 회복. 판정이 약해 오탐 위험 → 보강어 단독 통과 금지로 막음 |
| 둘 다 | v3-cross + `assist_lexical` | 기존 + assist | 후보는 넓게, 판정은 원 질의 cross로. 목표 구성 |

- 단계 2는 단계 1 없이도 동작해야 한다 (리랭커 장애 시 폴백 때문). 다만 채택 판단은 "리랭커 켬" 상태를
  기준으로 한다 (12.2절).

---

## 7. 불변식

완화 정책 v2의 INV-01~INV-20은 모두 유지한다. INV-02는 4.3절 계약으로 개정한다. 새 불변식은 다음과 같다.

| ID | 불변식 | 테스트 오라클 |
|---|---|---|
| INV-R1 | 한 요청 안에서 같은 문서의 `cross`와 `R`은 모든 계획에서 같다 | 계획별 evidence 비교, 차이 ≤ 1e-6 |
| INV-R2 | 두 요청에서 모두 채점된 문서의 `R`은 `limit`, `now`, 요청 잠금과 무관하게 같다 | INV-02 테스트를 v3로 확장 |
| INV-R3 | `limit`만 다른 요청은 리랭크 창이 같다 | limit 1/2/10/50 창 비교 |
| INV-R4 | 리랭커 질의와 문서 텍스트에 플랫폼·유형·기간 표현과 메타가 없다 | `build_rerank_query/text` 단위 테스트. facet 추출기를 돌려 검출 0 |
| INV-R5 | 리랭커가 건너뛴 요청은 v2 묶음 결과와 바이트 단위로 같다 (debug의 skip 사유 제외) | 타임아웃·예외·busy 주입 후 v2 단독 실행과 비교 |
| INV-R6 | 각 프로필의 R 문턱은 그 프로필의 특징 최대값으로 도달 가능하다 (여유 0.05) | 설정 로딩 검사와 단위 테스트 |
| INV-R7 | 한 응답 안에서 v2와 v3 척도가 섞이지 않는다 | 결과 문서 전부 같은 `relevance_profile` |
| INV-R8 | recorded 모드는 녹화본 밖의 쌍을 만나면 실패한다 | 녹화본에서 한 행을 지운 뒤 `RerankCacheMiss` |
| INV-R9 | 창 밖 문서는 corroborated이고 `R_unscored ≥ τ_unscored`일 때만 반환되며 창 안 문서 뒤에 온다 | 합성 후보로 단위 테스트 |
| INV-A1 | 트리거되지 않은 질의는 보조를 켜도 결과가 바이트 단위로 같다 | dev 전체에서 비트리거 질의 결과 비교 |
| INV-A2 | LLM은 기간·플랫폼·유형·의도·요청 잠금을 바꾸지 못한다 | facet을 섞은 악성 fixture 응답 후 `ResolvedFilters`·hard filter 불변, 필터 위반 0 |
| INV-A3 | 보강 어휘만으로는 게이트를 통과할 수 없다 | original=0, 의미 계열 floor 미만, assist_lexical=1 후보 거부 |
| INV-A4 | 검증 실패, 타임아웃, 거절, 빈 결과는 모두 원래 경로로 돌아간다 | 상태별 fixture 후 결과가 보조 끔과 같음 |
| INV-A5 | 리랭커 질의와 `semantic_text_original`, `original_terms`는 보조 후에도 바뀌지 않는다 | 보조 전후 q₀ 필드 비교 |
| INV-A6 | assist 계획은 완화로 기록되지 않는다 | assist 후보가 1위여도 `applied_relaxations`에 보조 관련 기록 없음 |
| INV-A7 | API 엔진은 동의 플래그 없이 시작하지 않고, 질의 문장 외 데이터를 보내지 않는다 | 동의 없음 → 시작 실패. 요청 본문 캡처 테스트 |
| INV-A8 | recorded 모드는 녹화본 밖의 LLM 호출을 만나면 실패한다 | `AssistCacheMiss` |

---

## 8. 평가 설계: 켬/끔 A/B

### 8.1 실험 팔(arm)

| 팔 | 리랭커 | 보조 | 용도 |
|---|---|---|---|
| A0 | 끔 | 끔 | 기준. Loop 3 병합 커밋으로 고정 (T30) |
| A1 | 켬 | 끔 | 단계 1 채택 판단 |
| A2 | 끔 | 켬 | 단계 2 단독 영향 (참고) |
| A3 | 켬 | 켬 | 단계 2 채택 판단 |

- 모든 팔은 같은 골든셋, 같은 녹화본, 같은 v2 묶음 설정으로 돈다. 팔 사이에 바뀌는 것은 두 스위치와
  그에 딸린 묶음(v3-cross, assist 계수)뿐이다.
- 하네스 명령: `jupjup eval ab --mode recorded --split dev --arms A0,A1,A2,A3 --out reports/ab_<날짜>.json`.
  각 팔의 `EvalReport`와 팔 간 비교표(`ABComparison`)를 함께 낸다.

### 8.2 지표

- PRD 3.2절 전 지표와 v2 13.3절 추가 지표 (카테고리별, split별)
- challenge positive Recall@10, challenge negative true empty
- **트리거 부분집합 지표** (단계 2): 트리거된 질의만으로 계산한 Recall@10, nDCG@10, true/false empty.
  분류별(low_signal, cross_lingual, ambiguous)로도 낸다.
- 단계별 운영 지표: 리랭크 skip 비율과 사유별 비율, 창 크기 분포, `rerank_truncated` 비율, 보조 트리거
  비율, 상태별 비율(`applied/empty/invalid_output/timeout/...`), facet 가드 발동 수, 스키마 첫 시도 통과율
- 지연 (live 벤치마크만): 단계별 p50/p95, 검색 전체 p50/p95, 장치별
- 비용: API 팔만. 호출당 토큰과 1,000질의당 추정 비용

### 8.3 통계 방법

- **질의 단위 쌍 부트스트랩**: 같은 질의의 두 팔 지표 차이를 1,000회 재표집하고 95% 구간을 낸다.
  seed를 고정해 결정적으로 만든다 (`seed = 20261030`).
- 표본이 작으므로(dev positive 약 140, negative 약 15, challenge dev 16) 구간이 넓다. 그래서 다음을 함께
  보고한다.
  - 질의별 승/패/무 개수와 부호 검정 p값
  - 개선·악화된 질의 목록 (id, 질의, 지표 전후, 1위 문서 전후)
- 비율 지표(true empty, false empty)는 분모와 분자를 같이 쓴다 (v2 10.1절 `MetricObservation`).

### 8.4 데이터 사용 규칙 (v2 13.1절 확장)

1. 모든 계수, calibration, 문턱, 창 크기, 트리거 규칙은 **recorded dev만** 보고 정한다.
2. challenge dev는 dev와 같은 취급이다. challenge test와 queries test는 최종 확인에만 쓴다.
3. 고정 회귀 사례(9절)는 불변식 확인에만 쓰고 튜닝 목적 함수에 넣지 않는다.
4. 설정을 동결하고 dev 결과를 보고한 뒤에만 test를 **팔마다 한 번** 돌린다 (T44).
5. 현재 test split은 이미 여러 번 소비됐다 (Loop 2 검수 L3). PM·사용자가 동결 test v2를 만들기로
   결정하면 T44는 test v2로 판정하고, 기존 test는 회귀 확인용으로만 쓴다. 결정이 없으면 기존 test로
   판정하되 "blind가 아님"을 보고서에 명시한다 (Q-RA1).

---

## 9. 고정 회귀 사례와 challenge set 기대 효과

### 9.1 반드시 유지할 사례 (모든 팔 공통)

완화 정책 v2 12절 표 전부와 Loop 2 검수 1.3절의 정상 동작 사례(S7, q_0173, `다리 운동 영상`,
`경주 맛집 인스타`, `하체 운동 유튜브`, `경주 맛집 카톡 논문`, `지지난주 성수 카페 약속`, 요청 잠금
사례, 오타 사례, browse)가 A1과 A3에서도 1위, 완화 기록, 빈 결과 여부까지 그대로여야 한다. 리랭커가
순위를 바꾸더라도 1위가 바뀌면 실패다. 1위가 바뀌는 사례가 나오면 그 사례의 cross 값과 원인을
보고하고 PM이 판단한다 (기대값을 몰래 바꾸지 않는다).

### 9.2 개선을 기대하는 사례

아래 기대는 **가설**이다. 각 행의 오라클로 A/B에서 확인하고, 맞지 않으면 그대로 보고한다.
test 사례는 튜닝에 쓰지 않으므로 dev 대응 사례를 함께 적는다.

| 사례 | split | 현재 (A0, Loop 2 기준) | 단계 1 기대 (A1) | 단계 2 기대 (A3) | 오라클 |
|---|---|---|---|---|---|
| ch_0017 `coffee cardiovascular health paper` | test | empty | 정답 cross 높음 → low-signal cross floor 통과 | 번역 보강(커피, 심혈관)으로 후보 순위 상승 | 정답 top 3 |
| ch_0023 `retrieval augmented generation survey paper` | test | empty | 같음 | 번역 보강(검색증강생성) | 정답 top 3 |
| ch_0001, ch_0003, ch_0009, ch_0015 (교차 언어 dev 대응) | dev | 대부분 통과 | 유지 또는 순위 상승 | 유지 | Recall@10 하락 없음, ch_0003 `c_alice_0096` 1위 유지 |
| q_0207 `낚시 포인트 추천` | test | `c_alice_0021` 오탐 | 글램핑 문서 cross 낮음 → semantic-only cross floor 탈락 → empty | 트리거될 수 있음(범용어 `추천`). 보강어 단독 통과 금지라 empty 유지 | empty |
| q_0199, q_0203, q_0206, q_0211, ch_0011, ch_0012 (negative dev 대응) | dev | empty | empty 유지 | empty 유지 | true empty 1.0 유지 |
| q_0180 `환경 다큐` | test | 정답 5위 (MRR 0.2) | 음성 인식 논문 cross 낮음 → lexical-only cross floor 탈락. 정답 1위 | 유지 | 정답 1위 |
| (신규 dev 대응) "범용어 + 핵심어 1개" 사례 | dev | T37에서 추가 | 의미가 강한 정답이 단일 단어 일치 문서보다 위 | 유지 | 정답 1위 |
| q_0057, q_0071 (부분 일치 g1) | dev | g1 거부 | cross 중간 이상이면 corroborated로 통과 | 유지 | g1 top 10 회복 (최소 1건) |
| ch_0010 `유툭 십분 전신 홈트 그거` | dev | 확인 필요 | 영향 작음 | low_signal/ambiguous 트리거, 동의어(유튜브, 10분) 보강으로 후보 회복 | 정답 top 3 |
| q_0045 `카톡으로 받은 회이 장소` | test | g1 1위 (MRR 0.33) | 정답 cross가 g1보다 높으면 순위 개선 | 영향 작음 (트리거 안 될 수 있음) | MRR 개선 (참고) |
| q_0167 `다리 운동 영상` (사전 항목 제거 시) | dev | 사전 없으면 실패 (N5) | 정답 cross 높으면 사전 없이도 1위 가능 | 트리거 안 됨 (원형이 어휘에 있음) | **참고 진단만**: 사전 항목을 지운 사본에서 A1 결과를 보고 |

- 단계 1의 위험: 크로스 인코더가 짧은 한국어 구어 질의(`그 카페`)나 OCR 위주 문서에서 점수를 낮게 줄 수
  있다. 그래서 corroborated의 cross veto는 아주 낮게(0.05) 시작한다. T35에서 카테고리별 cross 분포를
  보고 이 위험을 확인한다.
- 단계 2의 위험: 보강어가 다른 저장물의 단어를 우연히 맞혀 후보를 늘리는 것. 판정은 cross와 원형 증거가
  하므로 결과에 미치는 영향은 제한적이라고 가정한다. 트리거 부분집합의 true empty로 확인한다.

### 9.3 recorded 통합 테스트 추가 (Loop 2 검수 N2 지적 반영)

고정 negative 회귀(`북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `낚시 포인트 추천`, ch_0011)와
교차 언어 positive(ch_0001, ch_0003)를 **recorded 컨테이너로도** 돌리는 통합 테스트를 둔다. 리랭커 녹화본이
있으면 A1 설정으로도 같은 테스트를 돌린다.

---

## 10. 채택 기준

PRD 3.5.5절의 판정 구조(절대 기준 → 허용 하락 → 신뢰구간 → 지연·비용 → test 확인 → 사용자 승인)를
그대로 따른다. 판단은 recorded dev에서 하고, 통과한 설정만 test에서 한 번 확인한다.

### 10.1 단계 1 (A1 대 A0)

다음을 **모두** 만족해야 recorded/live 기본값을 켠다.

1. **절대 기준**: PRD 3.3.4절 recorded 열 전부, v2 13.3절 추가 기준(challenge positive 합산 Recall@10
   ≥ 0.9091, challenge negative true empty = 1.0, 9.1절 고정 회귀 전부), 안전 지표 0
2. **허용 하락** (A1 − A0, dev): Recall@10, MRR@10, nDCG@10 각각 ≥ −0.01, true empty ≥ 0, false empty
   증가 ≤ 0.01, 카테고리별 Recall@10 최저값 ≥ −0.02
3. **개선 요건**: 다음 중 하나 이상이 개선되고, 그 지표의 쌍 부트스트랩 95% 구간 하한 > 0
   - nDCG@10 +0.02 이상 (PRD 5.4.2절 조건)
   - Success@1 +0.03 이상
   - challenge positive Recall@10 +0.05 이상
   - 시소 해소: true empty와 positive Recall@10이 **둘 다** 떨어지지 않으면서 둘 중 하나가 개선
4. **신뢰도**: 2번의 각 하락 지표에 대해 95% 구간 하한 ≥ −허용치
5. **지연** (live 벤치마크, 4.9절): mps에서 리랭크 단계 p95와 검색 전체 p95가 예산 이내. cpu가 예산을
   넘으면 단계 1은 채택하되 `enabled_on_cpu=false`로 둔다
6. **운영**: dev 실행에서 리랭크 skip 비율 ≤ 2% (live 벤치마크 기준), 메모리 증가 ≤ 1.5GB
7. **test 확인**: 위 1~4를 test(또는 test v2)에서도 만족
8. **사용자 승인**: A/B 리포트를 PM이 요약해 사용자 승인을 받은 뒤 `cross_rerank.enabled` 기본값과
   recorded 기준선을 갱신한다. 기준선 갱신은 v2 정책 결정(Loop 2 검수 재검수 조건 6)과 함께 처리한다.

### 10.2 단계 2 (A3 대 A1)

단계 1이 채택된 상태를 기준으로 판단한다. 단계 1이 채택되지 않으면 A2 대 A0으로 같은 규칙을 적용하되,
보조 단독 오탐 위험 때문에 3번의 true empty 조건을 "트리거 부분집합 true empty 하락 0"으로 엄격히 둔다.

1. **표본 충분성**: dev(challenge dev 포함) 트리거 질의 ≥ 20건, 그중 positive ≥ 12건, negative ≥ 4건.
   모자라면 T37에서 dev 사례를 보강한 뒤 판단한다 (PRD 3.5.5절 7항의 부분집합 최소 20건 규칙과 같다)
2. **비트리거 무변화**: 비트리거 질의 결과가 A1과 바이트 단위로 같다 (INV-A1)
3. **트리거 부분집합 개선**: Recall@10 +0.05 이상이고 95% 구간 하한 > 0. true empty 하락 없음,
   false empty 증가 없음
4. **전체 허용 하락**: 10.1절 2번과 같은 허용치
5. **출력 품질**: 스키마 첫 시도 통과율 ≥ 0.98, 상태 `invalid_output + error` ≤ 3%, 필터 위반 0
   (facet 가드가 지운 건수는 보고만 한다)
6. **지연**: 트리거 질의 검색 전체 p95 ≤ 1.5초, LLM 호출 p95 ≤ 0.9초 (로컬 mps), 트리거 비율 ≤ 25%
7. **비용**: 로컬은 0. API를 기본으로 제안하려면 로컬 대비 트리거 부분집합 Recall@10이 +0.03 이상 높아야
   하고, 1,000질의당 비용과 데이터 외부 전송을 리포트에 명시한다. 그래도 기본값은 로컬이다
8. **test 확인과 사용자 승인**: 10.1절 7, 8번과 같다

### 10.3 로컬 모델 선택 규칙 (EXAONE 대 Qwen)

T39에서 같은 하네스로 두 모델을 A3 설정에 넣어 dev에서 비교한다. 다음 순서로 고른다.

1. 라이선스가 프로젝트 사용 범위(현재 개인·연구 개발, 이후 서비스 가능성)에 맞지 않는 후보는 제외
2. 10.2절 5, 6번(출력 품질, 지연)을 통과하지 못한 후보는 제외
3. 남은 후보 중 트리거 부분집합 Recall@10이 높은 쪽. 차이가 0.02 이내면 p95 지연이 낮은 쪽
4. 둘 다 제외되면 라이선스 대안 모델을 같은 절차로 비교하고, 그것도 실패하면 단계 2를 보류한다

### 10.4 보고서 형식 (`specs/phase2_reranker_ab_report.md`, `specs/phase2_query_assist_ab_report.md`)

- 팔별 지표표, 차이와 95% 구간, 승/패/무
- 9.2절 사례별 결과 (가설 맞음/틀림)
- 개선·악화 질의 목록과 원인 분석 (cross, R_base, R, 프로필, 게이트 사유)
- 튜닝한 값, 탐색 범위, 선택 근거, 녹화 갱신 이력
- 지연 벤치마크 원자료 (장치, 반복 수, p50/p95/max)
- 채택 규칙 각 항목의 통과/실패와 결론 (`ADOPT` / `ADOPT_WITH_LIMITS` / `REJECT`)

---

## 11. 하네스 확장

```python
# eval/ab.py (신규)
class ArmConfig(BaseModel):
    name: str                                    # "A0" ...
    cross_rerank: bool; query_assist: bool
    search_overrides: dict[str, Any] = Field(default_factory=dict)

class ABConfig(BaseModel):
    mode: Literal["recorded", "live"] = "recorded"
    split: Literal["dev", "test"] = "dev"
    arms: list[ArmConfig]
    bootstrap_iterations: int = 1000
    bootstrap_seed: int = 20261030
    baseline_arm: str = "A0"

class DeltaCI(BaseModel):                         # PRD 3.5.6절 이름 재사용
    metric: str; delta: float; ci_low: float; ci_high: float
    wins: int; losses: int; ties: int; sign_test_p: float

class ABComparison(BaseModel):
    baseline: str; candidate: str
    deltas: list[DeltaCI]
    subset_deltas: dict[str, list[DeltaCI]]      # "assist_triggered", "trigger:<kind>", "challenge"
    changed_queries: list[QueryDelta]
    decision: AdoptionDecision                   # rules: list[RuleResult], verdict

def run_ab(config: ABConfig, container_factory: Callable[..., AppContainer]) -> ABReport
def decide_reranker(cmp: ABComparison, latency: LatencyReport | None) -> AdoptionDecision    # 10.1절
def decide_assist(cmp: ABComparison, latency: LatencyReport | None) -> AdoptionDecision      # 10.2절
```

- `jupjup bench search --device mps|cpu --arms A0,A1 --repeat 3`: live 지연 벤치마크. 결과는
  `LatencyReport`(단계별 p50/p95/max, 장치, 메모리)로 저장한다. recorded 지표와 섞지 않는다.
- 기존 `EvalHarness`는 팔 하나를 돌리는 데 그대로 쓴다. `QueryResult`에 `rerank_status`, `assist_status`,
  `assist_trigger`를 추가한다.

---

## 12. 구현 작업 분할

번호는 PRD 7장(T0~T26) 뒤를 잇는다. 각 작업은 별도 워크트리에서 하고, 같은 파일을 동시에 고치는 작업을
병렬로 띄우지 않는다.

### 단계 0 — 공통

**T30. 기준 고정과 A/B 러너**
- 범위: Loop 3 병합 커밋을 A0으로 고정, `eval/ab.py`, 쌍 부트스트랩과 부호 검정, `ABReport`, `jupjup eval ab`
- 의존성: Loop 3 PM 병합
- 인수 기준: A0 대 A0 비교에서 모든 delta가 0이고 구간이 [0, 0]이다. 같은 입력으로 두 번 돌리면 리포트가
  바이트 단위로 같다(타임스탬프 제외). 부트스트랩 손계산 예제 2건과 일치한다.

### 단계 1 — 리랭커

**T31. live 지연 벤치마크 스파이크 (go/no-go)**
- 범위: `BgeCrossEncoderReranker` 최소 구현, mps/cpu × max_length(256/384) × 창(12/20/32) 지연과 메모리
  측정, `jupjup bench rerank`
- 의존성: 없음 (T30과 병렬 가능. `src/providers/rerank_bge.py`만 만든다)
- 인수 기준: 측정표가 보고서에 있다. 4.9절 예산 대비 go/no-go 판단과 `enabled_on_cpu` 기본값 제안이 있다.
  no-go면 이후 단계 1 작업을 멈추고 PM에 보고한다.

**T32. 리랭커 제공자와 설정**
- 범위: `Reranker` Protocol 확장(`score_logits`, `model_id`, `revision`), `MockReranker` 주입 옵션,
  `RecordingReranker`, `RecordedReranker`, 에러 계층, `RerankModelSettings`, optional extra `[rerank]`,
  컨테이너 조립
- 의존성: T31 go
- 인수 기준: 기본 설치(extra 없음)로 mock/recorded 테스트가 전부 통과하고 torch를 import하지 않는다
  (import 감시 테스트). INV-R8. revision이 비면 live 시작 거부. 녹화 행에 원문이 없다.

**T33. 리랭커 입력 텍스트와 녹화**
- 범위: `build_rerank_query`, `build_rerank_text`, `jupjup rerank record`(넓은 범위 녹화), 녹화본 커밋
- 의존성: T32
- 인수 기준: INV-R4. 골든·challenge·probe 전체가 녹화되고, 녹화 범위(상위 50 + 계획별 5)를 테스트로
  확인한다. 녹화 크기와 행 수를 보고한다.

**T34. 리랭크 단계 통합과 게이트 v3**
- 범위: `search/cross_rerank.py`(창 선택, 단일 비행 실행기, 타임아웃), `RelevanceScorer.apply_cross`,
  `RelevanceProfile` 두 묶음과 설정 마이그레이션, 게이트 v3 프로필, 창 밖 문서 규칙, v2 폴백,
  explain `rerank` 블록, 응답 `degraded_reasons`
- 의존성: T33
- 인수 기준: INV-R1~R3, R5~R7, R9와 v2 INV-01~20 전부 통과. 타임아웃·예외·busy 주입 테스트. 리랭커
  끔 상태에서 기존 테스트가 하나도 바뀌지 않는다.

**T35. recorded dev calibration과 튜닝**
- 범위: cross calibration → v3 계수 → 프로필 문턱과 cross floor → 창 크기와 `τ_pre` → tail margin 순서
  (v2 13.2절 순서 준수). facet 비용과 `Δmin`은 바꾸지 않는 것이 기본이고, 바꾸면 이유를 쓴다
- 의존성: T34, T30
- 인수 기준: 10.1절 1~4번이 dev에서 통과하거나, 통과하지 못한 항목과 원인을 보고한다. 9.3절 recorded
  통합 테스트 추가. 탐색 범위와 선택 근거가 보고서에 있다. test는 실행하지 않는다.

**T36. 단계 1 A/B 리포트와 채택 판단**
- 범위: live 벤치마크(A0, A1), A/B 리포트, `decide_reranker` 결과
- 의존성: T35
- 인수 기준: 10.4절 형식의 보고서. 판정이 `ADOPT`/`ADOPT_WITH_LIMITS`/`REJECT` 중 하나로 나온다.
  기본값 변경은 하지 않는다 (사용자 승인 대기).

### 단계 2 — 질의 보조

**T37. 트리거 분류기와 dev 사례 보강**
- 범위: `AssistTriggerClassifier`, dev 트리거 비율과 분류별 분포 보고, 표본 부족 시 dev 사례 추가
  (교차 언어·저신호·모호 positive와 negative, "범용어 + 핵심어 1개" 사례). 추가 사례는
  `review_status = needs_human_review`로 두고 template/entity가 test와 겹치지 않게 한다
- 의존성: T30. 단계 1 작업과 파일이 겹치지 않으므로 T32~T35와 병렬 가능 (`query/assist.py`, `data/golden/`만)
- 인수 기준: 분류 규칙 단위 테스트(분류별 ≥ 5건, 비트리거 ≥ 10건). dev 트리거 ≥ 20건(positive ≥ 12,
  negative ≥ 4). `jupjup eval validate` 통과. 트리거 비율 ≤ 25%.

**T38. 출력 스키마, 검증기, facet 가드**
- 범위: `AssistOutput`, `AssistValidator`, 상태 모델, mock fixture(정상, 스키마 위반, facet 섞임, 빈 응답,
  주입 시도)
- 의존성: T37
- 인수 기준: INV-A2, A4, A5. 검증 단계 1~6 각각 단위 테스트. 주입 fixture에서 지시를 따른 보강이
  결과에 반영되지 않는다.

**T39. 로컬 LLM 제공자와 모델 비교 스파이크**
- 범위: `LlamaCppLLM`(extra `[assist-local]`), 프롬프트 `qa-1`, EXAONE 3.5 2.4B와 Qwen2.5 3B GGUF 비교
  (스키마 통과율, 지연, 메모리, 라이선스), MLX 지연 참고 측정
- 의존성: T38
- 인수 기준: 비교표와 10.3절 규칙에 따른 추천 모델. 라이선스 확인 결과(조항 인용과 사용 범위 판단)가
  있다. 지연 예산 go/no-go.

**T40. LLM 녹화·재생과 녹화 명령**
- 범위: `RecordingLLM`/`RecordedLLM`(PRD T21 구현이 있으면 재사용), `jupjup assist record`, 녹화본 커밋
- 의존성: T39
- 인수 기준: INV-A8. 녹화 키에 모델 파일 해시, 프롬프트 버전, 스키마 버전, 디코딩 설정이 들어간다.
  같은 녹화본으로 두 번 평가한 결과가 같다.

**T41. assist 계획 통합**
- 범위: 병렬 실행(단일 비행 실행기, 마감 시각), `assist` 검색 계획, 합집합 합류, `assist_lexical` 특징과
  증거 계열, `ParsedQuery.assist`, 응답 `understanding.assist_applied`, `/v1/query:parse` 옵션
- 의존성: T40, T34 (`search/service.py`, `search/relevance.py`를 고치므로 T34·T35가 끝난 뒤)
- 인수 기준: INV-A1, A3, A6. 타임아웃 시 결과가 보조 끔과 같다. 비트리거 질의 지연 증가 없음(live 벤치).

**T42. API 엔진 (선택 옵션)**
- 범위: `AnthropicLLM` assist 경로(`claude-haiku-5-5`, effort low, 구조화 출력, 재시도 0, 거절 처리),
  동의 플래그, 비용 추정과 `--confirm-cost`, extra `[assist-api]`
- 의존성: T41. 사용자 동의와 자격 증명이 있을 때만 live 실행
- 인수 기준: INV-A7. 동의 없이 시작하지 않는다. 요청 본문에 질의 외 데이터가 없다(캡처 테스트).
  기본 설정과 테스트는 네트워크를 쓰지 않는다.

**T43. 단계 2 recorded dev 튜닝과 A/B 리포트**
- 범위: `βa`, 트리거 규칙 미세 조정(dev만), A2/A3 실행, live 벤치마크, `decide_assist`, (동의 시) API 팔 비교
- 의존성: T41 (API 비교는 T42)
- 인수 기준: 10.4절 형식 보고서와 판정. test는 실행하지 않는다.

### 마무리

**T44. 최종 test 확인**
- 범위: 동결된 설정으로 A0, A1, A3(채택 후보만)를 test(또는 test v2)에서 한 번씩 실행, 채택 규칙 최종 판정
- 의존성: T36, T43, 설정 동결 승인, Q-RA1 결정
- 인수 기준: 실행 이력과 결과가 보고서에 있다. 실패해도 test로 재튜닝하지 않고 새 dev 이슈로 등록한다.

**T45. 문서와 known_issues 정리**
- 범위: `prd_and_design.md` 4.3절 ⑤⑥, 5.2절, 5.4.2절, 5.8절을 이 설계에 맞게 갱신(또는 이 문서를 참조),
  `known_issues.md`에 해결·미해결 반영, 녹화본 README 갱신
- 의존성: T44
- 인수 기준: 문서 사이 모순이 없다 (예: 리랭커 지연 예산, LLM 기본 모델, 기본값 켬/끔).

### 12.1 의존성 트리

```text
Loop 3 병합
   └─ T30 ─┬─────────────────────────────┬──────────────────────────┐
           │                             │                          │
T31 ──▶ T32 ──▶ T33 ──▶ T34 ──▶ T35 ──▶ T36 ─────────────┐          │
                         │                                │          │
           T37 ──▶ T38 ──▶ T39 ──▶ T40 ──┴──▶ T41 ──▶ T43 ┴──▶ T44 ──▶ T45
                                              └──▶ T42 ──┘
```

- 병렬 가능: T31(T30과), T37~T40(T32~T35와). 파일 소유권: 단계 1은 `providers/rerank*.py`,
  `search/cross_rerank.py`, `search/relevance.py`, `search/gate.py`, `search/service.py`, `config.py`.
  단계 2의 T37~T40은 `query/assist.py`, `providers/llm*.py`, `data/golden/`, `data/fixtures/`, `prompts/`.
- `search/service.py`, `search/relevance.py`, `config.py`를 고치는 T34와 T41은 반드시 순서대로 한다.

---

## 13. 전체 인수 기준 (Reviewer 채점용)

1. 7절 불변식(INV-R1~R9, INV-A1~A8)과 v2 INV-01~20이 자동 테스트로 있고 통과한다.
2. 9.1절 고정 회귀가 A0, A1, A3 모두에서 통과한다.
3. 기본 설치(extra 없음)와 기본 설정으로 `uv run pytest` 전체가 네트워크 없이 통과하고, torch,
   sentence-transformers, llama-cpp, anthropic을 import하지 않는다.
4. recorded 모드 A/B 실행이 결정적이다 (두 번 실행한 리포트가 비결정 필드를 빼고 같다).
5. 녹화본에 원문 텍스트가 없고(리랭커), 녹화 미스는 조용히 넘어가지 않는다.
6. 리랭커 실패·타임아웃·busy 시 결과가 v2 단독과 같고 `degraded_reasons`가 남는다.
7. LLM 출력이 필터, 의도, 요청 잠금을 바꾸는 경로가 없다 (코드 구조와 악성 fixture 테스트로 증명).
8. API 엔진은 동의 플래그와 자격 증명 없이는 쓰이지 않고, 질의 문장 외 데이터를 보내지 않는다.
9. 채택 판단 함수(`decide_reranker`, `decide_assist`)가 10절 규칙을 모두 계산해 표시하고, 단위 테스트로
   경계 사례(구간 하한이 정확히 허용치인 경우 등)를 검증한다.
10. 모든 튜닝 값(창 크기, floor, 문턱, 계수, 타임아웃, 트리거 규칙)이 설정에 있고 `search_overrides`로
    바꿀 수 있다. 모델 id와 revision은 설정에만 있다.
11. A/B 보고서가 10.4절 형식을 지키고, test 실행 이력을 숨기지 않는다.
12. `ruff check`, `mypy src`가 경고 없이 통과한다.

---

## 14. 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| mps 지연이 예산을 넘는다 | 단계 1 기본 켬 불가 | T31 go/no-go를 먼저 한다. max_length·창 축소안을 함께 잰다 |
| 크로스 인코더가 짧은 한국어 구어 질의에 약하다 | 정답 cross가 낮아 false empty 증가 | corroborated veto를 아주 낮게 시작. 카테고리별 cross 분포를 T35에서 보고 |
| v2 계수를 다시 바꾸면 창 구성이 바뀌어 녹화 미스 | recorded 평가 실패 | 넓은 녹화 범위(상위 50 + 계획별 5). 미스는 에러로 드러나므로 녹화 갱신 |
| 소형 LLM 라이선스가 상업 이용을 막는다 | 이후 서비스 전환 시 교체 필요 | T39에서 라이선스를 먼저 확인. 대안 모델을 같은 절차로 비교 |
| dev 트리거 표본이 작다 | 단계 2 판단 신뢰도 낮음 | T37에서 dev 보강. 표본 기준 미달이면 판단 보류 |
| test split 오염 | 최종 판정이 blind가 아님 | Q-RA1에서 test v2 결정. 결정 전에는 보고서에 명시 |
| 리랭커와 bge-m3를 함께 올린 메모리 | 저사양 장비에서 부담 | 메모리 측정. cpu-only·저메모리 장비는 리랭커 끔 |

---

## 15. Codex-Primary에게 넘길 핵심 사항

1. **Loop 3 병합 전에는 시작하지 않는다.** T30(A0 고정)이 첫 작업이다.
2. **T31 벤치마크가 go일 때만 단계 1을 진행한다.** 지연 예산을 못 지키는 리랭커는 채택되지 않는다.
3. **리랭커 질의와 문서 텍스트에는 facet을 넣지 않는다.** 플랫폼, 유형, 기간이 cross 점수 보너스가 되면
   완화 정책 v2의 비용 수식이 깨진다.
4. **한 응답 안에서 v2와 v3 척도를 섞지 않는다.** 리랭크가 일부라도 실패하면 전부 v2로 간다.
5. **문턱은 증거 공간의 floor로 정의하고, 도달 가능성을 설정 로딩 시 검사한다.** N1(low-signal 도달 불가)을
   반복하지 않는다.
6. **LLM은 후보만 넓힌다.** 리랭커 질의, `semantic_text_original`, `original_terms`, facet은 LLM 뒤에도
   그대로다. 보강어만으로는 게이트를 넘을 수 없다.
7. **녹화 미스는 에러다.** recorded 평가에서 조용히 폴백하지 않는다. live 서비스 경로에서는 실제 사용자
   질의를 녹화하지 않는다.
8. **튜닝은 recorded dev만.** test는 T44에서 팔마다 한 번만 돈다.
9. 설계와 다르게 구현해야 하면 보고서에 이유를 적는다.

---

## 16. 열린 질문과 PM 추천 기본값

사용자 확인이 없어도 아래 추천값으로 구현을 시작할 수 있다.

### Q-RA1. 최종 test 판정을 어느 split으로 할까요?
현재 test는 Loop 1~2에서 여러 번 소비됐습니다.
- **PM 추천 기본값:** 동결 test v2(사람 검수 포함)를 새로 만들어 T44 판정에 쓰고, 기존 test는 회귀 확인용으로만
  쓴다. test v2가 T44 시점까지 준비되지 않으면 기존 test로 판정하되 보고서에 "blind 아님"을 명시하고, 제품 PASS
  주장은 test v2 이후로 미룬다.

### Q-RA2. 리랭커 점수를 게이트에서 어떻게 쓸까요?
- **PM 추천 기본값:** 4.2절 안 A. cross를 `R`의 특징으로 넣고, semantic-only·low-signal·lexical-only의 결정
  근거를 cross floor로 옮긴다. 게이트를 cross 하나로 대체하지 않는다.

### Q-RA3. mock 모드에서 리랭커를 켤까요?
PRD 5.4.2절은 mock에서 MockReranker를 쓴다고 했습니다.
- **PM 추천 기본값:** mock 기본값은 끔. MockReranker는 배선 테스트에만 쓴다. 자카드 점수가 mock 기준선을
  흔들 뿐 품질 정보를 주지 않기 때문이다.

### Q-RA4. cpu 전용 환경에서 리랭커를 기본으로 켤까요?
- **PM 추천 기본값:** T31 결과로 정한다. cpu p95가 400ms를 넘으면 cpu에서는 기본 끔(`enabled_on_cpu=false`),
  사용자가 명시하면 켤 수 있다.

### Q-RA5. 로컬 소형 모델의 라이선스 기준은 무엇인가요?
EXAONE 3.5와 Qwen2.5 3B는 상업 이용 조건이 있을 수 있습니다.
- **PM 추천 기본값:** 지금은 개인·연구 개발 단계이므로 두 후보를 비교 대상으로 둔다. 다만 T39에서 라이선스
  조항을 확인해 보고하고, 서비스 전환 가능성을 고려해 성능 차이가 0.02 이내면 라이선스 제약이 적은 쪽을
  고른다.

### Q-RA6. LLM 보조를 부른 질의의 지연 예산을 1.2초에서 1.5초로 늘려도 될까요?
리랭커 지연이 더해지기 때문입니다.
- **PM 추천 기본값:** 1.5초로 조정. 트리거 비율 상한(25%)으로 전체 체감 지연을 묶는다.

### Q-RA7. API 엔진(`claude-haiku-5-5`)을 쓸 때 무엇을 보내도 될까요?
- **PM 추천 기본값:** 정규화된 질의 문장만 보낸다. 저장물 본문, 제목, 태그, 사용자 어휘는 보내지 않는다.
  사용자가 설정에서 명시적으로 동의(`api_consent=true`)했을 때만 쓰고, 기본값은 로컬이다.

### Q-RA8. LLM 보강 결과를 사용자에게 보여 줄까요?
- **PM 추천 기본값:** 응답 `understanding`에 `assist_applied`와 보강어 목록을 additive 필드로 넣는다. 클라이언트가
  "‘coffee’를 ‘커피’로도 찾아봤어요"처럼 안내할 수 있다. "AI 판단보다 사용자 선택 우선" 원칙에 따라 숨기지 않는다.

### Q-RA9. 리랭커 채택 시 recorded 기준선을 언제 갱신할까요?
- **PM 추천 기본값:** Loop 2 검수 재검수 조건 6(v2 기준선 재설정 결정)과 함께, 단계 1 채택 승인 시점에 한 번
  갱신한다. 그 전에는 A0 기준선 대비 A/B로만 판단한다.
