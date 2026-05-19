# MAGI Spec Engine 사용자 설명서

## 1) 개요

MAGI Spec Engine은 사용자 요청을 바로 구현하지 않고, 구현 에이전트가 사용할 수 있는 검토 완료 명세 문서를 생성하는 도구입니다.

핵심 원칙:

- MAGI는 코드 구현기가 아니라 명세 생성기입니다.
- 최종 산출물은 `final/FINAL_AGENT_SPEC.md`입니다.
- v1 런타임은 OpenAI-only이며, 다중 provider는 확장 포인트로만 유지됩니다.

## 2) 설치

```bash
pip install -e ".[dev]"
```

요구 버전:

- Python 3.11+

## 3) 기본 설정

OpenAI provider를 사용할 때:

```bash
set OPENAI_API_KEY=...
```

테스트/로컬 검증에서는 mock provider 설정을 사용하면 API 키 없이 실행할 수 있습니다.

예시(`mock_config.yaml`):

```yaml
model_routing:
  melchior:
    provider: mock
    model: deterministic
  balthasar:
    provider: mock
    model: deterministic
  casper:
    provider: mock
    model: deterministic
  conflict_resolver:
    provider: mock
    model: deterministic
  spec_composer:
    provider: mock
    model: deterministic
  critical_reporter:
    provider: mock
    model: deterministic
capabilities:
  web_search: "off"
  command_execution: false
```

## 4) 기본 사용 흐름

1. 입력으로 초안 명세 생성
2. 상태 확인
3. 승인 또는 수정 피드백 반영
4. 승인 시 최종 명세 확정

### 4.1 파일 입력

```bash
magi-spec generate --input request.md --output ./magi_output
```

### 4.2 텍스트 입력

```bash
magi-spec generate --text "Build a Python SDK for ..." --output ./magi_output
```

### 4.3 프로젝트 컨텍스트 포함

```bash
magi-spec generate --input request.md --project ./target_project --output ./magi_output
```

### 4.4 웹 리서치 모드

```bash
magi-spec generate --input request.md --output ./magi_output --web-search auto
```

모드:

- `auto`: 요청에 따라 조건부 검색
- `on`: 항상 검색
- `off`: 검색 비활성

### 4.5 가드된 명령 실행 허용

```bash
magi-spec generate --input request.md --output ./magi_output --allow-command-execution
```

명령 실행 기본값은 비활성이며, 허용 시에도 정책상 안전한 명령만 실행됩니다.

### 4.6 승인/수정/상태

```bash
magi-spec approve ./magi_output
magi-spec revise ./magi_output --feedback feedback.md
magi-spec status ./magi_output
```

## 5) Python API 사용

```python
from magi_spec import MagiSpecEngine

engine = MagiSpecEngine()
result = engine.generate_from_file(
    input_path="request.md",
    output_dir="./magi_output",
    project_dir="./target_project",
    web_search_mode="auto",
    allow_command_execution=False,
)

print(result.status)
print(result.approval_candidate_path)
```

## 6) 주요 출력물

`magi_output/` 아래에 다음이 생성됩니다.

- `raw/user_request.md`
- `context/project_manifest.json`
- `research/web_sources.json`
- `evidence/evidence_registry.json`
- `execution/command_log.json`
- `analysis/*.ko.md`
- `review_rounds/round_*/`
- `draft/approval_candidate_spec.en.md`
- `final/FINAL_AGENT_SPEC.md`
- `critical/CRITICAL_REPORT.ko.md` (실패 시)

## 7) 상태 해석

주요 상태:

- `PASS_PENDING_USER_APPROVAL`: 승인 후보 생성 완료
- `FINALIZED`: 최종 명세 확정
- `CRITICAL_BLOCKED`: 최대 라운드 내 합의 실패
- `REJECTED_BY_USER`: 사용자 피드백 기반 수정 대기/재실행

## 8) 정책 요약

- Model-blind 검토: agent-visible packet에서 provider/model 식별 메타데이터와 식별 문자열을 차단합니다.
- 최소/최대 라운드: 기본 3~10 라운드 검토.
- 만장일치 PASS 필요: MELCHIOR/BALTHASAR/CASPER 모두 PASS여야 승인 후보 생성.
- 증거 중심: USER_REQUEST/PROJECT_FILE/WEB_SOURCE/COMMAND_RESULT/AGENT_ASSUMPTION/AGENT_REVIEW 유형으로 기록.

## 9) 트러블슈팅

### OpenAI 키 오류

- 증상: OpenAI provider 선택 시 `OPENAI_API_KEY` 관련 에러
- 조치: 환경 변수 설정 또는 mock provider 사용

### config 오류

- 증상: `Invalid web_search mode` 또는 `min_review_rounds` 관련 에러
- 조치: `web_search`를 `auto|on|off`로 설정하고 `min <= max`, `min >= 1` 보장

### 승인 실패

- 증상: `approve` 실행 시 상태 오류
- 조치: 먼저 `status`에서 `PASS_PENDING_USER_APPROVAL`인지 확인

## 10) 운영 권장

- CI에서는 기본적으로 mock provider 테스트를 실행하세요.
- 실제 OpenAI 라우팅 검증은 별도 환경변수/비밀관리 정책 아래 스모크 테스트로 분리하세요.
- 산출물 디렉터리는 실행 단위로 분리(`./runs/<timestamp>`)해 이력 추적성을 유지하세요.
