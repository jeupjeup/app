# Phase 2 소규모 보강 보고서 — 검색 API / 리랭커

- 역할: Codex-Primary
- 기준: `phase4_review_search-api_loop1.md`, `phase4_review_reranker_loop2.md`
- 결론: 요청된 M1·M2와 S1~S3을 수정했다. 근거가 명확하고 범위 안인 L 항목도 함께 수정했다.
- 금지 범위 확인: 검색 순위·질의 이해 결과, 리랭커 기본값, A/B 계수·기준선, `data/recordings`를 변경하지 않았다. test A/B를 다시 돌리거나 튜닝 입력으로 쓰지 않았다.

## 1. 항목별 조치

| 리뷰 | 항목 | 조치 | 재현/회귀 테스트 |
|---|---|---|---|
| 검색 API | M1 strict bulkUpsert 원자성 | 콘텐츠와 임베딩 캐시를 한 SQLite 트랜잭션으로 저장하고, 제공자 작업은 쓰기 전에 완료한다. 사용자 인덱스는 copy-on-write로 준비한 뒤 한 번에 게시한다. API 검색·쓰기에는 같은 잠금을 적용해 중간 상태를 노출하지 않는다. 실패 응답은 실제 예외 code를 사용하며 non-strict도 제공자 실패 전에 DB를 쓰지 않는다. | `test_bulk_upsert_index_failure_leaves_response_database_and_index_consistent[True/False]` |
| 검색 API | M2 빈 사용자 인덱스 영구 생성 | `UserIndexRegistry.peek`을 추가해 읽기 경로가 미등록 사용자의 임시 빈 인덱스를 사용하게 했다. 영구 등록은 인덱싱 쓰기 경로에서만 한다. | `test_unknown_user_reads_do_not_persist_empty_indexes` |
| 검색 API | L1 OpenAPI 에러 봉투 | `ErrorEnvelope`를 정의하고 search/parse/admin의 400·422·500·503 응답 스키마를 실제 봉투와 맞췄다. | `test_openapi_documents_error_envelope` |
| 검색 API | L2 요청 내 중복 id | 중복된 모든 항목을 `DUPLICATE_CONTENT`로 실패시키며 strict 요청은 쓰지 않는다. | `test_bulk_upsert_rejects_duplicate_ids_without_writes` |
| 검색 API | L3 lax scalar 변환 | 공개 DTO의 `limit`, `explain`, `strict`를 엄격 scalar 타입으로 바꿨다. ISO datetime 문자열 계약은 유지했다. | `test_search_body_does_not_coerce_public_scalar_types` |
| 검색 API | L5 미명세 HTTP code | 405를 `METHOD_NOT_ALLOWED`로 명시 매핑하고 5.9절 에러 표를 갱신했다. | `test_not_ready_health_and_method_error_are_explicit` |
| 검색 API | L6/L7 준비 상태 | 앱의 별도 상태를 제거하고 `registry.ready`로 단일화했다. 준비 실패·진행 중 health는 503, `status=starting`, `index_ready=false`다. | `test_index_not_ready_maps_to_503`, `test_not_ready_health_and_method_error_are_explicit` |
| 검색 API | L8 테스트 공백 | 인덱싱 실패, 미등록 사용자, 엄격 타입, OpenAPI, 준비 상태, 중복 id 경계를 통합 테스트로 고정했다. | 위 API 테스트들 |
| 검색 API | L9 정리 | CLI의 `Settings(**updates) # type: ignore`를 `Settings.model_validate(updates)`로 바꿨고 bulkUpsert를 준비/커밋 단계로 분리했다. | 전체 mypy/pytest |
| 리랭커 | S1 extra 미설치 + required | live 조립에서 장치 정책보다 먼저 torch와 sentence-transformers 설치 여부를 검사한다. `required=true`는 `RerankerUnavailable`, optional은 명시적 `RuntimeWarning`과 `unavailable` 상태를 낸다. | `test_live_missing_extra_is_explicit_even_when_cpu_is_disabled` |
| 리랭커 | S2 고정 회귀 범위/조용한 생략 | 9.1절의 고정표, 요청 잠금 5건, 오타 5건, browse 2건을 all-split 회귀 실행으로 분리했다. A0/A1 양쪽과 별도 완화 프로브의 기대 개수를 판정 입력에 저장하고, 누락 또는 개수 불일치는 규칙 1 실패다. | `test_fixed_regressions_never_silently_skip_missing_cases`, 기존 `test_a0_vs_a0_has_zero_deltas_and_is_deterministic` |
| 리랭커 | S3 test 분모 0 / 규칙 7 경로 | challenge 부분집합의 positive/negative 분모를 기록한다. 분모 0은 `n/a`로 표시하고 규칙 1에서 제외하되 입력 자체가 없으면 계속 fail-closed한다. `eval ab --confirm-with <test-report>`가 test 비교의 규칙 1~4를 재계산해 dev 판정의 규칙 7에 전달한다. | `test_zero_challenge_negative_denominator_is_explicitly_not_applicable`, `test_test_confirmation_recomputes_rules_one_through_four` |
| 리랭커 | L1/L2 보고서 정확성 | live 입력이 없던 Loop 2의 규칙 5~6을 FAIL로 정정하고, `activation_fn=Identity` 서술과 끊긴 번호 목록을 실제 제네릭 항등 함수 구조에 맞게 고쳤다. | 문서 대조 |
| 리랭커 | L3/L5 타입·dtype 중복 | `Reranker.is_replay`를 Protocol에 선언해 덕 타이핑을 제거했다. 장치별 dtype 결정은 `resolve_rerank_dtype` 하나로 통합했다. | 전체 mypy/pytest |
| 리랭커 | L4 now 축 테스트 | 시간 표현이 없는 질의 대신 `지난주 카톡으로 받은 회의 장소`와 7일 차이의 now를 사용해 실제 시간 창 변화가 있는 INV-R2를 검사한다. | `test_cross_and_relevance_ignore_now_for_documents_scored_twice` |
| 리랭커 | L6 메모리 측정 누락 | `rss_increase_mb=None`은 운영 규칙 6 실패로 바꿨다. | `test_missing_rss_measurement_fails_operations_rule` |

검색 API L4(`platforms: []`)는 명세가 필터 없음과 빈 허용 집합 중 어느 의미인지 정하지 않아 동작을 바꾸지 않았다. 리랭커 L7의 프로브 now는 현재 골든 now와 일치하고 설정 인터페이스에 공통 now가 없어, 이번 결함 수정에 필요한 범위를 넘기지 않았다.

## 2. 직접 실행한 명령과 결과

기본 설치 확인:

- `uv run python -c "...find_spec('torch')...find_spec('sentence_transformers')..."` → 둘 다 `None`.
- 재현 테스트는 구현 전에 추가했다. 최초 대상 실행은 새 심볼 부재로 collection 실패했고, 구현 후 대상 테스트가 통과했다.

최종 품질 게이트:

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **646 passed, 3 deselected**, 경고 1건 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 60 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json --out /tmp/...` | PASS — R@10 0.9620, MRR 0.9958, nDCG 0.9795, category min 0.8838 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json --out /tmp/...` | PASS — R@10 0.9420, MRR 0.9867, nDCG 0.9589, category min 0.7812 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json --out /tmp/...` | PASS — R@10 0.9712, MRR 1.0000, nDCG 0.9860, category min 0.8894 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json --out /tmp/...` | PASS — R@10 0.9720, MRR 0.9911, nDCG 0.9801, category min 0.8900 |
| `git diff --check` | PASS |
| `git diff --name-only -- data/recordings` | 변경 없음 |

평가 산출물은 저장소 밖 `/tmp/jupjup-phase2-hardening-eval/`에 썼다. 기준선과 녹화본은 수정하지 않았다.

## 3. 설계와 달라진 점

- strict bulkUpsert의 원자성 정의를 5.9절에 명시했다. 검증뿐 아니라 provider 준비, 콘텐츠·임베딩 저장, 라이브 인덱스 게시까지 성공해야 반영으로 센다.
- health 준비 실패는 기존 200 `ok/false` 대신 503 `starting/false`로 바꿨다. 준비 상태의 의미와 HTTP 상태를 일치시키기 위한 L6 조치다.
- 리랭커 채택 판정의 test 확인은 bool 수동 주입만 허용하던 구조에서, 같은 mode/팔의 test A/B JSON을 읽어 규칙 1~4를 재계산하는 명시적 경로로 확장했다. 리랭커 기본값과 판정 기준값은 바꾸지 않았다.

## 4. 남은 문제

1. recorded test Recall@10은 회귀 하한 `0.9720`과 같아 여유가 0이다. 수치 회귀는 없지만 경계 상태다.
2. 사람 검수 표본은 여전히 0건이다. 이번 결과는 기술 게이트 PASS이며 제품 품질의 사람 검수 근거는 아니다.
3. 기본 설치 pytest에 Starlette TestClient/httpx 비권장 경고가 1건 남아 있다.
4. `filters.platforms: []`의 계약은 미정이다. 명세 결정을 받기 전까지 기존의 빈 허용 집합 동작을 유지했다.
5. 리랭커는 기존 A/B 결론대로 미채택이며 기본값은 꺼져 있다. 이번 작업에서 재튜닝, 기준선 갱신, test A/B 재실행은 하지 않았다.
