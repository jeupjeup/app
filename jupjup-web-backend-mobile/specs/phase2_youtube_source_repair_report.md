# 유튜브 수집·요약 오류 수정 결과

구현 워커의 CLI 한도 도달 뒤 PM이 미커밋 변경을 회수하여 검사·보고를 마무리했다.

## 변경

- 유튜브 watch HTML/제목을 영상 본문으로 분석하지 않는다. 공개 player caption track을 찾아 기존 HTTP의 DNS/IP 고정·SSRF·redirect·시간·용량 제한 안에서 JSON3 자막을 요청한다.
- 공개 자막 미제공/접근 실패/빈 응답은 SOURCE_TEXT_UNAVAILABLE로 분석 전 실패한다. 약관·메뉴-only HTML을 거부하며 직접 텍스트/정상 기사/자막 입력은 유지한다.
- 과거 watch HTML snapshot 재분석도 차단하되 정상 transcript 증거가 있는 snapshot은 유지한다.
- 목록/상세에 mock 여부를 표시하고 고정 mock 문구를 실제 모델 요약처럼 노출하지 않는다. 실패한 영상 상세에서 자막·본문을 별도 텍스트 항목으로 저장할 수 있다. 기존 항목은 덮어쓰거나 삭제하지 않는다.
- scripts/repair_youtube_source.py: 원래 문제 항목 한 건에만 적용 가능한 dry-run/상태지문/백업/활성작업 차단 복구 도구. 원문·사용자 요약/태그 보존. 현재 실데이터에서는 대상이 이미 없어 skip_missing이며 다른 새 강의 항목은 수정하지 않았다.

## 검증

- 구현 워커의 관련 backend 회귀 150개 통과 기록 확인. PM이 관련 새 테스트와 save/search/ingest API 회귀를 별도로 재실행했다(집계는 PM 최종 확인 참조).
- PM 최종 frontend check: 7개 파일/23개 테스트 PASS. lint error 0, 기존 경고 6개. build PASS.
- PM ruff check src + 신규 테스트/복구 스크립트 PASS. mypy src: 107개 파일 PASS.
- 단위/통합 검증: 정상 공개 caption→HTTP→추출, 미제공/차단/빈 자막, 악성 caption URL/redirect/DNS·용량 한도, 정상 VTT/SRT/JSON, 직접 텍스트·기사·약관 관련 정상 기사, 백업·대상 제한·사용자 데이터 보존, 실패 화면의 대체 텍스트 저장.
- 실제 두 URL(EbL67RhCGbY, wpk7AM6FPRc)은 watch/자막 트랙까지 접근했으나 자막 응답은 HTTP200/0bytes여서 실패로 기록했다. 성공한 영상 요약이나 자막 확보라고 주장하지 않는다. 로그인/쿠키/차단 우회 및 외부 LLM 없음.
- 기존 t25r-venv/llama-cpp-python0.3.36과 로컬 Kanana2.1B 가중치 해시 검증 후 직접 작성한 정상 자막 한 건 smoke PASS. 첫 응답 형식 통과, 8.95초. 기본 profile/mock 및 품질 기준은 변경하지 않았다. 실제 두 영상의 내용이나 품질 기준 통과를 뜻하지 않는다. 상세 로그는 Git 제외 var/youtube_local_smoke_t25r.log.
- 검색 순위/질의 해석/recorded embeddings/골든 test split/모델 가중치 무변경.

## 배포 및 제한

초기 인계 시에는 반영 전이었으나, 아래 PM 최종 반영을 완료했다. 기존8780 데모와 사용자가 개발한 원본 프론트는 건드리지 않았다.

현재 모델 기본값은 여전히 mock이다. 자막이 공개되어도 접근 환경에 따라 빈 응답/차단될 수 있으며 이 경우 직접 텍스트 입력이 필요하다. 검증되지 않은 모델을 정식 품질로 승격하지 않는다.


## PM 최종 반영 (2026-11-05)

- 1차 수집 수정 98점 PASS, 기존 항목 읽기 안내 후속 수정 100점 PASS. 모두 PM 및 실행 워크트리에 병합했다. 후속 결과는 phase2_youtube_legacy_notice_report.md, 검수는 phase4_review_youtube-legacy-notice_loop2.md.
- PM 독립 회귀 127개 PASS, 후속 관련71개/프론트26개 PASS, build/ruff/mypy107 PASS. 실서버 HTTP smoke(저장·승인·편집·재분석·검색·숨김·삭제)도 반영 후 PASS.
- 새 검증 사용자로 실제 강의 URL을 저장해 빈 자막에서 SOURCE_TEXT_UNAVAILABLE/analysis_failed, summary=null/tags=[]/candidate=null 확인. 이 검증 항목만 삭제했다.
- 실제 기존 C++ 항목은 데이터 변경 없이 source_text_available=false/reason=legacy_watch_snapshot로 조회되고, 잘못된 AI 유효값은 상세·목록에서 제외된다. 사용자 콘텐츠2개/원문/요약/태그의 저장 지문이 반영 전후 동일했다.
- 브라우저에서 영상 본문 확보 실패 안내, 자막·본문 입력란, 새 항목 저장 버튼, 기존 원문 접힘 열람, 재분석 비활성화 및 잘못된 AI태그 미노출 확인.
- 실행 URL: http://127.0.0.1:5177/contents/c_f7164cb29434443393406f5dc7e02fee
- API terminal: term_7809f7aa-5e63-4a3b-afc8-ebb41629d40b / worker: term_de7d296f-1283-4de7-a482-16a2e8bb42c4. Vite는 기존 term_cd3df04c-ef52-4412-9c2a-e3003b1b1a37 유지. 모두 frontend-integration 워크트리에서 실행.
- 실행 DB 백업: PM/var/backups/frontend-before-youtube-source-repair-20261105-142936.db (Git 제외). 사용자 데이터 복구/삭제는 실행하지 않았다. 원래 문제 대상은 skip_missing.
- 실제 두 영상의 공개 자막 확보는 여전히 실패한다. 로컬 모델 실행 smoke와 품질 채택은 별개이며 기본 mock은 유지한다. 검수 점수는 이 수정 범위의 동작 검증이다.
