# MAGI Spec Engine v2 구현 명세 — SpecForge / Directive Compiler

> 출처: `MAGI_FAILURE_REPORT.pdf` 실패 회고 기반. 본 문서는 로드맵이 아니라 **구현 명세**다.
> 실제 코드(`src/magi_spec/**`)를 정독한 뒤 작성했으며, 각 Phase는 구체적 타입·시그니처·그래프 배선·테스트 단언을 포함한다.

> **[구현 완료 상태]** M1–M7 전체 구현 완료. 아래 §0의 일부 사항은 구현 과정에서 갱신되었다.
> 실제 코드와 이 문서의 차이는 §0 "구현 후 변경사항" 참조.

---

## 0. 코드베이스 핵심 사실 (구현 완료 기준)

### 0.1 v2 에이전트 라우팅 키 (실제 구현)

| 역할 | v2 라우팅 키 | v1 레거시 키 |
|---|---|---|
| Spec Interviewer + Requirement Lock Builder | `interviewer` | `balthasar` |
| Checklist Critic | `critic` | `casper` |
| Spec Compiler | `compiler` | `spec_composer` |
| Critical Reporter | `critical_reporter` | `critical_reporter` |
| (v1 전용) Architecture Reviewer | — | `melchior` |
| (v1 전용) Conflict Resolver | — | `conflict_resolver` |

`MagiConfig.default()` → `AGENT_KEYS_V2 = [interviewer, critic, compiler, critical_reporter]`, `pipeline_version="v2"`
`MagiConfig.mock()` → `AGENT_KEYS_V1 = [melchior, balthasar, casper, conflict_resolver, spec_composer, critical_reporter]`, `pipeline_version="v1"` (기존 v1 테스트 보호)
`MagiConfig.mock_v2()` → `AGENT_KEYS_V2`, `pipeline_version="v2"`

### 0.2 상태 불변식 (유지됨)

- `WorkflowState(TypedDict, total=False)` — LangGraph 노드용
- `MagiState(@dataclass(slots=True))` — 디스크 직렬화용
- `MagiState.from_dict`는 유효 필드만 수락(`dataclasses.fields` 필터), 구버전 state 파일 안전 로딩.
- 새 v2 필드: `pipeline_version`, `request_type`, `requirement_lock_sheet`, `structured_issues`, `critic_pass_count`, `max_critic_passes`

### 0.3 v2 상태 상수 (신규)

`STATUS_COMPILING`, `STATUS_CRITIQUING`, `STATUS_NEEDS_USER_INPUT` 추가 (`core/state.py`)

### 0.4 최종 명세 계약 (유지됨)

`spec_composer.REQUIRED_FINAL_SPEC_HEADINGS` (26개, `# Final Agent Specification` … `## 23. Instructions for AI Coding Agent`). `english_only()` + `has_required_headings()` 통과. **변경 없음.**

### 0.5 config (`core/config.py`)

- `AGENT_KEYS_V1`, `AGENT_KEYS_V2`, `_ALL_KNOWN_AGENT_KEYS` 분리
- `from_dict()`: pipeline version을 먼저 읽어 해당 파이프라인의 기본 라우팅으로 base 구성
- `max_critic_passes` 추가 (1–3, default 2)

### 0.6 테스트 스타일

- v2 라우팅·정책: `test_v2_pipeline_bounds.py` (순수 함수), `test_spec_interviewer.py` (E2E mock v2)
- v1 테스트: `MagiConfig.mock()` 사용, 기존 파일 그대로 유지

---

## 1. 개요 / 목표

v2는 "3-agent 자동 토론 루프"를 **결정론적 4단계 컴파일러**로 교체한다.

```
Spec Interviewer → Requirement Lock → Spec Compiler → Checklist Critic
```

성공 정의 (승인 후보 = `PASS_PENDING_USER_APPROVAL` 진입 조건):
- 모든 `blocking=true` issue가 `resolved`.
- `REQUIRED_FINAL_SPEC_HEADINGS` 전부 존재 + english_only.
- Requirement Lock Sheet의 모든 `mandatory_requirements`가 최종 명세에 반영.
- critic는 **최대 2회** 실행(`max_critic_passes`), 미해결 시 `CRITICAL_BLOCKED` 또는 `NEEDS_USER_INPUT`.

호환성 원칙: v1 경로를 즉시 삭제하지 않는다. `pipeline_version`(기본 `v2`)으로 분기하고, Phase 7에서만 v1 노드를 격리/제거한다.

---

## 2. v2 아키텍처와 그래프 배선

신규 노드(`graph/nodes.py`에 메서드 추가 또는 `pipeline/stages.py`로 분리):

| 노드 | 대체하는 v1 | 산출 |
|---|---|---|
| `interview` | `analysis` 일부 | blocking_questions, assumptions, request_type |
| `requirement_lock_stage` | `analysis`의 requirement_lock | `requirement_lock_sheet`(구조화) |
| `spec_compile` | `compose_candidate` | draft spec |
| `checklist_critic` | `initial_agents`+`review_round`+`conflict_resolver` | `structured_issues[]` |

v2 그래프(`pipeline/builder.py::build_v2_workflow`):
```
START → project_context → web_research → interview
  interview ─(route_after_interview)→ requirement_lock_stage | await_user
  requirement_lock_stage → spec_compile → checklist_critic
  checklist_critic ─(route_after_critic)→ spec_compile | compose_candidate | critical_report | await_user
  compose_candidate → END ; critical_report → END ; await_user → END
```
- `route_after_interview`: blocking question이 **방향전환급(direction-changing)** 이고 비대화 모드면 `await_user`(status `NEEDS_USER_INPUT`), 아니면 진행.
- `route_after_critic`: `unresolved_blocking == 0` → compose_candidate; `critic_pass_count < max_critic_passes and unresolved_blocking > 0` → spec_compile(재컴파일); `critic_pass_count >= max_critic_passes` → critical_report.
- `project_context`/`web_research`/`compose_candidate`/`critical_report`는 v1 노드 재사용.

`engine._run_workflow`는 `self.config.pipeline_version`에 따라 `build_workflow`(v1) 또는 `build_v2_workflow`(v2)를 선택. 기본 `v2`.

---

## 3. Phase 1 — 상태/데이터 계약 도입

### 3.1 신규 파일 `src/magi_spec/schemas/issue_packet.py`
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

VALID_SEVERITY = {"blocking", "major", "minor"}
VALID_ISSUE_STATUS = {"open", "resolved", "deferred"}

@dataclass(slots=True)
class IssueEvidence:
    source: str
    quote: str
    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "quote": self.quote}

@dataclass(slots=True)
class IssuePacket:
    issue_id: str
    section: str
    severity: str           # blocking|major|minor
    blocking: bool
    checklist_id: str
    problem: str
    required_change: str
    evidence: list[IssueEvidence] = field(default_factory=list)
    suggested_patch: str | None = None
    status: str = "open"    # open|resolved|deferred

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_provider_dict(cls, data: dict[str, Any], *, fallback_id: str) -> "IssuePacket":
        # severity/status는 화이트리스트로 정규화, blocking은 severity=="blocking"로 강제 동기화
        ...

def normalize_severity(value: Any, *, default: str = "major") -> str: ...
def parse_issue_list(data: Any) -> list[IssuePacket]:  # provider JSON {"issues":[...]} 파싱, 잘못된 항목 skip
    ...
def count_unresolved_blocking(issues: list[IssuePacket]) -> int:
    return sum(1 for i in issues if i.blocking and i.status != "resolved")
```
설계 규칙: `blocking`은 항상 `severity == "blocking"`과 일치하도록 `from_provider_dict`에서 강제. provider가 비정상 JSON이면 `parse_issue_list`는 빈 리스트가 아니라 **1개의 합성 blocking issue**(`checklist_id="CRITIC-MALFORMED"`)를 반환해 무한 PASS를 막는다(회고록의 "PASS 기준 모호" 교훈).

### 3.2 신규 파일 `src/magi_spec/schemas/requirement_lock.py`
```python
@dataclass(slots=True)
class RequirementItem:
    id: str
    text: str
    source: str = "user_request"   # user_request|user_answer|assumption|web_evidence

@dataclass(slots=True)
class QAItem:
    question_id: str
    question: str
    answer: str

@dataclass(slots=True)
class AssumptionItem:
    id: str
    text: str
    risk: str = "low"   # low|medium|high

@dataclass(slots=True)
class RequirementLockSheet:
    lock_id: str
    request_type: str               # product|feature|bugfix|refactor|infra
    request_summary: str
    user_answers: list[QAItem] = field(default_factory=list)
    mandatory_requirements: list[RequirementItem] = field(default_factory=list)
    recommended_requirements: list[RequirementItem] = field(default_factory=list)
    optional_requirements: list[RequirementItem] = field(default_factory=list)
    non_scope: list[RequirementItem] = field(default_factory=list)
    assumptions: list[AssumptionItem] = field(default_factory=list)
    constraints: list[RequirementItem] = field(default_factory=list)
    acceptance_criteria_seed: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "RequirementLockSheet": ...   # 중첩 dataclass 복원
    def to_markdown(self) -> str: ...   # analysis/requirement_lock_sheet.ko.md 생성용
```

### 3.3 `core/state.py` 변경 (두 정의 동시 수정)
`WorkflowState`와 `MagiState`에 동일 필드 추가:
```python
# WorkflowState (TypedDict)         # MagiState (dataclass, 기본값 필수)
pipeline_version: str               pipeline_version: str = "v2"
request_type: str                   request_type: str = ""
requirement_lock_sheet: dict | None requirement_lock_sheet: dict | None = None
structured_issues: list[dict]       structured_issues: list[dict] = field(default_factory=list)
critic_pass_count: int              critic_pass_count: int = 0
max_critic_passes: int              max_critic_passes: int = 2
```
신규 상태 상수 추가: `STATUS_COMPILING = "COMPILING"`, `STATUS_CRITIQUING = "CRITIQUING"`, `STATUS_NEEDS_USER_INPUT = "NEEDS_USER_INPUT"`.

> `requirement_lock_sheet`는 dict로 저장(JSON 직렬화 호환). dataclass ↔ dict 변환은 `RequirementLockSheet.to_dict/from_dict`로 노드 내부에서 수행.

### 3.4 변경/추가 테스트
- `tests/test_issue_packet_schema.py` (신규):
  - `parse_issue_list({"issues":[{...severity:"blocking"...}]})` → `blocking is True`.
  - severity 미지정 → `"major"`, `blocking is False`.
  - 잘못된 JSON(`None`) → 길이 1, `checklist_id=="CRITIC-MALFORMED"`, `blocking is True`.
  - `count_unresolved_blocking` 정확성(resolved 제외).
- `tests/test_requirement_lock_sheet.py` (신규): `to_dict`→`from_dict` 라운드트립 동등성, `to_markdown`에 mandatory/non_scope 항목 포함.
- `tests/test_state_transitions.py` (기존, 보강): 새 필드 포함 `MagiState().to_dict()`/`from_dict` 라운드트립, **구버전 state(신규 키 없음) 로드 시 기본값 적용** 단언.

산출물(추가): `analysis/requirement_lock_sheet.json`, `analysis/requirement_lock_sheet.ko.md`, `review/checklist_issues.json`. 기존 `analysis/0X_*.ko.md`는 v2에서도 호환 위해 병행 생성(아래 Phase 2/3).

---

## 4. Phase 2 — Spec Interviewer

### 4.1 `src/magi_spec/interview/question_templates.py`
```python
@dataclass(slots=True)
class Question:
    question_id: str
    text: str
    direction_changing: bool   # True면 미답변 시 명세 방향이 바뀜 → await_user 후보
    applies_to: tuple[str, ...]  # ("product","feature",...) 또는 ("*",)

QUESTION_SETS: dict[str, list[Question]] = {
    "product":  [...],   # 제품형: 라이브러리/CLI/웹서비스? 배포 방식? 사용자=개발자?
    "feature":  [...],   # 기능형: 입력/출력? 기존 모듈 영향? 완료 기준?
    "bugfix":   [...],   # 버그수정형: 재현 조건? 회귀 위험? 데이터 영향?
    "refactor": [...],   # 리팩토링형: 동작 보존 범위? 금지 변경?
    "infra":    [...],
}
COMMON_QUESTIONS: list[Question] = [
    Question("FORBIDDEN-001","절대 수정/삭제하면 안 되는 파일·기능은?", True, ("*",)),
    Question("DONE-001","무엇이 충족되면 성공인가(완료 기준)?", True, ("*",)),
]
HARD_CAP = 7

def classify_request_type(user_request: str, manifest: dict) -> str:
    # 키워드/매니페스트 휴리스틱: 빈 프로젝트+"build/만들" → product;
    # 기존 프로젝트+"fix/버그" → bugfix; "refactor/리팩토링" → refactor; 그 외 feature
    ...
def select_questions(request_type: str, *, answered_ids: set[str]) -> list[Question]:
    # COMMON + 유형별, answered 제외, HARD_CAP로 절단(direction_changing 우선)
    ...
```

### 4.2 `src/magi_spec/interview/interviewer.py`
```python
class SpecInterviewer:
    agent_id = "balthasar"   # 라우팅 재사용(신규 AGENT_KEY 추가 회피)
    def run(self, state: WorkflowState, manifest: dict) -> InterviewResult:
        # 1) classify_request_type
        # 2) LLM 1회: 템플릿 질문 중 "이 요청 맥락에서 실제로 미해결인 것"만 남기고
        #    각 질문에 대해 답을 추론 가능하면 assumption으로, 불가하면 blocking_question으로 분류
        #    (프롬프트: prompts/interviewer.md, JSON {request_type, assumptions[], blocking_questions[], answers[]})
        # 3) fallback: LLM 실패 시 select_questions의 direction_changing만 blocking으로
        ...
```
`InterviewResult`: `request_type, assumptions[], blocking_questions[], pre_answers[QAItem]`.

### 4.3 노드 & 라우팅
- `nodes.interview(state)` → interviewer 실행, 기존 `analysis()`의 산출 호환을 위해 `analysis/04_initial_assumptions.ko.md`, `analysis/05_blocking_questions.ko.md`도 계속 기록. 추가로 `request_type` 상태 세팅. status=`STATUS_ANALYZING`.
- `route_after_interview(state)`:
  ```python
  def route_after_interview(state) -> Literal["requirement_lock_stage","await_user"]:
      if not state.get("user_request","").strip():
          return "await_user"   # 완전 공백
      # 방향전환급 blocking이 있고 답이 없으면 사용자 입력 대기
      if state.get("blocking_questions") and _has_direction_changing(state):
          return "await_user"
      return "requirement_lock_stage"
  ```
- `nodes.await_user(state)`: `analysis/05_blocking_questions.ko.md` 보장 기록, status=`STATUS_NEEDS_USER_INPUT`. END.

> v1 `route_after_analysis`의 기존 동작(빈 요청만 early-exit, informational 질문은 통과)을 v2에서도 보존해 `test_review_policy.py`의 의미를 깨지 않는다. v2는 거기에 "direction-changing → await_user"만 추가.

### 4.4 사용자 답변 주입
- 신규 CLI `magi-spec answer <output_dir> --answers answers.json`(또는 기존 `revise` 확장). `answers.json` = `[{question_id, answer}]`.
- `engine.answer(...)`: state 로드 → `pre_answers`/`user_answers`에 병합 → blocking_questions에서 해당 항목 제거 → `current_round`/critic_pass_count 리셋 → `_run_workflow` 재진입.

### 4.5 테스트
- `tests/test_question_templates.py`: `classify_request_type` 케이스별, `select_questions` HARD_CAP 절단·answered 제외·direction_changing 우선.
- `tests/test_spec_interviewer.py`: mock provider로 `interview` 노드 → request_type 설정, blocking_questions 생성. `route_after_interview`가 빈요청→await_user, 일반→requirement_lock_stage, direction-changing→await_user.
- `tests/test_cli_generate.py`(보강): 비대화 모드에서 direction-changing blocking이면 종료 상태 `NEEDS_USER_INPUT`.

---

## 5. Phase 3 — Requirement Lock Sheet

### 5.1 `src/magi_spec/compiler/requirement_lock.py`
```python
class RequirementLockBuilder:
    agent_id = "balthasar"
    def build(self, state, manifest, interview: InterviewResult) -> RequirementLockSheet:
        # LLM 1회(prompts/requirement_lock.md 재사용+확장): JSON으로 lock sheet 채움
        # fallback: interview 결과 + 기존 analysis fallback 문구로 최소 sheet 구성
        # mandatory에는 항상 "MAGI는 대상 프로젝트를 직접 구현하지 않는다"류 non_scope 보장
        ...
```
- `nodes.requirement_lock_stage(state)`:
  - lock sheet 생성 → `writer.write_json("analysis/requirement_lock_sheet.json", sheet.to_dict())`, `writer.write_text("analysis/requirement_lock_sheet.ko.md", sheet.to_markdown())`.
  - 호환: 기존 `analysis/02_requirement_lock.ko.md`도 `sheet.to_markdown()`로 계속 기록.
  - 상태: `requirement_lock_sheet = sheet.to_dict()`, `requirement_lock`(문자열, 기존 필드)에는 markdown 저장. status=`STATUS_ANALYZING`.

### 5.2 revise 의미 변경
`engine.revise`는 v2에서 전체 리뷰 루프 리셋이 아니라:
- feedback을 `user_answers`/`constraints`에 병합 → `requirement_lock_sheet` 갱신 → `spec_compile`부터 재진입(`critic_pass_count=0`). v1 분기는 기존 동작 유지.

### 5.3 테스트
- `tests/test_requirement_lock_sheet.py`(Phase 1과 공유): 빌더 fallback이 non_scope에 "직접 구현 안 함" 포함.
- `tests/test_cli_revise.py`(보강): revise 후 `requirement_lock_sheet.json`의 `user_answers`/`constraints`에 feedback 반영, status가 재컴파일 경로로 진행.
- `tests/test_artifact_writer.py`(보강): 신규 3개 artifact 경로 생성 단언.

---

## 6. Phase 4 — 단일 Spec Compiler

### 6.1 입력 계약 축소
- `src/magi_spec/compiler/spec_compiler.py` 신설(또는 `SpecComposer` 래핑). 핵심: 입력을 **`RequirementLockSheet` + project manifest 요약 + structured_issues(재컴파일 시)** 로 제한. v1처럼 전체 agent output을 넘기지 않는다(토큰 절감, 회고록 9장).
- `SpecComposer.compose` 시그니처는 유지하되, 새 메서드 추가:
  ```python
  def compose_from_lock(self, sheet: RequirementLockSheet, manifest: dict,
                        issues: list[IssuePacket] | None = None) -> str:
      # 프롬프트 입력 = sheet.to_dict() + manifest 요약 + (issues의 required_change 목록)
      # 기존 _compose_prompt 대신 _compose_prompt_v2 사용
      # 반환 후 english_only + has_required_headings 검사 → 실패 시 _fallback_spec
  ```
- `REQUIRED_FINAL_SPEC_HEADINGS`(26개)와 `_fallback_spec`은 **그대로 유지**. 재컴파일 시 issues의 `required_change`를 프롬프트에 "must fix" 목록으로 전달.

### 6.2 노드
- `nodes.spec_compile(state)`:
  - sheet 복원(`RequirementLockSheet.from_dict(state["requirement_lock_sheet"])`).
  - `issues = parse_issue_list(state.get("structured_issues"))`(재진입 시).
  - `spec = composer.compose_from_lock(sheet, manifest, issues)`.
  - `assert english_only`(아니면 fallback). `writer.write_text("draft/approval_candidate_spec.en.md", spec)`.
  - status=`STATUS_COMPILING`. (compose_candidate와 달리 아직 승인대기 아님 → critic 후 결정.)

### 6.3 테스트
- `tests/test_final_spec_contract.py`(유지+보강): `compose_from_lock` 결과가 26개 heading 전부 포함 + english_only. lock sheet의 mandatory 텍스트가 fallback 경로에서도 User Intent/Mandatory 섹션에 반영.
- `tests/test_acceptance_smoke.py`(보강): mock provider end-to-end로 `draft/approval_candidate_spec.en.md` 생성.

---

## 7. Phase 5 — Checklist Critic

### 7.1 `src/magi_spec/critic/checklist.py`
```python
@dataclass(slots=True)
class ChecklistItem:
    checklist_id: str
    section: str
    severity: str           # 위반 시 부여할 severity
    description: str

CHECKLIST: list[ChecklistItem] = [
    ChecklistItem("SEC-REQUIRED-001","structure","blocking","필수 26개 heading 전부 존재"),
    ChecklistItem("SCOPE-NONSCOPE-001","scope","blocking","Out of Scope(4.2) 비어있지 않음"),
    ChecklistItem("FORBIDDEN-001","forbidden","blocking","Forbidden Behaviors(10) 비어있지 않음"),
    ChecklistItem("AC-001","acceptance","blocking","Acceptance Criteria(20)가 검증 가능 형태"),
    ChecklistItem("TEST-001","test_plan","blocking","Test Plan(21) 존재"),
    ChecklistItem("AMBIG-001","requirements","major","모호어(적절히/robust/좋은) 미사용"),
    ChecklistItem("LOCK-COVER-001","requirements","blocking","lock sheet의 모든 mandatory가 명세에 등장"),
    ChecklistItem("UNRESOLVED-Q-001","intent","blocking","unresolved blocking question 0개"),
]

def run_deterministic_checks(spec_md: str, sheet: RequirementLockSheet) -> list[IssuePacket]:
    # LLM 없이 문자열/포함 검사로 1차 issue 생성 (결정론적, 토큰 0)
    ...
```

### 7.2 `src/magi_spec/critic/checklist_critic.py`
```python
class ChecklistCritic:
    agent_id = "casper"   # 라우팅 재사용
    def critique(self, spec_md: str, sheet: RequirementLockSheet) -> list[IssuePacket]:
        deterministic = run_deterministic_checks(spec_md, sheet)
        # LLM 1회(prompts/checklist_critic.md): 체크리스트 위반만 IssuePacket[] JSON으로
        # parse_issue_list로 파싱 → deterministic과 병합(issue_id 중복 제거)
        # 자유 토론 금지: 프롬프트가 "오직 issue packet JSON만" 강제
        ...
```
출력은 자유 텍스트가 아니라 `IssuePacket[]`. malformed면 합성 blocking issue(무한 PASS 방지).

### 7.3 노드 & 라우팅
- `nodes.checklist_critic(state)`:
  - `issues = critic.critique(spec, sheet)`.
  - `writer.write_json("review/checklist_issues.json", {"issues":[i.to_dict() ...], "pass": critic_pass_count+1})`.
  - 상태: `structured_issues = [...]`, `critic_pass_count += 1`, status=`STATUS_CRITIQUING`.
- `route_after_critic(state)`:
  ```python
  def route_after_critic(state) -> Literal["spec_compile","compose_candidate","critical_report"]:
      unresolved = count_unresolved_blocking(parse_issue_list(state.get("structured_issues")))
      passes = int(state.get("critic_pass_count", 0))
      maxp = int(state.get("max_critic_passes", 2))
      if unresolved == 0:
          return "compose_candidate"
      if passes < maxp:
          return "spec_compile"   # required_change 반영 재컴파일
      return "critical_report"
  ```
- `compose_candidate`(v1 노드 재사용): 이미 spec이 draft에 있으면 그대로 승인 후보로 승격, status=`PASS_PENDING_USER_APPROVAL`. (v2에서는 새 compose 호출 대신 검증된 draft를 사용하도록 분기 추가.)
- `critical_report`(v1 재사용): `CRITICAL_REPORT.ko.md`에 미해결 issue 목록 요약. critical_reporter 입력에 `structured_issues` 추가.

### 7.4 테스트
- `tests/test_checklist_critic.py`: `run_deterministic_checks`가 (a) heading 누락 시 `SEC-REQUIRED-001` blocking, (b) "robust/좋은" 포함 시 `AMBIG-001` major, (c) mandatory 누락 시 `LOCK-COVER-001` blocking 생성. malformed LLM 응답 → 합성 blocking.
- `tests/test_v2_pipeline_bounds.py`: `route_after_critic`가 unresolved=0→compose, unresolved>0 & passes<2→spec_compile, passes>=2→critical. **critic는 최대 2회**(루프 비수렴 방지, 회고록 6.1/8장).

---

## 8. Phase 6 — CLI / API / config 전환

### 8.1 config
- `MagiConfig`에 `pipeline_version: str = "v2"` 추가. `from_dict`에서 `data.get("pipeline", {}).get("version", "v2")` 읽기. `validate()`에 `pipeline_version ∈ {"v1","v2"}` 체크.
- `max_critic_passes: int = 2` 추가, `review.max_critic_passes`로 override. validate: `1 <= max_critic_passes <= 3`.

### 8.2 engine
- `_run_workflow`: `build_v2_workflow` vs `build_workflow` 분기.
- `generate_from_text`에서 `state.pipeline_version = self.config.pipeline_version`, `state.max_critic_passes = self.config.max_critic_passes` 세팅.
- 신규 `answer()` 메서드(Phase 2.4).
- `_result_from_state`: `NEEDS_USER_INPUT`일 때 `approval_candidate_path` None 유지, blocking 질문 파일 경로를 노출하도록 `MagiResult`에 `questions_path: str | None = None` 추가(선택).

### 8.3 CLI
- `generate`에 `--pipeline {v1,v2}`(기본 config 값) 추가.
- `answer` 서브커맨드 추가: `answer output_dir --answers answers.json`.
- 종료 코드: `NEEDS_USER_INPUT` → 신규 코드 `3`(또는 README 명시 후 `0`+안내). README "Exit Codes" 갱신.

### 8.4 문서
- `README.md`: Review Loop 섹션을 SpecForge 4단계로 교체, exit code 표, `answer`/`--pipeline` 추가.
- `docs/USER_GUIDE.ko.md`: 인터뷰→Lock→컴파일→체크리스트 흐름, answers.json 예시.

### 8.5 테스트
- `tests/test_cli_config_validation.py`(보강): `pipeline.version` 잘못된 값 → 종료 1. `max_critic_passes` 범위 검증.
- `tests/test_cli_generate.py`/`test_cli_approve.py`/`test_cli_revise.py`: v2 기본 경로로 통과(approve/finalize 계약 불변).

---

## 9. Phase 7 — v1 구조 축소 (마지막, 호환 깨짐 주의)

순서 중요(테스트 그린 유지):
1. v2가 기본이고 전 테스트 통과 확인 후 진행.
2. `graph/builder.py`의 v1 함수(`build_workflow`, `route_after_analysis`, `route_after_review`, `all_agents_pass`)는 **삭제하지 않고 `graph/legacy.py`로 이동**, import 경로 유지(`test_review_policy.py`가 참조). 또는 `pipeline_version="v1"` 회귀 테스트로만 유지.
3. `agents/{melchior,balthasar,casper,conflict_resolver}.py`: balthasar/casper는 interviewer·critic이 `agent_id`로 라우팅을 재사용하므로 **클래스는 남기되 review 루프 호출만 제거**. melchior/conflict_resolver는 v1 분기에서만 사용.
4. `core/agent_context.py`의 전체 output relay: v2 경로에서 호출 안 함(컴파일러는 sheet만 받음). 함수 자체는 v1용으로 유지.
5. `skills/command_execution.py`: v2 core path에서 호출 제거(`_maybe_execute_guarded_review_command`는 v1 review_round에만 존재 → 그대로). config `command_execution` 기본 off 유지.
6. provider stubs(`anthropic/google/local/self_hosted`)·`model_blind`: 삭제하지 않음. 단 v2는 단일 컴파일러라 model-blind 중요도↓. `test_model_blind_*`는 v1 회귀로 유지하거나 컴파일러 출력에 provider 식별자 미포함만 검증하도록 축소.

> **AGENT_KEYS 유지**: interviewer=balthasar, critic=casper, compiler=spec_composer로 재사용하므로 `AGENT_KEYS`/config 라우팅/`private_model_assignments.json` 구조는 변경하지 않는다(테스트 `test_model_routing_usage.py` 보호).

### 9.1 테스트
- `tests/test_review_policy.py`: v1 함수가 legacy로 이동했으면 import 경로 갱신, 아니면 `pipeline_version="v1"` 회귀로 변환.
- 전체 스위트 그린 확인: `pytest -q`.

---

## 10. 데이터 계약 요약 (참조)

### 10.1 IssuePacket JSON
```json
{
  "issue_id": "AC-001", "section": "acceptance", "severity": "blocking",
  "blocking": true, "checklist_id": "AC-001",
  "problem": "Acceptance criteria are not objectively verifiable.",
  "required_change": "Rewrite as observable pass/fail conditions.",
  "evidence": [{"source": "draft/approval_candidate_spec.en.md", "quote": "should be robust"}],
  "suggested_patch": null, "status": "open"
}
```
승인 후보 조건: `count(blocking && status!="resolved") == 0`.

### 10.2 RequirementLockSheet JSON: 3.2의 dataclass 직렬화 형태(생략 — `to_dict()` 결과).

---

## 11. 리스크 및 검증

| 리스크 | 방지책 | 테스트 |
|---|---|---|
| critic 비수렴(CASPER 재현) | `max_critic_passes=2` 하드 캡, 초과 시 critical | `test_v2_pipeline_bounds.py` |
| 무한 PASS(모호 기준) | malformed→합성 blocking, 결정론적 체크 우선 | `test_checklist_critic.py` |
| 질문 폭주 | `HARD_CAP=7`, direction_changing 우선 절단 | `test_question_templates.py` |
| 상태 직렬화 파손 | 필드는 추가만, 기본값 필수, 라운드트립 테스트 | `test_state_transitions.py` |
| 최종 명세 계약 회귀 | 26 heading + english_only 불변 | `test_final_spec_contract.py` |
| CLI/승인 흐름 회귀 | approve/finalize 불변 | `test_cli_*` |
| lock 무시 컴파일 | LOCK-COVER-001 blocking | `test_checklist_critic.py` |

유지: `test_final_spec_contract / test_cli_generate / test_cli_approve / test_cli_revise / test_artifact_writer / test_project_scan / test_provider_credentials`.
추가: `test_issue_packet_schema / test_requirement_lock_sheet / test_question_templates / test_spec_interviewer / test_checklist_critic / test_v2_pipeline_bounds / test_feedback_reflection`.

검증 명령:
```bash
pip install -e ".[dev]"
pytest -q            # 각 Phase 종료 시 그린 유지
```

---

## 12. 마일스톤 순서 (의존성)

1. **M1 (Phase 1)** schema/state — 다른 모든 Phase의 토대.
2. **M2 (Phase 2)** interviewer — M1의 request_type/blocking 필요.
3. **M3 (Phase 3)** requirement lock — M2 결과 소비.
4. **M4 (Phase 4)** compiler — M3 sheet 소비.
5. **M5 (Phase 5)** critic + 라우팅 — M4 draft 소비, 루프 완성.
6. **M6 (Phase 6)** CLI/API/config/docs — v2를 기본화.
7. **M7 (Phase 7)** v1 축소 — 전 테스트 그린 후에만.

각 마일스톤은 독립적으로 `pytest -q` 그린 상태로 종료해야 다음으로 진행한다.
