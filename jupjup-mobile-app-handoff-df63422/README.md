# jupjup

자연어로 개인 저장물을 찾는 검색 코어의 Phase 2 구현입니다. Python 3.12, FastAPI,
SQLite, kiwipiepy, 앱 내장 BM25F와 numpy 벡터 검색을 사용하며 기본 `mock` 모드는 네트워크를
사용하지 않습니다.

## 설치와 검증

```bash
uv sync
uv run pytest
uv run ruff check
uv run mypy src
```

실제 로컬 임베딩은 별도 extra다. 첫 실행 때 `BAAI/bge-m3` 모델을 지정한 캐시에 내려받는다.

```bash
uv sync --extra embed
uv run --extra embed pytest -m embed
uv run jupjup embedding record --force
```

기본 모델 캐시는 `var/models/`다. `JUPJUP_BGE_CACHE_DIR`, `JUPJUP_BGE_DEVICE=auto|cpu|mps`,
`JUPJUP_BGE_BATCH_SIZE`로 바꿀 수 있다. 기본 설치와 `mock`/`recorded` 재생에는 이 extra가 필요 없다.

## 로컬 데모

골든 시드는 AI가 작성한 **초안, 사용자 검수 전** 데이터입니다. 기본 DB는 `var/jupjup.db`입니다.

```bash
uv run jupjup seed load
uv run jupjup search "지난달 인스타에서 본 성수동 카페" --user u_alice --now 2026-10-15T12:00+09:00
uv run jupjup demo serve --mode mock
uv run jupjup demo serve --mode recorded
uv run --extra embed jupjup demo serve --mode live
```

다른 DB를 쓰려면 두 명령 모두 `--db /path/to/demo.db`를 붙이거나 `JUPJUP_DB_PATH`를 지정합니다.
검색 출력에는 해석된 기간과 필터 창, 플랫폼/유형 필터, 키워드와 의미 질의, 상위 결과와 매칭
근거가 포함됩니다. `--explain`은 검색기별 순위와 RRF 점수를 추가합니다.

## 오프라인 평가

```bash
uv run jupjup eval validate
uv run jupjup eval run --mode mock --split dev
uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json
uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json
uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json
```

`recorded`는 커밋된 bge-m3 녹화본만 읽으며 네트워크를 사용하지 않는다. 녹화본에 없는 문서나
질의는 `EmbeddingCacheMiss`로 실패한다. 현재 recorded test는 실제 제공자 절대 기준을 통과하고,
dev는 negative 질의의 true-empty 기준만 미달한다. 평가 명령은 이를 숨기지 않고 종료 코드 1과
FAIL 리포트로 알린다.

## 통합 프론트엔드

사용자가 만든 React 프론트엔드는 `frontend/`에 통합되어 있습니다. 로컬 화면은 http://127.0.0.1:5177/dashboard 이며, 연결 범위와 실행 방법은 [프론트엔드 안내](frontend/README.md)를 참고하세요. 분석기는 시험용 mock 기본값을 유지합니다.

## Mobile app integration

Use `<scheme>://<host>:8000/api` as the base URL. Register or log in and send the
returned token as `Authorization: Bearer <token>`; store it in the platform's
secure storage. On a 401 clear the session and sign in again. Every POST or
PATCH requires JSON and `Content-Type: application/json`; send `{}` for
bodyless POSTs. Branch on `error.code` and refresh `/state` after writes and
when the app returns to the foreground.

For a development phone on the same LAN, find the host's LAN IP and run:

```sh
JUPJUP_AUTH_BACKEND=app_session uv run jupjup api serve --host 0.0.0.0 --port 8000 --allow-external-bind
python scripts/app_contract_smoke.py --base-url http://<LAN-IP>:8000/api
```

The external bind disables the development admin API. Use the LAN IP on a
physical device, `10.0.2.2` in the Android emulator, or `127.0.0.1` in the
iOS simulator. Debug builds may need local-network permission and a scoped
cleartext HTTP exception; release builds require HTTPS. Native requests do not
need CORS; WebViews require their exact origin in `CORS_ORIGINS`. Production
requires a domain and HTTPS reverse proxy and `JUPJUP_AUTH_BACKEND=app_session`.
