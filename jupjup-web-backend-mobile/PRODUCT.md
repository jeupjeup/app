# Product

<!-- impeccable:product-schema 1 -->

> 이 문서는 사용자가 확정한 로컬 웹 데모 요청과 기존 Phase 2 설계/구현에서 추론한 제품 문맥이다.
> 별도 인터뷰 없이 진행하라는 요청에 따라, 추론 항목은 아래에 명시했다.

## Platform

web

## Users

- 줍줍저장소의 자연어 검색 품질을 로컬에서 검토하거나 시연하는 사용자.
- 추론: 주 사용 장면은 개발자 또는 제품 담당자가 데스크톱·모바일 브라우저에서 골든 시드 데이터를
  검색하며 질의 해석과 결과 순위를 함께 확인하는 상황이다.

## Product Purpose

사용자가 저장물의 정확한 제목을 기억하지 못해도 기억나는 기간, 플랫폼, 유형, 주제와 목적을 자연어로
말해 다시 찾게 한다. 로컬 웹 데모의 성공은 기존 검색 코어를 바꾸지 않고 그 해석 과정과 결과를 사람이
빠르게 이해할 수 있게 보여 주는 것이다.

## Positioning

검색 결과만 보여 주는 대신, 기간·필터 창·플랫폼·유형·키워드·의미 질의로 기억이 어떻게 해석됐는지와
각 결과의 매칭 근거를 같은 화면에서 드러낸다.

## Operating Context

- Python 3.12, FastAPI, SQLite, kiwipiepy, 앱 내장 BM25F, numpy 벡터 검색, uv.
- 로컬 개발 환경에서 골든 시드를 SQLite에 적재한 뒤 브라우저로 시연한다.
- 사용자 선택은 `u_alice`, `u_bob`, `u_carol`이며 재현 기준 시각은
  `2026-10-15T12:00+09:00`이다.

## Capabilities and Constraints

- 데모는 `src/jupjup/demo/`에 격리된 dev 전용 표면이다.
- 기존 `AppContainer`와 `SearchService`를 그대로 호출하며 검색 로직을 복제하지 않는다.
- 네트워크 제공자나 외부 CDN을 사용하지 않는다. Hashing 임베더와 Mock 제공자만 사용한다.
- 단일 HTML 페이지에 인라인 CSS/JS를 사용하며 모바일 폭과 다크모드를 지원한다.
- 이 데모는 운영 API가 아니며 인증·배포 기능을 제공하지 않는다.

## Brand Commitments

- 제품명은 “줍줍저장소”.
- 한국어로 친근하고 명료하게 말한다.
- 검색창의 안내 문구는 “기억나는 대로 말해보세요.”이다.

## Evidence on Hand

- 제품/검색 설계: `specs/prd_and_design.md`
- Phase 2 구현 및 데모 질의: `specs/phase2_report.md`
- 골든 시드 200건: `data/golden/seeds.jsonl` — **초안, 사용자 검수 전**
- 기존 CLI와 검색 응답: `src/jupjup/cli.py`, `src/jupjup/search/`

## Product Principles

1. 검색 코어는 하나만 둔다. 데모는 기존 서비스를 설명하고 호출할 뿐이다.
2. 결과와 함께 해석 근거를 보여 신뢰와 디버깅 가능성을 높인다.
3. 골든 데이터의 초안 상태와 dev 전용 경계를 숨기지 않는다.
4. 재현 가능한 기준 시각과 사용자 격리를 유지한다.

## Accessibility & Inclusion

키보드만으로 검색할 수 있어야 하고, 명확한 포커스 상태·충분한 대비·의미 있는 상태 메시지를 제공한다.
시스템 다크모드와 작은 모바일 화면에서도 정보 손실 없이 사용할 수 있어야 한다.
