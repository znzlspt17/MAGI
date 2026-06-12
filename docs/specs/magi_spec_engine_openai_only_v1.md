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
[Pre-Analysis Phase — executed by BALTHASAR on behalf of the orchestrator]
  Intent Parser           (BALTHASAR: parse_intent)
  Requirement Lock        (BALTHASAR: parse_intent + classify_scope)
  Scope Classifier        (BALTHASAR: classify_scope)
  Assumption Builder      (BALTHASAR: generate_assumptions)
  Blocking Question Det.  (BALTHASAR: detect_blocking_questions)
Pre-Analysis outputs are saved to analysis/ and shared with all three agents.
  ↓
[Initial Review Phase — all three agents in parallel]
  MELCHIOR Initial Pass
  BALTHASAR Initial Pass
  CASPER Initial Pass
  ↓
[Cross Review Phase — per round, see Section 6.5]
  Cross Review Loop
  ↓
  Conflict Resolver
  ↓
  Spec Composer
  ↓
Review Gate
  ├─ all agents PASS and minimum rounds satisfied      → Approval Candidate
  ├─ all agents PASS and min rounds NOT satisfied      → Increment round_counter → Next Review Round
  ├─ not PASS and max rounds not reached               → Next Review Round
  └─ not PASS and max rounds reached                   → Critical Report

round_counter is stored as an integer in magi_state.json.
Minimum rounds: 3  |  Maximum rounds: 10
  ↓
User Approval
  ├─ approved → Write FINAL_AGENT_SPEC.md → END (FINALIZED, exit code 0)
  └─ rejected + feedback
        ↓
    Merge Feedback into MagiState.revision_feedback
        ↓
    Requirement Lock  ← Revision Loop re-entry point
        ↓
    (workflow continues as normal; round_counter resets to 0)
    New review rounds saved under review_rounds/revision_N/ (N = revise call count)

[On CRITICAL_BLOCKED]
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
END
```

---

## 5. MAGI Agents

### 5.0 Component Classification

All system components are classified into one of three tiers:

```text
[Main Review Agents — perform independent judgment via LLM calls]
  MELCHIOR         — Architecture Agent
  BALTHASAR        — Requirement Guardian
  CASPER           — Failure Analyst

[Orchestrator Components — LLM calls executed under orchestrator direction]
  Conflict Resolver  — Aggregates agent outputs; resolves conflicts
  Spec Composer      — Composes spec draft from passed sections
  Critical Reporter  — Produces CRITICAL_REPORT on CRITICAL_BLOCKED

[Orchestrator Core — no LLM calls; pure control logic]
  LangGraph Workflow, State Manager, Artifact Writer, Evidence Registry
```

Rules:

```text
- Restrictions in Section 8.1 and Section 11.6 apply to Main Review Agents only.
- Orchestrator Components operate under orchestrator authority and may receive
  model routing information from the orchestrator for execution purposes.
- Orchestrator Components must never include raw model identity in LLM prompts.
```

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

The following is the authoritative section list, corresponding 1:1 with the 23 sections defined in Section 21:

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

All 23 sections must reach PASS status for the workflow to transition to Approval Candidate.

### 6.5 Cross Review Structure

The Cross Review Loop executes the following structure every round:

```text
Step 1 — Input Packet Preparation (orchestrator)
  - Collect each agent's output from the previous round (or initial pass).
  - Apply Section 8.2 redaction: remove provider, model, model_version fields.
  - Each agent receives only the other two agents' outputs (not its own):
      MELCHIOR receives: BALTHASAR output + CASPER output
      BALTHASAR receives: MELCHIOR output + CASPER output
      CASPER receives:   MELCHIOR output + BALTHASAR output

Step 2 — Cross Review Execution (parallel)
  - MELCHIOR: reviews BALTHASAR's requirement analysis and CASPER's failure analysis
              from an architecture perspective.
  - BALTHASAR: reviews MELCHIOR's architecture analysis and CASPER's failure analysis
               from a requirement perspective.
  - CASPER: reviews MELCHIOR's architecture analysis and BALTHASAR's requirement analysis
            from a failure-mode perspective.

Step 3 — Aggregation (Conflict Resolver)
  - Receives all three cross-review results.
  - Identifies conflicting section verdicts (e.g., one agent PASS, another FAIL).
  - Writes conflict_resolution.ko.md.
  - Updates section_status.json using the following aggregation rules:
      If any agent gives FAIL for a section   → section status = FAIL
      If no FAIL but any agent gives REVISE   → section status = REVISE
      All agents PASS                         → section status = PASS
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

Default configuration (applied when no user config file is provided):

```yaml
model_routing:
  melchior:
    provider: openai
    model: gpt-5.4-nano    # default
  balthasar:
    provider: openai
    model: gpt-5.4-nano    # default
  casper:
    provider: openai
    model: gpt-5.4-nano    # default
  conflict_resolver:
    provider: openai
    model: gpt-5.4-nano    # default
  spec_composer:
    provider: openai
    model: gpt-5.4-nano    # default
```

Do not hardcode unavailable model names as mandatory requirements.

Configuration file lookup priority (highest to lowest):

```text
1. CLI --config ./model_config.yaml
2. Environment variable MAGI_CONFIG_PATH
3. magi_config.yaml inside the output directory
4. Built-in defaults (shown above)
```

The system must run with built-in defaults when no config file is provided.
If `OPENAI_API_KEY` is missing, the system must fail clearly regardless of the configured model.

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

Access control mechanisms for this file:

```text
1. Code-level exclusion
   - AgentContext objects passed to agents must not include a model_assignments field.
   - The AgentContext class must not expose model assignment data at construction time.

2. Prompt-level redaction
   - ProviderOutputPacket objects sent to agents must not contain provider, model,
     or model_version fields.
   - Section 8.2 redaction rules are enforced in code, not just by convention.

3. Skill-level path restriction
   - The read_project_file skill must not allow access to magi_output/state/.
   - Allowed paths: files within the user-specified --project directory only.
   - Forbidden paths: magi_output/state/ and any private orchestrator directories.

4. Test validation (Section 24.6)
   - Tests must assert that AgentContext serialization contains no model identity fields.
   - Tests must assert that cross-review packets contain no provider or model keys.
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

Valid review arguments must cite one of the following:

Always permitted:

```text
user requirements
project-folder evidence
web evidence (only when --web-search on or auto is active)
explicit assumptions
spec consistency
architecture constraints
failure modes
```

Conditionally permitted (only when --allow-command-execution is active):

```text
test results (COMMAND_RESULT evidence type)
static analysis output
build output
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

Every skill must define all attributes required by Section 9. The following is the authoritative skill definitions:

```yaml
skills:
  - capability_id: read_user_request
    purpose: Reads the user's input request from file or inline text.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {source: str}
    output_contract: {content: str}
    safety_restrictions: [Read-only]
    artifact_logging: none
    output_shareable: true

  - capability_id: scan_project_folder
    purpose: Scans the target project folder and builds a file manifest.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {project_dir: str}
    output_contract: {manifest: "list[{path, size, type}]"}
    safety_restrictions:
      - Read-only; must not write to project files
      - Must apply binary/large file ignore rules (Section 12.3)
      - Must not access .env or secret files
    artifact_logging: required  # context/project_manifest.json
    output_shareable: true

  - capability_id: read_project_file
    purpose: Reads a single file from within the project folder.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {file_path: str}
    output_contract: {content: str}
    safety_restrictions:
      - Read-only
      - Must not access magi_output/state/ or private orchestrator directories
      - Must reject paths outside the --project directory
    artifact_logging: none
    output_shareable: true

  - capability_id: summarize_project_context
    purpose: Produces a Korean-language summary of the scanned project context.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {manifest: dict, file_contents: "list[str]"}
    output_contract: {summary: str}
    safety_restrictions: []
    artifact_logging: required  # context/project_summary.ko.md
    output_shareable: true

  - capability_id: web_search
    purpose: Searches the web for technical information and records results as evidence.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {query: str, max_results: "int (default 5)"}
    output_contract: {results: "list[{url, title, summary, retrieved_at}]"}
    safety_restrictions:
      - Forbidden when --web-search off
      - Results must be recorded in evidence_registry
      - Must not classify web-derived claims as user requirements
    artifact_logging: required  # research/web_sources.json
    output_shareable: true

  - capability_id: record_evidence
    purpose: Records a traceable evidence entry in the evidence registry.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER, conflict_resolver]
    input_contract: {source_type: str, content: str, citation: str}
    output_contract: {evidence_id: str}
    safety_restrictions:
      - COMMAND_RESULT type is forbidden when --allow-command-execution is inactive
    artifact_logging: required  # evidence/evidence_registry.json
    output_shareable: true

  - capability_id: parse_intent
    purpose: Parses the user request to extract structured intent and goals.
    allowed_agents: [BALTHASAR]
    input_contract: {user_request: str}
    output_contract: {intent: "dict({primary_goal, secondary_goals, external_dependency_check_needed: bool})"}
    safety_restrictions: []
    artifact_logging: required  # analysis/01_intent_parse.ko.md
    output_shareable: true

  - capability_id: classify_scope
    purpose: Classifies what is in-scope and out-of-scope for the specification.
    allowed_agents: [BALTHASAR]
    input_contract: {intent: dict}
    output_contract: {scope: "dict({in_scope: list, out_of_scope: list})"}
    safety_restrictions: []
    artifact_logging: required  # analysis/03_scope_classification.ko.md
    output_shareable: true

  - capability_id: generate_assumptions
    purpose: Generates explicit assumptions to fill gaps in the user request.
    allowed_agents: [BALTHASAR]
    input_contract: {intent: dict, scope: dict}
    output_contract: {assumptions: "list[str]"}
    safety_restrictions:
      - Must not present assumptions as confirmed user requirements
    artifact_logging: required  # analysis/04_initial_assumptions.ko.md
    output_shareable: true

  - capability_id: detect_blocking_questions
    purpose: Identifies questions that must be answered before the spec can proceed.
    allowed_agents: [BALTHASAR]
    input_contract: {intent: dict, assumptions: "list[str]"}
    output_contract: {blocking_questions: "list[str]"}
    safety_restrictions: []
    artifact_logging: required  # analysis/05_blocking_questions.ko.md
    output_shareable: true

  - capability_id: architecture_review
    purpose: Reviews specification sections for architectural quality.
    allowed_agents: [MELCHIOR]
    input_contract: {spec_sections: dict, context: dict}
    output_contract: {section_verdicts: "dict({section_id: PASS|REVISE|FAIL})", rationale: str}
    safety_restrictions:
      - Must not cite model authority (Section 8.3)
    artifact_logging: required  # agents/initial/ or review_rounds/
    output_shareable: true

  - capability_id: requirement_review
    purpose: Reviews specification sections for requirement completeness and fidelity.
    allowed_agents: [BALTHASAR]
    input_contract: {spec_sections: dict, context: dict}
    output_contract: {section_verdicts: dict, rationale: str}
    safety_restrictions:
      - Must not cite model authority
    artifact_logging: required
    output_shareable: true

  - capability_id: failure_review
    purpose: Reviews specification sections for failure modes, edge cases, and vagueness.
    allowed_agents: [CASPER]
    input_contract: {spec_sections: dict, context: dict}
    output_contract: {section_verdicts: dict, rationale: str}
    safety_restrictions:
      - Must not cite model authority
    artifact_logging: required
    output_shareable: true

  - capability_id: cross_review
    purpose: Reviews another agent's output from one's own specialist perspective.
    allowed_agents: [MELCHIOR, BALTHASAR, CASPER]
    input_contract: {peer_outputs: "list (redacted outputs of the other two agents)"}
    output_contract: {section_verdicts: dict, rationale: str}
    safety_restrictions:
      - Peer outputs must be redacted per Section 8.2 before delivery
      - Must not cite model authority
    artifact_logging: required  # review_rounds/round_N/
    output_shareable: true

  - capability_id: resolve_conflicts
    purpose: Aggregates cross-review results and resolves section-level conflicts.
    allowed_agents: [conflict_resolver]
    input_contract: {cross_review_results: "list (from all three agents)"}
    output_contract: {section_status: dict, conflict_summary: str}
    safety_restrictions: []
    artifact_logging: required  # review_rounds/round_N/conflict_resolution.ko.md, section_status.json
    output_shareable: true

  - capability_id: compose_final_spec
    purpose: Composes the approval candidate spec draft from passed sections.
    allowed_agents: [spec_composer]
    input_contract: {section_status: dict, section_contents: dict}
    output_contract: {spec_draft: str}
    safety_restrictions:
      - May run in CRITICAL_BLOCKED state to produce FAILED_AGENT_SPEC_DRAFT
      - Must insert WARNING headers on REVISE/FAIL sections in CRITICAL_BLOCKED mode
    artifact_logging: required  # draft/approval_candidate_spec.en.md or critical/FAILED_AGENT_SPEC_DRAFT.en.md
    output_shareable: false

  - capability_id: generate_critical_report
    purpose: Produces the Korean critical report when CRITICAL_BLOCKED is entered.
    allowed_agents: [critical_reporter]
    input_contract: {magi_state: dict, section_status: dict, evidence_registry: dict}
    output_contract: {report: str}
    safety_restrictions:
      - Must not expose raw hidden chain-of-thought
      - Must include path to FAILED_AGENT_SPEC_DRAFT.en.md
    artifact_logging: required  # critical/CRITICAL_REPORT.ko.md
    output_shareable: false

  - capability_id: write_artifact
    purpose: Writes an artifact file to the output directory with UTF-8 encoding.
    allowed_agents: [conflict_resolver, spec_composer, critical_reporter]
    input_contract: {relative_path: str, content: str}
    output_contract: {absolute_path: str}
    safety_restrictions:
      - Must create parent directories automatically
      - Must record written path in state/magi_state.json
      - Must not write to state/private_model_assignments.json
    artifact_logging: none  # self-logging
    output_shareable: false

  - capability_id: execute_command_guarded
    purpose: Executes safe, non-destructive commands (tests, linting, static analysis).
    allowed_agents: [MELCHIOR, CASPER]
    input_contract: {command: str, working_dir: str}
    output_contract: {exit_code: int, stdout_summary: str, stderr_summary: str, timestamp: str}
    safety_restrictions:
      - Forbidden unless --allow-command-execution is active
      - Only permitted command categories (Section 14) are allowed
      - Destructive commands (rm -rf, file deletion, credential exfiltration, etc.) are forbidden
    artifact_logging: required  # execution/command_log.json
    output_shareable: true
```

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
large binary files (see criteria below)
.env files
secret files
```

Binary and large file ignore criteria:

```text
Size threshold: any single file > 1 MB

Binary extensions (always ignored regardless of size):
  Images:    .png .jpg .jpeg .gif .bmp .ico .svg
  Video:     .mp4 .mov .avi .mkv
  Audio:     .mp3 .wav .ogg
  Archives:  .zip .tar .gz .bz2 .7z .rar
  Documents: .pdf .docx .xlsx .pptx
  Binaries:  .exe .dll .so .dylib .bin
  Python:    .pyc .pyd .pyo
  Data:      .db .sqlite .sqlite3

Priority exceptions (always read regardless of size or extension):
  README.md  README.txt  README.rst
  pyproject.toml  setup.py  setup.cfg  requirements*.txt
  package.json  package-lock.json  yarn.lock
  .env.example  (note: .env and .env.local are still ignored)
  *.md  *.toml  *.yaml  *.yml  *.json (under 1 MB)
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

Behavior of `--web-search auto`:

```text
Trigger conditions (execute web search if any of the following apply):
  1. The user request mentions a specific external library, SDK, API, or framework by name.
  2. The user request requires verification of version compatibility, current behavior,
     or up-to-date documentation.
  3. BALTHASAR's parse_intent output sets the external_dependency_check_needed flag to true.
  4. The Blocking Question Detector identifies a blocking question that depends on
     an external technical fact.

Non-trigger conditions (skip web search only if all of the following apply):
  - The user request concerns purely internal logic or algorithm design.
  - The user request contains no references to external libraries or APIs.

The decision to execute web search in auto mode must be recorded in
analysis/01_intent_parse.ko.md.
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

Every important claim in reviews should be traceable to one of the following evidence types:

Always permitted:

```text
USER_REQUEST
PROJECT_FILE
WEB_SOURCE      (only when --web-search on or auto is active)
AGENT_ASSUMPTION
AGENT_REVIEW
```

Conditionally permitted:

```text
COMMAND_RESULT  (only when --allow-command-execution is active)
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
record created artifact paths in state/magi_state.json
preserve failed drafts
separate public agent-visible artifacts from private orchestrator artifacts
```

### 16.1 Unconditional Artifacts

The following artifacts are always generated:

```text
raw/user_request.md
context/project_manifest.json    (empty manifest if --project is not specified)
context/project_summary.ko.md    (records "No project context" if --project is not specified)
evidence/evidence_registry.json
analysis/01_intent_parse.ko.md through 05_blocking_questions.ko.md
agents/initial/*.ko.md
review_rounds/round_*/...
state/magi_state.json
state/private_model_assignments.json
```

### 16.2 Conditional Artifacts

The following artifacts are generated only under the stated conditions:

```text
research/web_sources.json              — only when --web-search on, or auto triggers search
research/web_research_summary.ko.md   — same condition as above
execution/command_log.json             — only when --allow-command-execution is active
draft/approval_candidate_spec.en.md   — only after all sections reach PASS
critical/CRITICAL_REPORT.ko.md         — only on CRITICAL_BLOCKED
critical/FAILED_AGENT_SPEC_DRAFT.en.md — only on CRITICAL_BLOCKED
final/FINAL_AGENT_SPEC.md              — only after magi-spec approve is executed
```

### 16.3 Overwrite Policy

```text
1. New generate run:
   - If output_dir already exists, abort and return an error.
   - With --force flag: retain the existing directory and overwrite contents.

2. magi-spec revise run:
   - Overwriting is permitted (explicit user action).
   - draft/approval_candidate_spec.en.md is overwritten.
   - New review rounds are saved under review_rounds/revision_N/ (N = revise call count).
   - The previous draft is backed up as:
     draft/approval_candidate_spec.en.revision_{N-1}.md

3. magi-spec approve run:
   - If final/FINAL_AGENT_SPEC.md already exists, abort and return an error.
   - With --force flag: overwrite.
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

This command performs the following steps:

```text
1. Reads feedback.md and stores its content in magi_state.json under revision_feedback.
2. Transitions state from AWAITING_REVISION to REVIEWING.
3. Re-enters the workflow at the Requirement Lock node.
4. revision_feedback is merged into existing requirements at the Requirement Lock stage.
5. round_counter is reset to 0.
6. Load User Request and Optional Project Folder Scan are not re-executed.
   (Original request and project context are unchanged.)
7. New review round artifacts are saved under review_rounds/revision_N/
   where N is the number of times magi-spec revise has been called.
```

---

## 18. CLI Specification

### 18.1 Generate from File

```bash
magi-spec generate --input request.md --output ./magi_output [--force]
```

Use `--force` to allow overwriting an existing output directory.

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

### 18.9 Exit Codes

```text
0  — Successful completion (Approval Candidate generated, or FINALIZED after approve)
1  — Input error (missing file, missing OPENAI_API_KEY, invalid arguments, etc.)
2  — CRITICAL_BLOCKED (review could not reach consensus within max rounds)
```

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

Status:

```python
status = engine.status("./magi_output")
print(status.state)              # REVIEWING | APPROVAL_CANDIDATE | FINALIZED | CRITICAL_BLOCKED
print(status.current_round)      # number of completed review rounds
print(status.section_statuses)   # dict[str, str] — per-section current status
print(status.artifacts)          # list of generated artifact paths
print(status.last_updated_at)    # ISO 8601 timestamp
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
        read_project_file.py
        web_search.py
        command_execution.py
        record_evidence.py
        write_artifact.py

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

### 22.1 FAILED_AGENT_SPEC_DRAFT Generation Rules

```text
- Based on the final round's Spec Composer output (round_10 or the last round reached).
- Spec Composer runs in CRITICAL_BLOCKED state to produce a partial draft based on
  the last round's section_status.json.
- Sections with PASS status are included with their final content.
- Sections with REVISE or FAIL status are included with the following warning prepended:

  > ⚠️ WARNING: This section did not reach consensus.
  > Status: {REVISE | FAIL}
  > Failing agents: {agent names}
  > See CRITICAL_REPORT.ko.md for details.

- CRITICAL_REPORT.ko.md must include the path to FAILED_AGENT_SPEC_DRAFT.en.md.
```

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
Unconditional artifacts (must always be present):
  raw request saved
  project manifest saved (empty manifest if --project not specified)
  evidence registry saved
  Korean analysis files saved
  review round files saved
  state files saved

Conditional artifacts (only under stated conditions):
  web evidence saved only when --web-search on or auto triggers search
  command logs saved only when --allow-command-execution is active
  approval candidate saved only after all sections reach PASS
  final spec saved only after magi-spec approve is executed
  critical report saved only on CRITICAL_BLOCKED
  failed spec draft saved only on CRITICAL_BLOCKED
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
