# Phase 2 실제 임베딩 연결 보고서

## 범위와 결론

사용자 결정 Q6에 따라 로컬 `BAAI/bge-m3` dense 임베딩을 연결했다. Anthropic 및 다른 LLM 연동은
포함하지 않았다. 검색 규칙과 가중치는 변경하지 않았으며, `specs/phase4_review_loop3.md`의 남은
피드백 1~4는 `specs/known_issues.md`에 후속 이슈로만 기록했다.

recorded test split은 실제 제공자 절대 기준을 모두 통과했다. dev split은 순위·질의 이해·안전
기준은 통과했지만 negative 질의의 `true_empty_rate=0.7333`이 recorded 기준 0.80에 미달했다.
이는 mock에서도 같은 값이던 규칙 측 결과이며 이번 범위에서는 튜닝하지 않았다.

## 구현 내용

- `BgeM3Embedder`
  - `sentence-transformers` 기반 `BAAI/bge-m3`, 1024차원 dense float32 벡터
  - 모델 출력에 다시 L2 정규화를 적용해 provider 계약을 보장
  - 배치 크기 설정과 `auto|cpu|mps` 디바이스 선택 (`auto`는 MPS 우선, 아니면 CPU)
  - 모델 첫 사용 시 다운로드, 기본 캐시 `var/models/`
  - 모델 로딩과 추론 실패를 `EmbeddingProviderError`로 정제
- 의존성 분리
  - `sentence-transformers`와 torch 계열은 `[project.optional-dependencies].embed`에만 포함
  - 모듈을 지연 import해 기본 설치의 mock 및 recorded 경로는 무거운 의존성 없이 실행
- 모드 조립
  - `mock`: 기존 `HashingEmbedder`
  - `live`: `BgeM3Embedder`를 `RecordingEmbedder`로 감싸 실제 추론과 녹화를 함께 수행
  - `recorded`: 1024차원 `RecordedEmbedder`로 녹화본만 결정적으로 재생
- 녹화
  - 시드 200건의 문서·청크 400벡터와 골든·challenge 및 진단 probe에서 실제 검색이 소비하는
    질의 235벡터, 총 635벡터를 녹화
  - 완화 재검색이 만드는 파생 `semantic_query`도 전체 검색 순회로 포함
  - 원문 없이 model id, query/document kind, text hash, base64 float32 벡터만 저장
  - `data/recordings/embeddings.bge-m3.jsonl`, 3.41MiB이므로 저장소에 포함
  - 기존 숫자 배열 JSONL도 `RecordedEmbedder`가 계속 읽을 수 있게 호환 유지
- 데모
  - `jupjup demo serve --mode mock|recorded|live` 추가, 기본은 `mock`
  - 기존 dev/test 전용 및 외부 바인딩 안전장치는 유지
- 평가
  - `data/baselines/recorded.json`에 dev/test 기준선 생성
  - 커밋된 녹화본의 test 절대/회귀 게이트 및 두 번 재생 결정성을 기본 테스트에 연결
  - 실제 모델 통합 테스트는 `embed` pytest 마커로 분리

## 설치, 녹화 재생성, 실행

기본 경로는 embed extra 없이 동작한다.

```bash
uv sync
uv run pytest
uv run ruff check
uv run mypy src
```

실제 모델 설치와 별도 통합 테스트:

```bash
uv sync --extra embed
uv run --extra embed pytest -m embed
```

모델 다운로드 및 녹화본 전체 재생성:

```bash
uv run --extra embed jupjup embedding record --force
```

캐시와 실행 설정은 `JUPJUP_BGE_CACHE_DIR`, `JUPJUP_BGE_DEVICE=auto|cpu|mps`,
`JUPJUP_BGE_BATCH_SIZE` 또는 녹화 명령의 `--cache-dir`, `--device`, `--batch-size`로 바꿀 수 있다.

결정적 평가와 데모:

```bash
uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json
uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json
uv run jupjup seed load --db var/demo.db
uv run jupjup demo serve --db var/demo.db --mode recorded
uv run --extra embed jupjup demo serve --db var/demo.db --mode live
```

## mock 대비 recorded 지표

질의 이해는 두 모드 모두 같은 규칙 경로이므로 모든 지표가 동일했다. 격리 위반과 요청 필터 위반도
두 모드 모두 0이다. 아래 값은 현재 골든과 challenge를 함께 평가한 결과다.

### dev (158질의, challenge 16)

| 지표 | mock | recorded | 변화 |
|---|---:|---:|---:|
| Recall@5 | 0.9466 | 0.9497 | +0.0032 |
| Recall@10 | 0.9690 | 0.9665 | -0.0025 |
| MRR@10 | 0.9916 | 1.0000 | +0.0084 |
| nDCG@10 | 0.9737 | 0.9793 | +0.0056 |
| Success@1 | 0.9832 | 1.0000 | +0.0168 |
| 카테고리 Recall@10 최저값 | 0.8856 | 0.8801 | -0.0056 |
| True Empty Rate | 0.7333 | 0.7333 | 0.0000 |
| False Empty Rate | 0.0000 | 0.0000 | 0.0000 |
| 기간/플랫폼/유형/키워드 | 1.0000/1.0000/1.0000/0.9832 | 동일 | 0.0000 |

recorded dev 판정은 **FAIL**이다. 유일한 실패는 True Empty Rate의 실제 제공자 기준 0.80이다.

### test (101질의, challenge 8)

| 지표 | mock | recorded | 변화 |
|---|---:|---:|---:|
| Recall@5 | 0.9674 | 0.9707 | +0.0033 |
| Recall@10 | 0.9820 | 0.9820 | 0.0000 |
| MRR@10 | 0.9867 | 0.9867 | 0.0000 |
| nDCG@10 | 0.9761 | 0.9808 | +0.0046 |
| Success@1 | 0.9733 | 0.9733 | 0.0000 |
| 카테고리 Recall@10 최저값 | 0.9375 | 0.9375 | 0.0000 |
| True Empty Rate | 0.8000 | 0.9000 | +0.1000 |
| False Empty Rate | 0.0000 | 0.0000 | 0.0000 |
| 기간/플랫폼/유형/키워드 | 1.0000/1.0000/1.0000/0.9333 | 동일 | 0.0000 |

recorded test 판정은 **PASS**이며 실제 제공자 절대 기준과 recorded 기준선 회귀 조건을 모두 통과했다.

## known issues 사례 결과

| 사례 | mock 상위 | recorded 상위 | recorded 결과 |
|---|---|---|---|
| 경주 맛집 인스타 | `0020, 0019, 0004` | `0019, 0020, 0004` | 과소 완화 유지. 정답 `0153` 대신 인스타 맛집만 반환, 완화 기록 없음 |
| 하체 운동 유튜브 | `0050, 0051` | `0050, 0051` | 과소 완화 유지. 정답 `0040`이 플랫폼 hard filter에 막힘 |
| 다리 운동 영상 | `0050, 0040, 0051` | `0040, 0051, 0050` | bge-m3가 기대 정답 `0040`을 1위로 올림. 단, `다리→자리` 오교정 자체는 유지 |
| 경주 맛집 카톡 논문 | `0153, 0020, 0019` | `0153, 0019, 0020` | 정답 1위. blog/article로 두 facet을 위반하지만 기록은 `platform_filter_dropped` 하나뿐 |
| 레스토랑 추천 블로그 | `0152, 0153` | `0152, 0153` | blog facet과 무완화 유지, 기대 정답 `0153`은 2위 |
| S7 지난주 카톡 회의 장소 | `0136, 0146` | `0136, 0146` | 정답 1위, `time_window_expanded`, 결과 `relaxed=true` 유지 |

ID의 `c_alice_` 접두사는 표에서 생략했다. 실제 임베딩은 정상어 오교정의 순위 영향을 완화했지만,
과소 완화와 이중 facet 기록 결함은 해결하지 않았다. 이는 규칙을 변경하지 않았다는 측정 목적과 일치한다.

## challenge set 결과

24건은 전부 `needs_human_review` 상태다. positive 22건과 negative 2건을 분리해 집계했다.

| 모드 | Positive Recall@10 | MRR@10 | nDCG@10 | Success@1 | Negative True Empty |
|---|---:|---:|---:|---:|---:|
| mock | 0.6591 | 0.6227 | 0.6289 | 0.5909 | 0.5000 |
| recorded | 0.9091 | 0.9242 | 0.9164 | 0.9091 | 0.5000 |
| 변화 | +0.2500 | +0.3015 | +0.2875 | +0.3182 | 0.0000 |

split별 recorded는 dev positive 14건에서 Recall@10 0.8929, Success@1 0.8571이고, test positive
8건에서 Recall@10 0.9375, Success@1 1.0000이다. negative 2건은 모두 dev에 있으며 한 건만 정확히
비웠다.

| ID | split | 상위 결과 | 관련 정답 최고 순위 | Recall@10 | 비고 |
|---|---|---|---:|---:|---|
| ch_0001 | dev | `0016` | 3 | 1.0 | 관련 결과는 찾았으나 1위 실패 |
| ch_0002 | dev | `0001` | 1 | 1.0 | PASS |
| ch_0003 | dev | 없음 | - | 0.0 | 영어 기후 논문, `content_type_filter_dropped` 후에도 빈 결과 |
| ch_0004 | dev | `0114` | 1 | 1.0 | PASS |
| ch_0005 | dev | `0041` | 1 | 1.0 | PASS |
| ch_0006 | dev | `0041` | 1 | 1.0 | PASS |
| ch_0007 | dev | `0136` | 1 | 0.5 | 정답 1위, 보조 relevance 1건 누락, 기간 완화 |
| ch_0008 | dev | `0136` | 1 | 1.0 | PASS |
| ch_0009 | dev | `0050` | 1 | 1.0 | PASS |
| ch_0010 | dev | `0050` | 1 | 1.0 | PASS |
| ch_0011 | dev | `0154` | negative | - | false positive, `spelling_expanded` |
| ch_0012 | dev | 없음 | negative | - | true empty |
| ch_0013 | dev | `0132` | 1 | 1.0 | PASS |
| ch_0014 | dev | `0132` | 1 | 1.0 | PASS |
| ch_0015 | dev | `0052` | 1 | 1.0 | PASS |
| ch_0016 | dev | `0052` | 1 | 1.0 | PASS |
| ch_0017 | test | `0112` | 1 | 1.0 | PASS |
| ch_0018 | test | `0112` | 1 | 1.0 | PASS |
| ch_0019 | test | `0146` | 1 | 1.0 | PASS |
| ch_0020 | test | `0146` | 1 | 1.0 | PASS |
| ch_0021 | test | `0116` | 1 | 0.5 | 정답 1위, 보조 relevance 1건 누락 |
| ch_0022 | test | `0116` | 1 | 1.0 | PASS |
| ch_0023 | test | `0100` | 1 | 1.0 | PASS |
| ch_0024 | test | `0100` | 1 | 1.0 | 기간 확장·제거 후 정답 1위 |

ID의 `c_alice_` 접두사는 표에서 생략했다.

## 검증 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 497 passed, 실제 모델 1건 deselected |
| `uv run ruff check` | PASS |
| `uv run mypy src` | PASS — 51개 소스 파일 |
| `uv run --extra embed pytest -m embed` | PASS — 실제 `BAAI/bge-m3` 다운로드·추론·shape·정규화 |
| mock dev/test + `data/baselines/mock.json` | 둘 다 PASS |
| recorded dev + `data/baselines/recorded.json` | FAIL — True Empty Rate 0.7333만 기준 미달 |
| recorded test + `data/baselines/recorded.json` | PASS — 절대/회귀 기준 모두 통과 |
| recorded dev 두 번 재생 | PASS — timestamp/git SHA/perf 제외 결정적 결과 일치 |

recorded 지연 수치는 녹화 재생 지연이므로 실제 bge-m3 추론 지연으로 해석하지 않는다.

## 다음 단계 제안

1. 검색 규칙 작업을 별도 사이클로 열어 `known_issues.md` 1~4를 우선순위대로 수정한다. 특히
   query-derived facet만 비용 기반으로 완화하고 요청 잠금 facet은 절대 보존해야 한다.
2. `ch_0003`의 영어 climate 질의 빈 결과와 `ch_0001`의 1위 실패를 분석하되, bge 가중치나 gate
   조정은 dev에서만 실험하고 test는 최종 확인에만 쓴다.
3. negative challenge의 false positive(`ch_0011`)와 dev True Empty Rate를 함께 다루는 관련도 게이트
   실험을 진행한다. recorded test의 현재 순위 개선을 회귀 기준으로 보호한다.
4. 실제 live 성능은 모델 warm-up과 CPU/MPS를 나눠 별도 벤치마크한다. 이번 recorded p95는 실제 모델
   추론 시간이 아니다.
