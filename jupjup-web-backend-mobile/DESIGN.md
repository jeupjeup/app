---
name: "줍줍저장소 로컬 검색 데모"
description: "흐릿한 기억을 해석 가능한 단서와 근거 있는 저장물로 잇는 오프라인 검색 작업면"
colors:
  workbench: "light-dark(#eef3f8, #0d1520)"
  paper: "light-dark(#ffffff, #151f2c)"
  paper-soft: "light-dark(#f7f9fc, #1a2635)"
  ink: "light-dark(#152235, #edf4fc)"
  ink-muted: "light-dark(#53657b, #afbed0)"
  ink-faint: "light-dark(#5f7186, #a4b3c5)"
  rule: "light-dark(#d6e0ea, #314054)"
  cobalt-action: "light-dark(#1467e8, #78aefb)"
  cobalt-action-strong: "light-dark(#0d4fae, #b9d6ff)"
  cobalt-action-soft: "light-dark(#e8f1ff, #1c3558)"
  success: "light-dark(#13715a, #78d6b8)"
  warning: "light-dark(#9a4f0c, #ffbd73)"
  token-surface: "light-dark(#edf2f6, #243244)"
  token-ink: "light-dark(#33475e, #d1dbea)"
  error: "#b23a3a"
typography:
  display:
    fontFamily: '"Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    fontSize: "clamp(1.6rem, 5vw, 3.25rem)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  headline:
    fontFamily: '"Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    fontSize: "clamp(1.45rem, 3vw, 2rem)"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.03em"
  title:
    fontFamily: '"Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    fontSize: "1.05rem"
    fontWeight: 800
    lineHeight: 1.35
    letterSpacing: "-0.02em"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    fontSize: "0.78rem"
    fontWeight: 720
    lineHeight: 1.35
    letterSpacing: "normal"
rounded:
  reason: "7px"
  control: "11px"
  standard: "14px"
  stage-mobile: "18px"
  stage: "22px"
  pill: "999px"
spacing:
  xs: "5px"
  sm: "8px"
  md: "12px"
  lg: "18px"
  xl: "22px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.cobalt-action}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.standard}"
    padding: "0 22px"
    height: "58px"
    width: "112px"
  button-primary-hover:
    backgroundColor: "{colors.cobalt-action-strong}"
    textColor: "{colors.paper}"
    rounded: "{rounded.standard}"
  input-search:
    backgroundColor: "{colors.paper-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.standard}"
    padding: "0 18px"
    height: "58px"
  chip-example:
    backgroundColor: "transparent"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
    padding: "8px 12px"
  panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.standard}"
    padding: "20px"
---

# Design System: 줍줍저장소 로컬 검색 데모

## Overview

**Creative North Star: "기억 경로표"**

이 데모는 흐릿한 개인의 기억이 차분한 작업면 위에서 단서로 정리되고, 근거가 붙은 저장물에 도착하는 과정을 한눈에 읽게 한다. 푸른 회색 바탕과 흰 기록지, 원형 순위 표식은 검색 결과의 양보다 해석 경로를 앞세운다. 친근한 한국어 문장과 높은 정보 명료도를 유지하되, 소비자용 마케팅 화면처럼 꾸미거나 대시보드형 카드 격자로 분절하지 않는다.

이 시각 계약은 `src/jupjup/demo/`의 dev 전용 단일 페이지에 한정된다. 구현은 외부 자산이나 CDN 없이 하나의 인라인 HTML/CSS/JS 문서로 동작하고, 밝은 모드와 어두운 모드, 데스크톱과 작은 모바일 폭에서 같은 정보 구조를 보존해야 한다.

**Key Characteristics:**

- 푸른 회색 작업면 위의 중립적 기록지
- `기억 입력 → 단서 해석 → 저장물 도착`으로 이어지는 명시적 진행 경로
- 행동과 포커스에만 드물게 등장하는 코발트
- 둥근 제어 요소와 절제된 구조적 선, 검색 시작면에만 쓰는 부드러운 부유감
- 한국어로 친근하지만 상태와 데이터 경계를 숨기지 않는 문장

## Colors

팔레트는 차가운 중립색을 구조와 읽기에 사용하고, 코발트는 사용자가 행동하거나 초점을 옮기는 순간에만 사용한다. frontmatter의 `light-dark()` 쌍은 각각 구현의 밝은 모드 값과 시스템 다크 모드 재정의 값을 그대로 묶은 규범 토큰이다.

### Primary

- **행동 코발트:** 검색 버튼, 입력 포커스, 예시 질의 호버처럼 상호작용 가능한 상태를 식별한다.
- **강한 행동 코발트:** 주요 행동의 호버 상태와 강조된 상호작용 텍스트에만 쓴다.
- **옅은 행동 코발트:** 포커스 링이나 호버 배경처럼 행동 코발트를 받치는 낮은 강도의 상태면이다.

### Neutral

- **푸른 회색 작업면:** 페이지 전체 배경과 진행 표식의 바깥 링을 만든다.
- **기록지:** 검색 시작면, 해석 패널, 결과 카드의 기본 표면이다.
- **부드러운 기록지:** 입력 필드, 이유 배지처럼 표면 안의 낮은 층을 구분한다.
- **잉크:** 제목, 현재 단계, 순위 표식처럼 가장 높은 정보 우선순위를 담당한다.
- **중간 잉크 / 옅은 잉크:** 본문 보조 정보와 메타데이터를 두 단계로 낮춘다. 옅은 잉크도 접근 가능한 대비를 유지한다.
- **구조선:** 패널, 필드, 결과 카드와 흐름선을 조용히 구분한다.
- **토큰 표면 / 토큰 잉크:** 해석된 키워드와 목적어를 작고 읽기 쉬운 캡슐로 묶는다.
- **성공 / 경고 / 오류:** 태그 기호, 삭제 상태, 검증 오류처럼 의미가 있는 상태에만 사용한다.

### Named Rules

**The Action-Only Cobalt Rule.** 코발트는 주요 행동, 호버, 포커스처럼 사용자의 다음 조작을 알리는 데만 쓴다. 브랜드 면적, 순위 원, 장식 선이나 일반 정보 배지로 확장하지 않는다.

**The Neutral Evidence Rule.** 검색 해석과 결과 근거는 중립색의 위계, 선, 간격으로 설명한다. 상태색을 데이터 분류색처럼 남용하지 않는다.

## Typography

**Display Font:** Apple SD Gothic Neo, Noto Sans KR, sans-serif fallback
**Body Font:** system UI, Apple SD Gothic Neo, Noto Sans KR, sans-serif fallback

**Character:** 크고 단단한 한국어 제목과 차분한 시스템 본문을 조합한다. 별도의 재배포 가능한 한국어 디스플레이 폰트가 프로젝트에 번들되어 있지 않으므로, 구현은 의도적으로 오프라인 안전한 시스템 한국어 글꼴 스택을 사용한다. 외부 폰트 요청이나 CDN 의존성을 추가하지 않는다.

### Hierarchy

- **Display:** 검색 시작면의 한 문장에만 쓰며, 짧고 균형 잡힌 두 줄을 허용한다.
- **Headline:** 제품명과 화면 최상위 식별자에 사용한다.
- **Title:** 패널 제목과 결과 제목에 사용한다. 결과 제목은 읽기 흐름을 위해 조금 더 느슨한 행간을 유지한다.
- **Body:** 설명, 요약, 상태 메시지에 사용하며 결과 요약은 약 70자 폭을 넘기지 않는다.
- **Label:** 제어 레이블, 메타데이터, 진행 단계와 작은 배지에 사용한다. 대문자화하지 않는다.

### Named Rules

**The Offline Korean Rule.** 한국어 글꼴은 설치된 시스템 글꼴로 자연스럽게 폴백되어야 한다. 번들에 없는 특정 폰트를 가장하거나 네트워크 폰트를 불러오지 않는다.

**The Short Display Rule.** 큰 디스플레이 크기는 검색 장면의 핵심 약속 한 문장에만 쓴다. 데이터 패널과 결과는 촘촘하고 안정적인 제목 위계로 돌아온다.

## Layout

콘텐츠는 최대 폭 1180px의 중앙 셸에 놓이고, 데스크톱에서 좌우 여백은 20px 이상, 위쪽은 32px이다. 큰 검색면이 첫 시야를 점유한 뒤, 3단계 경로와 `해석 250–330px / 결과 가변 폭`의 두 열 작업영역이 이어진다. 해석 패널은 데스크톱에서 상단 20px에 고정되어 결과를 읽는 동안 단서를 계속 비교할 수 있다.

공간 리듬은 8px과 12px을 작은 단위로 삼고 18px, 22px, 32px으로 섹션을 확장한다. 정보는 카드 격자로 균등 분할하지 않고 하나의 수직 검색 서사로 흐른다. 결과의 숫자, 시간, 점수는 탭형 숫자로 정렬한다.

760px 이하에서는 셸 여백을 12px로 줄이고 검색 입력과 버튼, 보조 제어, 해석/결과 열을 모두 한 열로 쌓는다. 고정 해석 패널은 일반 흐름으로 돌아오고, 결과가 나타나면 예시 질의는 숨긴다. 결과 카드는 순위 원을 32px로 줄이고 점수는 제목 아래로 이동한다. 검색 완료 후 경로 표식으로 부드럽게 스크롤하되, 모션 감소 설정에서는 즉시 이동한다.

**The One Journey Rule.** 반응형 변화는 `기억 입력 → 단서 해석 → 저장물 도착` 순서를 바꾸지 않는다. 좁은 화면에서도 어떤 정보도 삭제하지 않고 재배치한다.

## Elevation & Depth

시스템은 대부분 선과 색조 층으로 깊이를 만든다. 검색 시작면만 주변 작업면에서 떠 있는 진입점으로 보여 주기 위해 넓고 낮은 주변 그림자를 사용한다. 패널과 결과 카드는 기본적으로 평평하며 1px 구조선으로 구분한다. 다크 모드에서는 검색 시작면의 그림자만 검은색 투명도를 높인다.

### Shadow Vocabulary

- **검색 시작면:** 밝은 모드의 `0 18px 50px rgba(37, 64, 92, .11)`와 어두운 모드의 `0 18px 54px rgba(0, 0, 0, .28)`을 사용한다. 다른 카드에는 복제하지 않는다.
- **포커스 후광:** 검색 입력은 행동 코발트의 옅은 상태면을 4px 외곽으로 두르고, 버튼·칩·보조 제어는 3px 반투명 아웃라인과 2px 오프셋을 사용한다.

### Named Rules

**The Entry Surface Rule.** 그림자는 검색을 시작하는 한 면에만 허용한다. 검색 결과나 해석 패널의 중요도를 그림자 경쟁으로 표현하지 않는다.

## Shapes

기본 패널, 결과 카드, 검색 입력과 버튼은 14px의 부드러운 모서리를 공유한다. 작은 보조 제어는 11px, 이유 배지는 7px을 사용한다. 검색 시작면은 더 넓은 22px 모서리로 장면을 묶고 모바일에서 18px로 조인다. 예시 질의와 해석 토큰은 완전한 알약 형태이며, 순위와 진행 표식은 원형이다. 1px 구조선은 형태를 설명하고, 점선은 빈 결과 면처럼 아직 채워지지 않은 상태에만 사용한다.

**The Nested Radius Rule.** 바깥 장면이 가장 크게, 일반 구성요소가 중간, 내부 근거 배지가 가장 작게 둥글어야 한다. 모든 요소를 같은 알약 형태로 만들지 않는다.

## Components

### Buttons

- **Shape:** 검색 입력과 높이를 맞춘 14px 모서리의 단단한 직사각형이다.
- **Primary:** 행동 코발트 배경과 높은 대비의 글자를 사용하며 최소 높이 58px, 최소 폭 112px을 보장한다. 모바일에서는 한 줄 전체 폭이다.
- **Hover / Focus:** 호버는 강한 행동 코발트로 깊어지고, 포커스는 3px 반투명 코발트 아웃라인을 표시한다. 누르는 순간 0.98 배 축소하며, 모션 감소 설정에서는 전환을 사실상 제거한다.
- **Loading / Disabled:** `찾는 중…` 문구, 대기 커서와 낮은 불투명도로 비동기 상태를 명시한다.

### Chips

- **Example chip:** 투명 배경과 구조선, 중간 잉크를 사용한다. 호버에서만 옅은 코발트 배경과 강한 코발트 텍스트를 받는다.
- **Interpretation token:** 조작 요소가 아닌 읽기 전용 캡슐이며 중립 토큰 표면과 잉크를 사용한다. 예시 질의 칩과 시각적으로 구분한다.

### Cards / Containers

- **Search stage:** 22px 모서리, 기록지 배경과 유일한 주변 그림자를 갖는 진입 면이다.
- **Understanding panel:** 14px 모서리, 1px 구조선, 20px 안쪽 여백을 사용하며 항목은 얇은 구분선으로 이어진다.
- **Result card:** 14px 모서리와 1px 구조선만 사용한다. 44px 원형 순위 표식, 제목·점수, 메타, 요약, 태그, 매칭 근거 순으로 읽힌다.
- **Empty result:** 같은 모서리와 점선 구조선으로 아직 결과가 없음을 표현하고, 상태 문장과 다음 행동을 함께 제공한다.

### Inputs / Fields

- **Search input:** 높이 58px, 14px 모서리, 부드러운 기록지 배경을 사용한다. 한국어 플레이스홀더는 “기억나는 대로 말해보세요.”를 유지한다.
- **Secondary controls:** 사용자와 기준 시각 제어는 최소 높이 42px, 11px 모서리로 검색 입력보다 낮은 위계를 갖는다.
- **Focus:** 배경을 기록지로 올리고 행동 코발트 선과 명확한 외곽 후광을 표시한다.
- **Error:** 오류 상태는 텍스트로 이유와 다음 행동을 말하고 의미 있는 오류색을 사용한다. 색만으로 상태를 전달하지 않는다.

### Navigation

검색 흐름은 세 개의 동일한 열, 가는 연결선과 원형 점으로 구성한다. 현재 단계는 잉크색과 `aria-current="step"`으로 함께 표시한다. 이 탐색은 페이지 이동용 탭이 아니라 현재 검색 여정의 상태 표시다.

### Status and Results

상태 문구는 `role="status"`와 `aria-live="polite"`로 로딩, 성공, 저하, 오류를 알린다. 검색 결과는 새 데이터가 도착할 때 짧은 페이드·상승·블러 해제 전환을 한 번 사용하며, 모션 감소 설정을 존중한다. 결과에는 순위와 점수뿐 아니라 플랫폼, 유형, 저장일, 원본 삭제 여부, 태그와 매칭 이유를 포함해 신뢰 근거를 보존한다.

## Do's and Don'ts

### Do:

- **Do** 모든 새 표면을 외부 자산 없는 단일 인라인 HTML/CSS/JS라는 dev 데모 경계 안에서 구현한다.
- **Do** 시스템 다크 모드와 280px 이상의 작은 화면에서 정보 손실 없는 레이아웃을 유지한다.
- **Do** 모든 필드와 행동에 프로그램적으로 연결된 레이블, 키보드 접근, 명확한 포커스와 텍스트 상태를 제공한다.
- **Do** 코발트는 행동과 포커스에만 사용하고, 나머지 위계는 중립 토큰으로 만든다.
- **Do** 검색 화면의 중심 서사를 `기억 입력 → 단서 해석 → 저장물 도착` 순서로 유지한다.
- **Do** 화면 하단에서 골든 데이터가 검수 전 초안이며 화면이 dev 전용 로컬 데모임을 계속 밝힌다.

### Don't:

- **Don't** CDN, 웹폰트, 원격 아이콘, 이미지 또는 다른 외부 자산을 추가한다.
- **Don't** 별도의 재배포 가능한 한국어 디스플레이 폰트가 번들되어 있다고 가정한다. 오프라인 안전한 시스템 한국어 글꼴 스택을 유지한다.
- **Don't** 결과를 장식적 카드 격자나 다채로운 카테고리 색으로 바꾸어 해석 경로와 근거를 약화한다.
- **Don't** 코발트를 브랜드 장식, 일반 배지, 순위 표식 또는 넓은 배경 면으로 확장한다.
- **Don't** 로딩, 오류, 저하, 삭제 상태를 색이나 모션만으로 표현한다.
