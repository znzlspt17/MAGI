# MAGI Spec Engine — Codex Implementation Plan

## 0. Purpose

This document is the revised implementation plan for **MAGI Spec Engine**.

It is written for an AI coding agent such as **Codex**. The implementation agent must follow this plan exactly.

The important revision is:

```text
MAGI v1 must run fully with OpenAI only.

Multi-provider support must exist as an architecture extension point,
but Anthropic / Claude, Google / Gemini, local, and self-hosted providers
are not required for v1 acceptance.
```

---

## 1. Product Summary

### 1.1 Product Name

```text
MAGI Spec Engine
```

### 1.2 Python Package Name

```text
magi_spec
```

### 1.3 CLI Command

```text
magi-spec
```

### 1.4 Product Type

MAGI Spec Engine is a local:

```text
Python package + thin CLI
```

It generates strict Markdown specifications for AI coding agents.

MAGI does **not** implement the user's target project.  
MAGI does **not** execute Codex, Copilot, Cursor, Claude Code, or other implementation agents.

---

## 2. Mission

Build a local Python package and CLI tool that converts a user's high-level development request into a rigorously reviewed, implementation-ready Markdown specification.

The final approved output must be:

```text
final/FINAL_AGENT_SPEC.md
```

This file must be written in English and must be suitable for direct use as the instruction document for an AI coding agent.

---

## 3. Critical Scope Revision

### 3.1 Previous Overly Broad Requirement

The previous plan implied that v1 must support heterogeneous live provider execution:

```text
MELCHIOR may use Claude.
BALTHASAR may use Gemini.
CASPER may use OpenAI.
```

This is too broad for v1.

### 3.2 Revised v1 Requirement

MAGI v1 must be fully operational with OpenAI only.

```text
Required in v1:
- OpenAI provider adapter
- OPENAI_API_KEY support
- Agent-specific OpenAI model routing
- Model-blind peer review
- Provider adapter interface for future expansion

Not required in v1:
- Live Anthropic / Claude integration
- Live Google / Gemini integration
- Live local model integration
- Live self-hosted model integration
```

### 3.3 Future Provider Direction

The architecture must allow future providers through adapters, but those adapters may be stubs in v1.

Future optional providers:

```text
Anthropic / Claude
Google / Gemini
Local models
Self-hosted models
Other future providers
```

---

## 4. Core Workflow

MAGI must use LangGraph for orchestration.

```text
START
  ↓
Load User Request
  ↓
Optional Project Folder Scan
  ↓
Optional Web Research
  ↓
Intent Parser
  ↓
Requirement Lock
  ↓
Scope Classifier
  ↓
Assumption Builder
  ↓
Blocking Question Detector
  ↓
MELCHIOR Initial Pass
BALTHASAR Initial Pass
CASPER Initial Pass
  ↓
Cross Review Loop
  ↓
Conflict Resolver
  ↓
Spec Composer
  ↓
Review Gate
  ├─ all agents PASS and minimum rounds satisfied → Approval Candidate
  ├─ not PASS and max rounds not reached → Next Review Round
  └─ not PASS and max rounds reached → Critical Report
  ↓
User Approval
  ├─ approved → FINAL_AGENT_SPEC.md
  └─ rejected with feedback → Revision Loop
END
```

---

## 5. MAGI Agents

MAGI has three main review agents.

### 5.1 MELCHIOR — Architecture Agent

MELCHIOR checks:

```text
module boundaries
dependency direction
SRP compliance
interface design
state flow
extensibility
implementation order
maintainability
```

MELCHIOR must fail sections that allow poor architecture or mixed responsibilities.

### 5.2 BALTHASAR — Requirement Guardian

BALTHASAR checks:

```text
explicit user requirements
implicit but necessary requirements
non-goals
assumptions
blocking questions
scope boundaries
acceptance criteria
user approval flow
```

BALTHASAR must fail sections that weaken, distort, or omit user intent.

### 5.3 CASPER — Failure Analyst

CASPER checks:

```text
likely AI coding agent misreadings
vague wording
hidden edge cases
overengineering risks
underspecified behavior
missing tests
dangerous defaults
forbidden behavior coverage
failure handling
```

CASPER must fail sections that leave room for plausible but wrong implementation.

---

## 6. Review Policy

### 6.1 Minimum Review Rounds

MAGI must run at least:

```text
3 review rounds
```

Even if all agents PASS earlier, the workflow must continue until the minimum review count is satisfied.

### 6.2 Maximum Review Rounds

MAGI must stop after:

```text
10 review rounds
```

If all agents cannot PASS by the maximum round, MAGI must enter:

```text
CRITICAL_BLOCKED
```

### 6.3 Unanimous PASS Requirement

Final review requires:

```text
MELCHIOR: PASS
BALTHASAR: PASS
CASPER: PASS
```

2/3 approval is not enough.

### 6.4 Section-Level Review

PASS / REVISE / FAIL must be tracked per section.

Example:

```json
{
  "mission": "PASS",
  "scope": "PASS",
  "architecture": "REVISE",
  "test_plan": "PASS",
  "agent_instructions": "REVISE"
}
```

---

## 7. Model Routing Policy for v1

### 7.1 OpenAI-Only Runtime

All v1 runtime LLM calls must use OpenAI.

Required credential:

```bash
OPENAI_API_KEY
```

The system must fail clearly if OpenAI is selected and `OPENAI_API_KEY` is missing.

### 7.2 Agent-Specific OpenAI Model Routing

Even though v1 is OpenAI-only, each agent must be configurable independently.

Example configuration:

```yaml
model_routing:
  melchior:
    provider: openai
    model: configurable-openai-model
  balthasar:
    provider: openai
    model: configurable-openai-model
  casper:
    provider: openai
    model: configurable-openai-model
  conflict_resolver:
    provider: openai
    model: configurable-openai-model
  spec_composer:
    provider: openai
    model: configurable-openai-model
```

Do not hardcode unavailable model names as mandatory requirements.

### 7.3 Provider Adapter Interface

Implement a provider abstraction.

Required v1 adapter:

```text
OpenAIProvider
```

Optional future stubs:

```text
AnthropicProvider
GoogleProvider
LocalProvider
SelfHostedProvider
```

Non-OpenAI provider stubs must not require real credentials and must not be required for v1 acceptance.

Recommended interface:

```python
class LLMProvider:
    provider_name: str

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        ...
```

---

## 8. Model-Blind Peer Review Policy

Model-blind review remains mandatory even in OpenAI-only v1.

Agents must not know:

```text
which model other agents use
whether another agent uses a newer or older model
benchmark reputation of another model
release timing of another model
pricing tier
context window size
```

If future providers are added, agents also must not know:

```text
which provider other agents use
whether another agent is from OpenAI, Anthropic, Google, or any other provider
```

### 8.1 Orchestrator Visibility

The orchestrator may know model routing for execution and audit.

This information must be stored privately:

```text
state/private_model_assignments.json
```

### 8.2 Agent-Visible Redaction

Agent-visible packets must not contain:

```text
provider name
model name
model version
release date
benchmark claims
pricing tier
context window size
```

Agents may see:

```text
agent role name
agent output content
section-level review status
cited evidence
conflict summaries
```

### 8.3 Forbidden Model Authority Arguments

Any output that argues from model authority must be invalidated.

Forbidden examples:

```text
I am a newer model, so my answer should override yours.
My benchmark score is higher, so this section should PASS.
OpenAI / Claude / Gemini is better, so this review is more reliable.
```

Valid review arguments must cite:

```text
user requirements
project-folder evidence
web evidence
explicit assumptions
test results
spec consistency
architecture constraints
failure modes
```

---

## 9. Tool-Enabled Capability Model

MAGI agents must be tool-enabled.

Agents are not merely prompt personas. Each agent must operate through an explicit capability and skill permission model.

Every capability must define:

```text
capability_id
purpose
allowed_agents
input contract
output contract
safety restrictions
artifact logging requirement
whether the capability output can be shared with other agents
```

No agent may use undeclared tools or undeclared skills.

---

## 10. Skill Registry

Implement a Skill Registry.

Required initial skills:

```text
read_user_request
scan_project_folder
read_project_file
summarize_project_context
web_search
record_evidence
parse_intent
classify_scope
generate_assumptions
detect_blocking_questions
architecture_review
requirement_review
failure_review
cross_review
resolve_conflicts
compose_final_spec
generate_critical_report
write_artifact
execute_command_guarded
```

Each skill must have an explicit permission list.

---

## 11. Agent Skill Permission Matrix

### 11.1 MELCHIOR Allowed Skills

```text
read_user_request
scan_project_folder
read_project_file
summarize_project_context
web_search
record_evidence
architecture_review
cross_review
execute_command_guarded, only if --allow-command-execution is enabled
```

### 11.2 BALTHASAR Allowed Skills

```text
read_user_request
scan_project_folder
read_project_file
summarize_project_context
web_search
record_evidence
parse_intent
classify_scope
generate_assumptions
detect_blocking_questions
requirement_review
cross_review
```

### 11.3 CASPER Allowed Skills

```text
read_user_request
scan_project_folder
read_project_file
summarize_project_context
web_search
record_evidence
failure_review
cross_review
execute_command_guarded, only if --allow-command-execution is enabled
```

### 11.4 Conflict Resolver Allowed Skills

```text
record_evidence
resolve_conflicts
write_artifact
```

### 11.5 Spec Composer Allowed Skills

```text
compose_final_spec
write_artifact
```

### 11.6 Critical Reporter Allowed Skills

```text
generate_critical_report
write_artifact
```

No agent may access private model routing metadata.

---

## 12. Input Contract

MAGI v1 must support:

### 12.1 File Input

```bash
magi-spec generate --input request.md --output ./magi_output
```

Supported extensions:

```text
.md
.txt
```

### 12.2 Direct Text Input

```bash
magi-spec generate --text "Build a Python SDK for ..." --output ./magi_output
```

### 12.3 Project Folder Input

```bash
magi-spec generate \
  --input request.md \
  --project ./target_project \
  --output ./magi_output
```

Project folder access is read-only by default.

MAGI may inspect:

```text
README files
pyproject.toml
package.json
source files
test files
docs
existing specification files
configuration files
```

MAGI must ignore by default:

```text
.git/
.venv/
venv/
node_modules/
dist/
build/
__pycache__/
large binary files
.env files
secret files
```

---

## 13. Web Search Policy

MAGI must support web research.

Recommended CLI option:

```bash
--web-search auto
```

Valid modes:

```text
auto
on
off
```

Web research should be used for:

```text
current framework documentation
current SDK/API behavior
library compatibility
security-sensitive technical claims
fast-changing tooling details
```

Every web result used in reasoning must be logged as evidence.

Required artifacts:

```text
research/web_sources.json
research/web_research_summary.ko.md
```

MAGI must distinguish between:

```text
user-provided facts
project-folder evidence
web evidence
agent assumptions
```

Final specs must not present web-derived claims as user requirements unless explicitly confirmed or classified.

---

## 14. Command Execution Policy

MAGI must not execute commands by default.

Command execution is allowed only when the user passes:

```bash
--allow-command-execution
```

When enabled, command execution must be controlled, logged, and non-destructive.

Allowed command categories may include:

```text
pytest
ruff check
mypy
python -m build
package metadata inspection
static analysis commands
```

Forbidden command categories include:

```text
rm -rf
file deletion
uncontrolled package installation
credential exfiltration
network upload
repository mutation
service deployment
background daemon launch
```

Every executed command must be saved with:

```text
command
working directory
exit code
stdout summary
stderr summary
timestamp
requesting agent
```

Required artifact:

```text
execution/command_log.json
```

If command execution is not enabled, agents may recommend commands but must not run them.

---

## 15. Evidence Policy

MAGI must maintain an evidence registry.

Every important claim in reviews should be traceable to one of:

```text
USER_REQUEST
PROJECT_FILE
WEB_SOURCE
COMMAND_RESULT
AGENT_ASSUMPTION
AGENT_REVIEW
```

Required artifact:

```text
evidence/evidence_registry.json
```

The final English spec should not be overloaded with citations, but Korean internal analysis and critical reports must preserve evidence references.

---

## 16. Artifact Policy

MAGI must save every intermediate and final artifact.

Required output structure:

```text
magi_output/
  raw/
    user_request.md

  context/
    project_manifest.json
    project_summary.ko.md

  research/
    web_sources.json
    web_research_summary.ko.md

  evidence/
    evidence_registry.json

  execution/
    command_log.json

  analysis/
    01_intent_parse.ko.md
    02_requirement_lock.ko.md
    03_scope_classification.ko.md
    04_initial_assumptions.ko.md
    05_blocking_questions.ko.md

  agents/
    initial/
      melchior_architecture.ko.md
      balthasar_requirements.ko.md
      casper_failure_review.ko.md

  review_rounds/
    round_01/
      melchior_review.ko.md
      balthasar_review.ko.md
      casper_review.ko.md
      conflict_resolution.ko.md
      section_status.json

  draft/
    approval_candidate_spec.en.md

  final/
    FINAL_AGENT_SPEC.md

  critical/
    CRITICAL_REPORT.ko.md
    FAILED_AGENT_SPEC_DRAFT.en.md

  state/
    magi_state.json
    private_model_assignments.json
```

The artifact writer must:

```text
create directories automatically
write UTF-8 files
avoid overwriting prior runs unless explicitly allowed
record created artifact paths in state/magi_state.json
preserve failed drafts
separate public agent-visible artifacts from private orchestrator artifacts
```

---

## 17. Approval Flow

MAGI must not finalize `FINAL_AGENT_SPEC.md` until user approval.

### 17.1 Generate Approval Candidate

After successful MAGI review, generate:

```text
draft/approval_candidate_spec.en.md
```

### 17.2 Approve Command

```bash
magi-spec approve ./magi_output
```

This command promotes:

```text
draft/approval_candidate_spec.en.md
```

to:

```text
final/FINAL_AGENT_SPEC.md
```

and updates state to:

```text
FINALIZED
```

### 17.3 Revision Command

```bash
magi-spec revise ./magi_output --feedback feedback.md
```

---

## 18. CLI Specification

### 18.1 Generate from File

```bash
magi-spec generate --input request.md --output ./magi_output
```

### 18.2 Generate from Text

```bash
magi-spec generate --text "Build a Python library that..." --output ./magi_output
```

### 18.3 Generate with Project Context

```bash
magi-spec generate \
  --input request.md \
  --project ./target_project \
  --output ./magi_output
```

### 18.4 Generate with Web Research

```bash
magi-spec generate \
  --input request.md \
  --output ./magi_output \
  --web-search auto
```

### 18.5 Generate with Command Execution

```bash
magi-spec generate \
  --input request.md \
  --project ./target_project \
  --output ./magi_output \
  --allow-command-execution
```

### 18.6 Approve

```bash
magi-spec approve ./magi_output
```

### 18.7 Revise

```bash
magi-spec revise ./magi_output --feedback feedback.md
```

### 18.8 Status

```bash
magi-spec status ./magi_output
```

The CLI must remain thin. Core workflow logic must live in the Python package.

---

## 19. Python API Specification

Recommended usage:

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

Approval:

```python
result = engine.approve("./magi_output")
print(result.final_spec_path)
```

Revision:

```python
result = engine.revise(
    output_dir="./magi_output",
    feedback_path="feedback.md",
)
```

---

## 20. Recommended Repository Structure

```text
magi-spec-engine/
  README.md
  pyproject.toml
  src/
    magi_spec/
      __init__.py
      engine.py
      cli.py

      core/
        state.py
        workflow.py
        artifacts.py
        config.py
        errors.py
        approval.py
        evidence.py

      graph/
        builder.py
        nodes.py
        transitions.py

      agents/
        base.py
        melchior.py
        balthasar.py
        casper.py
        conflict_resolver.py
        spec_composer.py
        critical_reporter.py

      skills/
        registry.py
        permissions.py
        project_scan.py
        file_read.py
        web_search.py
        command_execution.py
        evidence.py
        artifact_write.py

      providers/
        base.py
        openai_adapter.py
        anthropic_stub.py
        google_stub.py
        local_stub.py

      prompts/
        intent_parser.md
        requirement_lock.md
        melchior.md
        balthasar.md
        casper.md
        conflict_resolver.md
        spec_composer.md
        critical_reporter.md

      schemas/
        state.py
        agent_result.py
        section_status.py
        artifacts.py
        evidence.py
        provider_config.py

      exporters/
        markdown.py
        json.py

  tests/
    test_cli_generate.py
    test_cli_project_context.py
    test_cli_approve.py
    test_state_transitions.py
    test_artifact_writer.py
    test_review_policy.py
    test_skill_permissions.py
    test_model_blind_review.py
    test_command_execution_guard.py
    test_web_evidence.py
    test_final_spec_contract.py
```

---

## 21. Final Agent Spec Contract

`FINAL_AGENT_SPEC.md` must be English-only.

It must contain at minimum:

```text
# Final Agent Specification

## 1. Mission
## 2. Background
## 3. User Intent
## 4. Scope
### 4.1 In Scope
### 4.2 Out of Scope
## 5. Definitions
## 6. Evidence Summary
## 7. Mandatory Requirements
## 8. Recommended Requirements
## 9. Optional Requirements
## 10. Forbidden Behaviors
## 11. Input Contract
## 12. Output Contract
## 13. Architecture
## 14. Module Responsibilities
## 15. Data Flow
## 16. Error Handling Policy
## 17. Configuration Policy
## 18. Persistence / Artifact Policy
## 19. Implementation Order
## 20. Acceptance Criteria
## 21. Test Plan
## 22. Manual Verification Checklist
## 23. Instructions for AI Coding Agent
```

---

## 22. Critical Report Contract

If the workflow enters `CRITICAL_BLOCKED`, generate:

```text
critical/CRITICAL_REPORT.ko.md
```

The report must include:

```text
unresolved conflicts
failed sections
failing agent per section
repeated failure patterns
unsafe assumptions
blocking questions
attempted revision summary
recommended user decisions
path to failed English spec draft
evidence summary
```

The report must include decision logs and review rationales.

It must not expose raw hidden chain-of-thought. It must provide user-facing reasoning summaries only.

---

## 23. README Requirements

The README must be English.

It must explain:

```text
what MAGI Spec Engine is
what it does not do
installation
environment setup
OpenAI-only v1 runtime
future provider adapter extension point
model-blind review policy
CLI usage
Python API usage
project folder context
web research mode
command execution guard
output directory structure
approval flow
review loop behavior
critical report behavior
```

The README must not imply that MAGI directly implements code.

---

## 24. Testing Requirements

Tests must not require real API calls by default.

### 24.1 CLI Tests

```text
generate from file
generate from text
generate with project folder
approve candidate
reject invalid approval state
show status
```

### 24.2 State Tests

```text
initial state creation
transition to reviewing
transition to approval candidate
transition to finalized
transition to critical blocked
```

### 24.3 Review Policy Tests

```text
minimum 3 rounds enforced
maximum 10 rounds enforced
unanimous PASS required
section-level status persisted
```

### 24.4 Artifact Tests

```text
raw request saved
project manifest saved
web evidence saved
command logs saved when commands run
Korean analysis files saved
review round files saved
approval candidate saved
final spec saved only after approval
critical report saved on failure
```

### 24.5 Skill Permission Tests

```text
MELCHIOR cannot use BALTHASAR-only skills
BALTHASAR cannot execute commands
CASPER cannot access private model routing metadata
Spec Composer cannot run web search
command execution is blocked without explicit flag
```

### 24.6 Model-Blind Review Tests

```text
cross-review packets do not contain provider names
cross-review packets do not contain model names
model authority claims are rejected
private model assignment metadata is not included in agent-visible context
```

### 24.7 OpenAI-Only v1 Tests

```text
system runs with OpenAIProvider
system requires OPENAI_API_KEY when real OpenAIProvider is selected
tests can use MockProvider without OPENAI_API_KEY
non-OpenAI provider stubs are not required for v1 runtime
Anthropic/Gemini/local credentials are not required
```

---

## 25. Implementation Order

### Phase 1 — Project Skeleton

```text
Create Python package structure.
Add pyproject.toml.
Add CLI entry point.
Add README skeleton.
```

### Phase 2 — State, Artifact, and Evidence System

```text
Implement MagiState.
Implement artifact writer.
Implement evidence registry.
Implement output directory structure.
Implement state persistence.
Implement public/private artifact separation.
```

### Phase 3 — OpenAI Provider Adapter

```text
Implement provider adapter base.
Implement OpenAIProvider.
Read OPENAI_API_KEY.
Add MockProvider for tests.
Add provider config schema.
Add optional future provider stubs.
```

### Phase 4 — Model-Blind Routing

```text
Implement private model routing config.
Implement private_model_assignments.json.
Implement agent-visible context redaction.
Reject model authority arguments.
```

### Phase 5 — Skill Registry and Permissions

```text
Implement skill registry.
Implement permission checks.
Implement project scan skill.
Implement web search skill.
Implement guarded command execution skill.
Implement artifact and evidence skills.
```

### Phase 6 — Agent Prompt System

```text
Add prompt files.
Implement prompt loader.
Implement agent-visible context builder.
Ensure provider/model metadata is excluded.
```

### Phase 7 — MAGI Agents

```text
Implement MELCHIOR.
Implement BALTHASAR.
Implement CASPER.
Implement Conflict Resolver.
Implement Spec Composer.
Implement Critical Reporter.
```

### Phase 8 — LangGraph Workflow

```text
Build graph nodes.
Build transitions.
Enforce minimum and maximum review rounds.
Enforce unanimous PASS.
Persist round artifacts.
```

### Phase 9 — Approval Flow

```text
Implement approval candidate generation.
Implement approve command.
Implement revise command.
Implement status command.
```

### Phase 10 — Tests

```text
Add unit tests.
Add CLI tests.
Add mock provider tests.
Add skill permission tests.
Add model-blind review tests.
Add artifact contract tests.
```

### Phase 11 — Documentation

```text
Complete English README.
Add usage examples.
Explain generated artifacts.
Explain OpenAI-only v1.
Explain future provider adapter interface.
Explain model-blind policy and tool permissions.
```

---

## 26. Forbidden Behaviors for Codex

The implementation agent must not:

```text
build a web server
build a GUI
build a VSCode extension
call Codex/Copilot/Cursor/Claude Code directly
implement the user's target project
skip artifact persistence
finalize FINAL_AGENT_SPEC.md before user approval
expose raw hidden chain-of-thought
merge CLI logic with core workflow logic
require real LLM calls for tests
require Anthropic/Gemini/local credentials in v1
silently continue with missing OpenAI credentials when OpenAIProvider is selected
silently discard failed review outputs
treat 2/3 MAGI approval as sufficient
skip minimum review rounds
exceed max review rounds without producing a critical report
allow agents to access private model routing metadata
allow model authority arguments
execute commands without --allow-command-execution
modify project files during project scanning
```

---

## 27. Acceptance Criteria

The implementation is acceptable only if all of the following are true.

1. The project installs as a Python package.
2. The CLI command `magi-spec` is available.
3. The system accepts `--input request.md`.
4. The system accepts `--text "..."`.
5. The system accepts `--project ./target_project`.
6. The system supports web research and saves web evidence.
7. The system blocks command execution unless `--allow-command-execution` is passed.
8. The system reads OpenAI credentials from `OPENAI_API_KEY` when OpenAIProvider is selected.
9. The system runs fully with OpenAI only in v1.
10. The provider adapter interface exists for future non-OpenAI providers.
11. Non-OpenAI provider integrations are not required for v1 acceptance.
12. Anthropic, Gemini, local, or self-hosted credentials are not required for v1.
13. Different agents can be assigned different OpenAI models.
14. Agents cannot see other agents' model identity.
15. Model authority arguments are invalidated.
16. The system uses LangGraph for workflow orchestration.
17. The system saves all required intermediate artifacts.
18. Korean analysis files are generated.
19. An English approval candidate spec is generated after review PASS.
20. `FINAL_AGENT_SPEC.md` is not created before approval.
21. `magi-spec approve` finalizes the spec.
22. The review loop requires MELCHIOR, BALTHASAR, and CASPER to PASS.
23. The review loop runs at least 3 rounds.
24. The review loop stops at or before 10 rounds.
25. If PASS is impossible, a Korean critical report is generated.
26. Tests run without real API calls by default.
27. README is written in English.
28. The system does not directly execute implementation agents.

---

## 28. Final Instruction to Codex

You are implementing **MAGI Spec Engine**.

Follow this document exactly.

The most important v1 constraint is:

```text
OpenAI-only runtime.
Future multi-provider architecture.
Model-blind peer review always enforced.
```

Do not attempt to implement live Claude, Gemini, local, or self-hosted provider integrations as required v1 features.

Do implement clean interfaces and stubs so that future provider integrations can be added later without rewriting the workflow.

Do not connect MAGI to Codex, Copilot, Cursor, Claude Code, or any implementation executor.

MAGI only generates final Markdown instructions.

Implementation execution is an external stage.

Start with the project skeleton, then implement state/artifacts/evidence, then OpenAI provider adapter, then model-blind routing, then skill registry, then agents, then LangGraph workflow, then approval flow, then tests, then README.
