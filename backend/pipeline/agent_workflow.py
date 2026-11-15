"""계획 모델이 지휘하는 영속 StateGraph 실행."""

from copy import deepcopy
from contextlib import nullcontext
import hashlib
import json
import re
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.errors import InvalidStateError
from backend.infrastructure.workflow_store import workflow_store, persistence_boundary
from backend.models import State, WorkflowState
from backend.pipeline.builder import _stage
from backend.pipeline.execution_policy import (
    StopReason, evaluate_execution, required_plan, stop_policy, stop_message, execution_diagnostic,
)
from backend.pipeline.planner import (
    execution_constraints, plan_next, task_signature,
)
from backend.services.failure_policy import journal_failure_category
from backend.services.review_transitions import COMPLETION_INVALIDATIONS, retry_upgrade_reason, failed_review_recovery_reason


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def task_id(state, name):
    identity = [state['run_id'],state.get('revision',0),len(state.get('plan_history',[])),name]
    if state.get("rubric_recoveries"):
        # 저널 재사용은 복구 이전과 이후 입력을 혼동하지 않아야 한다.
        identity.append(state["rubric_recoveries"][-1])
    if name in {"mcp_decide", "mcp_execute"}:
        identity.append(state.get("mcp", {}).get("round", 0))
    return digest(identity)


class AgentWorkflow:
    def __init__(self, engine, nodes, writer, evidence, on_progress=None):
        self.engine, self.nodes, self.writer, self.evidence = engine, nodes, writer, evidence
        self.progress = on_progress

    async def persist(self, stage, state):
        meter = self.engine.runtime.meter
        if meter is not None:
            (await meter.access.check_execution(meter.uid, meter.jid, meter.generation, meter.execution_id))
        with persistence_boundary("Workflow state could not be persisted."):
            # 2026-11-13: 근거 문서와 색인 입력을 함께 확정해 재시작 시 유실을 막는다.
            changed = getattr(self.writer, 'changed', None)
            previous_changed = dict(changed) if changed is not None else None
            previous_state = getattr(self.writer, 'state', None)
            try:
                async with self.writer.store.transaction():
                    (await self.writer.write_json("evidence/evidence_registry.json", self.evidence.to_dict()))
                    self.writer.state = State.from_dict(state).to_dict()
                    (await self.engine.runtime.commit(stage, self.writer.state))
            except BaseException:
                if previous_changed is not None:
                    self.writer.changed = previous_changed
                self.writer.state = previous_state
                raise

    async def durable(self, name, state, operation, *, projection_stage=None):
        ident = task_id(state,name)
        from backend.knowledge.runtime import INDEX_STAGES, index_stage
        effective_stage = index_stage(projection_stage or name)
        replay = ident == getattr(self, "replay_task_id", None)
        from backend.access.context import AccessError
        with persistence_boundary("Workflow journal could not be read.", passthrough=(InvalidStateError, AccessError)):
            saved = await self.journal.get(ident, retry_safe=name == "approve" or replay)
        from backend.services.rubric import POLICY_VERSION
        rubric_stage = effective_stage in {"planner", "spec_compile", "checklist_critic", "review_resolution", "compose_candidate"}
        if saved is not None and rubric_stage and saved.get("rubric_policy_version") != POLICY_VERSION:
            # 완료 결과만 새 정책으로 재검증한다. 저널 ID를 바꿔 미확정 호출 보호를 우회하지 않는다.
            saved = None
        if saved is not None:
            effective_stage = index_stage(saved.get('projection_stage', effective_stage))
            from backend.infrastructure.evidence_registry import EvidenceRegistry
            restored = EvidenceRegistry.from_dict(saved["evidence"])
            result = saved["result"]
            previous_changed = dict(self.writer.changed)
            previous_state = self.writer.state
            previous_evidence = getattr(self.evidence, 'items', None)
            runtime = getattr(self.engine, 'runtime', None)
            previous_retrieved = getattr(runtime, 'retrieved', None)
            try:
                # 2026-11-13: 재생으로 복원한 문서도 큐 접수와 함께 확정한다.
                with persistence_boundary("Workflow state could not be persisted."):
                    async with self.writer.store.transaction():
                        await self.writer.bind_versions(saved.get("documents", {}))
                        if saved.get('_prepared'):
                            staged = self.writer.restore_stage(saved.get('staged_documents', []))
                            await self.writer.flush_stage(staged)
                            await self.journal.complete(ident, {
                                'documents': {k: v for k, v in self.writer.changed.items() if k != 'state/provider_usage.json'},
                            })
                        self.evidence.items = restored.items
                        if "knowledge_context" in result and runtime is not None:
                            runtime.retrieved = result["knowledge_context"]
                        await self.persist(effective_stage, {**state, **result})
            except BaseException:
                self.writer.changed = previous_changed
                self.writer.state = previous_state
                self.evidence.items = previous_evidence
                if runtime is not None and 'knowledge_context' in result:
                    runtime.retrieved = previous_retrieved
                raise
        else:
            with persistence_boundary("Workflow journal could not be started."):
                (await self.journal.begin(ident))
            if replay:
                self.replay_task_id = None
            self.writer.changed = {}
            from backend.infrastructure.provider_call import WORKFLOW_MESSAGES
            recorded: dict[str, list[dict]] = {}
            token = WORKFLOW_MESSAGES.set(recorded)
            from backend.infrastructure.workflow_store import CURRENT_ATTEMPT
            attempt = {"journal": self.journal, "task_id": ident, "call_count": 0, "allow_replay": replay}
            attempt_token = CURRENT_ATTEMPT.set(attempt)
            staging = self.writer.stage_writes() if effective_stage in INDEX_STAGES and hasattr(self.writer, "stage_writes") else nullcontext(None)
            try:
                with staging as staged:
                    result = (await operation(deepcopy(state)))
            except Exception as exc:
                category = journal_failure_category(exc, attempt["call_count"])
                with persistence_boundary("Workflow journal progress could not be persisted."):
                    (await self.journal.progress(ident, attempt["call_count"], category=category))
                from protocol.logging import get_logger
                get_logger("backend.server").warning(
                    "workflow task failed stage=%s category=%s provider_entered=%s call_count=%s",
                    name, category, bool(attempt["call_count"]), attempt["call_count"],
                )
                if category in {"validation", "not_called"}:
                    # 반환된 결과의 검증 실패는 통신 완료 여부가 불명확한 오류와 구분한다.
                    with persistence_boundary("Workflow journal failure could not be persisted."):
                        (await self.journal.failed(ident))
                if category == "call_uncertain":
                    # 2026-11-05: 호출 기록은 미확정으로 보존하되 접근 거부 계약은 유지한다.
                    if isinstance(exc, AccessError):
                        raise
                    from backend.errors import WorkflowExecutionUncertain
                    raise WorkflowExecutionUncertain("External call completion is uncertain.") from exc
                raise
            finally:
                CURRENT_ATTEMPT.reset(attempt_token)
                WORKFLOW_MESSAGES.reset(token)
            result["task_messages"] = {**state.get("task_messages", {}), **recorded}
            payload = {"result": result, "evidence": self.evidence.to_dict(),
                       "projection_stage": effective_stage,
                       "rubric_policy_version": POLICY_VERSION if rubric_stage else None,
                       "documents": {k: v for k, v in self.writer.changed.items() if k != "state/provider_usage.json"},
                       "staged_documents": staged.history if staged is not None else []}
            with persistence_boundary("Workflow journal could not be prepared."):
                await self.journal.prepare(ident, payload)
            with persistence_boundary("Workflow journal could not be persisted.", passthrough=()):
                # 2026-11-13: 산출물, 완료 저널과 RAG 접수를 하나의 짧은 트랜잭션으로 확정한다.
                previous_changed = dict(self.writer.changed)
                previous_state = self.writer.state
                try:
                    async with self.writer.store.transaction():
                        if staged is not None:
                            await self.writer.flush_stage(staged)
                        await self.journal.complete(ident, {"result": result, "evidence": self.evidence.to_dict(),
                                                  "rubric_policy_version": POLICY_VERSION if rubric_stage else None,
                                                  "documents": {k:v for k,v in self.writer.changed.items() if k != "state/provider_usage.json"}})
                        await self.persist(effective_stage, {**state, **result})
                except BaseException:
                    self.writer.changed = previous_changed
                    self.writer.state = previous_state
                    raise
        return result

    async def prepare(self, state):
        from backend.services.execution_segment import prepare_segment

        result = prepare_segment(state)
        (await self.persist("input", {**state, **result}))
        return result

    async def recover_rubric(self, graph, config, current, reason):
        """2026-11-05: checkpoint 초안과 확정 입력으로 복구 지문을 고정한다."""
        ledger_path = "state/rubric_recoveries.json"
        with persistence_boundary("Workflow recovery ledger could not be read."):
            ledger = (await self.writer.read_json(ledger_path)) if (await self.writer.exists(ledger_path)) else {"fingerprints": []}
        fingerprints = ledger.get("fingerprints") if isinstance(ledger, dict) else None
        if (not isinstance(fingerprints, list) or any(not isinstance(x, str) or len(x) != 64
                or any(c not in "0123456789abcdef" for c in x) for x in fingerprints)):
            raise InvalidStateError("저장된 복구 기록을 확인할 수 없습니다.")
        current = {**current, "rubric_recoveries": list(dict.fromkeys([*current.get("rubric_recoveries", []), *fingerprints]))}
        sheet_data = current.get("requirement_lock_sheet")
        if not isinstance(sheet_data, dict):
            raise InvalidStateError("Review contract is invalid. Start a new generation.")
        from backend.models import RequirementLockSheet
        from backend.services.rubric import inputs as rubric_inputs, POLICY_VERSION
        sheet = RequirementLockSheet.from_dict(sheet_data).require_validated()
        _, input_hash = rubric_inputs(sheet, current)
        versions = current.get("document_versions", [])
        if versions:
            version_hash = versions[-1].get("hash")
            if not isinstance(version_hash, str):
                raise InvalidStateError("Reviewed candidate draft is missing.")
            spec = (await self.writer.read_text(f"draft_versions/{version_hash}.md"))
            if hashlib.sha256(spec.encode()).hexdigest() != version_hash:
                raise InvalidStateError("Reviewed candidate draft is missing.")
        else:
            spec = (await self.writer.read_text("draft/approval_candidate_spec.ko.md"))
        if not spec.strip():
            raise InvalidStateError("Reviewed candidate draft is missing.")
        fingerprint = digest([input_hash, hashlib.sha256(spec.encode()).hexdigest(), POLICY_VERSION, reason])
        from backend.services.execution_segment import prepare_segment
        recovery_state = {**current, "pending_input": {"action": "rubric_recovery",
                            "reason": reason, "fingerprint": fingerprint}}
        prepared = prepare_segment(cast(WorkflowState, recovery_state))
        with persistence_boundary("Workflow recovery checkpoint could not be persisted."):
            # checkpoint 실패 후에도 동일 복구를 다시 소비하지 않도록 지문을 먼저 보존한다.
            (await self.writer.write_json(ledger_path, {"version": 1, "fingerprints": prepared["rubric_recoveries"]}))
            (await self.persist("input", {**recovery_state, **prepared}))
            if versions:
                # 2026-11-13: 복구 초안의 공개와 색인 접수를 함께 확정하되 checkpoint 연결과 겹치지 않는다.
                previous_changed, previous_state = dict(self.writer.changed), self.writer.state
                try:
                    async with self.writer.store.transaction():
                        await self.writer.write_text("draft/approval_candidate_spec.ko.md", spec, overwrite=True)
                        await self.persist("spec_compile", {**recovery_state, **prepared})
                except BaseException:
                    self.writer.changed, self.writer.state = previous_changed, previous_state
                    raise
            (await graph.aupdate_state(config, {**current, **prepared}, as_node="prepare"))

    async def planner(self, state):
        safety_limit = state.get("remaining_steps", 128) <= 3
        forced = None if safety_limit else required_plan(state, evaluate_execution(state, self.engine.config))
        if safety_limit:
            forced = {**state.get("plan", {}), "goal": "실행 안전 한도",
                      "action": "blocked", "stop_reason": StopReason.EXECUTION_LIMIT.value}
        state = {**state, "execution_constraints": execution_constraints(state, self.engine.config)}
        from backend.pipeline.builder import _progress
        (await _progress(self.progress, "planner", "started"))
        try:
            async def select_plan(current):
                return {"plan": await plan_next(current, self.nodes)}
            plan = forced or (await self.durable("planner", state, select_plan))["plan"]
        except Exception as exc:
            from backend.server.diagnostics import diagnose_exception
            (await _progress(self.progress, "planner", "failed", {"diagnostic": diagnose_exception(exc)}))
            raise
        history = [*state.get("plan_history", []), {**plan, "revision": state.get("revision", 0)}]
        result = {"plan": plan, "plan_history": history, "allowed_actions": [],
                  "execution_constraints": state["execution_constraints"]}
        if plan.get("action") in {"interview", "ask_user"} and state.get("mcp", {}).get("snapshot"):
            result["mcp"] = {"snapshot": state["mcp"]["snapshot"], "round": 0, "results": []}
        (await self.persist("planner", {**state, **result}))
        (await _progress(self.progress, "planner", "completed", {"plan": plan}))
        return result

    async def mcp_decide(self, state):
        """2026-11-03: 판단과 외부 호출을 분리해 각각 독립 복구 경계를 둔다."""
        from backend.mcp_client.service import MCPService
        from backend.mcp_client.workflow import interview_messages, model_messages, native_tools
        from backend.mcp_client.security import validate_arguments
        from backend.models import InterviewResponse
        from backend.infrastructure.prompt_context import prepare_context
        from backend.infrastructure.provider_call import _complete_once
        from backend.infrastructure.output_language import language_issues, OutputLanguageError

        async def operation(current):
            info = current.get("mcp", {})
            owner = self.engine.runtime.job.get("owner_id")
            available = (await MCPService(self.writer.store).available(owner, info.get("snapshot", []))) if owner else []
            if not available and not info.get("results") and not info.get("pending_tool_results"):
                return {"mcp": {**info, "bypass": True}}
            messages = (await interview_messages(self.nodes, self.writer, current))
            projected, references = (await prepare_context(self.writer, messages, "interview"))
            may_call = info.get("round", 0) < 3
            projected = model_messages(projected, available, info.get("results", []), allow_tools=may_call)
            definitions, mapping = native_tools(available if may_call else [])
            # 2026-11-07: 서버 대화에 도구 호출은 이미 있으므로 결과만 한 번 이어 붙인다.
            last = (info.get("results") or [None])[-1]
            tool_result = info.get("pending_tool_results")
            if tool_result is None and isinstance(last, dict) and last.get("tool_call_id"):
                tool_result = [{"call_id": last["tool_call_id"], "content": json.dumps(
                    {"status": last.get("status"), "text": last.get("text", "")}, ensure_ascii=False)}]
            choice = (await _complete_once(self.writer, self.nodes.provider, projected,
                model=self.nodes.config.model_routing["interviewer"].model, stage="interview",
                isolated_schema=InterviewResponse, tools=definitions,
                tool_choice="auto" if definitions else "none", tool_result=tool_result,
                return_completion=True))
            calls = choice.tool_calls
            if not isinstance(calls, list):
                raise InvalidStateError("도구 응답을 확인할 수 없습니다.")
            updated = {key: value for key, value in info.items() if key != "pending_tool_results"}
            if not calls:
                if not isinstance(choice.parsed, InterviewResponse):
                    raise InvalidStateError("인터뷰 결과를 확인할 수 없습니다.")
                answer = references.restore(choice.parsed)
                issues = language_issues(answer)
                if issues:
                    raise OutputLanguageError(issues)
                return {"mcp": {**updated, "response": answer.model_dump(), "bypass": False}}
            call_ids = [item.get("id") for item in calls if isinstance(item, dict)]
            if (len(call_ids) != len(calls) or any(not isinstance(item, str) or
                    not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item) for item in call_ids)
                    or len(set(call_ids)) != len(call_ids)):
                raise InvalidStateError("도구 호출 식별자를 확인할 수 없어 대화를 재개할 수 없습니다.")
            def reject_calls():
                # 2026-11-07: 거부된 호출에도 대응하는 결과를 남겨 원격 대화를 이어갈 수 있다.
                if info.get("round", 0) > 3:
                    raise InvalidStateError("도구 호출 한도를 초과했습니다.")
                return {"mcp": {**updated, "request": {"rejected_call_ids": call_ids}}}
            if len(calls) != 1 or not may_call or choice.parsed is not None:
                return reject_calls()
            call = calls[0]
            call_id, name, arguments = call.get("id"), call.get("name"), call.get("args")
            selected = mapping.get(name) if isinstance(name, str) else None
            if selected is None:
                return reject_calls()
            try:
                validate_arguments(selected[1]["schema"], arguments)
                encoded = json.dumps(arguments, ensure_ascii=False)
            except (ValueError, TypeError, RecursionError):
                return reject_calls()
            return {"mcp": {**updated, "request": {"connection_id": selected[0]["id"],
                    "tool_name": selected[1]["name"], "arguments_json": encoded, "tool_call_id": call_id}}}

        return (await self.durable("mcp_decide", state, operation))

    async def mcp_execute(self, state):
        from backend.infrastructure.workflow_store import provider_entered
        from backend.mcp_client.service import MCPService
        from backend.mcp_client.security import MCPValidationError, validate_arguments

        async def operation(current):
            info = current.get("mcp", {})
            request = info.get("request", {})
            if "rejected_call_ids" in request:
                pending = [{"call_id": call_id, "content": "허용되지 않은 도구 요청을 실행하지 않았습니다."}
                           for call_id in request["rejected_call_ids"]]
                return {"mcp": {**{key: value for key, value in info.items() if key != "request"},
                                "pending_tool_results": pending, "round": info.get("round", 0) + 1}}
            owner = self.engine.runtime.job.get("owner_id")
            service = MCPService(self.writer.store)
            available = (await service.available(owner, info.get("snapshot", []))) if owner else []
            selected = next(((row, tool) for row, tool in available if row["id"] == request.get("connection_id")
                             and tool["name"] == request.get("tool_name")), None)
            try:
                raw = request.get("arguments_json", "")
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384 or selected is None:
                    raise MCPValidationError("허용된 도구와 입력을 확인하세요.")
                arguments = json.loads(raw)
                validate_arguments(selected[1]["schema"], arguments)
            except (ValueError, TypeError, RecursionError):
                result = {"status": "invalid", "text": "도구 입력 또는 허용 상태를 확인할 수 없습니다."}
            else:
                argument_hash = digest(arguments)
                previous = (await self.writer.read_json("research/mcp_results.json")).get("results", []) if (await self.writer.exists("research/mcp_results.json")) else []
                cached = next((item for item in previous if item.get("connection_id") == request["connection_id"]
                               and item.get("tool_name") == request["tool_name"] and item.get("arguments_hash") == argument_hash
                               and item.get("schema_hash") == selected[1]["schema_hash"] and item.get("connection_version") == selected[0]["version"]
                               and item.get("status") == "ok"), None)
                if cached is None:
                    # 네트워크 호출의 불확실성은 모델 호출과 별도 저널 경계로 기록한다.
                    (await provider_entered())
                    result = (await service.invoke(owner, info.get("snapshot", []), request["connection_id"], request["tool_name"], arguments))
                else:
                    result = {"status": cached["status"], "text": cached["text"]}
            entry = {"connection_id": request.get("connection_id"), "tool_name": request.get("tool_name"), **result}
            if isinstance(request.get("tool_call_id"), str):
                entry["tool_call_id"] = request["tool_call_id"]
            if selected is not None and result.get("status") != "invalid":
                entry.update(arguments_hash=argument_hash, schema_hash=selected[1]["schema_hash"], connection_version=selected[0]["version"])
            results = [*info.get("results", []), entry]
            saved = (await self.writer.read_json("research/mcp_results.json")).get("results", []) if (await self.writer.exists("research/mcp_results.json")) else []
            if entry not in saved:
                saved.append(entry)
            (await self.writer.write_json("research/mcp_results.json", {"results": saved}))
            if result.get("status") == "ok":
                self.evidence.add("MCP_SOURCE", "외부 도구 결과", request.get("connection_id", ""),
                                  metadata={"tool": request.get("tool_name", "")})
            next_info = {key: value for key, value in {**info, "results": results, "round": info.get("round", 0) + 1}.items() if key != "request"}
            if entry.get("tool_call_id"):
                next_info["pending_tool_results"] = [{"call_id": entry["tool_call_id"], "content": json.dumps(
                    {"status": result.get("status"), "text": result.get("text", "")}, ensure_ascii=False)}]
            return {"mcp": next_info}

        return (await self.durable("mcp_execute", state, operation))

    async def blocked(self, state, reason=None, stop_reason=None):
        stop_reason = stop_reason or state.get("plan", {}).get("stop_reason") or StopReason.MODEL_BLOCKED.value
        policy = stop_policy(stop_reason)
        if state.get("blocking_questions") and policy.allow_questions:
            return (await self.ask(state))
        reason = stop_message(policy, reason or state.get("plan", {}).get("reason") or "추가 확인이 필요합니다.")
        result = {"status": "CRITICAL_BLOCKED", "wait_reason": reason,
                  "stop_reason": str(stop_reason),
                  "execution_diagnostic": execution_diagnostic(state, self.engine.config, stop_reason),
                  "allowed_actions": ["message", "revise", "retry"],
                  "plan": {**state.get("plan", {}), "action": "blocked", "reason": reason}}
        if policy.create_report and state.get("requirement_lock_sheet") and state.get("structured_issues"):
            report = (await self.durable("critical_report", {**state, **result}, self.nodes.critical_report))
            result.update(report)
        (await self.persist("blocked", {**state, **result}))
        return {**state, **result}

    async def execute(self, state):
        action = state["plan"]["action"]
        constraints = execution_constraints(state, self.engine.config)
        decision = evaluate_execution(state, self.engine.config)
        if action in constraints["repeated_actions"] and action != decision.required_action:
            # 오래된 계획 재개에서도 같은 작업을 반복하지 않고 모델에 재계획을 맡긴다.
            result = {"execution_constraints": constraints, "allowed_actions": []}
            (await self.persist("replan", {**state, **result}))
            return result
        if action not in decision.allowed_actions:
            raise InvalidStateError("현재 상태에서 실행할 수 없는 계획입니다.")
        signature = task_signature(state, action)
        recent = state.get("task_results", [])
        if action == "knowledge_search":
            async def operation(current):
                runtime = self.engine.runtime
                if runtime:
                    query = current["plan"].get("target") or current.get("revision_feedback") or current["user_request"]
                    (await runtime.refresh(query[:20000]))
                return {"knowledge_context": runtime.retrieved if runtime else {}}
        else:
            stage_operation = _stage("requirement_lock" if action == "requirement_lock_stage" else action,
                getattr(self.nodes, action),
                self.progress, defer_completed=True)
            async def operation(current):
                # 2026-11-13: 후보 복원도 최종 단계 결과와 함께 확정되어야 이전 색인과 어긋나지 않는다.
                if action in {"checklist_critic", "review_resolution", "compose_candidate"}:
                    versions = current.get("document_versions", [])
                    if versions:
                        version_hash = versions[-1]["hash"]
                        content = await self.writer.read_text(f"draft_versions/{version_hash}.md")
                        if hashlib.sha256(content.encode()).hexdigest() != version_hash:
                            raise InvalidStateError("명세 버전의 내용을 확인할 수 없습니다.")
                        await self.writer.write_text("draft/approval_candidate_spec.ko.md", content, overwrite=True)
                return await stage_operation(current)
        result = (await self.durable(action, state, operation))
        done = list(dict.fromkeys([*state.get("completed_tasks", []), action]))
        done = [name for name in done if name not in COMPLETION_INVALIDATIONS.get(action, frozenset())]
        versions = list(state.get("document_versions", []))
        if action == "spec_compile":
            from backend.application.execution_history import ExecutionHistory
            history = (await ExecutionHistory(self.writer).graph())
            step: dict = next((item for item in reversed(history.get("nodes", [])) if item.get("stage") == "spec_compile"), {})
            versions.append({"revision": state.get("revision", 0), "hash": (await self._candidate_hash()),
                             "step_id": step.get("id"),
                             "requirements_hash": digest(state.get("requirement_lock_sheet")),
                             "input_refs": state["plan"].get("input_refs", [])})
            (await self.writer.write_text(f"draft_versions/{(await self._candidate_hash())}.md",
                                   (await self.writer.read_text("draft/approval_candidate_spec.ko.md")), overwrite=True))
        result.update(completed_tasks=done, document_versions=versions,
                      task_results=[*recent, {"action": action, "revision": state.get("revision", 0),
                          "segment": state.get("execution_segment"),
                          "signature": signature, "result_hash": digest(result),
                          "reason": state["plan"]["reason"], "status": "completed"}])
        if action == "compose_candidate":
            # 최고점 복원 후 최신 버전 참조도 선택된 초안에 맞춘다.
            chosen = (await self._candidate_hash())
            (await self.writer.write_text(f"draft_versions/{chosen}.md", (await self.writer.read_text("draft/approval_candidate_spec.ko.md")), overwrite=True))
            result["document_versions"] = [*versions, {"revision": state.get("revision", 0), "hash": chosen}]
            result.update(candidate_hash=(await self._candidate_hash()), wait_reason="검토를 마친 명세를 승인하거나 수정해주세요.",
                          allowed_actions=["approve", "message", "revise", "retry"])
        (await self.persist("requirement_lock" if action == "requirement_lock_stage" else action, {**state, **result}))
        if action != "knowledge_search":
            # 2026-11-05: 완료 표시는 저널과 재개 상태가 보존된 뒤에만 확정한다.
            from backend.pipeline.builder import _progress
            (await _progress(self.progress, "requirement_lock" if action == "requirement_lock_stage" else action,
                      "completed", result, state))
        return result

    async def ask(self, state):
        completed_assessment = None
        if not state.get("blocking_questions"):
            constraints = execution_constraints(state, self.engine.config)
            if "ask_user" in constraints["repeated_actions"]:
                result = {"execution_constraints": constraints, "allowed_actions": []}
                (await self.persist("replan", {**state, **result}))
                return result
            review = bool(state.get("requirement_lock_sheet") and any(
                item.get("status") != "resolved" and (
                    item.get("severity") in {"blocking", "major"}
                    or item.get("resolution_kind") == "user_decision" or item.get("decision_answer_id")
                ) for item in state.get("structured_issues", [])
            ))
            stage = "review_resolution" if review else "interview"
            operation = (lambda current: self.nodes.review_resolution(current, final=True)) if review else self.nodes.interview
            # 질문 생성은 별도 저널에 기록해 실패 후 재개 시 호출 중복을 막는다.
            assessment = (await self.durable("ask", state, _stage(stage, operation, self.progress, defer_completed=True), projection_stage=stage))
            result = {**assessment, "allowed_actions": [], "task_results": [*state.get("task_results", []), {
                "action": "ask_user", "revision": state.get("revision", 0),
                "segment": state.get("execution_segment"), "signature": task_signature(state, "ask_user"),
                "result_hash": digest(assessment), "reason": state.get("plan", {}).get("reason", ""),
                "status": "completed" if assessment.get("blocking_questions") else "no_questions",
            }]}
            state = {**state, **result}
            completed_assessment = (stage, assessment)
            if not state.get("blocking_questions"):
                (await self.persist("question_assessment", state))
                from backend.pipeline.builder import _progress
                (await _progress(self.progress, stage, "completed", assessment, state))
                return result
        result = {**self.nodes.await_user(state), "allowed_actions": ["answer", "message", "revise"],
                  "plan": {**state.get("plan", {}), "action": "ask_user"}, "stop_reason": "",
                  "wait_reason": "미확정 요구사항에 대한 답변이나 수정 의견이 필요합니다."}
        (await self.persist("await_user", {**state, **result}))
        if completed_assessment:
            from backend.pipeline.builder import _progress
            (await _progress(self.progress, completed_assessment[0], "completed", completed_assessment[1], state))
        return {**state, **result}

    async def wait(self, state) -> Command[Literal["prepare", "finalize"]]:
        # 이 노드는 재개 시 처음부터 실행되므로 영속 쓰기와 외부 호출을 하지 않는다.
        value = interrupt({"reason": state.get("wait_reason", ""),
                           "allowed_actions": state.get("allowed_actions", []),
                           "revision": state.get("revision", 0)})
        action = value.get("action") if isinstance(value, dict) else None
        from backend.services.refinement import needs_upgrade
        upgrade_retry = action == "retry" and needs_upgrade(state)
        if action not in state.get("allowed_actions", []) and not upgrade_retry:
            raise InvalidStateError("현재 대기 상태에 맞지 않는 입력입니다.")
        if action == "approve":
            incoming = value.get("state", {})
            return Command(update={"pending_input": {"action": action},
                "approval_acceptance": incoming.get("approval_acceptance", {})}, goto="finalize")
        incoming = value.get("state")
        if not isinstance(incoming, dict) or incoming.get("run_id") != state["run_id"]:
            raise InvalidStateError("재개 입력의 작업을 확인할 수 없습니다.")
        return Command(update={**incoming, "pending_input": {
            "action": action, "origin_reason": state.get("awaiting_input_reason")}}, goto="prepare")

    async def finalize(self, state):
        if (await self._candidate_hash()) != state.get("candidate_hash"):
            raise InvalidStateError("승인 후보가 변경되었습니다. 다시 검토해야 합니다.")
        async def operation(current):
            return (await self.engine.finalize(current))
        result = (await self.durable("approve", state, operation))
        return {**result, "allowed_actions": ["message", "revise"], "wait_reason": ""}

    async def _candidate_hash(self):
        name = "draft/approval_candidate_spec.ko.md"
        return hashlib.sha256((await self.writer.read_text(name)).encode()).hexdigest() if (await self.writer.exists(name)) else ""

    def build(self, saver):
        graph = StateGraph(WorkflowState)
        for name in ("prepare", "planner", "execute", "ask", "blocked", "wait", "finalize", "mcp_decide", "mcp_execute"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges("prepare", lambda state: "ask" if state.get("blocking_questions") else "planner")
        def route_plan(state):
            action = state["plan"]["action"]
            review = bool(state.get("requirement_lock_sheet") and any(
                item.get("status") != "resolved" and (item.get("severity") in {"blocking", "major"}
                    or item.get("resolution_kind") == "user_decision" or item.get("decision_answer_id"))
                for item in state.get("structured_issues", [])))
            if (state.get("mcp", {}).get("snapshot") and not state.get("blocking_questions")
                    and (action == "interview" or (action == "ask_user" and not review))):
                return "mcp_decide"
            return {"ask_user": "ask", "blocked": "blocked"}.get(action, "execute")
        graph.add_conditional_edges("planner", route_plan)
        graph.add_conditional_edges("mcp_decide", lambda state:
            "mcp_execute" if state.get("mcp", {}).get("request") else
            "ask" if state.get("plan", {}).get("action") == "ask_user" else "execute")
        graph.add_edge("mcp_execute", "mcp_decide")
        graph.add_conditional_edges("execute", lambda state: "wait" if state.get("allowed_actions") else "planner")
        graph.add_conditional_edges("ask", lambda state: "wait" if state.get("allowed_actions") else "planner")
        graph.add_edge("blocked", "wait")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=saver)

    async def run(self, state, *, action="generate", replay_pending=False):
        if state.workflow_schema != 1:
            raise InvalidStateError("지원하지 않는 실행 상태 버전입니다. 원본은 보존됩니다.")
        thread_id = self.writer.job_id
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 128}
        async with workflow_store(self.writer.store, thread_id) as (saver, journal):
            self.journal = journal
            graph = self.build(saver)
            snapshot = (await graph.aget_state(config))
            self.replay_task_id = None
            if action == "retry":
                from backend.infrastructure.workflow_store import retry_state
                recovery = (await retry_state(self.writer))
                if not recovery["can_retry"] or (recovery["retry_requires_replay"] and not replay_pending):
                    raise InvalidStateError("미완료 단계 재실행에는 명시적인 동의가 필요합니다." if recovery["retry_requires_replay"] else recovery["retry_unavailable_reason"])
                if recovery["retry_requires_replay"]:
                    self.replay_task_id = recovery["task_id"]
            if not snapshot.values and action != "generate":
                raise InvalidStateError("저장된 그래프 상태를 찾을 수 없습니다. 실행 DB와 checkpoint 백업을 확인해주세요.")
            incoming = state.to_workflow_state()
            from backend.services.rubric import POLICY_VERSION
            old_policy = snapshot.values.get("rubric", {}).get("policy_version")
            upgrade_reason = retry_upgrade_reason(action, old_policy, POLICY_VERSION,
                recovery["retry_requires_replay"] if action == "retry" else False, bool(snapshot.next))
            if upgrade_reason:
                # 미확정 호출은 위의 원래 재실행 보호를 유지한다. 완료 여부가 확정된 구형 단계만 새 평가로 전환한다.
                (await self.recover_rubric(graph, config, dict(snapshot.values), upgrade_reason))
                inputs: Command | dict | None = None
            elif snapshot.values and snapshot.next:
                if any(task.interrupts for task in snapshot.tasks):
                    resume_action = "revise" if action == "revise" else action
                    inputs = Command(resume={"action": resume_action, "state": incoming})
                elif action == "retry" or (action == "approve" and snapshot.next == ("finalize",)):
                    # 실패 복구에는 새 입력 대신 None으로 저장된 실행을 이어간다.
                    inputs = None
                elif action in {"revise", "message"}:
                    # 실패한 실행에 명시적인 수정 입력으로 새 계획을 적용한다.
                    incoming.update((await self.prepare({**incoming, "pending_input": {"action": action}})))
                    (await graph.aupdate_state(config, incoming, as_node="prepare"))
                    inputs = None
                else:
                    raise InvalidStateError("중단된 실행을 먼저 재개해주세요.")
            else:
                if snapshot.values:
                    incoming = {**snapshot.values, **incoming}
                incoming["pending_input"] = {"action": action}
                inputs = incoming
            try:
                (await graph.ainvoke(inputs, config=config, durability="sync"))
            except Exception as exc:
                reason = failed_review_recovery_reason(exc)
                if reason is None:
                    raise
                (await self.recover_rubric(graph, config, dict((await graph.aget_state(config)).values), reason))
                (await graph.ainvoke(None, config=config, durability="sync"))
            final = State.from_workflow_state((await graph.aget_state(config)).values)
            (await self.persist("state", final.to_dict()))
            return final
