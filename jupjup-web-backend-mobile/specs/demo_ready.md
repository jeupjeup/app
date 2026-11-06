# 로컬 웹 데모 준비 완료

## 실행

```bash
uv run jupjup seed load --db var/demo.db --strict
uv run jupjup demo serve --db var/demo.db --port 8780
```

브라우저에서 `http://127.0.0.1:8780`을 연다. 기본 host는 `127.0.0.1`이며, 데모는 dev/mock
모드에서만 실행된다. 외부 CDN이나 네트워크 제공자를 사용하지 않는다.

## 검증 결과

- `uv run pytest`: **432 passed, 1 xfailed, 1 warning** (13.41초)
- `uv run ruff check`: 통과
- `uv run mypy src`: 45개 소스 파일, 오류 0
- TestClient: 단일 HTML/외부 자산 없음, 실제 SearchService 검색 응답, 빈 결과 상태 검증
- Chrome 렌더: 데스크톱 및 모바일 device metrics 확인, 390px에서 가로 overflow 없음
- Impeccable UI detector: 지적 사항 0건

xfail 1건은 기존 T14 미구현에 따른 mock 절대 게이트이며 이번 데모 변경과 무관하다. warning 1건은
FastAPI TestClient가 내는 `httpx`/`httpx2` 전환 안내다. git 커밋은 만들지 않았다.

외부 자산 금지 조건에 따라 한글 서체는 페이지에 폰트를 번들하지 않고 macOS/한국어 시스템 폰트
스택을 사용한다.
