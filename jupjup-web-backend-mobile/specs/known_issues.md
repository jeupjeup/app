# Known issues

`specs/phase4_review_loop3.md`에서 이관된 항목과 Phase 2 완화 정책 v2의 해결 현황이다.
2026-10-30 기준 1~3번은 구현 및 회귀 테스트로 해결했다. 4번은 오교정 자체는 해결했지만 검색 품질이
curated 방향 확장에 의존한다. 최종 평가 결과와 별도 잔여 문제는
`specs/phase2_relaxation_v2_report.md`에 기록한다.

## 1. 질의 유래 hard facet의 과소 완화

- **해결 상태:** 해결 (Phase 2 완화 정책 v2)

- **심각도:** 높음
- **관련 코드:** `src/jupjup/search/service.py`
- **현상:** 기존 후보보다 hard facet 위반 수가 늘면 관련도 개선 폭과 무관하게 완화 후보를 거부한다.
  요청에서 잠근 facet이 아니라 질의에서 추출한 플랫폼·유형도 사실상 풀리지 않는다.
- **재현:** `경주 맛집 인스타`, `하체 운동 유튜브`
- **영향:** 약한 same-facet 후보가 하나라도 있으면 더 강한 키워드 증거를 가진 정답을 찾지 못한다.
- **해결:** 요청 facet은 모든 불변 계획과 최종 postcondition에서 잠그고, 질의 facet만 실제 위반
  비용과 `ΔR > ΔC + Δmin + epsilon` 경계로 비교한다. `경주 맛집 인스타`, `하체 운동 유튜브`를
  limit 1/2/10/50 통합 회귀로 고정했다.

## 2. 플랫폼·유형 이중 완화 기록 누락

- **해결 상태:** 해결 (Phase 2 완화 정책 v2)

- **심각도:** 중간
- **관련 코드:** `src/jupjup/search/relaxation.py`
- **현상:** 플랫폼과 유형을 한 상태에서 함께 hard→soft로 바꾼 뒤 이름만 다른 상태를 두 번 내보낸다.
  첫 상태에서 결과가 나오면 유형 완화가 응답 기록에 남지 않는다.
- **재현:** `경주 맛집 카톡 논문`
- **영향:** 실제 결과가 플랫폼과 유형을 모두 위반해도 `applied_relaxations`에는
  `platform_filter_dropped`만 표시될 수 있다.
- **해결:** 계획 이름이 아니라 선택 결과와 원 질의 facet의 실제 위반 집합에서 canonical order로
  `applied_relaxations`와 결과별 `relaxed_facets`를 산출한다. `경주 맛집 카톡 논문`은 플랫폼과
  유형 두 항목을 정확히 기록하도록 limit 1/2/10/50 회귀로 고정했다.

## 3. human-reviewed 게이트의 분모 0 및 split 메타데이터 불일치

- **해결 상태:** 해결 (Phase 2 완화 정책 v2)

- **심각도:** 중간
- **관련 코드:** `src/jupjup/eval/harness.py`
- **현상:** negative, filter-only, 기간·플랫폼·유형·키워드 사례가 0건이어도 기본값 1.0으로 절대
  게이트를 통과할 수 있다. 전역 `reviewed_query_count`를 split별 `human_count`와 비교하기도 한다.
- **영향:** 대표성이 없는 human-reviewed 표본이 제품 품질 PASS 근거가 되거나, dev/test에 정상적으로
  분산된 메타데이터가 불일치로 판정될 수 있다.
- **해결:** `MetricObservation`에 분자·분모·최소 분모·eligibility를 도입해 분모 0을
  `not_evaluated`로 처리한다. review metadata는 total/dev/test count와 overall/dev/test kappa를
  분리 검증하며, 제품 기준선 갱신도 eligible evidence가 없으면 거부한다. INV-17/18로 고정했다.

## 4. 정상어 `다리` 오교정 및 curated 확장 의존

- **해결 상태:** 오교정·원형 대체는 해결, 사전 의존은 잔여

- **심각도:** 낮음
- **관련 코드:** `src/jupjup/query/understanding.py`, `src/jupjup/query/spell.py`
- **현상:** `다리 운동 영상`에서 정상어 `다리`가 고빈도 어휘 `자리`로 교정된다.
- **영향:** 기대 정답 `c_alice_0040`이 2위이고 generic 홈트 `c_alice_0050`이 1위가 된다.
- **해결:** 원형 용어와 원형 semantic query를 불변으로 보존하고, 짧은 한국어 자동 교정과 Latin
  자동 교정을 보수화했다. `다리`의 방향 확장은 keywords에서 원형을 대체하지 않고 `[다리, 하체]`를
  나란히 보존한다. `다리 운동 영상`의 원형 보존과 `c_alice_0040` 1위를 회귀 테스트로 고정했다.
- **잔여:** `data/lexicon/synonyms.yaml`의 `다리 → 하체` 방향 확장을 제거하면 mock은 `c_alice_0050`,
  recorded는 `c_alice_0051`이 1위가 되어 사례가 실패한다. 따라서 오교정 방지는 일반화됐지만 이 사례의
  재현율은 curated 사전에 의존한다.

## 5. 완화 정책 v2의 기준선 대비 test 재현율 회귀

- **해결 상태:** 기술 게이트 해결 (Loop 3), 제품 판정 잔여

- **심각도:** 중간 (recorded test 회귀 하한과 동일, 여유 0)
- **관련 코드:** `src/jupjup/search/relevance.py`, `src/jupjup/search/gate.py`, `src/jupjup/search/service.py`
- **현상:** Loop 3에서 recorded test Recall@10 0.9720으로 회귀 하한을 다시 맞췄고, mock
  `split=all` 회귀 게이트도 통과한다. 다만 recorded test의 여유가 0이고 현 test는 이미 소비됐다.
- **원인(dev에서 확인한 유형):** 최소 계획 선택으로 넓은 계획의 g1 꼬리 문서가 빠짐(ch_0007, q_0081),
  상하위어 동의어 제거(q_0059, q_0178), 세 어절 중 한 어절만 일치하는 g1 문서가 negative 오탐과 같은
  증거 모양이라 함께 거부됨(q_0057, q_0071), 0.75~0.90 신뢰도 오타가 hashing 의미 신호로는 보완되지 않음(mock q_0048).
- **다음 조치:** 설정을 recorded dev에서만 튜닝하고, 새 동결 test v2와 사람 검수 이후 제품
  품질을 따로 판정한다. 이번 리랭커 사이클은 A0 기준선을 낮추지 않는다.

## 6. Phase 4 cycle 2 Loop 3 후속 F1~F6

`specs/phase4_review_cycle2_loop3.md`의 F1~F6을 리랭커 사이클 착수 조건으로 이관했다.

- **F1 — 해결:** anchored tail의 `utility <= anchor` 버리기 조건을 제거하고 primary 결과 뒤에서만
  정렬하도록 바꿔 단조성을 복구했다. mock dev q_0176 `주식 공부 영상`과 recorded anchored-tail
  단조성 회귀를 고정했다.
- **F2 — 미해결:** recorded dev가 semantic-only·low-signal의 cross floor 이전을 지지하지 않았고,
  리랭커도 채택 기준 미달로 기본값이 꺼져 있다. 기본 v2 경로는 여전히 bge-m3 cosine floor
  0.61 하나를 semantic-only 결정 근거로 쓴다(q_0207 여유 0.004). 다음 재평가 전에 포화되지 않은
  recorded dev v2와 한국어 구어·사전 정규형 변형을 보강한다.
- **F3 — 잔여:** v3 프로필은 특징 최댓값 대비 0.05 여유를 요구한다. v2의 실측 분포 기반
  validator 보강은 별도 후속으로 남긴다.
- **F4 — 잔여:** ch_0017·ch_0023·q_0180은 기존 test가 이미 소비된 상태의 회귀 확인용으로만
  유지한다. 새 동결 test v2가 비어 있어 제품 PASS 판정은 유보한다.
- **F5 — 부분 해결:** 기존 5번의 상태를 갱신한다. Loop 3 현재 recorded test Recall@10은
  **0.9720**으로 회귀 하한과 같고, pytest mock 회귀 게이트는 통과한다. 여유 0은 위험으로
  남긴다. q_0176은 F1 회귀로 복구했다.
- **F6 — 부분 해결/잔여:** F1에서 primary/tail 정렬을 분리했다. 임베딩 장애 fallback과
  anchored-tail 판정을 gate 단일 진입점으로 완전히 이전하는 구조 개선과 장애 모드 negative
  고정 테스트는 잔여한다.

## 7. 크로스 인코더 리랭커(단계 1) 미채택

- **해결 상태:** 구현 완료, 채택 기준 미달로 기본값 끔 (`specs/phase2_reranker_report.md`)
- **심각도:** 중간 (기능 확장 보류, 기존 품질에는 영향 없음)
- **관련 코드:** `src/jupjup/search/cross_rerank.py`, `src/jupjup/search/relevance.py`(`apply_cross`),
  `src/jupjup/search/gate.py`(v3), `src/jupjup/config.py`(`RerankModelSettings`, `CrossRelevanceSettings`)
- **현상:** recorded dev A1(리랭커 켬) 대 A0에서 이긴 질의가 사실상 없고(nDCG 1승 9패), Recall@10 −0.0315.
  test 1회 확인도 개선 경로 없음. 판정 REJECT.
- **원인:** (1) A0 dev가 이미 포화다 (Success@1 1.0, TE 1.0, FE 0). 개선 요건(nDCG +0.02 등)을 만족할 여지가
  거의 없다. (2) `bge-reranker-v2-m3`가 사전 동의어로 맞는 짧은 한국어 질의(`스파게티→파스타`, `다리→하체`,
  `언젠가 저장한 선크림`)에 로짓 −6 안팎을 준다. 같은 구간에 `북극곰 다큐→환경 다큐` 오탐(−6.3)이 있어
  cross floor 하나로도 시소가 다시 생긴다. (3) 정답 등급 g3/g2 사이 순서를 cross가 자주 뒤집는다.
- **다음 조치:** 리랭커 질의에 사전 정규형(canonical) 표현을 함께 넣는 변형, 한국어 구어 데이터로 calibration
  표본 보강, 포화되지 않은 dev v2 사례(교차 언어·부분 일치 g1) 추가 뒤 재평가. 단계 2(LLM 질의 보조)는
  설계 10.2절에 따라 A2 대 A0 기준으로 판단한다.
- **참고:** live 리랭커 서비스 경로에서 cpu는 창 20쌍 p95 1.17초로 예산(400ms)을 넘어 `enabled_on_cpu=false`가
  기본이다. 리랭커 질의에 `언젠가` 같은 상투어가 일부 남는다 (`build_rerank_query`가 `residual_text`를 그대로 쓴다).

## 8. 인제스트 골든셋 플랫폼군 내부 다양성 부족

- **해결 상태:** 어려운 사례 라벨은 Loop 2에서 보강, 전체 80건 재작성은 잔여
- **심각도:** 중간 (T24 mock 배선에는 영향 없고, T25 실제 분석기 제품 판정에는 사용 금지)
- **관련 파일:** `data/golden/ingest/`, `scripts/generate_ingest_golden.py`
- **현상:** 숫자·날짜 밀집 5건, 영어 중심 5건, 광고·해시태그 과다 5건은 각각 수치가 든 핵심 사실,
  영어 고유명사, 광고성 금지 주장을 갖도록 고쳤다. 하지만 나머지 데이터는 플랫폼군별 태그·엔티티·
  카테고리가 같은 템플릿의 변형이라 실제 모델의 폭넓은 품질을 대표하지 못한다.
- **다음 조치:** `data/golden/ingest/REVIEW_GUIDE.md`의 재작성 완료 조건에 따라 원문과 라벨을 함께
  독립 재작성하고 두 명의 사람 검수를 거친다. 그 전에는 `ai_draft_unreviewed` 상태를 유지하며 T25 제품
  품질 PASS나 기준선 갱신의 근거로 쓰지 않는다.
