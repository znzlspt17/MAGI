"""계획 모델이 지휘하는 영속 StateGraph 실행."""

from copy import deepcopy
import hashlib
import json
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.errors import InvalidStateError
from backend.infrastructure.heartbeat import RunHeartbeat
from backend.infrastructure.workflow_store import workflow_store
from backend.models import State, WorkflowState
from backend.pipeline.builder import _stage
from backend.pipeline.planner import allowed_tasks, plan_next


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class AgentWorkflow:
    def __init__(self, engine, nodes, writer, evidence, on_progress=None):
        self.engine, self.nodes, self.writer, self.evidence = engine, nodes, writer, evidence
        self.progress = on_progress

    def persist(self, stage, state):
        from backend.access.context import METER
        meter = METER.get()
        if meter is not None:
            meter.access.check_execution(meter.uid, meter.jid, meter.generation)
        self.writer.write_json_atomic("evidence/evidence_registry.json", self.evidence.to_dict())
        from backend.knowledge.runtime import CURRENT
        runtime = CURRENT.get()
        if runtime:
            runtime.commit(stage, state)
        self.writer.write_json_atomic("state/state.json", State.from_dict(state).to_dict())

    def durable(self, name, state, operation):
        from backend.knowledge.runtime import read_artifacts, restore_artifacts
        ident = digest([state["run_id"], state.get("revision", 0),
                        len(state.get("plan_history", [])), name])
        saved = self.journal.get(ident, retry_safe=name == "approve")
        if saved is not None:
            restore_artifacts(self.writer.output_dir, saved["artifacts"])
            from backend.infrastructure.evidence_registry import EvidenceRegistry
            restored = EvidenceRegistry.from_dict(saved["evidence"])
            self.evidence.items = restored.items
            result = saved["result"]
            if "knowledge_context" in result:
                from backend.knowledge.runtime import CURRENT
                runtime = CURRENT.get()
                if runtime:
                    runtime.retrieved = result["knowledge_context"]
        else:
            self.journal.begin(ident)
            from backend.infrastructure.provider_call import WORKFLOW_MESSAGES
            recorded = {}
            token = WORKFLOW_MESSAGES.set(recorded)
            try:
                result = operation(deepcopy(state))
            except Exception as exc:
                from backend.errors import RequirementNormalizationError, ReviewValidationError, SpecCompilationError
                from backend.infrastructure.output_language import OutputLanguageError
                if isinstance(exc, (RequirementNormalizationError, ReviewValidationError, SpecCompilationError, OutputLanguageError)):
                    # 반환된 결과의 검증 실패는 통신 완료 여부가 불명확한 오류와 구분한다.
                    self.journal.failed(ident)
                raise
            finally:
                WORKFLOW_MESSAGES.reset(token)
            result["task_messages"] = {**state.get("task_messages", {}), **recorded}
            artifacts = read_artifacts(self.writer.output_dir)
            # 실패한 호출의 사용량이나 사용자 이력을 이전 사본으로 되돌리지 않는다.
            artifacts = {path: text for path, text in artifacts.items()
                         if path not in {"state/state.json", "state/provider_usage.json", "state/execution_history.json"}}
            self.journal.complete(ident, {"result": result, "artifacts": artifacts,
                                          "evidence": self.evidence.to_dict()})
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
                  "execution_segment": state.get("execution_segment", 0) + 1,
                  "wait_reason": "", "resume_stage": None}
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
        if state.get("segment_steps", 0) >= 20:
            return self.blocked(state, "자동 실행 한도에 도달했습니다. 결과를 확인하고 추가 실행을 선택해주세요.")
        from backend.pipeline.builder import _progress
        _progress(self.progress, "planner", "started")
        plan = self.durable("planner", state, lambda current: {"plan": plan_next(current, self.nodes.context)})["plan"]
        history = [*state.get("plan_history", []), {**plan, "revision": state.get("revision", 0)}]
        result = {"plan": plan, "plan_history": history, "allowed_actions": [],
                  "segment_steps": state.get("segment_steps", 0) + 1}
        self.persist("planner", {**state, **result})
        _progress(self.progress, "planner", "completed")
        return result

    def blocked(self, state, reason=None):
        reason = reason or state.get("plan", {}).get("reason") or "추가 확인이 필요합니다."
        result = {"status": "CRITICAL_BLOCKED", "wait_reason": reason,
                  "allowed_actions": ["message", "revise", "retry"],
                  "plan": {**state.get("plan", {}), "action": "blocked", "reason": reason}}
        if state.get("requirement_lock_sheet") and state.get("structured_issues"):
            report = self.durable("critical_report", state, self.nodes.critical_report)
            result.update(report)
        self.persist("blocked", {**state, **result})
        return result

    def execute(self, state):
        action = state["plan"]["action"]
        if action not in allowed_tasks(state, self.engine.config):
            raise InvalidStateError("현재 상태에서 실행할 수 없는 계획입니다.")
        # 동일한 입력과 동일한 결과가 반복되면 추가 호출 전에 멈춘다.
        signature = digest([action, state.get("revision"), state.get("requirement_lock_sheet"),
                            state.get("structured_issues"), self._candidate_hash(),
                            state.get("critic_pass_count", 0), state.get("diagnosed_keys", []),
                            state["plan"].get("target"), state["plan"].get("input_refs")])
        recent = state.get("task_results", [])
        if sum(item.get("signature") == signature and item.get("segment") == state.get("execution_segment")
               for item in recent[-8:]) >= 2:
            return self.blocked(state, "동일한 작업이 진전 없이 반복되었습니다. 결정이나 수정 의견이 필요합니다.")
        if action == "knowledge_search":
            def operation(current):
                from backend.knowledge.runtime import CURRENT
                runtime = CURRENT.get()
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
                getattr(self.nodes, "checklist_critic_node" if action == "checklist_critic" else action),
                self.progress, checkpoint=lambda *args: None)
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
            history = ExecutionHistory(self.writer.output_dir).graph()
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
        result = {**self.nodes.await_user(state), "allowed_actions": ["answer", "message", "revise"],
                  "wait_reason": "미확정 요구사항에 대한 답변이나 수정 의견이 필요합니다."}
        self.persist("await_user", {**state, **result})
        return result

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
            stored = self.writer.read_json("state/state.json")
            if stored.get("status") == "FINALIZED" and stored.get("candidate_hash") == self._candidate_hash():
                return stored
            self.persist("approval_input", {**current, "pending_input": {}})
            self.engine._finalize(str(self.writer.output_dir), on_progress=self.progress)
            return self.writer.read_json("state/state.json")
        result = self.durable("approve", state, operation)
        return {**result, "allowed_actions": ["message", "revise"], "wait_reason": ""}

    def _candidate_hash(self):
        path = self.writer.path("draft/approval_candidate_spec.en.md")
        return hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest() if path.is_file() else ""

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
        graph.add_edge("ask", "wait")
        graph.add_edge("blocked", "wait")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=saver)

    def run(self, state, *, action="generate"):
        if state.workflow_schema not in {0, 1}:
            raise InvalidStateError("지원하지 않는 실행 상태 버전입니다. 원본은 보존됩니다.")
        from backend.knowledge.runtime import CURRENT
        runtime = CURRENT.get()
        self.writer.allow_overwrite = True
        thread_id = runtime.job["id"] if runtime else state.run_id
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 128}
        storage = self.engine.workflow_store_factory or workflow_store
        with storage(self.writer, thread_id) as (saver, journal):
            self.journal = journal
            graph = self.build(saver)
            snapshot = graph.get_state(config)
            if state.workflow_schema and not snapshot.values:
                raise InvalidStateError("저장된 그래프 상태를 찾을 수 없습니다. 실행 DB와 checkpoint 백업을 확인해주세요.")
            incoming = state.to_workflow_state()
            incoming["workflow_schema"] = 1
            incoming["resume_stage"] = None
            if not snapshot.values and action != "generate":
                incoming = self.import_legacy(incoming)
                status = incoming.get("status")
                if status in {"PASS_PENDING_USER_APPROVAL", "NEEDS_USER_INPUT", "CRITICAL_BLOCKED"}:
                    allowed = {"PASS_PENDING_USER_APPROVAL": ["approve", "message", "revise"],
                               "NEEDS_USER_INPUT": ["answer", "message", "revise"],
                               "CRITICAL_BLOCKED": ["retry", "message", "revise"]}[status]
                    graph.update_state(config, {**incoming, "allowed_actions": allowed,
                        "candidate_hash": self._candidate_hash()}, as_node="execute")
                    graph.invoke(None, config=config, durability="sync")
                else:
                    graph.update_state(config, incoming, as_node="prepare")
                snapshot = graph.get_state(config)
            if snapshot.values and snapshot.next:
                if any(task.interrupts for task in snapshot.tasks):
                    resume_action = "revise" if action == "revise" else action
                    inputs = Command(resume={"action": resume_action, "state": incoming})
                elif action == "retry" or (action == "approve" and snapshot.next == ("finalize",)):
                    # 실패 복구에는 새 입력 대신 None으로 저장된 실행을 이어간다.
                    inputs = None
                elif not state.workflow_schema or action in {"revise", "message"}:
                    # 이전 실행을 공식 상태 갱신으로 가져온 후 새 입력을 적용한다.
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
            heartbeat = RunHeartbeat(writer=self.writer, state=state)
            heartbeat.start()
            try:
                graph.invoke(inputs, config=config, durability="sync")
                final = State.from_workflow_state(graph.get_state(config).values)
                self.persist("state", final.to_dict())
                heartbeat.stop(final_status=final.status)
                return self.engine._result_from_state(final)
            except Exception as exc:
                heartbeat.stop(exc=exc)
                saved = graph.get_state(config)
                current = dict(saved.values)
                node = saved.next[0] if saved.next else ""
                name = current.get("plan", {}).get("action") if node == "execute" else "approve" if node == "finalize" else node
                ident = digest([current.get("run_id"), current.get("revision", 0),
                                len(current.get("plan_history", [])), name])
                uncertain = journal.status(ident) == "pending" and name != "approve"
                actions = ["message"] if uncertain else ["message", "retry"]
                reason = ("이전 호출의 완료 여부가 불명확해 자동 재전송하지 않습니다. 수정 의견으로 새 계획을 시작할 수 있습니다."
                          if uncertain else "저장된 결과를 유지했습니다. 재개하거나 수정 의견을 보내주세요.")
                # 복구 안내 저장 실패가 원래 실행 오류를 가리지 않게 한다.
                try:
                    records = current.get("resolution_history", [])
                    if records:
                        resolved = self.writer.read_text("review/resolved_draft.en.md")
                        if hashlib.sha256(resolved.encode()).hexdigest() == records[-1].get("draft_hash"):
                            self.writer.write_text("draft/approval_candidate_spec.en.md", resolved, overwrite=True)
                    self.persist("recovery", {**current, "allowed_actions": actions, "wait_reason": reason})
                except Exception:
                    pass
                raise

    def import_legacy(self, state):
        done = []
        if state.get("request_type"):
            done.append("interview")
        if state.get("requirement_lock_sheet"):
            done.append("requirement_lock_stage")
        if state.get("approval_candidate_spec") and self._candidate_hash():
            done.append("spec_compile")
        if state.get("status") == "PASS_PENDING_USER_APPROVAL":
            self.engine._validate_candidate_for_approval(self.writer.path("draft/approval_candidate_spec.en.md"), State.from_dict(state))
            done.extend(["checklist_critic", "review_resolution"])
        return {**state, "completed_tasks": done, "workflow_schema": 1}
