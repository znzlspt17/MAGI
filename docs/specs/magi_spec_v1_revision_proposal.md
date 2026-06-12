# MAGI Spec Engine — 논리적 오류 수정안

> 대상 문서: `magi_spec_engine_codex_plan_openai_only_v1.md`  
> 작성일: 2026-05-19  
> 오류 총계: 18건 (🔴 심각 7, 🟠 중요 7, 🟡 보통 4)

---

## 수정 1 — Review Gate 분기 누락 🔴

### 문제

Section 4 워크플로우의 Review Gate에 "모든 에이전트 PASS이지만 최소 라운드 미충족" 케이스가 없다.
라운드 1에서 전원 PASS 시 조기 탈출하거나 무한루프에 빠질 수 있다.

### 현행

```
Review Gate
  ├─ all agents PASS and minimum rounds satisfied → Approval Candidate
  ├─ not PASS and max rounds not reached → Next Review Round
  └─ not PASS and max rounds reached → Critical Report
```

### 수정안

```
Review Gate
  ├─ all agents PASS and minimum rounds satisfied    → Approval Candidate
  ├─ all agents PASS and minimum rounds NOT satisfied → Increment Round Counter → Next Review Round
  ├─ not PASS and max rounds not reached             → Next Review Round
  └─ not PASS and max rounds reached                → Critical Report
```

**추가 명시사항:**  
`round_counter`는 `magi_state.json`에 정수형으로 저장되며, Review Gate 진입 시마다 1씩 증가한다.  
최소 라운드 기준값은 `3`, 최대는 `10`으로 상수 정의한다.

---

## 수정 2 — Revision Loop 재진입 지점 미정의 🔴

### 문제

`rejected with feedback → Revision Loop`라고만 표시되어, 워크플로우가 어느 노드부터 재시작되는지 정의되지 않는다.  
`magi-spec revise` CLI가 구현 불가 상태이다.

### 수정안

Section 4 워크플로우를 아래와 같이 명시한다.

```
User Approval
  ├─ approved          → Write FINAL_AGENT_SPEC.md → END (FINALIZED)
  └─ rejected + feedback
        ↓
    Merge Feedback into MagiState.revision_feedback
        ↓
    Requirement Lock   ← Revision Loop 재진입 지점
        ↓
    (이하 기존 워크플로우 동일)
```

**재진입 규칙:**

- Revision Loop는 `Requirement Lock` 노드부터 재시작한다.
- `Load User Request` 및 `Optional Project Folder Scan`은 재실행하지 않는다.  
  (사용자 원본 요청과 프로젝트 컨텍스트는 변경되지 않으므로)
- `revision_feedback`은 Requirement Lock 단계에서 기존 요구사항에 병합된다.
- `round_counter`는 Revision Loop 시작 시 0으로 초기화한다.
- 이전 `review_rounds/` 아티팩트는 보존하고, `review_rounds/revision_N/` 하위 디렉터리에 신규 라운드를 저장한다. (`N`은 revise 호출 횟수)

**Section 17.3 추가:**

```bash
magi-spec revise ./magi_output --feedback feedback.md
```

이 커맨드는 다음을 수행한다:
1. `feedback.md`를 읽어 `magi_state.json`의 `revision_feedback` 필드에 저장한다.
2. 상태를 `AWAITING_REVISION → REVIEWING`으로 전환한다.
3. `Requirement Lock` 노드부터 워크플로우를 재실행한다.

---

## 수정 3 — 전처리 노드 실행 주체 모호 🔴

### 문제

워크플로우에 `Intent Parser → Requirement Lock → Scope Classifier → Assumption Builder → Blocking Question Detector`가 에이전트 Initial Pass **이전** 독립 노드로 표시된다.  
그러나 `parse_intent`, `classify_scope`, `generate_assumptions`, `detect_blocking_questions` 스킬은 BALTHASAR에게만 허용되어 있어, 실행 주체가 불명확하다.

### 수정안

전처리 노드는 **오케스트레이터 레벨 노드**로 명시하며, BALTHASAR가 이를 수행한다.

Section 4에 다음 주석을 추가한다:

```
[Pre-Analysis Phase — executed by BALTHASAR on behalf of the orchestrator]
  Intent Parser           (BALTHASAR: parse_intent)
  Requirement Lock        (BALTHASAR: parse_intent + classify_scope)
  Scope Classifier        (BALTHASAR: classify_scope)
  Assumption Builder      (BALTHASAR: generate_assumptions)
  Blocking Question Det.  (BALTHASAR: detect_blocking_questions)

[Initial Review Phase — all three agents in parallel]
  MELCHIOR Initial Pass
  BALTHASAR Initial Pass
  CASPER Initial Pass
```

**보완 규칙:**

- Pre-Analysis Phase에서 BALTHASAR의 출력은 `analysis/` 아티팩트로 저장된다.
- Pre-Analysis Phase 결과는 세 에이전트 모두에게 공유된다.
- Pre-Analysis Phase는 Initial Review Phase 이전에 반드시 완료되어야 한다.
- BALTHASAR는 Pre-Analysis Phase 동안 `web_search`, `scan_project_folder` 스킬도 사용할 수 있다.

---

## 수정 4 — Critical Report 이후 흐름 미정의 🔴

### 문제

`CRITICAL_BLOCKED → Critical Report 생성` 이후 워크플로우가 종료되는지, 사용자에게 어떤 안내가 제공되는지, CLI exit code가 무엇인지 전혀 명시되지 않는다.

### 수정안

Section 4 워크플로우 끝에 다음을 추가한다:

```
Critical Report
  ↓
Write critical/CRITICAL_REPORT.ko.md
Write critical/FAILED_AGENT_SPEC_DRAFT.en.md
Update magi_state.json → status: CRITICAL_BLOCKED
  ↓
Print to stdout:
  "MAGI review could not reach consensus after {N} rounds.
   See: {output_dir}/critical/CRITICAL_REPORT.ko.md"
  ↓
EXIT (code 2)
```

**CLI exit code 정의 (Section 18 하단에 추가):**

| 상태 | exit code |
|---|---|
| 정상 완료 (Approval Candidate 생성) | 0 |
| 사용자 승인 완료 (FINAL_AGENT_SPEC.md 생성) | 0 |
| CRITICAL_BLOCKED | 2 |
| 입력 오류 (파일 없음, 인증 실패 등) | 1 |

---

## 수정 5 — 아티팩트 덮어쓰기 정책 자기모순 🔴

### 문제

Section 16: `avoid overwriting prior runs unless explicitly allowed`  
Section 17.3: `magi-spec revise`는 `draft/approval_candidate_spec.en.md`를 재생성해야 한다.

Revision Loop가 여러 번 실행되면 동일 경로에 덮어쓰기가 불가피한데, 예외 처리가 없다.

### 수정안

**Section 16 Artifact Policy에 다음 규칙을 추가한다:**

```
Overwrite Policy:

1. 신규 generate 실행 시:
   - output_dir가 이미 존재하면 실행을 중단하고 오류를 반환한다.
   - 단, --force 플래그 전달 시 기존 디렉터리를 유지하고 내용을 덮어쓴다.

2. magi-spec revise 실행 시:
   - 명시적 사용자 요청에 의한 재실행이므로 overwrite를 허용한다.
   - draft/approval_candidate_spec.en.md는 덮어쓴다.
   - review_rounds/ 아티팩트는 revision_N/ 하위에 새로 생성한다. (N = revise 호출 횟수)
   - 이전 draft는 draft/approval_candidate_spec.en.revision_{N-1}.md로 백업한다.

3. magi-spec approve 실행 시:
   - final/FINAL_AGENT_SPEC.md가 이미 존재하면 오류를 반환한다.
   - 단, --force 플래그 전달 시 덮어쓴다.
```

**CLI에 `--force` 옵션 추가 (Section 18.1~18.5):**

```bash
magi-spec generate --input request.md --output ./magi_output [--force]
```

---

## 수정 6 — 비활성 기능 아티팩트의 Required 지정 🔴

### 문제

- `execution/command_log.json` → Required이지만 커맨드 실행 기본 비활성화
- `research/web_sources.json` → Required이지만 `--web-search off`면 웹 검색 없음

### 수정안

Section 16 Artifact Policy 표를 아래와 같이 조건부 분류로 수정한다:

**항상 생성되는 아티팩트 (Unconditional):**
```
raw/user_request.md
context/project_manifest.json  (--project 없으면 빈 manifest 생성)
context/project_summary.ko.md  (--project 없으면 "No project context" 기록)
evidence/evidence_registry.json
analysis/01_intent_parse.ko.md ~ 05_blocking_questions.ko.md
agents/initial/*.ko.md
review_rounds/round_*/...
draft/approval_candidate_spec.en.md
state/magi_state.json
state/private_model_assignments.json
```

**조건부 생성 아티팩트 (Conditional):**
```
research/web_sources.json           — --web-search on 또는 auto(검색 실행 시)에만 생성
research/web_research_summary.ko.md — 동상
execution/command_log.json          — --allow-command-execution 활성화 시에만 생성
critical/CRITICAL_REPORT.ko.md      — CRITICAL_BLOCKED 상태에서만 생성
critical/FAILED_AGENT_SPEC_DRAFT.en.md — 동상
final/FINAL_AGENT_SPEC.md           — magi-spec approve 실행 후에만 생성
```

Section 24.4 Artifact Tests에도 동일한 조건부 기대를 반영한다.

---

## 수정 7 — test results를 유효 증거로 인정하나 실행 불가 🔴

### 문제

Section 8.3: 유효한 리뷰 논거로 `test results` 인용을 허용한다.  
그러나 커맨드 실행은 기본 비활성화(Section 14)이므로, 기본 모드에서 테스트 결과를 얻는 것이 불가능하다.

### 수정안

Section 8.3의 유효 증거 목록을 다음과 같이 조건부로 분리한다:

```
유효한 리뷰 논거 (항상 허용):
  user requirements
  project-folder evidence
  web evidence (--web-search on/auto 시)
  explicit assumptions
  spec consistency
  architecture constraints
  failure modes

유효한 리뷰 논거 (조건부 허용 — --allow-command-execution 활성화 시에만):
  test results (COMMAND_RESULT 타입 증거)
  static analysis output
  build output
```

Section 15 Evidence Policy에도 동일 분류를 반영한다:

```
항상 허용: USER_REQUEST, PROJECT_FILE, WEB_SOURCE, AGENT_ASSUMPTION, AGENT_REVIEW
조건부 허용: COMMAND_RESULT (--allow-command-execution 활성화 시에만)
```

---

## 수정 8 — Section 9 Capability 속성을 Section 10이 이행하지 않음 🟠

### 문제

Section 9는 capability마다 7가지 속성(capability_id, purpose, allowed_agents, input contract, output contract, safety restrictions, artifact logging requirement, output sharing 여부)을 정의하도록 요구한다.  
Section 10은 스킬 이름만 나열하고 이를 전혀 이행하지 않는다.

### 수정안

Section 10 Skill Registry를 구조화된 테이블로 대체한다.  
아래는 대표 스킬의 예시이며, 모든 스킬에 동일 형식을 적용한다.

```yaml
skills:
  - capability_id: web_search
    purpose: 외부 웹에서 기술 정보를 검색하고 증거로 기록한다
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract:
      query: str          # 검색 쿼리
      max_results: int    # 최대 결과 수 (기본 5)
    output_contract:
      results: list[WebResult]   # {url, title, summary, retrieved_at}
    safety_restrictions:
      - "--web-search off 시 호출 금지"
      - "결과를 evidence_registry에 반드시 기록"
      - "검색 결과를 user requirement로 오분류 금지"
    artifact_logging: required   # research/web_sources.json
    output_shareable: true       # 다른 에이전트에게 공유 가능

  - capability_id: execute_command_guarded
    purpose: 정적 분석, 테스트 등 안전한 명령을 제한적으로 실행한다
    allowed_agents: [MELCHIOR, CASPER]
    input_contract:
      command: str
      working_dir: str
    output_contract:
      exit_code: int
      stdout_summary: str
      stderr_summary: str
    safety_restrictions:
      - "--allow-command-execution 없으면 호출 금지"
      - "허용 명령 카테고리만 실행 (Section 14 참조)"
      - "파일 삭제, 네트워크 업로드 등 파괴적 명령 금지"
    artifact_logging: required   # execution/command_log.json
    output_shareable: true
```

모든 19개 스킬에 대해 동일 형식의 YAML 블록을 Section 10에 작성한다.

---

## 수정 9 — Section-Level Review 추적 섹션 목록 권위 부재 🟠

### 문제

Section 6.4 예시는 5개 섹션만 보여주고, Section 21은 23개 섹션을 정의한다.  
어느 섹션 목록이 section_status.json의 공식 추적 대상인지 명시되지 않는다.

### 수정안

Section 6.4에 다음 공식 섹션 목록을 추가한다:

```json
{
  "mission": "PASS | REVISE | FAIL",
  "background": "PASS | REVISE | FAIL",
  "user_intent": "PASS | REVISE | FAIL",
  "scope_in": "PASS | REVISE | FAIL",
  "scope_out": "PASS | REVISE | FAIL",
  "definitions": "PASS | REVISE | FAIL",
  "evidence_summary": "PASS | REVISE | FAIL",
  "mandatory_requirements": "PASS | REVISE | FAIL",
  "recommended_requirements": "PASS | REVISE | FAIL",
  "optional_requirements": "PASS | REVISE | FAIL",
  "forbidden_behaviors": "PASS | REVISE | FAIL",
  "input_contract": "PASS | REVISE | FAIL",
  "output_contract": "PASS | REVISE | FAIL",
  "architecture": "PASS | REVISE | FAIL",
  "module_responsibilities": "PASS | REVISE | FAIL",
  "data_flow": "PASS | REVISE | FAIL",
  "error_handling": "PASS | REVISE | FAIL",
  "configuration": "PASS | REVISE | FAIL",
  "artifact_policy": "PASS | REVISE | FAIL",
  "implementation_order": "PASS | REVISE | FAIL",
  "acceptance_criteria": "PASS | REVISE | FAIL",
  "test_plan": "PASS | REVISE | FAIL",
  "agent_instructions": "PASS | REVISE | FAIL"
}
```

이 목록은 Section 21 Final Spec Contract의 23개 섹션과 1:1 대응한다.  
**모든 23개 섹션이 PASS여야 Approval Candidate로 전환된다.**

---

## 수정 10 — Cross Review 메커니즘 미정의 🟠

### 문제

"Cross Review Loop" 노드가 존재하고 세 에이전트 모두 `cross_review` 스킬을 갖지만, 실제로 어떤 순서로 무엇을 검토하는지 정의되지 않는다.

### 수정안

Section 4 또는 별도 Section 6.5로 Cross Review 구조를 추가한다:

```
Cross Review — 매 라운드 내 실행 구조:

1. 입력 패킷 준비 (오케스트레이터)
   - 각 에이전트의 직전 라운드 출력을 수집한다.
   - Section 8.2 규칙에 따라 provider/model 정보를 제거한 패킷을 생성한다.
   - 각 에이전트는 자신의 출력을 제외한 나머지 두 에이전트의 출력만 수신한다.
     (MELCHIOR는 BALTHASAR + CASPER 패킷 수신, 나머지 동일)

2. Cross Review 실행 (병렬)
   - MELCHIOR: BALTHASAR의 요구사항 분석 + CASPER의 실패 분석을 아키텍처 관점에서 검토
   - BALTHASAR: MELCHIOR의 아키텍처 분석 + CASPER의 실패 분석을 요구사항 관점에서 검토
   - CASPER: MELCHIOR의 아키텍처 분석 + BALTHASAR의 요구사항 분석을 실패 관점에서 검토

3. 결과 집계 (Conflict Resolver)
   - 세 에이전트의 cross review 결과를 수신한다.
   - 섹션별 상충되는 판정(한 에이전트 PASS, 다른 에이전트 FAIL)을 식별한다.
   - conflict_resolution.ko.md를 작성한다.
   - section_status.json을 최종 업데이트한다.
   - 한 섹션에서 한 에이전트라도 FAIL이면 해당 섹션은 FAIL로 집계된다.
   - 한 섹션에서 FAIL은 없지만 REVISE가 있으면 REVISE로 집계된다.
   - 모두 PASS여야 PASS로 집계된다.
```

---

## 수정 11 — `--web-search auto` 트리거 기준 미정의 🟠

### 문제

`auto` 모드가 언제 웹 검색을 실행하는지 판단 기준이 없어 구현마다 달라진다.

### 수정안

Section 13에 `auto` 모드 트리거 기준을 명시한다:

```
--web-search auto 트리거 조건 (다음 중 하나 이상 해당 시 실행):

1. 사용자 요청에 특정 외부 라이브러리, SDK, API, 프레임워크 이름이 언급된 경우
2. 사용자 요청에 버전 호환성, 최신 문서, 현재 동작 방식 확인이 필요한 경우
3. BALTHASAR의 parse_intent 결과에 "외부 의존성 확인 필요" 플래그가 설정된 경우
4. Blocking Question Detector가 외부 기술 사실에 의존하는 blocking question을 감지한 경우

--web-search auto 비실행 조건 (모두 해당 시 스킵):
- 사용자 요청이 순수 내부 로직 또는 알고리즘 설계에만 관련된 경우
- 사용자 요청에 외부 라이브러리나 API 참조가 전혀 없는 경우

auto 모드에서 웹 검색 실행 여부는 analysis/01_intent_parse.ko.md에 기록한다.
```

---

## 수정 12 — large binary files 판단 기준 미정의 🟠

### 문제

"large binary files"를 무시하라고 하지만 기준이 없다.

### 수정안

Section 12.3 Project Folder Input에 다음 기준을 추가한다:

```
Binary/Large File 무시 기준 (다음 중 하나라도 해당 시 무시):

크기 기준:
  - 단일 파일 크기 > 1 MB

확장자 기준 (바이너리):
  .png, .jpg, .jpeg, .gif, .bmp, .ico, .svg
  .mp4, .mov, .avi, .mkv
  .mp3, .wav, .ogg
  .zip, .tar, .gz, .bz2, .7z, .rar
  .pdf, .docx, .xlsx, .pptx
  .exe, .dll, .so, .dylib, .bin
  .pyc, .pyd, .pyo
  .db, .sqlite, .sqlite3

예외 (크기에 상관없이 항상 읽음):
  README.md, README.txt, README.rst
  pyproject.toml, setup.py, setup.cfg, requirements*.txt
  package.json, package-lock.json, yarn.lock
  .env.example (단, .env, .env.local 등 실제 환경변수 파일은 무시)
  *.md (문서)
  *.toml, *.yaml, *.yml (설정)
  *.json (1 MB 미만)
```

---

## 수정 13 — FAILED_AGENT_SPEC_DRAFT 생성 기반 미정의 🟠

### 문제

CRITICAL_BLOCKED 시 `critical/FAILED_AGENT_SPEC_DRAFT.en.md`를 생성해야 하는데, 10라운드 중 어느 라운드를 기반으로 하는지 명시되지 않는다.

### 수정안

Section 22 Critical Report Contract에 다음을 추가한다:

```
FAILED_AGENT_SPEC_DRAFT.en.md 생성 기준:

- 최종 라운드(round_10 또는 max_rounds에 해당하는 라운드)의 Spec Composer 출력을 기반으로 생성한다.
- Spec Composer는 CRITICAL_BLOCKED 상태에서도 마지막 라운드의 section_status.json을 기반으로
  부분 초안을 작성한다.
- PASS 판정을 받은 섹션은 최종 내용으로 포함한다.
- REVISE 또는 FAIL 판정을 받은 섹션은 내용을 포함하되,
  섹션 상단에 다음 경고를 삽입한다:
  
  > ⚠️ WARNING: This section did not reach consensus.
  > Status: {REVISE | FAIL}
  > Failing agents: {agent names}
  > See CRITICAL_REPORT.ko.md for details.

- CRITICAL_REPORT.ko.md에는 FAILED_AGENT_SPEC_DRAFT.en.md의 경로를 명시한다.
```

---

## 수정 14 — 기본 OpenAI 모델 설정값 없음 🟠

### 문제

`configurable-openai-model`이 플레이스홀더로만 표시되고 기본값이 없다.  
사용자가 설정 파일을 작성하지 않으면 어떤 모델이 사용되는지 불명확하다.

### 수정안

Section 7.2에 기본값 규칙을 추가한다:

```yaml
# 기본 model_routing 설정 (사용자 설정 파일 없을 시 적용)
model_routing:
  melchior:
    provider: openai
    model: gpt-4o          # 기본값
  balthasar:
    provider: openai
    model: gpt-4o          # 기본값
  casper:
    provider: openai
    model: gpt-4o          # 기본값
  conflict_resolver:
    provider: openai
    model: gpt-4o-mini     # 기본값 (집계 작업이므로 경량 모델 허용)
  spec_composer:
    provider: openai
    model: gpt-4o          # 기본값
```

**설정 파일 우선순위 (높은 순):**
1. CLI `--config ./model_config.yaml`
2. 환경변수 `MAGI_CONFIG_PATH`
3. 출력 디렉터리 내 `magi_config.yaml`
4. 내장 기본값 (위 표)

설정 파일이 없어도 시스템은 내장 기본값으로 정상 실행된다.  
단, `OPENAI_API_KEY`가 없으면 기본값과 무관하게 명확한 오류를 반환한다.

---

## 수정 15 — Python API에 `status()` 메서드 누락 🟡

### 문제

CLI는 `magi-spec status ./magi_output`을 정의하지만 Section 19 Python API에 대응 메서드가 없다.

### 수정안

Section 19에 `status()` 메서드를 추가한다:

```python
from magi_spec import MagiSpecEngine

engine = MagiSpecEngine()

# 기존
result = engine.generate_from_file(...)
result = engine.approve("./magi_output")
result = engine.revise(output_dir="./magi_output", feedback_path="feedback.md")

# 추가
status = engine.status("./magi_output")
print(status.state)              # REVIEWING | APPROVAL_CANDIDATE | FINALIZED | CRITICAL_BLOCKED
print(status.current_round)     # 현재 완료된 라운드 수
print(status.section_statuses)  # dict[str, str] — 섹션별 현재 상태
print(status.artifacts)         # 생성된 아티팩트 경로 목록
print(status.last_updated_at)   # ISO 8601 타임스탬프
```

---

## 수정 16 — 스킬 파일명과 스킬 이름 불일치 🟡

### 문제

| Section 20 파일명 | Section 10 스킬 이름 | 불일치 |
|---|---|---|
| `skills/file_read.py` | 없음 (`read_project_file` 있음) | 파일 존재, 스킬 미등록 |
| `skills/artifact_write.py` | `write_artifact` | 이름 불일치 |
| `skills/evidence.py` | `record_evidence` | 이름 불일치 |

### 수정안

**옵션 A — 파일명을 스킬 이름에 맞춤 (권장):**

```
skills/
  registry.py
  permissions.py
  project_scan.py
  web_search.py
  command_execution.py
  read_project_file.py    ← file_read.py → 변경
  write_artifact.py       ← artifact_write.py → 변경
  record_evidence.py      ← evidence.py → 변경
```

Section 10 Skill Registry에 `file_read` 대신 `read_project_file`이 이미 있으므로,  
`skills/file_read.py`를 `skills/read_project_file.py`로 rename한다.

**옵션 B — 스킬 이름을 파일명에 맞춤:**  
Section 10에 `file_read` 스킬을 추가하고 `read_project_file`을 제거 또는 통합.  
단, 기존 permission matrix(Section 11)와 충돌이 발생하므로 옵션 A 권장.

---

## 수정 17 — 에이전트와 오케스트레이터 경계 미정의 🟡

### 문제

Conflict Resolver, Spec Composer, Critical Reporter가 에이전트(Section 11에 권한 정의)인지  
오케스트레이터 컴포넌트인지 불명확하며, "에이전트" 정의가 없다.

### 수정안

Section 5 또는 Section 1 앞에 다음 정의를 추가한다:

```
컴포넌트 분류:

[Main Review Agents — LLM 호출로 독립적 판단 수행]
  MELCHIOR, BALTHASAR, CASPER

[Orchestrator Components — 오케스트레이터 지시 하에 LLM 호출 수행]
  Conflict Resolver — 주요 에이전트 출력 집계 및 갈등 해소
  Spec Composer     — 검토 통과 섹션 기반 스펙 초안 작성
  Critical Reporter — CRITICAL_BLOCKED 상태 보고서 작성

[Orchestrator Core — LLM 호출 없음, 순수 제어 로직]
  LangGraph Workflow, State Manager, Artifact Writer, Evidence Registry

"에이전트에게 금지된 사항"(Section 8.1, 11.6)은
Main Review Agents에게만 적용된다.
Orchestrator Components는 오케스트레이터 권한으로 동작하며,
private_model_assignments.json 접근이 필요한 경우 오케스트레이터가 정보를 전달한다.
단, Orchestrator Components도 raw model identity를 LLM 프롬프트에 포함하지 않는다.
```

---

## 수정 18 — private_model_assignments.json 접근 차단 메커니즘 미정의 🟡

### 문제

에이전트가 `private_model_assignments.json`에 접근할 수 없어야 한다고 명시하지만,  
이를 기술적으로 강제하는 방법이 정의되지 않는다.

### 수정안

Section 8.1 또는 Section 5 Skill Registry에 다음 구현 규칙을 추가한다:

```
private_model_assignments.json 접근 제어 메커니즘:

1. 파일 접근 차단 (코드 레벨)
   - 에이전트에게 전달되는 AgentContext 객체는 model_assignments 필드를 포함하지 않는다.
   - AgentContext 클래스 정의에서 model_assignments를 private으로 선언하고
     에이전트 생성 시 주입하지 않는다.

2. 프롬프트 레벨 차단
   - 오케스트레이터가 에이전트에게 전달하는 context 패킷(ProviderOutputPacket)에
     provider, model, model_version 필드를 포함하지 않는다.
   - Section 8.2 redaction 규칙이 코드로 강제 적용된다.

3. 스킬 레벨 차단
   - read_project_file 스킬은 state/ 디렉터리에 대한 접근을 허용하지 않는다.
   - 허용 경로: 사용자 지정 --project 디렉터리 내 파일만
   - 금지 경로: magi_output/state/, magi_output/private/ 이하 모든 파일

4. 테스트 검증 (Section 24.6)
   - 테스트에서 AgentContext 직렬화 결과에 모델 정보가 없음을 assert한다.
   - 테스트에서 cross-review 패킷에 provider/model 키가 없음을 assert한다.
```

---

## 변경 요약표

| # | 섹션 | 변경 유형 | 핵심 내용 |
|---|---|---|---|
| 1 | Section 4 | 워크플로우 분기 추가 | Review Gate 4번째 분기 |
| 2 | Section 4, 17.3 | 워크플로우 재진입 정의 | Revision Loop → Requirement Lock |
| 3 | Section 4, 11.2 | 실행 주체 명시 | 전처리 노드 = BALTHASAR on behalf of orchestrator |
| 4 | Section 4 | 종료 흐름 추가 | CRITICAL_BLOCKED exit code 2 |
| 5 | Section 16, 17 | 정책 수정 | overwrite 예외 + --force + revision 버전닝 |
| 6 | Section 16 | 분류 수정 | Unconditional vs Conditional 아티팩트 분리 |
| 7 | Section 8.3, 15 | 조건부 분류 | test results는 --allow-command-execution 시에만 유효 |
| 8 | Section 10 | 내용 보완 | 모든 스킬에 7가지 capability 속성 YAML 정의 |
| 9 | Section 6.4 | 목록 명시 | 23개 섹션 공식 추적 목록 |
| 10 | Section 4 (또는 6.5) | 메커니즘 추가 | Cross Review 6회 구조 + 집계 규칙 |
| 11 | Section 13 | 기준 추가 | auto 모드 트리거 조건 명시 |
| 12 | Section 12 | 기준 추가 | binary/large file 크기 및 확장자 기준 |
| 13 | Section 22 | 생성 규칙 추가 | FAILED_DRAFT = 마지막 라운드 + 상태 경고 삽입 |
| 14 | Section 7.2 | 기본값 추가 | 에이전트별 기본 모델 + 설정 우선순위 |
| 15 | Section 19 | API 추가 | `engine.status()` 메서드 |
| 16 | Section 10, 20 | 이름 통일 | 파일명 → 스킬 이름 일치 (옵션 A) |
| 17 | Section 5 (또는 Section 1) | 정의 추가 | 에이전트 vs 오케스트레이터 경계 정의 |
| 18 | Section 8.1 | 메커니즘 추가 | AgentContext 필드 제외 + 스킬 경로 차단 |
