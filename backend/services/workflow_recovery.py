"""성공한 단계의 상태와 산출물만 수동 재시도에 사용한다."""

from copy import deepcopy
import json

from backend.errors import ArtifactError, InvalidStateError, ReviewValidationError


CHECKPOINT_PATH = "state/retry_checkpoint.json"
STAGES = {"project_context", "web_research", "interview", "await_user", "requirement_lock",
          "spec_compile", "checklist_critic", "review_resolution", "compose_candidate", "critical_report", "workflow_entry"}
ENTRY_STAGES = (STAGES - {"requirement_lock", "workflow_entry"}) | {"requirement_lock_stage"}


class CheckpointPersistenceError(ArtifactError):
    """완료 결과를 저장하지 못한 경우 제공자 호출을 다시 실행하지 않는다."""


def next_stage(stage, state):
    from backend.pipeline.builder import route_after_interview, route_after_resolution
    if stage == "workflow_entry":
        value = state.get("resume_stage") or "project_context"
        if value not in ENTRY_STAGES:
            raise InvalidStateError("재개할 단계를 확인할 수 없습니다.")
        return value
    if stage == "interview":
        return route_after_interview(state)
    if stage == "review_resolution":
        return route_after_resolution(state)
    return {"project_context": "web_research", "web_research": "interview",
            "requirement_lock": "spec_compile", "spec_compile": "checklist_critic",
            "checklist_critic": "review_resolution", "await_user": None,
            "compose_candidate": None, "critical_report": None}[stage]


def checkpoint_artifact(state, artifacts, stage, execution_id):
    merged = deepcopy(state)
    merged["resume_stage"] = next_stage(stage, merged)
    # 사용량·제공자 대화·이력은 실패한 호출도 포함하는 최신 기록을 유지한다.
    mutable = {CHECKPOINT_PATH, "state/state.json", "state/execution_history.json", "state/provider_usage.json",
               "state/conversation_state.json", "state/prompt_references.json", "state/private_model_assignments.json"}
    frozen = {path: text for path, text in artifacts.items()
              if path not in mutable and not path.startswith(("history/", "completed/", "translations/", "impact_"))}
    return {"version": 1, "execution_id": execution_id, "stage": stage,
            "state": merged, "artifacts": frozen}


def validate_checkpoint(value):
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("stage") not in STAGES:
        raise InvalidStateError("저장된 재시도 지점을 확인할 수 없습니다.")
    state, artifacts = value.get("state"), value.get("artifacts")
    if (not isinstance(state, dict) or not state.get("run_id") or not isinstance(artifacts, dict)
            or any(not isinstance(path, str) or not isinstance(text, str) for path, text in artifacts.items())
            or state.get("resume_stage") != next_stage(value["stage"], state)):
        raise InvalidStateError("저장된 재시도 자료가 올바르지 않습니다.")
    return value


def applied_input_checkpoint(state, action, payload, writer, execution_id):
    """이전 형식에서 이미 반영한 입력은 재주입하지 않고 안전한 시작점으로 옮긴다."""
    from backend.knowledge.runtime import read_artifacts
    data = state.to_dict()
    stage = "workflow_entry"
    if action == "revise" and state.status == "REJECTED_BY_USER" and state.revision_feedback == str(payload).strip():
        data.update(resume_stage="interview", final_agent_spec=None)
    elif action == "answer" and isinstance(payload, list):
        from backend.engine import _question_is_answered
        from backend.models import QAItem
        from backend.services.saved_answers import saved_answer_dicts
        saved = saved_answer_dicts(data)
        by_id = {item["question_id"]: item for item in saved}
        if not payload or not all(isinstance(item, dict) and item.get("question_id") in by_id
                                  and by_id[item["question_id"]]["answer"] == item.get("answer") for item in payload):
            return None
        remaining = [question for question in state.blocking_questions
                     if not _question_is_answered(question, set(by_id), [QAItem.from_dict(item) for item in saved])]
        data.update(blocking_questions=remaining, final_agent_spec=None)
        if remaining:
            stage = "await_user"
        else:
            review = state.awaiting_input_reason == "review"
            data.update(resume_stage="requirement_lock_stage" if review else "interview", awaiting_input_reason=None,
                        critic_pass_count=0, diagnosed_keys=[], resolution_stop=False)
            if not review:
                data["structured_issues"] = []
    else:
        return None
    return checkpoint_artifact(data, read_artifacts(writer.output_dir), stage, execution_id)


def save_checkpoint(writer, evidence, stage, state, result):
    try:
        _save_checkpoint(writer, evidence, stage, state, result)
    except (InvalidStateError, ReviewValidationError):
        raise
    except Exception as exc:
        raise CheckpointPersistenceError("완료된 처리 결과를 저장하지 못했습니다.") from exc


def _save_checkpoint(writer, evidence, stage, state, result):
    from backend.knowledge.runtime import CURRENT, read_artifacts
    merged = {**state, **(result or {})}
    merged["resume_stage"] = next_stage(stage, merged)
    writer.write_json_atomic("evidence/evidence_registry.json", evidence.to_dict())
    runtime = CURRENT.get()
    if runtime is not None:
        runtime.commit(stage, state, {**(result or {}), "resume_stage": merged["resume_stage"]})
        return
    history_path = writer.path("state/execution_history.json")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.is_file() else {}
    executions = history.get("executions", [])
    execution_id = executions[-1]["id"] if executions else merged.get("run_id")
    value = checkpoint_artifact(merged, read_artifacts(writer.output_dir), stage, execution_id)
    writer.write_json_atomic(CHECKPOINT_PATH, value)
    writer.write_json_atomic("state/state.json", merged)
