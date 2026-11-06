# Phase 2 T14 구현 보고서 — 관련도 게이트와 빈 결과

작성일: 2026-10-29 (Asia/Seoul)

골든셋 상태: **초안, 사용자 검수 전**. 아래 수치는 AI가 작성한 가상 골든셋 기준이며 제품 품질 보증으로
해석하지 않는다.

## 결과 요약

`FeatureReranker`, `RelevanceGate`, `RelaxationPolicy`와 구조화된 빈 결과 응답을 검색 파이프라인에
연결했다. dev에서만 튜닝한 최종 설정은 mock 절대 기준과 기존 기준선 회귀 규칙을 모두 통과했고,
T13 대비 dev nDCG@10은 **0.971306 → 0.973724**로 상승했다. 마지막 test 확인도 전체 기준을
통과했으며 `true_empty_rate`는 dev **0.733333**, test **0.800000**이다.

`test_mock_absolute_gate`의 strict xfail을 제거했고 전체 pytest는 실패·xfail 없이 통과했다. 웹 데모는
`empty_state`의 메시지·이유·제안, `applied_relaxations`, 결과별 `relaxed`를 응답하고 화면에 표시한다.
`캡처해둔` 같은 결합형 기억 동작은 유형 단어 `캡처`를 보존하면서 의미 질의에서 동작 접미만 제거한다.

## 변경 파일

- 검색 구현: `src/jupjup/search/rerank.py`, `gate.py`, `relaxation.py`, `service.py`
- 조립과 설정: `src/jupjup/container.py`, `src/jupjup/config.py`
- 질의 이해: `src/jupjup/query/understanding.py`
- 웹 데모: `src/jupjup/demo/app.py`, `src/jupjup/demo/page.py`
- 평가 기준선: `data/baselines/mock.json`
- 테스트: `tests/unit/test_relevance.py`, `test_understanding.py`,
  `tests/integration/test_demo.py`, `tests/eval/test_golden_regression.py`
- 보고서: `specs/phase2_t14_report.md`

## 구현 내용

### FeatureReranker

RRF 정규화, 키워드 커버리지와 제목·태그 강일치, 시간 점수, soft facet, 목적 일치, 벡터 유사도,
recency를 `SearchSettings.rerank` 가중치로 선형 결합한다. 게이트 진단용으로 n-gram 커버리지와 실제
필드 일치도 함께 계산한다. 최종 동점은 `saved_at` 내림차순, `content_id` 오름차순으로 정렬한다.

### RelevanceGate

설계의 키워드·벡터·n-gram 신호와 lookup 꼬리 절단을 구현했다. 일반 키워드와 분리되는 목적어가
`detail` 또는 `user_note`에 정확히 맞으면 명시적 어휘 신호로 인정한다. 4자 이상 철자 교정 결과가
제목·태그에 정확히 맞는 경우도 교정 반영 키워드 일치로 인정해 긴 오타의 관련 문서를 보존한다.

### RelaxationPolicy와 빈 결과

잠기지 않은 질의 유래 필터에만 `time_window_expanded` → `time_filter_dropped` → 플랫폼/유형 soft
전환 → `spelling_expanded` 순으로 적용한다. 요청 필터는 항상 locked 상태로 유지한다. 거리 +1 철자
확장은 우연 일치가 많은 짧은 단어를 제외하고 4자 이상에서 새 교정이 생길 때만 실행한다.

모든 단계 뒤에도 결과가 없으면 다음 응답을 반환한다.

```json
{
  "results": [],
  "empty_state": {
    "message": "다른 표현으로 다시 찾아볼까요?",
    "reason": "no_relevant_match",
    "suggestions": []
  }
}
```

제안은 풀 수 있는 질의 필터와 동의어 대체 표현에서 최대 3개를 결정적으로 만든다. 빈 결과에서도
실제로 시도한 `applied_relaxations`를 보존한다.

## 검증 결과

| 명령 | 결과 |
|---|---|
| `uv run ruff check` | 성공: `All checks passed!` |
| `uv run mypy src` | 성공: 48개 소스 파일, 오류 0 |
| `uv run pytest` | 성공: **441 passed**, xfail 0, 10.75초 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS |

pytest 경고 1건은 FastAPI TestClient가 내는 `httpx`/Starlette deprecation 경고이며 테스트 실패나 검색
동작 문제는 아니다.

## dev/test 지표와 기준 충족 여부

| 지표 | mock 기준 | dev | dev | test | test |
|---|---:|---:|:---:|---:|:---:|
| Recall@10 | ≥ 0.75 | 0.968978 | 충족 | 0.975333 | 충족 |
| Recall@5 | ≥ 0.65 | 0.946592 | 충족 | 0.960741 | 충족 |
| MRR@10 | ≥ 0.60 | 0.991597 | 충족 | 0.973333 | 충족 |
| nDCG@10 | ≥ 0.65 | 0.973724 | 충족 | 0.963918 | 충족 |
| Success@1 | ≥ 0.50 | 0.983193 | 충족 | 0.960000 | 충족 |
| 카테고리별 Recall@10 최저 | ≥ 0.55 | 0.885648 | 충족 | 0.937500 | 충족 |
| 기간 정확도 | ≥ 0.95 | 1.000000 | 충족 | 1.000000 | 충족 |
| 플랫폼 F1 | ≥ 0.97 | 1.000000 | 충족 | 1.000000 | 충족 |
| 유형 F1 | ≥ 0.95 | 1.000000 | 충족 | 1.000000 | 충족 |
| 키워드 포함률 | ≥ 0.90 | 0.974790 | 충족 | 0.933333 | 충족 |
| 정답 빈 결과율 | ≥ 0.70 | 0.733333 | 충족 | 0.800000 | 충족 |
| 오답 빈 결과율 | ≤ 0.05 | 0.000000 | 충족 | 0.000000 | 충족 |
| 격리 위반 | = 0 | 0 | 충족 | 0 | 충족 |
| 사용자 필터 위반 | = 0 | 0 | 충족 | 0 | 충족 |

주요 지표 회귀 규칙도 dev/test 모두 통과했다. p95 지연은 dev 7.4ms, test 7.6ms였으나 환경 의존
수치이므로 기준선에는 저장하지 않았다. 합산 `all` 기준선은 확정된 dev/test 리포트의 질의별 결과를
합쳐 갱신했으며 `true_empty_rate=0.76`, `false_empty_rate=0`이다.

## dev 튜닝 기록

test split은 아래 선택을 모두 끝낸 뒤 마지막에 한 번 명시 실행했다. 기준을 낮추거나 실패를 기준선으로
덮지 않았다.

| 순서 | dev 변경/실험 | Recall@10 | nDCG@10 | True Empty | False Empty | 판단 |
|---:|---|---:|---:|---:|---:|---|
| 0 | T13 기준선(게이트 없음) | 0.977801 | 0.971306 | 0.000000 | 0.000000 | 비교 기준 |
| 1 | 설계 기본값: `tau_vec=0.35`, `kw_min=0.50`, 기본 가중치 | 0.956373 | 0.963533 | 0.733333 | 0.008403 | nDCG 하락으로 보완 |
| 2 | 재순위 가중치를 RRF 1.0, 나머지 0으로 변경 | 0.9534 | 0.9590 | 0.7333 | 0.0084 | 순위 품질 저하, 폐기 |
| 3 | 목적어 정확 일치를 명시적 어휘 신호로 추가 | 0.9648 | 0.971936 | 0.7333 | 0.0000 | 채택 |
| 4 | `tau_vec: 0.35 → 0.36` | 0.9648 | 0.971936 | 0.7333 | 0.0000 | 이득 없음, 0.35 유지 |
| 5 | `kw_min: 0.50 → 0.60` | 0.9337 | 0.9553 | 0.9333 | 0.0168 | 빈 결과는 개선되나 순위 회귀, 폐기 |
| 6 | 거리 +1 교정을 짧은 단어에도 허용 | 0.9648 | 0.9719 | 0.6667 | 0.0000 | 우연 교정으로 기준 미달, 폐기 |
| 7 | 긴 교정의 제목·태그 정확 일치 보존, R4를 4자 이상으로 제한 | **0.968978** | **0.973724** | **0.733333** | **0.000000** | 최종 채택 |

최종 수치 설정은 설계 기본값인 `hashing-v1 tau_vec=0.35`, lookup `kw_coverage_min=0.50`, browse
`0.34`, n-gram 순위 `≤3`, n-gram 커버리지 `≥0.60`, 꼬리 비율 `0.35`를 유지한다. dev에서 확인한
문제는 숫자 문턱을 느슨하게 하는 대신 목적어·긴 교정의 정확 일치 신호와 짧은 확장 교정 가드로
해결했다.

## 설계와 달라진 점

- 설계의 세 게이트 신호에 목적어의 `detail/user_note` 정확 일치를 추가했다. 목적어는 일반 키워드에서
  의도적으로 빠지므로, 그렇지 않으면 목적 질의가 정답인데도 완전히 비는 문제를 막기 위한 변경이다.
- 키워드 커버리지의 “교정 반영”을 명확히 하기 위해 4자 이상 철자 교정 결과의 제목·태그 정확 일치를
  통과 신호로 취급한다.
- R4 거리 +1 교정은 4자 이상으로 제한했다. 짧은 단어에서는 `점수→전시`, `시세→기사` 같은 우연
  일치가 negative 질의를 살려 dev 빈 결과 기준을 깨뜨렸기 때문이다.

## 남은 문제

1. 골든셋은 사용자 검수 전 초안이다. 특히 negative 질의와 relevance 등급을 사람이 검수해야 한다.
2. Hashing 임베딩의 절대 유사도는 실제 임베딩과 다르다. recorded/live 문턱은 T17에서 별도로 튜닝해야
   하며 mock의 0.35를 재사용하면 안 된다.
3. 짧은 단어의 확장 철자 교정은 정밀도 때문에 보수적으로 막았다. 더 나은 사용자 어휘 빈도·문맥 모델이
   생기면 별도 dev 평가로 다시 검토할 수 있다.
4. 웹 데모는 dev/mock 전용이다. 운영 API 표면은 후속 T15 범위다.
