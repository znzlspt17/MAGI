"""계획 모델이 지휘하는 영속 StateGraph 실행."""

from copy import deepcopy
import hashlib
import json
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.errors import InvalidStateError
from backend.infrastructure.workflow_store import workflow_store
from backend.models import State, WorkflowState
from backend.pipeline.builder import _stage
from backend.pipeline.planner import (
    DECISION_STEP_RESERVE, EXECUTION_STEP_LIMIT, allowed_tasks,
    execution_constraints, plan_next, task_signature,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def task_id(state, name):
    return digest([state['run_id'],state.get('revision',0),len(state.get('plan_history',[])),name])


class AgentWorkflow:
    def __init__(self, engine, nodes, writer, evidence, on_progress=None):
        self.engine, self.nodes, self.writer, self.evidence = engine, nodes, writer, evidence
        self.progress = on_progress

    def persist(self, stage, state):
        meter = self.engine.runtime.meter
        if meter is not None:
            meter.access.check_execution(meter.uid, meter.jid, meter.generation, meter.execution_id)
        self.writer.write_json("evidence/evidence_registry.json", self.evidence.to_dict())
        self.writer.state = State.from_dict(state).to_dict()
        self.engine.runtime.commit(stage, self.writer.state)

    def durable(self, name, state, operation):
        ident = task_id(state,name)
        replay = ident == getattr(self, "replay_task_id", None)
        saved = self.journal.get(ident, retry_safe=name == "approve" or replay)
        if saved is not None:
            self.writer.bind_versions(saved.get("documents", {}))
            from backend.infrastructure.evidence_registry import EvidenceRegistry
            restored = EvidenceRegistry.from_dict(saved["evidence"])
            self.evidence.items = restored.items
            result = saved["result"]
            if "knowledge_context" in result:
                self.engine.runtime.retrieved = result["knowledge_context"]
        else:
            self.journal.begin(ident)
            if replay:
                self.replay_task_id = None
            self.writer.changed = {}
            from backend.infrastructure.provider_call import WORKFLOW_MESSAGES
            recorded = {}
            token = WORKFLOW_MESSAGES.set(recorded)
            from backend.infrastructure.workflow_store import CURRENT_ATTEMPT
            attempt = {"journal": self.journal, "task_id": ident, "call_count": 0}
            attempt_token = CURRENT_ATTEMPT.set(attempt)
            try:
                result = operation(deepcopy(state))
            except Exception as exc:
                from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError
                from backend.infrastructure.output_language import OutputLanguageError
                category = "validation" if isinstance(exc, (RequirementNormalizationError, ReviewValidationError, SpecCompilationError, OutputLanguageError)) else "not_called" if not attempt["call_count"] else "call_uncertain"
                self.journal.progress(ident, attempt["call_count"], category=category)
                import logging
                logging.getLogger("backend.server").warning(
                    "workflow task failed stage=%s category=%s provider_entered=%s call_count=%s",
                    name, category, bool(attempt["call_count"]), attempt["call_count"],
                )
                if category in {"validation", "not_called"}:
                    # 반환된 결과의 검증 실패는 통신 완료 여부가 불명확한 오류와 구분한다.
                    self.journal.failed(ident)
                raise
            finally:
                CURRENT_ATTEMPT.reset(attempt_token)
                WORKFLOW_MESSAGES.reset(token)
            result["task_messages"] = {**state.get("task_messages", {}), **recorded}
            self.journal.complete(ident, {"result": result, "evidence": self.evidence.to_dict(),
                                          "documents": {k:v for k,v in self.writer.changed.items() if k != "state/provider_usage.json"}})
        self.persist(name, {**state, **result})
        return result

    def prepare(self, state):
        action = state.get("pending_input", {}).get("action", "generate")
        done = list(state.get("completed_tasks", []))
        revision = state.get("revision", 0)
        if action in {"answer", "revise", "message"}:
            revision += 1
            # 변경 영향을 확정할 수 없는 입력은 생성물을 보수적으로 재검증한다.
            preserved = {"project_context", "knowledge_search", "web_research"}
            if action == "answer" and state.get("pending_input", {}).get("origin_reason") == "review":
                preserved.add("interview")
            done = [name for name in done if name in preserved]
        result = {"workflow_schema": 1, "revision": revision, "completed_tasks": done,
                  "segment_steps": 0, "allowed_actions": [], "pending_input": {},
                  "execution_constraints": {},
                  "execution_segment": state.get("execution_segment", 0) + 1,
                  "wait_reason": "", "stop_reason": ""}
        if action == "retry":
            result.update(critic_pass_count=0, resolution_stop=False, diagnosed_keys=[])
        if action in {"answer", "revise", "message"}:
            result.update(candidate_hash="", user_approval_status="PENDING", critical_report=None)
            reused = [{"action": name, "revision": revision, "status": "reused",
                       "reason": "새 입력의 영향을 받지 않는 이전 자료를 재사용합니다."} for name in done]
            result["task_results"] = [*state.get("task_results", []), *reused]
        self.persist("input", {**state, **result})
        return result

    def planner(self, state):
        if state.get("blocking_questions"):
            return {"plan": {**state.get("plan", {}), "action": "ask_user"}, "allowed_actions": []}
        if state.get("segment_steps", 0) >= EXECUTION_STEP_LIMIT + DECISION_STEP_RESERVE:
            return {"plan": {**state.get("plan", {}), "action": "blocked", "stop_reason": "execution_limit",
                             "reason": "자동 실행 한도에 도달했습니다."}, "allowed_actions": []}
        state = {**state, "execution_constraints": execution_constraints(state, self.engine.config)}
        from backend.pipeline.builder import _progress
        _progress(self.progress, "planner", "started")
        plan = self.durable("planner", state, lambda current: {"plan": plan_next(current, self.nodes)})["plan"]
        history = [*state.get("plan_history", []), {**plan, "revision": state.get("revision", 0)}]
        result = {"plan": plan, "plan_history": history, "allowed_actions": [],
                  "execution_constraints": state["execution_constraints"],
                  "segment_steps": state.get("segment_steps", 0) + 1}
        self.persist("planner", {**state, **result})
        _progress(self.progress, "planner", "completed")
        return result

    def blocked(self, state, reason=None, stop_reason=None):
        if state.get("blocking_questions"):
            return self.ask(state)
        stop_reason = stop_reason or state.get("plan", {}).get("stop_reason") or "model_blocked"
        reason = reason or state.get("plan", {}).get("reason") or "추가 확인이 필요합니다."
        label = {"repair_limit": "자동 보완 한계", "no_progress": "진전 없는 반복",
                 "execution_limit": "자동 실행 한도", "invalid_plan": "유효한 계획 생성 실패"}.get(stop_reason, "진행 중단")
        if not reason.startswith(label + " · "):
            reason = label + " · " + reason
        reason += " 남은 문제와 보완 내역을 확인하고 수정 의견을 보내거나 저장된 결과로 추가 실행해주세요. 같은 문제가 남을 수 있습니다."
        result = {"status": "CRITICAL_BLOCKED", "wait_reason": reason,
                  "stop_reason": stop_reason,
                  "allowed_actions": ["message", "revise", "retry"],
                  "plan": {**state.get("plan", {}), "action": "blocked", "reason": reason}}
        if state.get("requirement_lock_sheet") and state.get("structured_issues"):
            report = self.durable("critical_report", {**state, **result}, self.nodes.critical_report)
            result.update(report)
        self.persist("blocked", {**state, **result})
        return {**state, **result}

    def execute(self, state):
        action = state["plan"]["action"]
        constraints = execution_constraints(state, self.engine.config)
        if action in constraints["repeated_actions"]:
            # 오래된 계획 재개에서도 같은 작업을 반복하지 않고 모델에 재계획을 맡긴다.
            result = {"execution_constraints": constraints, "allowed_actions": []}
            self.persist("replan", {**state, **result})
            return result
        if action not in allowed_tasks(state, self.engine.config):
            raise InvalidStateError("현재 상태에서 실행할 수 없는 계획입니다.")
        signature = task_signature(state, action)
        recent = state.get("task_results", [])
        if action == "knowledge_search":
            def operation(current):
                runtime = self.engine.runtime
                if runtime:
                    query = current["plan"].get("target") or current.get("revision_feedback") or current["user_request"]
                    runtime.refresh(query[:20000])
                return {"knowledge_context": runtime.retrieved if runtime else {}}
        else:
            if action in {"checklist_critic", "review_resolution", "compose_candidate"}:
                versions = state.get("document_versions", [])
                if versions:
                    version_hash = versions[-1]["hash"]
                    content = self.writer.read_text(f"draft_versions/{version_hash}.md")
                    if hashlib.sha256(content.encode()).hexdigest() != version_hash:
                        raise InvalidStateError("명세 버전의 내용을 확인할 수 없습니다.")
                    self.writer.write_text("draft/approval_candidate_spec.en.md", content, overwrite=True)
            operation = _stage("requirement_lock" if action == "requirement_lock_stage" else action,
                getattr(self.nodes, action),
                self.progress)
        result = self.durable(action, state, operation)
        done = list(dict.fromkeys([*state.get("completed_tasks", []), action]))
        invalidates = {
            "interview": {"requirement_lock_stage", "spec_compile", "checklist_critic", "review_resolution", "compose_candidate"},
            "requirement_lock_stage": {"spec_compile", "checklist_critic", "review_resolution", "compose_candidate"},
            "checklist_critic": {"review_resolution", "compose_candidate"},
        }
        done = [name for name in done if name not in invalidates.get(action, set())]
        if action == "spec_compile":
            done = [name for name in done if name not in {"checklist_critic", "review_resolution", "compose_candidate"}]
        versions = list(state.get("document_versions", []))
        if action == "spec_compile":
            from backend.server.execution_history import ExecutionHistory
            history = ExecutionHistory(self.writer).graph()
            step = next((item for item in reversed(history.get("nodes", [])) if item.get("stage") == "spec_compile"), {})
            versions.append({"revision": state.get("revision", 0), "hash": self._candidate_hash(),
                             "step_id": step.get("id"),
                             "requirements_hash": digest(state.get("requirement_lock_sheet")),
                             "input_refs": state["plan"].get("input_refs", [])})
            self.writer.write_text(f"draft_versions/{self._candidate_hash()}.md",
                                   self.writer.read_text("draft/approval_candidate_spec.en.md"), overwrite=True)
        result.update(completed_tasks=done, document_versions=versions,
                      task_results=[*recent, {"action": action, "revision": state.get("revision", 0),
                          "segment": state.get("execution_segment"),
                          "signature": signature, "result_hash": digest(result),
                          "reason": state["plan"]["reason"], "status": "completed"}])
        if action == "compose_candidate":
            result.update(candidate_hash=self._candidate_hash(), wait_reason="검토를 마친 명세를 승인하거나 수정해주세요.",
                          allowed_actions=["approve", "message", "revise"])
        self.persist("requirement_lock" if action == "requirement_lock_stage" else action, {**state, **result})
        return result

    def ask(self, state):
        if not state.get("blocking_questions"):
            constraints = execution_constraints(state, self.engine.config)
            if "ask_user" in constraints["repeated_actions"]:
                result = {"execution_constraints": constraints, "allowed_actions": []}
                self.persist("replan", {**state, **result})
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
            assessment = self.durable("ask", state, _stage(stage, operation, self.progress))
            result = {**assessment, "allowed_actions": [], "task_results": [*state.get("task_results", []), {
                "action": "ask_user", "revision": state.get("revision", 0),
                "segment": state.get("execution_segment"), "signature": task_signature(state, "ask_user"),
                "result_hash": digest(assessment), "reason": state.get("plan", {}).get("reason", ""),
                "status": "completed" if assessment.get("blocking_questions") else "no_questions",
            }]}
            state = {**state, **result}
            if not state.get("blocking_questions"):
                self.persist("question_assessment", state)
                return result
        result = {**self.nodes.await_user(state), "allowed_actions": ["answer", "message", "revise"],
                  "plan": {**state.get("plan", {}), "action": "ask_user"}, "stop_reason": "",
                  "wait_reason": "미확정 요구사항에 대한 답변이나 수정 의견이 필요합니다."}
        self.persist("await_user", {**state, **result})
        return {**state, **result}

    def wait(self, state) -> Command[Literal["prepare", "finalize"]]:
        # 이 노드는 재개 시 처음부터 실행되므로 영속 쓰기와 외부 호출을 하지 않는다.
        value = interrupt({"reason": state.get("wait_reason", ""),
                           "allowed_actions": state.get("allowed_actions", []),
                           "revision": state.get("revision", 0)})
        action = value.get("action") if isinstance(value, dict) else None
        if action not in state.get("allowed_actions", []):
            raise InvalidStateError("현재 대기 상태에 맞지 않는 입력입니다.")
        if action == "approve":
            return Command(update={"pending_input": {"action": action}}, goto="finalize")
        incoming = value.get("state")
        if not isinstance(incoming, dict) or incoming.get("run_id") != state["run_id"]:
            raise InvalidStateError("재개 입력의 작업을 확인할 수 없습니다.")
        return Command(update={**incoming, "pending_input": {
            "action": action, "origin_reason": state.get("awaiting_input_reason")}}, goto="prepare")

    def finalize(self, state):
        if self._candidate_hash() != state.get("candidate_hash"):
            raise InvalidStateError("승인 후보가 변경되었습니다. 다시 검토해야 합니다.")
        def operation(current):
            return self.engine.finalize(current)
        result = self.durable("approve", state, operation)
        return {**result, "allowed_actions": ["message", "revise"], "wait_reason": ""}

    def _candidate_hash(self):
        name = "draft/approval_candidate_spec.en.md"
        return hashlib.sha256(self.writer.read_text(name).encode()).hexdigest() if self.writer.exists(name) else ""

    def build(self, saver):
        graph = StateGraph(WorkflowState)
        for name in ("prepare", "planner", "execute", "ask", "blocked", "wait", "finalize"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges("prepare", lambda state: "ask" if state.get("blocking_questions") else "planner")
        graph.add_conditional_edges("planner", lambda state: {
            "ask_user": "ask", "blocked": "blocked",
        }.get(state["plan"]["action"], "execute"))
        graph.add_conditional_edges("execute", lambda state: "wait" if state.get("allowed_actions") else "planner")
        graph.add_conditional_edges("ask", lambda state: "wait" if state.get("allowed_actions") else "planner")
        graph.add_edge("blocked", "wait")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=saver)

    def run(self, state, *, action="generate", replay_pending=False):
        if state.workflow_schema != 1:
            raise InvalidStateError("지원하지 않는 실행 상태 버전입니다. 원본은 보존됩니다.")
        thread_id = self.writer.job_id
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 128}
        with workflow_store(self.writer.store, thread_id) as (saver, journal):
            self.journal = journal
            graph = self.build(saver)
            snapshot = graph.get_state(config)
            self.replay_task_id = None
            if action == "retry":
                from backend.infrastructure.workflow_store import retry_state
                recovery = retry_state(self.writer)
                if not recovery["can_retry"] or (recovery["retry_requires_replay"] and not replay_pending):
                    raise InvalidStateError("미완료 단계 재실행에는 명시적인 동의가 필요합니다." if recovery["retry_requires_replay"] else recovery["retry_unavailable_reason"])
                if recovery["retry_requires_replay"]:
                    self.replay_task_id = recovery["task_id"]
            if not snapshot.values and action != "generate":
                raise InvalidStateError("저장된 그래프 상태를 찾을 수 없습니다. 실행 DB와 checkpoint 백업을 확인해주세요.")
            incoming = state.to_workflow_state()
            if snapshot.values and snapshot.next:
                if any(task.interrupts for task in snapshot.tasks):
                    resume_action = "revise" if action == "revise" else action
                    inputs = Command(resume={"action": resume_action, "state": incoming})
                elif action == "retry" or (action == "approve" and snapshot.next == ("finalize",)):
                    # 실패 복구에는 새 입력 대신 None으로 저장된 실행을 이어간다.
                    inputs = None
                elif action in {"revise", "message"}:
                    # 실패한 실행에 명시적인 수정 입력으로 새 계획을 적용한다.
                    incoming.update(self.prepare({**incoming, "pending_input": {"action": action}}))
                    graph.update_state(config, incoming, as_node="prepare")
                    inputs = None
                else:
                    raise InvalidStateError("중단된 실행을 먼저 재개해주세요.")
            else:
                if snapshot.values:
                    incoming = {**snapshot.values, **incoming}
                incoming["pending_input"] = {"action": action}
                inputs = incoming
            graph.invoke(inputs, config=config, durability="sync")
            final = State.from_workflow_state(graph.get_state(config).values)
            self.persist("state", final.to_dict())
            return final
