# MAGI Spec Engine 사용자 설명서 (v2)

## 1) 개요

MAGI Spec Engine은 사용자 요청을 바로 구현하지 않고, 구현 에이전트가 사용할 수 있는 검토 완료 명세 문서를 생성하는 도구입니다.

핵심 원칙:

- MAGI는 코드 구현기가 아니라 명세 생성기입니다.
- 최종 산출물은 `final/FINAL_AGENT_SPEC.md`입니다.
- 런타임은 OpenAI-only이며, 다른 provider는 확장 포인트로만 유지됩니다.
- SpecForge 4단계 파이프라인으로 동작합니다.

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

### mock 설정 예시

```yaml
model_routing:
  interviewer:
    provider: mock
    model: deterministic
  critic:
    provider: mock
    model: deterministic
  compiler:
    provider: mock
    model: deterministic
  critical_reporter:
    provider: mock
    model: deterministic
capabilities:
  web_search: "off"
  command_execution: false
pipeline:
  version: v2
review:
  max_critic_passes: 2
```


## 4) SpecForge 파이프라인

SpecForge는 4단계 결정론적 컴파일러입니다.

```
Spec Interviewer → Requirement Lock → Spec Compiler → Checklist Critic
```

### 4.1 Spec Interviewer

- 요청 유형을 분류합니다: `product` / `feature` / `bugfix` / `refactor` / `infra`
- 차단 질문(방향전환급)과 가정 가능한 답변을 식별합니다.
- 방향전환급 차단 질문이 있으면 `NEEDS_USER_INPUT` 상태로 종료합니다.

### 4.2 Requirement Lock

- 사용자 답변, 가정, 필수 요구사항, 비범위, 제약을 구조화된 Lock Sheet로 고정합니다.
- 산출물: `analysis/requirement_lock_sheet.json`, `analysis/requirement_lock_sheet.ko.md`

### 4.3 Spec Compiler

- Lock Sheet를 입력으로 단일 영어 Markdown 명세를 생성합니다.
- 반드시 26개 필수 섹션을 포함해야 합니다.
- 산출물: `draft/approval_candidate_spec.en.md`

### 4.4 Checklist Critic

- 결정론적 체크(토큰 0) + LLM 보조 체크를 수행합니다.
- 최대 2회(`max_critic_passes`) 실행합니다.
- Blocking issue가 남으면 재컴파일, 한계를 초과하면 `CRITICAL_BLOCKED`입니다.

체크 항목:

| 항목 | 심각도 |
|---|---|
| 26개 필수 섹션 존재 | blocking |
| Out of Scope 비어있지 않음 | blocking |
| Forbidden Behaviors 비어있지 않음 | blocking |
| Acceptance Criteria 검증 가능 | blocking |
| Test Plan 존재 | blocking |
| 미해결 차단 질문 0개 | blocking |
| 모호한 표현(robust, good 등) 없음 | major |
| 모든 필수 요구사항이 명세에 반영됨 | major |

## 5) 기본 사용 흐름

### 5.1 파일 입력

```bash
magi-spec generate --input request.md --output ./magi_output
```

### 5.2 텍스트 입력

```bash
magi-spec generate --text "Build a Python SDK for ..." --output ./magi_output
```

### 5.3 프로젝트 컨텍스트 포함

```bash
magi-spec generate --input request.md --project ./target_project --output ./magi_output
```

### 5.4 웹 리서치 모드

```bash
magi-spec generate --input request.md --output ./magi_output --web-search auto
```

모드:

- `auto`: 요청에 따라 조건부 검색
- `on`: 항상 검색
- `off`: 검색 비활성

### 5.5 승인/수정/상태

```bash
magi-spec approve ./magi_output
magi-spec revise ./magi_output --feedback feedback.md
magi-spec status ./magi_output
```

### 5.6 차단 질문 답변 주입

MAGI가 `NEEDS_USER_INPUT` 상태로 종료되면 `analysis/05_blocking_questions.ko.md`에 질문 목록이 생성됩니다.

```bash
magi-spec answer ./magi_output --answers answers.json
```

`answers.json` 형식:

```json
[
  {
    "question_id": "DONE-001",
    "question": "무엇이 충족되면 이 작업이 완료된 것으로 봅니까?",
    "answer": "사용자가 CLI 명령 하나로 명세를 생성할 수 있어야 합니다."
  }
]
```

### 5.7 처리 중 상태 모니터링

`generate` 또는 `revise`가 실행되는 동안 MAGI는 다음 파일을 즉시 생성하고 10초마다 갱신합니다.

```text
magi_output/state/heartbeat.json
```

- `running: true`이고 `last_heartbeat_at`이 최근이면 처리 중입니다.
- `running: false`이면 MAGI 처리가 종료된 상태입니다.
- 정상 종료 시 `lifecycle: stopped`와 최종 `status`가 기록됩니다.
- 예외 종료 시 `lifecycle: failed`와 에러 요약이 기록됩니다.

## 6) Python API 사용

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
print(result.questions_path)   # NEEDS_USER_INPUT일 때 질문 파일 경로
```

차단 질문 답변:

```python
result = engine.answer(
    "./magi_output",
    answers=[
        {"question_id": "DONE-001", "question": "완료 기준은?", "answer": "CLI 명령 하나로 명세 생성 가능"}
    ],
)
```

## 7) 주요 출력물

`magi_output/` 아래에 다음이 생성됩니다.

항상 생성:

- `raw/user_request.md`
- `context/project_manifest.json`
- `research/web_sources.json`
- `evidence/evidence_registry.json`
- `analysis/01_intent_parse.ko.md`
- `analysis/02_requirement_lock.ko.md`
- `analysis/04_initial_assumptions.ko.md`
- `analysis/05_blocking_questions.ko.md`
- `analysis/requirement_lock_sheet.json` ← Lock Sheet (구조화)
- `analysis/requirement_lock_sheet.ko.md`
- `review/checklist_issues.json` ← 체크리스트 critic 결과
- `state/magi_state.json`
- `state/heartbeat.json`

조건부 생성:

- `draft/approval_candidate_spec.en.md` ← blocking issue 0개일 때
- `final/FINAL_AGENT_SPEC.md` ← approve 후
- `critical/CRITICAL_REPORT.ko.md` ← CRITICAL_BLOCKED일 때
- `critical/FAILED_AGENT_SPEC_DRAFT.en.md` ← CRITICAL_BLOCKED일 때

## 8) 상태 해석

주요 상태:

| 상태 | 의미 |
|---|---|
| `DRAFT` | 초기화 완료 |
| `ANALYZING` | Interviewer / Requirement Lock 실행 중 |
| `COMPILING` | Spec Compiler 실행 중 |
| `CRITIQUING` | Checklist Critic 실행 중 |
| `NEEDS_USER_INPUT` | 방향전환급 차단 질문 대기 |
| `PASS_PENDING_USER_APPROVAL` | 승인 후보 생성 완료 |
| `FINALIZED` | 최종 명세 확정 |
| `CRITICAL_BLOCKED` | 최대 critic 패스 초과 |
| `REJECTED_BY_USER` | 사용자 피드백 기반 수정 대기 |

## 9) 트러블슈팅

### OpenAI 키 오류

- 증상: `OPENAI_API_KEY` 관련 에러
- 조치: 환경 변수 설정 또는 mock provider 사용

### pipeline.version 오류

- 증상: `Invalid pipeline_version` 에러
- 조치: `v2`로 설정

### 차단 질문으로 인한 NEEDS_USER_INPUT

- 증상: `NEEDS_USER_INPUT` 상태로 종료
- 조치: `analysis/05_blocking_questions.ko.md` 확인 후 `magi-spec answer`로 답변 주입

### critic 초과로 인한 CRITICAL_BLOCKED

- 증상: `CRITICAL_BLOCKED` 상태
- 조치: `critical/CRITICAL_REPORT.ko.md`의 미해결 이슈 확인, `revise`로 재시도

### 승인 실패

- 증상: `approve` 실행 시 상태 오류
- 조치: 먼저 `status`에서 `PASS_PENDING_USER_APPROVAL`인지 확인

## 10) 운영 권장

- CI에서는 기본적으로 mock provider 테스트를 실행하세요.
- 실제 OpenAI 라우팅 검증은 별도 환경변수/비밀관리 정책 아래 스모크 테스트로 분리하세요.
- 산출물 디렉터리는 실행 단위로 분리(`./runs/<timestamp>`)해 이력 추적성을 유지하세요.
- 웹서비스는 실행 중 요청마다 별도 output 디렉터리를 부여하고, `state/heartbeat.json`을 5~10초 간격으로 폴링하세요.
