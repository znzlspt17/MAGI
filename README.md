# MAGI Spec Engine

MAGI Spec Engine is a local Python package and thin CLI that converts a high-level development request into a reviewed, implementation-ready Markdown specification for an AI coding agent.

MAGI does not implement the requested target project. It does not run Codex, Copilot, Cursor, Claude Code, or any other implementation agent. Its boundary is specification generation.

User guide (Korean): [docs/USER_GUIDE.ko.md](docs/USER_GUIDE.ko.md)

## Installation

```bash
pip install -e ".[dev]"
```

Python 3.11 or newer is required.

## Environment Setup

MAGI v1 is an OpenAI-only runtime. When OpenAI is selected, MAGI reads credentials from:

```bash
OPENAI_API_KEY
```

If OpenAI is selected and credentials are missing, MAGI fails with an actionable error. Tests can route agents to the built-in `mock` provider so the test suite never requires real API calls.

## OpenAI-Only v1 Runtime

Different MAGI agents can still use different OpenAI models through private routing.

Default model configuration (applied when no config file is provided):

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
  critical_reporter:
    provider: openai
    model: gpt-5.4-nano    # default
```

Configuration file lookup priority (highest to lowest):

```text
1. CLI --config ./model_config.yaml
2. Environment variable MAGI_CONFIG_PATH
3. magi_config.yaml inside the output directory
4. Built-in defaults (shown above)
```

Anthropic, Google, local, and self-hosted providers are future extension stubs in v1. They do not require credentials, but they are not supported for production runtime.

## Mock Provider Config

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

## CLI Usage

Generate from a file:

```bash
magi-spec generate --input request.md --output ./magi_output
```

Generate from a file, overwriting an existing output directory:

```bash
magi-spec generate --input request.md --output ./magi_output --force
```

Generate from direct text:

```bash
magi-spec generate --text "Build a Python SDK for ..." --output ./magi_output
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

Revise with feedback:

```bash
magi-spec revise ./magi_output --feedback feedback.md
```

Revision re-enters the workflow at the `Requirement Lock` stage, merges the feedback into existing requirements, and resets the round counter. Previous review artifacts are preserved under `review_rounds/revision_N/`.

Show status:

```bash
magi-spec status ./magi_output
```

## Exit Codes

```text
0  — Successful completion (Approval Candidate generated, or FINALIZED after approve)
1  — Input error (missing file, missing OPENAI_API_KEY, invalid arguments, etc.)
2  — CRITICAL_BLOCKED (review could not reach consensus within max rounds)
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

## Output Directory

MAGI saves intermediate and final artifacts.

Always generated:

```text
magi_output/
  raw/user_request.md
  context/project_manifest.json
  context/project_summary.ko.md
  evidence/evidence_registry.json
  analysis/*.ko.md
  agents/initial/*.ko.md
  review_rounds/round_*/
  state/magi_state.json
  state/private_model_assignments.json
```

Generated only under stated conditions:

```text
  research/web_sources.json           — --web-search on or auto (when triggered)
  research/web_research_summary.ko.md — same
  execution/command_log.json          — --allow-command-execution only
  draft/approval_candidate_spec.en.md — after all sections reach PASS
  final/FINAL_AGENT_SPEC.md           — after magi-spec approve
  critical/CRITICAL_REPORT.ko.md      — CRITICAL_BLOCKED only
  critical/FAILED_AGENT_SPEC_DRAFT.en.md — CRITICAL_BLOCKED only
```

Intermediate analysis and review artifacts are Korean. The approval candidate and final agent specification are English.

## Review Loop

MAGI uses LangGraph to orchestrate stateful review. MELCHIOR reviews architecture, BALTHASAR guards requirements, and CASPER analyzes failure modes. The workflow requires unanimous PASS and at least three review rounds. It stops at the configured maximum and writes a Korean critical report if PASS cannot be reached.

## Model-Blind Review

Provider and model assignments are private orchestration metadata. Agents can see role names, output content, section status, cited evidence, and conflict summaries. They cannot see provider names, model names, model versions, benchmark claims, release timing, pricing tiers, or context window sizes.

Arguments based on model authority are invalid and must not be used to pass or fail a section.
Agent-visible context is additionally sanitized so provider/model identity terms are redacted from forwarded peer output text.

## Future Provider Extension Point

The provider interface is intentionally isolated behind `LLMProvider.complete(...)`. v1 ships a real OpenAI provider, a mock provider for tests, and non-OpenAI stubs for future integrations. Adding a future live provider should not require rewriting the workflow.

## Project Folder Context

Project scanning is read-only. MAGI skips `.git`, virtual environments, `node_modules`, build outputs, caches, `.env` files, secret-like files, and large binaries by default.

Large binary criteria: any file over 1 MB, or files with binary extensions (images, video, audio, archives, compiled binaries, `.pyc`, `.db`, etc.). Priority exceptions that are always read include `README.md`, `pyproject.toml`, `package.json`, `*.md`, `*.toml`, `*.yaml`, and `*.json` under 1 MB.

## Web Research

`--web-search` supports `auto`, `on`, and `off`. Web evidence is logged separately and must not be treated as a user requirement unless explicitly classified.

In `auto` mode, web search is triggered when: the user request names an external library, SDK, API, or framework; version compatibility verification is needed; or the Blocking Question Detector identifies a question that depends on an external technical fact.

## Command Execution Guard

MAGI does not execute commands by default. With `--allow-command-execution`, only narrow non-destructive command categories are allowed, and every command result is logged to `execution/command_log.json`.
When command execution is enabled, guarded diagnostic commands may run during review rounds (for example, safe metadata or test-version checks), and each entry records command, working directory, exit code, stdout/stderr summaries, timestamp, and requesting agent.

## Critical Reports

If MAGI cannot reach unanimous PASS before the maximum review round, it writes:

```text
critical/CRITICAL_REPORT.ko.md
critical/FAILED_AGENT_SPEC_DRAFT.en.md
```

The report summarizes unresolved conflicts, failed sections, unsafe assumptions, blocking questions, attempted revisions, and evidence summaries without exposing hidden reasoning.

## Test Status

The repository test suite validates CLI flows, review policy, model-blind routing, provider adapter behavior, command execution guards, project scanning policy, web-search policy, artifact contracts, and acceptance smoke paths.
