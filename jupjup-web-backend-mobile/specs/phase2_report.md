# Phase 2 구현 보고서 — T0~T13

작성일: 2026-10-29 (Asia/Seoul)

골든셋 상태: **초안, 사용자 검수 전**. 시드·질의·정답은 AI가 작성한 가상 데이터이며 사용자 검수를
거치지 않았다.

## 결과 요약

T0~T13의 Python 3.12/uv 프로젝트, 도메인·텍스트·질의 이해, 골든셋과 평가 지표, SQLite 저장소,
BM25F·Hashing 임베딩·numpy 벡터 인덱스, 사용자별 인덱스, SearchService v0, 평가 하네스와 mock
기준선을 구현하고 검증했다. 네트워크 제공자는 사용하지 않았고 기본 모드는 `HashingEmbedder`,
`MockLLM`, `MockReranker`만 조립한다.

전체 단위·통합·평가 테스트에는 실패가 없다. 다만 T13은 설계상 관련도 문턱(T14) 전 단계이므로
mock 절대 기준 중 `true_empty_rate`가 dev/test 모두 0.0이고, 두 `jupjup eval run` 명령은 이를
숨기지 않고 FAIL 및 종료 코드 1을 반환한다. pytest의 절대 게이트 테스트도 이 사유를 적은 strict
xfail 1건이다.

## 구현 파일 목록

- 프로젝트/실행: `pyproject.toml`, `uv.lock`, `README.md`, `.gitignore`
- 공통 조립: `src/jupjup/config.py`, `src/jupjup/container.py`, `src/jupjup/cli.py`
- 도메인: `src/jupjup/domain/errors.py`, `models.py`, `detail_tags.v1.json`
- 텍스트: `src/jupjup/text/normalize.py`, `tokenizer.py`, `lexicon.py`
- 질의 이해: `src/jupjup/query/temporal.py`, `facets.py`, `intent.py`, `spell.py`, `understanding.py`
- 저장소: `src/jupjup/storage/db.py`, `tables.py`, `repositories.py`, `seed.py`
- 인덱스: `src/jupjup/index/document.py`, `lexical.py`, `vector.py`, `registry.py`, `service.py`
- Mock 제공자: `src/jupjup/providers/embedding.py`, `llm.py`, `rerank.py`
- 검색: `src/jupjup/search/types.py`, `filters.py`, `fusion.py`, `service.py`
- 평가: `src/jupjup/eval/schema.py`, `metrics.py`, `harness.py`, `report.py`
- 사전: `data/lexicon/platforms.yaml`, `content_types.yaml`, `synonyms.yaml`, `stop_phrases.yaml`
- 골든셋: `data/golden/seeds.jsonl` 200건, `queries.jsonl` 219건,
  `lexicon_cases.jsonl` 139건, `data/golden/README.md`
- 생성 원본: `scripts/golden_v1/build.py`, `seeds_data.py`, `queries_data.py`, `lexicon_data.py`
- 기준선: `data/baselines/mock.json` (dev/test/all)
- 테스트: `tests/unit/` 11개 테스트 모듈, `tests/integration/` 3개 테스트 모듈,
  `tests/eval/test_golden_regression.py`

이번 이어받기 작업에서는 특히 인자 없는 `jupjup seed load`가 기본 골든 시드를 읽도록 고쳤고,
CLI 테스트가 지연 문자열의 `2.6ms`를 2위 결과로 오인하지 않도록 실제 순위 행 패턴만 검사하게 했다.
골든셋 작성·검수 규칙과 실행 README도 추가했다.

## 정적 검사와 테스트 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | 성공: **428 passed, 1 xfailed**, 11.57초 |
| `uv run ruff check` | 성공: `All checks passed!` |
| `uv run mypy src` | 성공: 42개 소스 파일, 오류 0 |
| `uv run jupjup eval validate` | 성공: seeds 200, queries 219(dev 134/test 85), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | **FAIL, exit 1**: `true_empty_rate` 미달 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | **FAIL, exit 1**: `true_empty_rate` 미달 |

xfail은 `tests/eval/test_golden_regression.py::test_mock_absolute_gate` 한 건이다. T14의
`RelevanceGate`가 없어 negative 질의에도 후보를 반환하는 현상을 명시한다. 안전 지표와 기준선 회귀
테스트는 별도로 통과한다.

## mock 평가 지표와 3.3.4절 충족 여부

두 split 모두 커밋된 mock 기준선 대비 주요 지표 회귀가 없었다. p95 지연은 실행 환경 의존값이라
기준선에는 넣지 않았으며, 이번 실행은 dev 4.2ms, test 5.2ms였다.

| 지표 | mock 기준 | dev | dev 충족 | test | test 충족 |
|---|---:|---:|:---:|---:|:---:|
| Recall@10 | ≥ 0.75 | 0.9778 | O | 0.9739 | O |
| Recall@5 | ≥ 0.65 | 0.9525 | O | 0.9581 | O |
| MRR@10 | ≥ 0.60 | 0.9870 | O | 0.9711 | O |
| nDCG@10 | ≥ 0.65 | 0.9713 | O | 0.9638 | O |
| Success@1 | ≥ 0.50 | 0.9832 | O | 0.9600 | O |
| 카테고리별 Recall@10 최저값 | ≥ 0.55 | 0.9162 | O | 0.9375 | O |
| 기간 정확도 | ≥ 0.95 | 1.0000 | O | 1.0000 | O |
| 플랫폼 F1 | ≥ 0.97 | 1.0000 | O | 1.0000 | O |
| 유형 F1 | ≥ 0.95 | 1.0000 | O | 1.0000 | O |
| 키워드 포함률 | ≥ 0.90 | 0.9748 | O | 0.9333 | O |
| 정답 빈 결과율 | ≥ 0.70 | **0.0000** | **X** | **0.0000** | **X** |
| 오답 빈 결과율 | ≤ 0.05 | 0.0000 | O | 0.0000 | O |
| 격리 위반 | = 0 | 0 | O | 0 | O |
| 사용자 필터 위반 | = 0 | 0 | O | 0 | O |

따라서 3.3.4절 전체 판정은 dev와 test 모두 **미충족**이다. 미달 항목은 정답 빈 결과율 하나다.
이는 T14의 특징 재순위·관련도 문턱·완화 정책을 구현하고 dev에서만 튜닝한 뒤 해결해야 한다. 기준을
낮추거나 baseline으로 실패를 덮지 않았다.

## 데모 CLI

기본 DB는 `var/jupjup.db`이고, 다음 두 명령만으로 데모할 수 있다.

```bash
uv run jupjup seed load
uv run jupjup search "지난달 인스타에서 본 성수동 카페" --user u_alice
```

재현 가능한 기간 해석을 보여 주려면 두 번째 명령에
`--now 2026-10-15T12:00+09:00`을 붙인다. 첫 명령의 실제 검증 결과는 적재 200, 인덱싱 200,
임베딩 대기 0이었고, 두 번째 명령은 기간 `2026-09-01 ~ 2026-10-01`, 인스타그램 hard 필터와
필터 창을 출력한 뒤 `c_alice_0001`을 1위로 반환했다. `--explain`을 붙이면 검색기별 순위와 RRF
점수도 표시한다.

데모하기 좋은 질의 5개:

1. `지난달 인스타에서 본 성수동 카페` — 기간 + 플랫폼 hard 필터
2. `작년 여름에 캡처해둔 제주 숙소` — 계절 경계 + 이미지 유형
3. `유툽에서 본 파스타 레시피 그거` — 구어체/별칭 + 플랫폼 + 불용 표현
4. `과제에 쓰려던 기후변화 논문` — 목적어 + 논문 유형 + 복수 관련 문서
5. `로우커피 핸드드립 원두` — 원본 삭제 후에도 스냅샷 검색 가능

별도 DB를 쓰려면 두 명령 모두 `--db PATH`를 붙이거나 `JUPJUP_DB_PATH`를 지정한다.

## 설계와 달라진 점

- `IndexingService.index_content`는 설계 초안의 `content_id` 단독 인자 대신 `user_id, content_id`를
  받는다. 저장소 조회 단계부터 사용자 범위를 강제해 격리를 구조적으로 지키기 위한 변경이다.
- summaries의 UNIQUE 키는 `(content_id, source, version)`이다. AI 요약 v1과 사용자 수정 요약 v1을
  동시에 보존하고 사용자 요약을 우선하기 위한 변경이며, 설계 표의 `(content_id, version)`보다 넓다.
- Mock LLM은 검증 전 원문과 토큰/지연 메타데이터를 보존하려고 `LLMRawResponse`를 반환하고,
  `parse_json_response`에서 스키마를 검증한다. 5.8.4절의 “검증된 BaseModel 직접 반환” 서명과 다르다.
- T0~T13 범위 밖인 FastAPI 라우터(T15), FeatureReranker/RelevanceGate/RelaxationPolicy(T14), 실제
  BGE/Anthropic 및 recorded 녹화(T17)는 구현하지 않았다. FastAPI 의존성과 이후 단계용 설정/Protocol
  자리만 있다.

## 남은 문제와 다음 단계

1. 가장 중요한 문제는 negative 질의의 정답 빈 결과율 0.0이다. T14에서 `FeatureReranker`와
   `RelevanceGate`를 구현하고 dev split의 negative 질의로 threshold를 튜닝해야 한다. test split은
   최종 확인 때만 다시 실행한다.
2. 골든셋은 사용자 검수 전 초안이다. 특히 relevance 등급, 모호 질의 정답 범위, 가상 요약/태그를
   사람이 검수하기 전에는 수치를 제품 품질 보증으로 해석하면 안 된다.
3. live/recorded 제공자는 사용자 승인과 자격 증명 후 T17에서 추가해야 한다. 현재 `recorded`는 재생
   구현만 있고 커밋된 실제 임베딩 녹화본은 없다.
4. API는 T15 범위이므로 현재 사용 가능한 데모 표면은 CLI다.
5. git 커밋은 만들지 않았다.
