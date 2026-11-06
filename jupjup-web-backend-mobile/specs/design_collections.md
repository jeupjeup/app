# 수동 컬렉션

범위: 사용자별 생성/목록/상세/이름·색 수정/삭제, 콘텐츠 다중 소속, 실제 API 기반 프론트 연결. 자동 분류·공유·협업·중첩·즐겨찾기·OAuth는 제외한다.

스키마 v29: collections(id,user_id,name,name_key,color,created_at,updated_at), collection_contents(collection_id,content_id,user_id). 이름은 NFC+trim 후 1~80자, NFC+casefold 키 사용자별 UNIQUE(충돌 409). 색은 #RRGGBB만 허용한다. 관계 PK와 양쪽 (id,user_id) 복합 FK로 중복·다른 사용자 연결을 DB에서도 차단한다. 양쪽 삭제 cascade는 관계만 지운다.

API: /v1/collections GET/POST, /{id} GET/PATCH/DELETE, /{id}/contents/{content_id} PUT/DELETE(204, idempotent). 양쪽 소유권을 확인하고 없는/타사용자 자원은 동일 404. GET /v1/contents?collection_id=... 기존 keyset pagination을 재사용한다. 기본 scope는 collection_id=None이면 유지하며 컬렉션 scope는 분리한다. list/detail에 collection_ids를 추가한다. count는 기본 콘텐츠 목록과 같이 hidden/duplicate 제외한다.

불변식: 소속 변경은 콘텐츠/원문/요약/태그/사용자층/saved_at/revision/분석 작업/검색 인덱스를 변경하지 않는다. v27/v28 checksum 소스는 수정하지 않는다. v29는 원자적 forward migration과 기존 DB 백업을 제공한다. rollback은 서버 중지 후 migration 전 백업 복원(컬렉션 신규 데이터는 별도 보관) 방식이다.

검증: 격리 DB에서 CRUD/소유권/정규화 중복과 경합/SQL cross-user 차단/cascade/데이터 보존/count/커서 다중 페이지, fresh+v28 upgrade+재시작+실패 rollback. 프론트 API 계약·CRUD·선택·오류/빈상태, 관련 save/index/ingest/metadata 회귀, ruff/mypy 및 npm check/build. 실DB/실서버는 PM만 검증한다.
