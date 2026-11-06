# 컬렉션 색상 편집 UI 수정

- 범위: `CollectionEditor`에 기존 팔레트 및 사용자 지정 hex 선택·미리보기 추가. 생성/수정 요청에 이름과 색을 함께 보내고 pending 중 선택·닫기·중복 제출을 막음. 기존 목록/카드의 서버 색 표시 경로 유지.
- 회귀: 생성 색 전송, 카드 서버 색, 저장된 임의 hex 재표시, 수정 색 PATCH, 실패 후 이름/색 유지 및 재시도, pending 차단을 커버.
- 검사: `npm run check` 통과 (9 files, 35 tests; lint 기존 경고 7건), `npm run build` 통과. 기존 `frontend/node_modules`를 이 워크트리에만 symlink로 연결.
- 커밋: 최종 커밋 해시는 `git log -1` 참조 (push 안 함).
