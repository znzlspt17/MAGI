# MAGI Spec Engine

MAGI Spec Engine is a local Python package and thin CLI that converts a high-level development request into a reviewed, implementation-ready Markdown specification for an AI coding agent.

MAGI does not implement the requested target project. It does not run Codex, Copilot, Cursor, Claude Code, or any other implementation agent. Its boundary is specification generation.

User guide (Korean): [docs/USER_GUIDE.ko.md](docs/USER_GUIDE.ko.md)
v2 implementation spec: [docs/magi_spec_engine_openai_only_v2.md](docs/magi_spec_engine_openai_only_v2.md)

## Installation

```bash
pip install -e ".[dev]"
```

Python 3.11 or newer is required.

## Environment Setup

MAGI is an OpenAI-only runtime. When OpenAI is selected, MAGI reads credentials from:

```bash
OPENAI_API_KEY
```

If OpenAI is selected and credentials are missing, MAGI fails with an actionable error. Tests can route agents to the built-in `mock` provider so the test suite never requires real API calls.

## Pipelines

MAGI ships two pipeline implementations selected via `pipeline.version` in the config (or `--pipeline` CLI flag).

### v2 — SpecForge (default)

4-stage deterministic compiler:

```
Spec Interviewer → Requirement Lock → Spec Compiler → Checklist Critic
```

| Stage | Agent route key | Role |
|---|---|---|
| Spec Interviewer | `interviewer` | Classifies request type; identifies blocking questions |
| Requirement Lock | `interviewer` | Fixes requirements/non-scope/assumptions as structured sheet |
| Spec Compiler | `compiler` | Compiles single English Markdown specification |
| Checklist Critic | `critic` | Runs structured checklist; max 2 passes |
| Critical Report | `critical_reporter` | Writes failure report if critic exceeds max passes |

Default v2 configuration (applied when no config file is provided):

```yaml
model_routing:
  interviewer:
    provider: openai
    model: gpt-5.4-nano    # default
  critic:
    provider: openai
    model: gpt-5.4-nano    # default
  compiler:
    provider: openai
    model: gpt-5.4-nano    # default
  critical_reporter:
    provider: openai
    model: gpt-5.4-nano    # default
pipeline:
  version: v2
review:
  max_critic_passes: 2     # critic runs at most 2 times
```

### v1 — 3-Agent Review Loop (legacy)

The original pipeline. Kept for backward compatibility. Not the default.

```yaml
model_routing:
  melchior:         # architecture reviewer
    provider: openai
    model: gpt-5.4-nano
  balthasar:        # requirements reviewer
    provider: openai
    model: gpt-5.4-nano
  casper:           # failure mode reviewer
    provider: openai
    model: gpt-5.4-nano
  conflict_resolver:
    provider: openai
    model: gpt-5.4-nano
  spec_composer:
    provider: openai
    model: gpt-5.4-nano
  critical_reporter:
    provider: openai
    model: gpt-5.4-nano
pipeline:
  version: v1
review:
  min_review_rounds: 3
  max_review_rounds: 10
```

Configuration file lookup priority (highest to lowest):

```text
1. CLI --config ./model_config.yaml
2. Environment variable MAGI_CONFIG_PATH
3. magi_config.yaml inside the output directory
4. Built-in defaults (v2 shown above)
```

Anthropic, Google, local, and self-hosted providers are future extension stubs. They do not require credentials, but they are not supported for production runtime.

## Mock Provider Config (v2, for tests)

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
```

## CLI Usage

Generate from a file:

```bash
magi-spec generate --input request.md --output ./magi_output
```

Generate from a file, overwriting an existing output directory:

```bash
magi-spec generate --input request.md --output ./magi_output --overwrite
```

Generate from direct text:

```bash
magi-spec generate --text "Build a Python SDK for ..." --output ./magi_output
```

Select pipeline version explicitly:

```bash
magi-spec generate --input request.md --output ./magi_output --pipeline v2
```

Include read-only project context:

```bash
magi-spec generate --input request.md --project ./target_project --output ./magi_output
```

Use web research:

```bash
magi-spec generate --input request.md --output ./magi_output --web-search auto
```

Allow guarded command execution:

```bash
magi-spec generate --input request.md --project ./target_project --output ./magi_output --allow-command-execution
```

Approve the reviewed candidate:

```bash
magi-spec approve ./magi_output
```

Revise with feedback (v2: merges into Requirement Lock; v1: resets review loop):

```bash
magi-spec revise ./magi_output --feedback feedback.md
```

Inject answers to blocking questions (v2 only):

```bash
magi-spec answer ./magi_output --answers answers.json
```

`answers.json` format: `[{"question_id": "DONE-001", "question": "...", "answer": "..."}]`

Show status:

```bash
magi-spec status ./magi_output
```

Monitor an active run:

```text
magi_output/state/heartbeat.json
```

While `generate` or `revise` is processing, MAGI writes this heartbeat immediately and then refreshes it every 10 seconds. Web services can treat the run as active when `running` is `true` and `last_heartbeat_at` is recent. On normal completion MAGI writes `running: false` with the final status; on an exception it writes `lifecycle: failed` with an error summary.

## Exit Codes

```text
0  — Successful completion (Approval Candidate generated, or FINALIZED after approve)
1  — Input error (missing file, missing OPENAI_API_KEY, invalid arguments, etc.)
2  — CRITICAL_BLOCKED (review/critic could not reach consensus within max passes/rounds)
3  — NEEDS_USER_INPUT (v2: blocking questions require user answers before proceeding)
```

## Python API

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
print(result.questions_path)   # v2: path to blocking questions file if NEEDS_USER_INPUT
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

Answer blocking questions (v2 only):

```python
result = engine.answer(
    "./magi_output",
    answers=[{"question_id": "DONE-001", "question": "...", "answer": "..."}],
)
```

Status:

```python
status = engine.status("./magi_output")
print(status.status)   # COMPILING | CRITIQUING | NEEDS_USER_INPUT |
                       # PASS_PENDING_USER_APPROVAL | FINALIZED | CRITICAL_BLOCKED
```

## Output Directory

MAGI saves intermediate and final artifacts.

Always generated (v2):

```text
magi_output/
  raw/user_request.md
  context/project_manifest.json
  context/project_summary.ko.md
  evidence/evidence_registry.json
  analysis/01_intent_parse.ko.md
  analysis/02_requirement_lock.ko.md      ← compatibility alias for lock sheet
  analysis/04_initial_assumptions.ko.md
  analysis/05_blocking_questions.ko.md
  analysis/requirement_lock_sheet.json    ← structured lock sheet (v2)
  analysis/requirement_lock_sheet.ko.md
  review/checklist_issues.json            ← structured critic output (v2)
  state/magi_state.json
  state/heartbeat.json
  state/private_model_assignments.json
```

Generated only under stated conditions:

```text
  research/web_sources.json               — --web-search on or auto (when triggered)
  research/web_research_summary.ko.md     — same
  execution/command_log.json              — --allow-command-execution only
  draft/approval_candidate_spec.en.md     — after checklist critic passes
  final/FINAL_AGENT_SPEC.md              — after magi-spec approve
  critical/CRITICAL_REPORT.ko.md         — CRITICAL_BLOCKED only
  critical/FAILED_AGENT_SPEC_DRAFT.en.md — CRITICAL_BLOCKED only
```

Intermediate analysis artifacts are Korean. The approval candidate and final agent specification are English.

## v2 SpecForge Pipeline Details

### Spec Interviewer

Classifies the request type (`product`, `feature`, `bugfix`, `refactor`, `infra`) and identifies blocking questions — questions that, if unanswered, would change the spec direction entirely. Non-direction-changing informational questions are converted to assumptions.

If direction-changing blocking questions are found in a non-interactive environment, the run exits with `NEEDS_USER_INPUT`. Use `magi-spec answer` to inject answers and resume.

### Pausing and Resuming (state model)

MAGI v2 does **not** use LangGraph's `interrupt()` / checkpointer human-in-the-loop mechanism. When the interview stage finds direction-changing blocking questions, the `await_user` node routes to `END` and the run terminates with `NEEDS_USER_INPUT`. The full run state is serialized to `state/magi_state.json`.

Resuming is not an in-process LangGraph resume. `magi-spec answer` (or `engine.answer(...)`) loads `magi_state.json`, injects the answers into the requirement lock sheet, and **re-invokes the graph from `START`**. Earlier idempotent nodes (`project_context`, `web_research`) may run again.

This is a deliberate trade-off: a portable JSON state file that survives across processes and machines, instead of keeping a live checkpointer in memory. The engine stays stateless between invocations and every run is fully auditable from disk.

### Requirement Lock Sheet

All user answers, inferred assumptions, mandatory requirements, non-scope items, and constraints are fixed into a structured JSON sheet (`analysis/requirement_lock_sheet.json`). This sheet is the single source of truth for the compiler. User feedback during `revise` updates only the lock sheet — it does not restart the full pipeline.

### Checklist Critic

Runs deterministic checks first (no LLM, zero token cost), then one LLM-assisted pass. Maximum 2 critic passes total (`max_critic_passes`). Each unresolved blocking issue causes a re-compile. If max passes are exhausted with blocking issues remaining, the run exits with `CRITICAL_BLOCKED`.

Deterministic checks cover: all 26 required headings present, Out of Scope non-empty, Forbidden Behaviors non-empty, Acceptance Criteria verifiable, Test Plan present, zero unresolved blocking questions, mandatory requirements reflected in spec.

## Model-Blind Review (v1)

In v1, provider and model assignments are private orchestration metadata. Agents cannot see provider names, model names, or benchmark claims. Arguments based on model authority are invalid.

In v2, only the single active agent per stage sees the routing key assigned to it. No cross-agent output relaying occurs.

## Project Folder Context

Project scanning is read-only. MAGI skips `.git`, virtual environments, `node_modules`, build outputs, caches, `.env` files, secret-like files, and large binaries by default.

Large binary criteria: any file over 1 MB, or files with binary extensions (images, video, audio, archives, compiled binaries, `.pyc`, `.db`, etc.). Priority exceptions that are always read include `README.md`, `pyproject.toml`, `package.json`, `*.md`, `*.toml`, `*.yaml`, and `*.json` under 1 MB.

## Web Research

`--web-search` supports `auto`, `on`, and `off`. Web evidence is logged separately and must not be treated as a user requirement unless explicitly classified.

In `auto` mode, web search is triggered when: the user request names an external library, SDK, API, or framework; version compatibility verification is needed; or a blocking question depends on an external technical fact.

## Command Execution Guard

MAGI does not execute commands by default. With `--allow-command-execution`, only narrow non-destructive command categories are allowed, and every command result is logged to `execution/command_log.json`.

## Critical Reports

If MAGI cannot produce a passing spec before the maximum critic passes (v2) or maximum review rounds (v1), it writes:

```text
critical/CRITICAL_REPORT.ko.md
critical/FAILED_AGENT_SPEC_DRAFT.en.md
```

The report summarizes unresolved issues, unsafe assumptions, blocking questions, and evidence summaries.

## Test Status

The repository test suite validates CLI flows, v1 and v2 pipeline behavior, review policy, model-blind routing, provider adapter behavior, command execution guards, project scanning policy, web-search policy, artifact contracts, checklist critic bounds, and acceptance smoke paths.
