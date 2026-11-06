# Phase 2 — YouTube 로컬 LLM 중요 정보 선별

## 범위와 설계

기준 HEAD `23bf3a0c50f85fcb7d338ba34ff77c36e30803b3`. Codex-Primary가 지정 워크트리에서 단독 구현했다. PM DB/API 8791/Vite 5177/기존 worker에는 접근하거나 변경하지 않았다. 외부 LLM/API/네트워크 요청/다운로드 없음. 검색 순위·query·embedding recordings·모델/프로필·DB migration 변경 없음. 기존 설치 패키지와 검증된 로컬 GGUF 캐시만 읽었다. push하지 않는다.

`youtube_metadata`의 실제 LLM 경로에서 기존 summary/tags/category 생성 직전에 별도의 `complete_json` 호출을 추가했다. 제목과 설명을 원문 위치가 있는 구간으로 구조화한다. 설명은 줄 단위, 긴 줄은 최대 500자로 나누며 내용은 정규식으로 삭제하지 않는다. 공백 구간만 생략한다. 모든 구간에 대한 응답 필드를 요구하는 동적 JSON schema를 사용한다.

LLM이 각 구간을 `primary_topic`, `background_music_credit`, `promotion_contact_link`, `license_boilerplate`로 판정한다. 제목·초반 설명·해시태그·채널/인물과 전체 문맥을 함께 보며, 음악 크레딧은 제목과 핵심 본문이 음악 자체일 때 주제 근거로 남을 수 있다. LLM이 생성할 수 있는 것은 역할 enum뿐이다. 원문 텍스트는 서버가 원본 구간에서 가져오므로 선별 단계에서 새 사실이나 가짜 인용을 생성할 수 없다.

`primary_topic` 구간만 기존 LLMContentAnalyzer 생성·검증·제한 재시도 루프에 전달한다. 원제목도 선택된 경우에만 후단 ContentMeta에 들어간다. metadata 전용 scope 지침을 추가해 제목·설명 기준임을 밝히고 게임/음악 문화 콘텐츠의 category, 근거 있는 태그 선택을 안내한다. 기존 요약·태그 수·금지 태그·근거 검증 기준은 낮추지 않았다. 일반 텍스트·정상 자막 분석 프롬프트는 변경하지 않았다.

`MetadataClassification.salience`와 별도 `youtube_salience` trace artifact에 선택/제외 구간, 원문 field/start/end/text, 각 역할, 모델 지문, 프롬프트 버전, 토큰, 지연을 저장한다. 위치는 Python Unicode 문자열 인덱스이며 end는 exclusive다. 기존 결과와 호환되는 optional 필드이며 migration은 없다. 원래 metadata/설명/사용자 원문은 그대로 보존한다. source_scope=youtube_metadata, basis=title_description(설명 없으면 title_only), transcript_reason=empty_captions 등 자막 부재 사유와 기존 안내는 유지한다.

## 실패 정책

제공자 오류는 그대로 전파한다. 빈 응답/JSON 오류/누락·추가 필드/잘못된 역할/전부 auxiliary/미완성·refusal 응답은 AnalysisSchemaError다. 자동 태그, 규칙 결과, mock, 원문 전체로 대체하지 않는다. 256개 구간 상한 초과는 자르지 않고 명시적으로 실패한다. 컨텍스트·출력 토큰 초과도 제공자/스키마 실패로 남는다. 선별 호출 자체의 내부 재요청은 없으며 기존 job 실패 정책만 따른다. 후단 생성 실패도 기존 기준에 따라 실패한다. 성공적인 선별 artifact는 후단 실패 때도 진단할 수 있다.

명시적 mock 평가 경로는 기존 규칙 baseline을 유지한다. live 선별/제공자 실패를 그 경로로 바꾸지 않는다. 저장·확정 트랜잭션은 기존 구현을 재사용한다. 재분석 실패 시 기존 snapshot/AI 요약·태그/수동 수정/메모/컬렉션 소속 보존을 격리 DB 통합 테스트로 확인했다.

## 실제 로컬 재현

외부 요청·다운로드 금지 및 실제 설명 전문의 부재 때문에, 사용자가 제시한 제목·상단 단서·반복 NCS 크레딧을 `tests/fixtures/youtube/salience_case.json`에 **재구성**했다. 실제 URL의 설명 전문을 캡처했다고 주장하지 않는다. URL은 문제 식별용이다. 별도 대조 입력은 제목과 핵심 본문이 Lost Sky 곡 자체인 음악 영상이다. 자막은 두 입력 모두 제공하지 않는다.

재현 명령:

```bash
scripts/live_local.sh scripts/verify_youtube_salience.py
# 실제 캡처가 준비되면 YoutubeMetadata JSON 경로를 첫 인자로 전달
scripts/live_local.sh scripts/verify_youtube_salience.py /absolute/path/captured_metadata.json
```

검증 스크립트는 DB/서버/embedding을 만들지 않고 실제 로컬 제공자와 동일 생성 검증 루프를 직접 호출한다. HF offline 환경이며 GGUF sha256 검증은 기존 제공자가 수행한다. 실행 모델: Kanana 1.5 2.1B Q4_K_M, `kanana-1.5-2.1b-instruct-q4km@5baf76ee0939~bbdbf37b`.

개발 중 확인한 실패도 숨기지 않는다. 초기 영문 ID 목록 선별은 반복 크레딧을 핵심으로 남겼고, 한국어 ID 목록은 제목만 남기면서 해시태그를 놓쳤다. 전체 구간별 bool 응답도 첫 음악 크레딧 한 줄을 남겼다. 최종 역할별 schema에서는 게임 입력의 제목·해시태그만 primary로, NCS 크레딧 전부를 auxiliary로 분리했다. 이후 기존 생성기의 플랫폼명 단독 태그 때문에 최소 태그 수 검증이 실패해, 검증 완화 대신 metadata scope 지침을 보강했다. 이 재현 fixture는 개발용이며 golden dev/test split이나 품질 기준을 변경하지 않았다.

### 확보된 실제 결과와 중단 시점

증거: `specs/youtube_salience_local_validation.json`. 초기 실패와 역할 schema 이후 실행을 구분해 보존했다. 중단 요청 직전에 시작된 추가 실행은 종료 확인 시 이미 프로세스가 사라진 상태였으며, 그 출력은 열거나 검증 결과로 채택하지 않았다. 새 모델 실측은 수행하지 않는다.

- 사용자 제공 기존 문제: 음악 소개로 요약, 발로란트트랙/ncs공개곡/음악소개, category=tech. 이 워크트리의 재구성 입력으로 실행한 기존 생성 경로는 검증 재요청을 소진했으므로, 사용자 제공 오분류를 동일 출력으로 재현했다고 주장하지 않는다.
- 실제 salience: 게임 입력에서 원제목과 `#발로란트 #김된모`만 primary. 음악 크레딧 전체는 background_music_credit, 상단 홍보/문의는 promotion_contact_link로 분리됐다. 음악 입력은 `Lost Sky - Dreams pt. II [NCS Release]` 제목을 primary로 보존하고 라이선스 안내는 auxiliary로 분리했다. 즉 NCS 문자열의 일괄 삭제가 아니다.
- 실제 후단 한계: 역할 schema 이후 게임·음악 입력 모두 플랫폼명 태그 제거 후 대표 태그가 2개만 남는 최소 태그 검증 실패가 관찰됐다. 실패를 저장 성공으로 바꾸지 않았다.
- 이후 확보된 실행에서는 게임 입력의 태그 발로란트/김된모/레디언트와 category=culture_media가 검증을 통과했다. 그러나 요약 첫 문장이 “발로란트는 결국 저를 통합니다.”로 제목을 부정확하게 바꾸고 제목·설명 범위도 문장에 명시하지 않았다. 이를 기대 품질 달성으로 보고하지 않는다. 같은 실행의 음악 입력은 가짜 evidence.source_span과 문장 수 등의 검증 실패가 남았다.
- 현재 보존한 구현에는 범위 명시·제목의 비유를 사실로 바꾸지 않기·원문 인용 지침이 더해져 있다. 그 마지막 소스 상태의 live 품질은 **미확인**이다. downstream 최종 생성 품질 보장은 미완료이며 추가 튜닝·반복 측정은 사용자 지시로 중단했다.

## 검사

개발 중 관련 pytest 282 passed / 2 skipped. 두 skip은 실제 설명 캡처가 이 워크트리에 없어 건너뛴 기존 테스트다. 두 warning은 의도된 provider 불가 테스트다. 원문 위치·구간 완전성·실제 음악 영상 보존·구간 상한·빈/무효/제공자 실패·후단 입력의 크레딧 제외·trace 보존·기존 수동 층/컬렉션 실패 보존을 포함한다.

사용자 중단 후 최소 최종 검사는 아래에 기록한다.

### 후속 수정 결과 (5ee55c3 이후)

최소 태그 검증이 실패한 metadata 전용 재요청에만 보완 문맥을 추가했다. 원문에 존재하는 서로 다른 해시태그의 `#`을 뗀 이름과 제목의 게임명·인물명·작품명으로 태그를 구성하도록 안내하며, 플랫폼명 단독 태그 배제와 원문 근거·기존 검증 기준은 유지한다. 일반 분석 프롬프트·validator·golden·DB는 수정하지 않았다. 기록 fake 테스트는 태그 2개인 첫 응답이 재요청되고 동일 검증을 통과하는 흐름과 재요청 지침을 확인한다.

문제 재구성 fixture에 대한 마지막 실제 Kanana 실행은 **1회**였다 (`scripts/live_local.sh scripts/verify_youtube_salience.py --skip-before --gaming-only`). salience에서 제목과 `#발로란트 #김된모`를 선택하고 반복 음악 크레딧은 제외했다. 후단 생성은 4개 대표 태그로 최소 수 검증을 통과했고 `youtube` 플랫폼 태그는 내지 않았다. 다만 결과에는 `발로란티브`, category=`howto_recipe`, 게임 장면·시스템을 소개한다는 근거 없는 진술이 포함됐다. 따라서 원래의 태그 수/플랫폼명 실패는 이 재구성 입력에서 해결했지만 의미 정확도는 통과로 볼 수 없으며, 재시도 보강이 이를 보장하지 않는다. 요청에 따라 이 결과 뒤 추가 live 실행은 하지 않았다. 음악 제목 보존은 기존 fixture/test 경로를 유지했고 이번 live에서 음악 입력을 추가 호출하지 않았다.

후속 관련 검사: `pytest tests/unit/test_youtube_salience.py tests/integration/test_live_llm_save.py tests/integration/test_youtube_metadata.py -q` **40 passed / 2 skipped**; 변경 Python ruff 통과; 변경 소스/검증 스크립트 mypy 통과; `git diff --check` 통과. 테스트 모듈은 저장소의 기존 mypy 설정에서 단독 검사 시 다수의 기존 무타입 함수 오류가 있어, mypy 대상은 변경 소스와 검증 스크립트로 한정했다.

## 한계

- 실제 영상/자막을 분석한 결과가 아니다. 게임의 구체적 장면·승패·발언은 알 수 없다. 실제 설명 전문으로의 재검증은 남는다.
- 추출 위치와 원문 일치는 결정적으로 보장하지만, 어떤 원문이 중요한지 판단하는 의미적 정확성은 로컬 모델 품질에 의존한다. 한 사례 성공이 기존 모델 품질 기준 통과를 의미하지 않는다.
- 한 줄에 주제와 광고/크레딧이 섞이면 같은 구간으로 판단할 수 있다. 장문은 500자 경계에서 나뉜다. 상한을 넘는 복잡한 입력은 실패할 수 있다.
- 로컬 호출 1회가 추가된다. metadata 선별의 토큰·지연은 별도 salience.meta에 있으며 후단 분석 지표에 합산하지 않는다.
- 선별된 근거가 부족해 기존 최소 태그 수/한국어 요약 검증을 만족하지 못하면 실패한다. 근거 없는 태그나 사실로 수를 채우지 않는다.
- 짧은 metadata 입력에서 재요청 지침은 해시태그·제목 단서를 더 잘 활용하도록 유도하지만, live 한 번에서 보듯 의미적 정확성이나 올바른 category를 보장하지 않는다.

### 정확한 메타데이터 후속 수정 검증 (2026-11-06)

사용자가 지정한 PM API GET `c_9915339028744c1897c4b2b8d37985b4`에서 읽기 전용으로 얻은 제목·설명 전체를 사용했다. 제목은 `모든 레디언트는 결국 저를 통합니다`, 설명의 주제 해시태그는 `#발로란트 #김된모`다. 생방송·문의·PC 링크와 Lost Sky/NCS 음악 크레딧이 설명에 함께 있다. API 쓰기, 재분석, 실제 DB 변경은 하지 않았다.

metadata 전용 지침을 보강해 해시태그/제목의 원문 표현을 사용하도록 하고, 대표 태그가 원문에서 확인되는지와 절차 안내 근거 없는 `howto_recipe`를 metadata 전용 재요청 검증에 추가했다. 기존 validator·최소 3개 태그 기준은 유지했다. Fake/격리 통합 검사는 live 전에 통과했다.

정확한 메타데이터를 넣은 실제 Kanana 스크립트는 1회 실행했다. Salience 결과는 제목과 `#발로란트 #김된모`를 primary로 선택하고 생방송·광고·PC 링크·음악 크레딧을 auxiliary로 분류했다. 다만 후단 생성은 대표 태그 3개가 원문 표현 검증을 통과하지 못해 기본 분석 1회와 기존 검증 재요청 2회를 거친 뒤 실패했다. 스크립트 결과는 `/tmp/kanana_metadata_once.json`에 남아 있다. 최종 summary/tags/category 검증은 성공하지 못했으며, 사용자의 단일 실행 제한에 따라 추가 live 실행과 사후 튜닝은 하지 않았다. 따라서 목표 완료로 판정하지 않는다.

이번에 추가한 metadata 전용 의미 검증은 제목·설명에서 공백을 무시한 원문 부분 문자열만 태그로 인정하며, howto_recipe에는 명시적인 절차/레시피 단서가 필요하다. 한국어 복합어·형태 변화가 많은 태그는 원문 표현과 정확히 대응하지 않을 수 있고, 이번 live 실패는 이 엄격한 검사와 모델 출력이 합치하지 못한 사례다. 규칙을 완화하거나 추가 live 호출로 맞추지 않았다.

후속 fake/recorded/격리 테스트: `tests/unit/test_youtube_salience.py`, `tests/integration/test_live_llm_save.py`, `tests/integration/test_youtube_metadata.py` 결과는 43 passed / 2 skipped. ruff와 mypy는 변경 소스에서 통과했다. 실제 live 결과는 위와 같이 실패로 기록하며 성공 기준 통과를 주장하지 않는다.

### MVP metadata grounded tag 복구 (820c762 후속)

실제 Kanana는 추가 호출하지 않았다. `youtube_metadata` 경로에서만 LLM JSON을 기존 validator에 넘기기 직전에 결정적 보정을 추가했다. 순서는 원문 해시태그 본문, 기존 LLM 태그 중 원문에 연속 부분 문자열로 있는 태그, 제목 토큰의 보수적 조사/어미 제거다. 공백 차이만 무시해 근거를 찾는다. 플랫폼·배포처와 제한된 일반 불용어는 후보에서 뺀다. 원문 근거 태그가 3개 이상 만들어질 때에만 태그 배열을 교체하며, 부족하면 기존 validator와 재요청 처리가 이어진다.

`howto_recipe`는 절차 표현이 없고 제목·선별 원문에서 명백한 게임/음악 단서가 있을 때에만 `culture_media`로 보정한다. 다른 주제의 `howto_recipe`는 변환하지 않아 metadata 전용 기존 검증/재요청 경로가 처리한다. 일반 분석 validator와 일반 텍스트 분석은 변경하지 않았다.

Fake/격리 DB 통합 테스트는 잘못된 태그(`발로란트트랙`, `ncs공개곡`, `음악소개`)와 how-to category를 `발로란트`, `김된모`, `레디언트` 및 `culture_media`로 복구해 job 저장까지 확인한다. 별도 unit 테스트는 음악 제목의 원문 근거 태그 보존, 불용어 제외, 복구 후보 3개 미만일 때 원 응답 유지, 비게임/비음악 how-to 보정을 하지 않는 경우를 확인한다. targeted pytest 44 passed / 2 skipped, ruff, mypy, `git diff --check` 통과.

한계: 새 보정은 이전 실제 Kanana 실패 응답에 대해 이번에 live 재생하지 않았다. 따라서 정확한 실제 모델 출력에서의 성공은 확인되지 않았다. 이 로직은 출처 문자열에 그대로 있거나 보수적으로 파생 가능한 표현만 살리며, 유효 후보가 3개 미만이면 태그를 채우지 않고 기존 실패/재요청 정책에 맡긴다. 단일 사례의 fake 성공을 전체 모델 의미 정확도 통과로 간주하지 않는다.

### 제목·해시태그 metadata grounded 후처리 (cb0f553 후속)

사용자 보고 통합 결과에서 salience primary가 제목과 `#발로란트 #김된모`만 정확히 남겼는데도, 후단 요약이 `발로란티브 게임의 인기 캐릭터`를 만들어내고 keywords 및 save intent에 `발로란티브`, `과제`, `공부자료`가 남은 문제를 보완했다. 실제 Kanana/API/네트워크/실DB 호출은 하지 않았다.

`youtube_metadata` 생성 응답 보정에만 적용하며, 선별된 비어 있지 않은 입력이 제목과 해시태그 전용 구간으로 구성된 경우로 한정했다. 요약을 제목·해시태그에서 확인할 수 있는 범위 안내 문장으로 결정적으로 교체한다. detail_tags.topics와 keywords는 해시태그 및 제목에서 뽑은 grounded 문자열로 다시 만들고, entities는 이름이 입력 원문에 그대로 있는 항목만 남긴다. save_intent와 purpose는 스키마를 유지하면서 보수적인 `정보보관` 기본값으로 정리한다. 기존 대표 태그 복구는 그대로 유지한다.

Fake 저장 통합 테스트는 잘못된 요약·keywords·entities·저장 의도를 보정한 응답이 실제 job 성공 및 저장 결과에 반영되는지 확인한다. 추가 unit 테스트는 제목/해시태그 한정 보정과 해시태그 없는 Lost Sky 음악 제목의 확장 보정 비적용을 확인한다. targeted pytest `tests/unit/test_youtube_salience.py tests/integration/test_live_llm_save.py tests/integration/test_youtube_metadata.py -q`: **46 passed / 2 skipped**. ruff, 변경 소스 mypy, `git diff --check` 통과.

한계: 이는 결정적이고 매우 좁은 제목·해시태그 전용 경로의 보정이며, 요약의 관련 콘텐츠 분류는 첫 해시태그에 기반한다. 일반적인 설명문 중심 입력, 다른 해시태그 의미, 실제 모델 출력에서의 보편적인 의미 정확성을 검증하거나 보장하지 않는다. 요청에 따라 실제 모델 실행은 생략했다.

이전 최소 최종 확인은 5ee55c3 시점에 pytest **86 passed / 2 skipped**, ruff/mypy 및 `git diff --check` 통과였다. 위 후속 검사와 마지막 live 결과는 그 이후 별도로 기록했다. 구현과 보고서를 새 커밋에 포함하며 push하지 않는다.
