"""로컬 단일 워커 작업 큐와 안전한 작업 메타데이터 저장소."""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.engine import Engine
from backend.errors import ReviewValidationError
from backend.infrastructure.usage import provider_usage_summary
from backend.models import State
from backend.server.diagnostics import diagnose_exception, safe_user_error
from backend.server.execution_history import ExecutionHistory
from backend.services.saved_answers import saved_answer_dicts
from backend.services.spec_translation import korean_translation, source_key
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.server.cleanup import Cleanup, tracked, synchronized
from backend.access.context import ACTOR, DEFERRED
from backend.server.cleanup import CleanupConflict


LOGGER = logging.getLogger("backend.server")


_ID = re.compile(r"[0-9a-f]{32}\Z")
_ACTIVE = {"queued", "running"}
_ENGINE = {
    "DRAFT",
    "ANALYZING",
    "RESEARCHING",
    "COMPILING",
    "CRITIQUING",
    "NEEDS_USER_INPUT",
    "PASS_PENDING_USER_APPROVAL",
    "CRITICAL_BLOCKED",
    "REJECTED_BY_USER",
    "APPROVED",
    "FINALIZED",
}
_JOB = _ENGINE | _ACTIVE | {"error", "interrupted"}
_ACTIONS = {"generate", "answer", "revise", "approve"}
_PROVIDERS = {"openai"}
_NORMALIZATION_ERROR_CODES = {
    "REQUIREMENT_NORMALIZATION_FAILED",
    "SOURCE_COVERAGE_MISSING",
}
_NORMALIZATION_RECOVERY_STATES = {
    "DRAFT",
    "ANALYZING",
    "RESEARCHING",
    "COMPILING",
    "CRITIQUING",
    "NEEDS_USER_INPUT",
    "PASS_PENDING_USER_APPROVAL",
    "CRITICAL_BLOCKED",
    "REJECTED_BY_USER",
}
_PROGRESS_STAGES = {
    "project_context",
    "web_research",
    "interview",
    "await_user",
    "requirement_lock",
    "spec_compile",
    "checklist_critic",
    "compose_candidate",
    "critical_report",
    "approve",
    "workflow",
}
_PROGRESS_STATES = {"started", "retrying", "completed", "failed"}
_GUARDS = {
    "answer": {"NEEDS_USER_INPUT"},
    "revise": {"PASS_PENDING_USER_APPROVAL", "CRITICAL_BLOCKED"},
    "approve": {"PASS_PENDING_USER_APPROVAL"},
}


class JobManager:
    """Persist jobs under one trusted directory and run one engine task at a time."""

    def __init__(
        self,
        data_dir: str | Path,
        engine_factory=Engine,
        on_change=None,
        knowledge=None,
    ) -> None:
        from backend.knowledge.format_guard import require_current
        require_current(data_dir)
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine_factory = engine_factory
        self.on_change = on_change
        self.lock = threading.RLock()
        self._document_locks: dict[tuple[str, str], threading.Lock] = {}
        self.jobs: dict[str, dict] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web")
        self._futures = {}
        self.closed = False
        self.knowledge = knowledge
        self._next_order = 0
        self._activities = {}
        self.cleanup = Cleanup(self)
        self.cleanup.recover()
        self._restore_jobs()
        if self.knowledge is None:
            from backend.services.completed_specs import restore_completed_cache
            for ident in self.jobs:
                data = self._read_json(self._job_root(ident) / "state/state.json") or {}
                if data.get("latest_completed"):
                    try:
                        restore_completed_cache(ArtifactWriter(self._job_root(ident)), State.from_dict(data))
                    except Exception:
                        LOGGER.warning("completed cache recovery unavailable id=%s", ident)

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        # 완료 콜백도 self.lock을 사용하므로 잠금 밖에서 실행 종료를 기다린다.
        # DB 독점 잠금을 해제하기 전에 진행 중인 외부 호출·저장을 마쳐야 한다.
        self.executor.shutdown(wait=True, cancel_futures=True)
        if getattr(self, 'public_service', None):
            self.public_service.recovery.close()
        if self.knowledge is not None:
            self.knowledge.close()

    def ids(self) -> list[str]:
        with self.lock:
            return [
                job["id"]
                for job in sorted(
                    self.jobs.values(), key=lambda item: (item.get("updated_at", ""), item["order"]), reverse=True
                )
                if ACTOR.get() is None or job.get('owner_id') == ACTOR.get()['id']
            ]

    @synchronized
    def create(
        self,
        request: str,
        demo: bool | None = None,
        provider: str | None = None,
        project_id: str | None = None,
    ) -> dict:
        selected_provider = self._validate_request(request, demo, provider)
        if project_id:
            raise ValueError("프로젝트 지정은 지원하지 않습니다. 새 대화 세션을 생성하세요.")
        with self.lock:
            self._require_open()
            if sum(job["status"] in _ACTIVE for job in self.jobs.values()) >= 20:
                raise ValueError("작업 큐가 가득 찼습니다.")
            order = self._new_order()
            now = _utc_now()
            job = {
                "id": uuid4().hex,
                "owner_id": ACTOR.get()['id'] if ACTOR.get() else None,
                "request": request.strip(),
                "demo": False,
                "provider": selected_provider,
                "status": "queued",
                "message": "작업 대기 중",
                "action": "generate",
                "created_at": now,
                "updated_at": now,
                "queued_at": now,
                "order": order,
                "queue_order": order,
                "project_id": None,
            }
            job["project_id"] = job["id"] if self.knowledge is not None else None
            job["execution_id"] = uuid4().hex
            if self.knowledge is not None:
                self.knowledge.store.accept_job(job, job["request"])
            self.jobs[job["id"]] = job
            if not self._export_job_locked(job):
                del self.jobs[job["id"]]
                raise RuntimeError("작업 정보를 저장할 수 없습니다.")
            self._start_history_execution_locked(job["id"], "generate", input_data=job["request"], execution_id=job["execution_id"])
            try:
                self._submit_locked(job["id"], "generate", None)
            except RuntimeError:
                job.update(status="error", message="작업 큐를 사용할 수 없습니다.", updated_at=_utc_now())
                self._save_locked(job)
            snapshot = self._snapshot(job)
        self._notify(snapshot)
        return snapshot

    @synchronized
    def continue_session(self, ident, payload, expected_execution_id):
        self._require_open()
        job = self._get_locked(ident)
        resumable = job["status"] == "FINALIZED" or (job["status"] in {"error", "interrupted"} and job["action"] == "revise")
        if (not isinstance(expected_execution_id, str) or expected_execution_id != job.get("execution_id")
            or not resumable or self._activities.get(ident)):
            raise CleanupConflict("세션 상태가 바뀌었거나 처리 중입니다. 현재 실행을 다시 확인하세요.")
        self._validate_payload("revise", payload, [])
        writer = ArtifactWriter(self._job_root(ident), allow_overwrite=True)
        from backend.services.completed_specs import require_conversation, archive_completed, restore_completed_cache
        require_conversation(writer)
        state = Engine()._load_state(writer)
        if state.status != "FINALIZED":
            raise CleanupConflict("완료된 명세가 있는 세션만 이어갈 수 있습니다.")
        from backend.models import RequirementLockSheet
        RequirementLockSheet.from_dict(state.requirement_lock_sheet).require_validated()
        restore_completed_cache(writer, state)
        state.latest_completed = archive_completed(writer, state)
        if state.latest_completed["path"] not in state.created_artifacts:
            state.created_artifacts.append(state.latest_completed["path"])
        writer.write_json("state/state.json", state.to_dict(), overwrite=True)
        if self.knowledge:
            from backend.knowledge.runtime import read_artifacts
            self.knowledge.store.commit_stage(job, job["execution_id"], "completion_archive", state.to_dict(), read_artifacts(writer.output_dir))
        return self.action(ident, "revise", payload, continuation=True)

    def action(self, ident: str, action: str, payload: object, *, continuation=False) -> dict:
        if action not in _ACTIONS - {"generate"}:
            raise KeyError(ident)
        with self.lock:
            self._require_open()
            job = self._get_locked(ident)
            previous = self._snapshot(job)
            effective = self._effective_status_locked(job)
            self._validate_payload(
                action, payload, self._pending_questions_locked(ident),
                (self._read_json(self.artifact(ident, "state/state.json")) or {}).get("question_forms", {})
            )
            if job["status"] in _ACTIVE or self._activities.get(ident):
                raise CleanupConflict("이미 실행·번역·저장 중인 세션입니다.")
            if sum(item["status"] in _ACTIVE for item in self.jobs.values()) >= 20:
                raise ValueError("작업 큐가 가득 찼습니다.")
            normalization_retry = self._normalization_retry_allowed_locked(job, action)
            if continuation and action == "revise" and self._persisted_state_status_locked(ident) == "FINALIZED":
                effective = "FINALIZED"
            if effective not in _GUARDS[action] and not normalization_retry and not (continuation and action == "revise" and effective == "FINALIZED"):
                raise CleanupConflict("현재 상태에서는 이 작업을 실행할 수 없습니다.")
            from backend.services.completed_specs import require_conversation
            writer = ArtifactWriter(self._job_root(ident))
            require_conversation(writer)
            Engine()._load_state(writer)
            now = _utc_now()
            job.update(
                status="queued",
                message="작업 대기 중",
                action=action,
                resume_status=effective or self._persisted_state_status_locked(ident),
                queued_at=now,
                updated_at=now,
                queue_order=self._new_order(),
            )
            job.pop("execution_id", None)
            job.pop("recoverable_status", None)
            self._clear_error_metadata(job)
            if normalization_retry:
                job["normalization_retry"] = True
            else:
                job.pop("normalization_retry", None)
            if self.knowledge is None and not self._save_locked(job):
                self.jobs[ident] = previous
                raise RuntimeError("작업 정보를 저장할 수 없습니다.")
            job["execution_id"] = self._start_history_execution_locked(
                ident, action, input_data=payload
            )
            if not self._save_action_locked(job, payload):
                self.jobs[ident] = previous
                self._save_locked(previous)
                raise RuntimeError("사용자 결정을 저장할 수 없습니다.")
            try:
                self._submit_locked(ident, action, copy.deepcopy(payload))
            except RuntimeError:
                self.jobs[ident] = previous
                self._save_locked(previous)
                raise
            snapshot = self._snapshot(job)
        self._notify(snapshot)
        return snapshot

    def get(self, ident: str) -> dict:
        with self.lock:
            return self._snapshot(self._get_locked(ident))

    def root(self, ident: str) -> Path:
        with self.lock:
            self._get_locked(ident)
            return self._job_root(ident)

    def artifact(self, ident: str, relative_path: str) -> Path:
        """Return an artifact path only when it resolves under the job root."""
        root = self.root(ident)
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise KeyError(ident) from exc
        return path

    def summary(self, ident: str) -> dict:
        with self.lock:
            source = self._get_locked(ident)
            keys = {
                "id",
                "request",
                "demo",
                "provider",
                "status",
                "message",
                "action",
                "created_at",
                "updated_at",
                "queued_at",
                "order",
                "progress",
                "execution_id",
                "project_id",
                "error_code",
                "error_stage",
            }
            result = {
                key: copy.deepcopy(value)
                for key, value in source.items()
                if key in keys
            }
            if source["status"] in {"error", "interrupted"}:
                retry_status = source.get("recoverable_status")
                if isinstance(retry_status, str):
                    result["retry_status"] = retry_status
            if self._normalization_retry_allowed_locked(source, "revise"):
                result["retry_action"] = "revise"
            if source["status"] == "queued":
                result["queue_position"] = self._queue_position_locked(source["id"])
            result["can_continue"] = False
            result["read_only"] = False
            result["latest_completed"] = None
            state = self._read_json(self._job_root(ident) / "state/state.json") or {}
            if isinstance(state.get("latest_completed"), dict):
                result["latest_completed"] = {key: state["latest_completed"].get(key) for key in ("id", "source_hash")}
                result["latest_completed"]["step_id"] = state["latest_completed"].get("id")
            if source["status"] not in _ACTIVE:
                try:
                    from backend.services.completed_specs import require_conversation
                    writer = ArtifactWriter(self._job_root(ident))
                    require_conversation(writer)
                    Engine()._load_state(writer)
                    from backend.models import RequirementLockSheet
                    if source["status"] in {"FINALIZED", "PASS_PENDING_USER_APPROVAL"}:
                        RequirementLockSheet.from_dict(state.get("requirement_lock_sheet")).require_validated()
                    result["can_continue"] = source["status"] == "FINALIZED" or (
                        source["status"] in {"error", "interrupted"} and source["action"] == "revise" and state.get("status") == "FINALIZED")
                except Exception as exc:
                    from backend.errors import ConversationUnavailableError
                    result["read_only"] = True
                    result["continuation_error"] = (safe_user_error(exc) if isinstance(exc, ConversationUnavailableError) else
                        "대화 연결 또는 저장 계약을 확인할 수 없습니다. 기록은 보존되며 새 작업이 필요합니다.")
            history = self._read_json(self._job_root(ident) / "state/execution_history.json") or {}
            completed = next((n for n in reversed(history.get("nodes", [])) if n.get("stage") == "approve" and n.get("has_document") and n.get("status") == "completed"), None)
            if completed and result["latest_completed"] is None:
                result["latest_completed"] = {**(result["latest_completed"] or {}), "step_id": completed["id"]}
            return result

    def public(self, ident: str) -> dict:
        with self.lock:
            source = self._get_locked(ident)
            job = self.summary(ident)
            state = self._read_json(self.artifact(ident, "state/state.json"))
            if state:
                public_state = {
                    key: state[key]
                    for key in ("status", "blocking_questions", "critic_pass_count", "awaiting_input_reason", "review_questions", "question_forms")
                    if key in state
                }
                pending_questions = state.get("blocking_questions")
                pending = (
                    pending_questions
                    if isinstance(pending_questions, list)
                    and all(isinstance(question, str) for question in pending_questions)
                    else []
                )
                legacy_sheet = self._read_json(
                    self.artifact(ident, "analysis/requirement_lock_sheet.json")
                )
                public_state["saved_answers"] = saved_answer_dicts(
                    state,
                    legacy_lock_sheet=legacy_sheet,
                    pending_questions=pending,
                )
                job["state"] = public_state
            heartbeat = self._read_json(self.artifact(ident, "state/heartbeat.json"))
            if heartbeat:
                job["heartbeat"] = {
                    key: heartbeat[key]
                    for key in ("running", "last_heartbeat_at", "status")
                    if key in heartbeat
                }
            usage = provider_usage_summary(
                self._read_json(self.artifact(ident, "state/provider_usage.json"))
            )
            if usage is not None:
                job["usage"] = usage
            history = ExecutionHistory(self._job_root(ident))
            try:
                graph = history.graph()
            except Exception as exc:
                LOGGER.warning("execution history read failed exception_type=%s", type(exc).__name__)
                graph = {
                    "version": 1,
                    "nodes": [],
                    "recording_incomplete": True,
                    "legacy": False,
                }
            if graph["legacy"]:
                if isinstance(source.get("execution_id"), str):
                    graph = {
                        "version": 1,
                        "nodes": [],
                        "recording_incomplete": True,
                        "legacy": False,
                    }
                else:
                    graph["nodes"] = [self._legacy_node(job)]
            job["execution_graph"] = graph
            job["session_events"] = history.conversation()
            from backend.services.completed_specs import completed_references
            job["completed_documents"] = [{"id": Path(path).stem, "title": "완료 명세 · " + Path(path).stem[:8]}
                                          for path in completed_references(state or {})]
            for relative, key in (
                ("draft/approval_candidate_spec.en.md", "candidate"),
                ("final/FINAL_AGENT_SPEC.md", "final"),
                ("critical/CRITICAL_REPORT.ko.md", "critical"),
            ):
                text = self._read_text(self.artifact(ident, relative))
                if text is not None:
                    job[key] = text
            from backend.services.change_review import CURRENT_REVIEW, digest, normalize
            change_review = self._read_json(self.artifact(ident, CURRENT_REVIEW))
            if isinstance(change_review, dict) and change_review.get("after_hash") == digest(normalize(job.get("candidate", ""))):
                job["change_review"] = change_review
            return job

    def step(self, ident: str, step_id: str) -> dict:
        """선택한 실행 노드의 저장된 상세만 돌려준다."""
        with self.lock:
            self._get_locked(ident)
            if not isinstance(step_id, str) or len(step_id) > 64:
                raise KeyError(ident)
            history = ExecutionHistory(self._job_root(ident))
            if re.fullmatch(r"[0-9a-f]{64}", step_id):
                from backend.services.completed_specs import completed_references, load_completed
                state = self._read_json(self._job_root(ident) / "state/state.json") or {}
                if f"completed/{step_id}.json" not in completed_references(state):
                    raise KeyError(step_id)
                content = load_completed(ArtifactWriter(self._job_root(ident)), step_id)["content"]
                detail = {"id": step_id, "stage": "completed_document", "title": "보존된 완료 명세", "status": "completed",
                          "document": {"content": content, "filename": "FINAL_AGENT_SPEC.en.md", "kind": "final"}}
            elif step_id == "legacy-current" and history.graph()["legacy"]:
                detail = self._legacy_node(self.summary(ident), detail=True)
            else:
                detail = history.detail(step_id)
            if detail is None:
                raise KeyError(ident)
            document = detail.get("document")
            if isinstance(document, dict) and isinstance(document.get("content"), str):
                document["source_hash"] = source_key(document["content"])
            return detail

    @tracked
    def document(self, ident: str, step_id: str, language: str) -> dict:
        """선택한 시점의 영어 명세 또는 그 스냅샷의 한국어본을 돌려준다."""
        if not isinstance(language, str) or language not in {"ko", "en"}:
            raise ValueError("지원하지 않는 문서 언어입니다.")
        detail = self.step(ident, step_id)
        document = detail.get("document")
        if not isinstance(document, dict) or not isinstance(document.get("content"), str):
            raise KeyError(ident)
        if language == "en":
            return {**document, "language": "en"}
        key = source_key(document["content"])
        with self.lock:
            translation_lock = self._document_locks.setdefault((ident, key), threading.Lock())
            provider_name = self._get_locked(ident)["provider"]
        # 원격 호출 중 작업 조회와 단계 진행을 막지 않는다.
        with translation_lock:
            engine = self._engine_for_provider(provider_name)
            writer = ArtifactWriter(self.artifact(ident, f"translations/{key}"), allow_overwrite=True)
            try:
                translated = korean_translation(document["content"], writer=writer, provider=engine.provider,
                                                model=engine.config.model_routing["compiler"].model)
            finally:
                # 실패한 번역도 안전한 검증 진단과 불확실한 호출 상태를 보존한다.
                if self.knowledge is not None:
                    paths = ("translation.ko.json", "validation.json", "state/provider_usage.json", "state/conversation_state.json")
                    artifacts = {f"translations/{key}/{path}": writer.read_text(path)
                                 for path in paths if writer.path(path).is_file()}
                    if artifacts:
                        self.knowledge.store.save_translation(ident, artifacts)
        stem = Path(document.get("filename", "SPEC.md")).stem.removesuffix(".en")
        return {**document, **translated, "filename": stem + ".ko.md"}

    def impact_context(self, params):
        from backend.knowledge.impact import impact_context
        ident = params.get("job_id")
        with self.lock:
            job = self._get_locked(ident)
            if job["status"] not in {"PASS_PENDING_USER_APPROVAL", "FINALIZED"}:
                raise ValueError("승인 후보가 준비된 작업에서 변경 영향을 검토할 수 있습니다.")
            if self.knowledge is None:
                raise ValueError("지식 저장소가 설정되지 않았습니다.")
        node_id = params.get("node_id") or None
        if node_id is not None and (not isinstance(node_id, str) or not re.fullmatch(r"[0-9a-f]{64}", node_id)):
            raise ValueError("요구사항 항목이 올바르지 않습니다.")
        return impact_context(self.knowledge.store, ident, node_id)

    def impact(self, params):
        from backend.knowledge.impact import impact_page
        return impact_page(self.impact_context(params), params.get("offset", 0))

    def cached_impact(self, params, request_key):
        from backend.services.impact_review import validate_request
        from backend.knowledge.projection import digest
        validate_request(params)
        ident = params.get("job_id")
        self.get(ident)  # 캐시 조회도 소유자 검증을 먼저 수행한다.
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("중복 방지 요청 키가 필요합니다.")
        path = self.artifact(ident, f"impact_requests/{digest(request_key)}.json")
        record = self._read_json(path)
        if not record:
            return None
        if record.get("fingerprint") != digest(params):
            raise ValueError("같은 요청 키에 다른 변경 가정을 사용할 수 없습니다.")
        key = record.get("id", "")
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("저장된 분석을 확인할 수 없습니다.")
        with self.lock:
            analysis_lock = self._document_locks.setdefault((ident, "impact:" + key), threading.Lock())
        if analysis_lock.locked():
            return None
        report = self._read_json(self.artifact(ident, f"impact_reviews/{key}/report.json"))
        if report is None:
            raise ValueError("접수된 분석의 결과를 확인할 수 없습니다. 자동 재전송하지 않습니다.")
        if report["status"] == "running":
            report = {**report, "status": "interrupted", "reason": "중단된 호출은 자동 재전송하지 않습니다."}
        return self._impact_result(params, report)

    def _impact_result(self, params, report):
        # 처리 중 접근 권한이 바뀌었다면 결과를 반환하지 않는다.
        self.get(params.get("job_id"))
        try:
            current = self.impact_context(params)["basis"]["id"]
        except ValueError:
            current = None
        return {**report, "stale": current != report.get("basis", {}).get("id")}

    @tracked
    def impact_analyse(self, ident, params, request_key):
        from backend.knowledge.projection import digest
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("중복 방지 요청 키가 필요합니다.")
        with self.lock:
            request_lock = self._document_locks.setdefault((ident, "impact-request:" + digest(request_key)), threading.Lock())
        with request_lock:
            return self._impact_analyse(ident, params, request_key)

    def _impact_analyse(self, ident, params, request_key):
        from backend.services.impact_review import prepare_review, run_review
        from backend.knowledge.projection import digest
        cached = self.cached_impact(params, request_key)
        if cached is not None:
            return cached
        context = self.impact_context(params)
        # 검색 결과는 문맥 선택에만 사용하고 기록된 관계에는 넣지 않는다.
        ranked = self.knowledge.search(params["proposal"], kind="spec", job_id=params["job_id"])
        prepared = prepare_review(context, params, [node["id"] for node in ranked.get("nodes", [])])
        key = prepared[0]
        if params["job_id"] != ident:
            raise ValueError("작업 범위가 일치하지 않습니다.")
        with self.lock:
            analysis_lock = self._document_locks.setdefault((ident, "impact:" + key), threading.Lock())
            provider_name = self._get_locked(ident)["provider"]
        with analysis_lock:
            writer = ArtifactWriter(self.artifact(ident, f"impact_reviews/{key}"), allow_overwrite=True)
            root = ArtifactWriter(self.root(ident), allow_overwrite=True)
            request_path = f"impact_requests/{digest(request_key)}.json"
            root.write_json_atomic(request_path, {"id": key, "fingerprint": digest(params)})

            def save():
                paths = ("input.json", "report.json", "state/provider_usage.json")
                artifacts = {f"impact_reviews/{key}/{path}": writer.read_text(path) for path in paths if writer.path(path).is_file()}
                artifacts[request_path] = root.read_text(request_path)
                self.knowledge.store.save_impact(ident, artifacts)

            engine = self._engine_for_provider(provider_name)
            report = run_review(writer, engine.provider, engine.config.model_routing["compiler"].model,
                                prepared, save, context["basis"])
            save()
        return self._impact_result(params, report)

    def _restore_jobs(self) -> None:
        if self.knowledge is not None:
            from backend.knowledge.runtime import restore_artifacts
            restored = []
            for data in self.knowledge.store.jobs():
                root = self._job_root(data["id"])
                restore_artifacts(root, self.knowledge.store.restore(data["id"]), reconcile=True)
                for action in self.knowledge.store.action_records(data["id"]):
                    history = ExecutionHistory(root)
                    history.start_execution(action["action"], action["id"], input_data=action.get("input"))
                    if action.get('status') == 'error':
                        history.terminal(action['id'], 'error', action.get('message', ''))
                restored.append((root / "job.json", data))
        else:
            restored = [(path, self._read_json(path)) for path in self.data_dir.glob("*/job.json")]
        for path, data in restored:
            migrated_provider = isinstance(data, dict) and "provider" not in data
            if migrated_provider:
                data["provider"] = "openai"
            if not self._valid_restored_job(path, data):
                continue
            assert data is not None
            with self.lock:
                self.jobs[data["id"]] = data
                self._next_order = max(
                    self._next_order, data["order"], data.get("queue_order", 0)
                )
                if data["status"] in _ACTIVE:
                    self._recover_interrupted_locked(data)
                    self._save_locked(data)
                elif data["status"] in {"error", "interrupted"}:
                    self._recover_retry_status_locked(data)
                    self._save_locked(data)
                elif migrated_provider:
                    self._save_locked(data)

    def _valid_restored_job(self, path: Path, data: dict | None) -> bool:
        if not isinstance(data, dict):
            return False
        ident = data.get("id")
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            return False
        try:
            root = self._job_root(ident)
        except KeyError:
            return False
        if path.resolve() != root / "job.json":
            return False
        if not isinstance(data.get("request"), str) or not data["request"].strip():
            return False
        if len(data["request"]) > 20_000 or not isinstance(data.get("demo"), bool):
            return False
        if (
            not isinstance(data.get("provider"), str)
            or data["provider"] not in _PROVIDERS
        ):
            return False
        if data["demo"] is not False:
            return False
        status = data.get("status")
        action = data.get("action")
        if (
            not isinstance(status, str)
            or status not in _JOB
            or not isinstance(action, str)
            or action not in _ACTIONS
        ):
            return False
        if not isinstance(data.get("message"), str) or len(data["message"]) > 500:
            return False
        if not isinstance(data.get("order"), int) or data["order"] < 1:
            return False
        if not isinstance(data.get("queue_order", data["order"]), int):
            return False
        if "recoverable_status" in data and (
            not isinstance(data["recoverable_status"], str)
            or data["recoverable_status"] not in _ENGINE
        ):
            return False
        if "resume_status" in data and (
            not isinstance(data["resume_status"], str)
            or data["resume_status"] not in _ENGINE
        ):
            return False
        if "normalization_retry" in data and type(data["normalization_retry"]) is not bool:
            return False
        if not self._valid_error_metadata(data):
            return False
        return all(
            isinstance(data.get(key), str) and data[key]
            for key in ("created_at", "updated_at", "queued_at")
        )

    def _recover_interrupted_locked(self, job: dict) -> None:
        try:
            ExecutionHistory(self._job_root(job["id"])).interrupt_execution(
                job.get("execution_id")
            )
        except Exception as exc:
            LOGGER.warning("execution history recovery failed exception_type=%s", type(exc).__name__)
        state = self._persisted_state_status_locked(job["id"])
        action = job["action"]
        if state in {
            "NEEDS_USER_INPUT",
            "PASS_PENDING_USER_APPROVAL",
            "CRITICAL_BLOCKED",
            "FINALIZED",
        } and self._state_was_updated_after_queue_locked(job):
            job.update(
                status=state,
                message=_message_for_status(state),
                recoverable_status=state,
                updated_at=_utc_now(),
            )
            return
        job.update(
            status="interrupted",
            message="작업이 중단되었습니다. 이전 저장 상태로 돌아왔습니다. 수정 또는 답변을 다시 제출하세요.",
            updated_at=_utc_now(),
        )
        if self._can_resume_action(action, state):
            job["recoverable_status"] = state

    def _recover_retry_status_locked(self, job: dict) -> None:
        state = self._persisted_state_status_locked(job["id"])
        if state in _GUARDS.get(job["action"], set()):
            job["recoverable_status"] = state
        job["updated_at"] = _utc_now()

    def _state_was_updated_after_queue_locked(self, job: dict) -> bool:
        try:
            queued_at = datetime.fromisoformat(job["queued_at"])
            if queued_at.tzinfo is None:
                return False
            state_path = self.artifact(job["id"], "state/state.json")
            return state_path.stat().st_mtime_ns >= int(
                queued_at.timestamp() * 1_000_000_000
            )
        except (KeyError, OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _can_resume_action(action: str, status: object) -> bool:
        if not isinstance(action, str) or not isinstance(status, str):
            return False
        if action == "generate":
            return status in {
                "NEEDS_USER_INPUT",
                "PASS_PENDING_USER_APPROVAL",
                "CRITICAL_BLOCKED",
                "FINALIZED",
            }
        return status in _GUARDS.get(action, set())

    def _pending_questions_locked(self, ident: str) -> list[str]:
        state = self._read_json(self.artifact(ident, "state/state.json"))
        questions = state.get("blocking_questions") if state else []
        return (
            questions
            if isinstance(questions, list)
            and all(isinstance(q, str) for q in questions)
            else []
        )

    def _persisted_state_status_locked(self, ident: str) -> str | None:
        state = self._read_json(self.artifact(ident, "state/state.json"))
        status = state.get("status") if state else None
        return status if isinstance(status, str) and status in _ENGINE else None

    def _normalization_retry_allowed_locked(self, job: dict, action: str) -> bool:
        if action != "revise" or job.get("status") not in {"error", "interrupted"}:
            return False
        has_error_code = (
            isinstance(job.get("error_code"), str)
            and job.get("error_code") in (_NORMALIZATION_ERROR_CODES | {"SPEC_COMPILATION_INVALID"})
        )
        return (
            (has_error_code or job.get("normalization_retry") is True)
            and self._has_recoverable_normalization_state_locked(job["id"])
        )

    def _has_recoverable_normalization_state_locked(self, ident: str) -> bool:
        """초기 생성 실패도 실제 저장 상태가 있을 때만 수정 재처리를 허용한다."""
        state_data = self._read_json(self.artifact(ident, "state/state.json"))
        if not isinstance(state_data, dict):
            return False
        required = ("run_id", "status", "user_request", "input_source", "output_dir")
        if not all(
            isinstance(state_data.get(key), str) and state_data[key].strip()
            for key in required
        ):
            return False
        try:
            state = State.from_dict(state_data)
            output_dir = Path(state.output_dir).resolve()
        except (OSError, TypeError, ValueError):
            return False
        if output_dir != self._job_root(ident):
            return False
        if state.status not in _NORMALIZATION_RECOVERY_STATES:
            return False
        evidence = self._read_json(self.artifact(ident, "evidence/evidence_registry.json"))
        return isinstance(evidence, dict)

    def _effective_status_locked(self, job: dict) -> str:
        if job["status"] in {"interrupted", "error"}:
            status = job.get("recoverable_status")
            return status if isinstance(status, str) else ""
        return job["status"]

    def _submit_locked(self, ident: str, action: str, payload: object) -> None:
        deferred = DEFERRED.get()
        if deferred is not None:
            deferred.append((ident, action, payload))
            return
        service = getattr(self, 'public_service', None)
        execution = None
        if service:
            from backend.access.recovery import Execution
            execution = Execution.from_job(self.jobs[ident])
        try:
            from contextvars import copy_context
            run = service.worker if service else self._run
            kwargs = {'execution': execution} if service else {}
            future = self.executor.submit(copy_context().run, run, ident, action, payload, **kwargs)
        except RuntimeError as exc:
            if service:
                from backend.access.recovery import Failure
                service.recovery.record(Failure(execution, False, execution.initial))
            raise RuntimeError("작업 큐를 사용할 수 없습니다.") from exc
        self._futures[future] = (ident, execution)
        future.add_done_callback(self._worker_done)

    def _worker_done(self, future):
        with self.lock:
            tracked = self._futures.pop(future, None)
        if tracked is None:
            return
        ident, execution = tracked
        if future.cancelled():
            if execution is not None:
                from backend.access.recovery import Failure
                self.public_service.recovery.record(Failure(execution, False, execution.initial))
            return
        exc = future.exception()
        if exc is not None:
            LOGGER.error('worker failed job_id=%s execution_id=%s generation=%s exception_type=%s',
                         ident, execution.execution_id if execution else None,
                         execution.generation if execution else None, type(exc).__name__)

    def _start_history_execution_locked(
        self, ident: str, action: str, *, input_data: object = None, execution_id: str | None = None
    ) -> str:
        try:
            return ExecutionHistory(self._job_root(ident)).start_execution(
                action, execution_id, input_data=input_data
            )
        except Exception as exc:
            LOGGER.warning("execution history start failed exception_type=%s", type(exc).__name__)
            return uuid4().hex

    @tracked
    def _run(self, ident: str, action: str, payload: object) -> None:
        with self.lock:
            try:
                job = self._get_locked(ident)
            except KeyError:
                return
            job.update(status="running", message="작업 실행 중", updated_at=_utc_now())
            provider = job["provider"]
            request_text = job["request"]
            resume_status = job.get("resume_status")
            if self.knowledge is not None and action != "generate":
                try:
                    from backend.knowledge.runtime import restore_artifacts
                    restore_artifacts(self._job_root(ident), self.knowledge.store.restore(ident), reconcile=True)
                except Exception:
                    job.update(status="error", message="DB에서 실행 상태를 복원하지 못했습니다.")
                    self._save_locked(job)
                    self._notify(self._snapshot(job))
                    return
            history = ExecutionHistory(self._job_root(ident))
            try:
                execution_id = history.start_execution(action, job.get("execution_id"), input_data=request_text if action == "generate" else payload)
            except Exception as exc:
                LOGGER.warning("execution history start failed exception_type=%s", type(exc).__name__)
                execution_id = job.get("execution_id") or uuid4().hex
            job["execution_id"] = execution_id
            saved = self._save_locked(job)
            if not saved:
                job.update(status="error", message="DB에 실행 상태를 저장하지 못했습니다.")
            snapshot = self._snapshot(job)
        self._notify(snapshot)
        if not saved:
            return
        LOGGER.info(
            "job started id=%s action=%s provider=%s",
            ident,
            action,
            provider,
        )
        try:
            root = self.root(ident)
            from backend.knowledge.runtime import CURRENT, RunKnowledge
            runtime = RunKnowledge(self.knowledge, job, root) if self.knowledge is not None else None
            token = CURRENT.set(runtime)
            if runtime is not None and action != "approve":
                latest = ""
                if action == "revise":
                    latest = str(payload)
                elif action == "answer":
                    latest = "\n".join(item["answer"] for item in payload)
                runtime.refresh((latest + "\n" + request_text).strip()[:20000])
            engine = self._engine_for_provider(provider)
            if action == "generate":
                result = engine.generate_from_text(
                    text=request_text,
                    output_dir=str(root),
                    web_search_mode="off",
                    on_progress=lambda event: self._engine_progress(ident, event),
                )
            elif action == "answer":
                result = engine.answer(
                    str(root),
                    answers=payload,
                    on_progress=lambda event: self._engine_progress(ident, event),
                )
            elif action == "revise":
                feedback = self.artifact(ident, "raw/web_feedback.md")
                feedback.parent.mkdir(parents=True, exist_ok=True)
                feedback.write_text(str(payload).strip() + "\n", encoding="utf-8")
                result = engine.revise(
                    output_dir=str(root),
                    feedback_path=str(feedback),
                    on_progress=lambda event: self._engine_progress(ident, event),
                )
            else:
                result = engine.approve(
                    str(root),
                    on_progress=lambda event: self._engine_progress(ident, event),
                )
            status = result.status if result.status in _ENGINE else "error"
            message = _message_for_status(status)
        except Exception as exc:
            if self.knowledge is not None:
                try:
                    from backend.knowledge.runtime import restore_artifacts
                    restore_artifacts(self._job_root(ident), self.knowledge.store.restore(ident), reconcile=True)
                    ExecutionHistory(self._job_root(ident)).start_execution(
                        action, execution_id, input_data=request_text if action == "generate" else payload)
                except Exception:
                    LOGGER.warning("committed cache recovery failed")
            status = "error"
            message = safe_user_error(exc)
            diagnostic = diagnose_exception(exc)
            _log_job_failure(ident, action, provider, exc, diagnostic=diagnostic)
        else:
            diagnostic = None
        finally:
            if "token" in locals():
                CURRENT.reset(token)
        with self.lock:
            try:
                job = self._get_locked(ident)
            except KeyError:
                return
            job.update(status=status, message=message, updated_at=_utc_now())
            job.pop("resume_status", None)
            if diagnostic is not None:
                self._set_error_metadata(job, diagnostic)
            else:
                self._clear_error_metadata(job)
            if status != "error":
                job.pop("normalization_retry", None)
            if status == "error" and self._can_resume_action(action, resume_status):
                job["recoverable_status"] = resume_status
            else:
                job.pop("recoverable_status", None)
            if not self._save_locked(job):
                job.update(status="error", message="DB에 작업 결과를 저장하지 못했습니다.")
                status = "error"
            snapshot = self._snapshot(job)
            execution_id = job.get("execution_id")
            terminal_result = self._terminal_result_locked(ident, status)
        if isinstance(execution_id, str):
            try:
                history = ExecutionHistory(self._job_root(ident))
                if action == "approve" and status == "FINALIZED":
                    history.capture(execution_id, "approve", root=self._job_root(ident))
                history.terminal(
                    execution_id, status, message, result=terminal_result
                )
            except Exception as exc:
                LOGGER.warning("execution history terminal failed exception_type=%s", type(exc).__name__)
        if self.knowledge is not None and status != "error":
            from backend.knowledge.runtime import RunKnowledge
            try:
                # terminal 이력도 커밋해 재시작 후 단계 상세를 복원한다.
                RunKnowledge(self.knowledge, job, self._job_root(ident)).commit("terminal", {})
            except RuntimeError:
                with self.lock:
                    job.update(status="error", message="DB에 실행 이력을 저장하지 못했습니다.")
                    snapshot = self._snapshot(job)
                    status = "error"
        self._notify(snapshot)
        LOGGER.info(
            "job completed id=%s action=%s provider=%s status=%s",
            ident,
            action,
            provider,
            status,
        )

    def _engine_progress(self, ident: str, event: object) -> None:
        if not isinstance(event, dict):
            return
        stage = event.get("stage")
        state = event.get("state")
        result = event.get("result")
        if not isinstance(stage, str) or not isinstance(state, str):
            return
        logged_stage = stage if stage in _PROGRESS_STAGES else "unknown"
        logged_state = state if state in _PROGRESS_STATES else "unknown"
        with self.lock:
            try:
                job = self._get_locked(ident)
            except KeyError:
                return
            job["progress"] = {"stage": stage, "state": state}
            if state == "retrying" and isinstance(result, dict):
                attempt = result.get("retry_attempt")
                if type(attempt) is int and 1 <= attempt <= 3:
                    job["message"] = f"재시도 중… ({attempt}/3)"
                    job["progress"].update(retry_attempt=attempt, max_retries=3)
            elif state in {"started", "completed"}:
                job["message"] = "작업 실행 중"
            if stage == "await_user" and state == "completed":
                event_result = result if isinstance(result, dict) else {}
                if "blocking_questions" not in event_result:
                    result = {
                        **event_result,
                        "blocking_questions": self._pending_questions_locked(ident),
                    }
            execution_id = job.get("execution_id")
            job["updated_at"] = _utc_now()
            self._save_locked(job)
            snapshot = self._snapshot(job)
        if isinstance(execution_id, str):
            try:
                history = ExecutionHistory(self._job_root(ident))
                from backend.knowledge.runtime import CURRENT
                runtime = CURRENT.get()
                persisted = state == "completed" and runtime is not None and stage in runtime.persisted_history
                if not persisted:
                    history.stage(execution_id, stage, state, result=result if isinstance(result, dict) else None)
                    if state == "completed":
                        history.capture(execution_id, stage, root=self._job_root(ident))
            except Exception as exc:
                LOGGER.warning("execution history progress failed exception_type=%s", type(exc).__name__)
        self._notify(snapshot)
        LOGGER.info(
            "job progress id=%s action=%s provider=%s stage=%s state=%s",
            ident,
            snapshot.get("action", "unknown"),
            snapshot.get("provider", "unknown"),
            logged_stage,
            logged_state,
        )

    def _engine_for_provider(self, provider: str):
        if provider != "openai":
            raise ValueError("OpenAI만 지원합니다.")
        return self.engine_factory()

    def _terminal_result_locked(self, ident: str, status: str) -> dict:
        result = {"status": status}
        if status != "NEEDS_USER_INPUT":
            return result
        state = self._read_json(self.artifact(ident, "state/state.json"))
        questions = state.get("blocking_questions") if isinstance(state, dict) else None
        if isinstance(questions, list) and all(isinstance(item, str) for item in questions):
            result["blocking_questions"] = questions
        if isinstance(state, dict):
            for key in ("awaiting_input_reason", "review_questions", "question_forms"):
                if key in state:
                    result[key] = state[key]
        return result

    def _notify(self, job: dict) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(
                {
                    "event": "job.changed",
                    "job": {
                        key: job[key]
                        for key in ("id", "status", "updated_at")
                        if key in job
                    },
                }
            )
        except Exception:
            return

    def _public_from_snapshot(self, job: dict) -> dict:
        keys = {
            "id",
            "request",
            "demo",
            "provider",
            "status",
            "message",
            "action",
            "created_at",
            "updated_at",
            "queued_at",
            "order",
            "progress",
            "error_code",
            "error_stage",
        }
        result = {
            key: copy.deepcopy(value) for key, value in job.items() if key in keys
        }
        if job.get("status") in {"error", "interrupted"} and isinstance(
            job.get("recoverable_status"), str
        ):
            result["retry_status"] = job["recoverable_status"]
        if self._normalization_retry_allowed_locked(job, "revise"):
            result["retry_action"] = "revise"
        return result

    def _legacy_node(self, job: dict, *, detail: bool = False) -> dict:
        """기존 기록에는 추측한 타임라인 대신 현재 상태 하나만 노출한다."""
        review = self._read_json(
            self.artifact(job["id"], "review/checklist_issues.json")
        )
        issues = review.get("issues") if isinstance(review, dict) else []
        issue_counts = {"blocking": 0, "major": 0, "minor": 0}
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict) or issue.get("status") == "resolved":
                    continue
                severity = issue.get("severity")
                if severity in issue_counts:
                    issue_counts[severity] += 1
        document_info: dict | None = None
        for relative, kind in (
            ("final/FINAL_AGENT_SPEC.md", "final"),
            ("draft/approval_candidate_spec.en.md", "draft"),
            ("critical/CRITICAL_REPORT.ko.md", "report"),
        ):
            path = self.artifact(job["id"], relative)
            if path.is_file():
                document_info = {"path": path, "filename": Path(relative).name, "kind": kind}
                break
        node = {
            "id": "legacy-current",
            "execution_id": "",
            "action": job.get("action", ""),
            "stage": "workflow",
            "title": "이전 기록",
            "status": _legacy_graph_status(job.get("status")),
            "summary": "이전 기록에는 상세 실행 이력이 없습니다.",
            "issue_counts": issue_counts,
            "has_document": document_info is not None,
            "has_issues": bool(sum(issue_counts.values())),
            "detail_available": True,
        }
        if detail:
            result: dict = {"status": job.get("status")}
            if isinstance(review, dict) and isinstance(review.get("issues"), list):
                result["issues"] = review["issues"]
            if document_info is not None:
                content = self._read_text(document_info["path"])
                if content is not None:
                    node["document"] = {
                        "content": content,
                        "filename": document_info["filename"],
                        "kind": document_info["kind"],
                    }
            node["result"] = result
        return node

    @staticmethod
    def _set_error_metadata(job: dict, diagnostic: dict) -> None:
        code = diagnostic.get("error_code")
        stage = diagnostic.get("error_stage")
        if (
            isinstance(code, str)
            and ((code in _NORMALIZATION_ERROR_CODES and stage == "requirement_lock")
                 or (code == "SPEC_COMPILATION_INVALID" and stage == "spec_compile")
                 or (code == "REVIEW_VALIDATION_FAILED" and isinstance(stage, str) and stage in ReviewValidationError.stages))
        ):
            job["error_code"] = code
            job["error_stage"] = stage
        else:
            JobManager._clear_error_metadata(job)

    @staticmethod
    def _clear_error_metadata(job: dict) -> None:
        job.pop("error_code", None)
        job.pop("error_stage", None)

    @staticmethod
    def _valid_error_metadata(data: dict) -> bool:
        code = data.get("error_code")
        stage = data.get("error_stage")
        if code is None and stage is None:
            return True
        return (
            isinstance(code, str)
            and ((code in _NORMALIZATION_ERROR_CODES and stage == "requirement_lock")
                 or (code == "SPEC_COMPILATION_INVALID" and stage == "spec_compile")
                 or (code == "REVIEW_VALIDATION_FAILED" and isinstance(stage, str) and stage in ReviewValidationError.stages))
        )

    def _save_locked(self, data: dict) -> bool:
        if self.knowledge is not None:
            try:
                self.knowledge.store.save_job(data)
            except (RuntimeError, ValueError, TypeError):
                return False
        return self._export_job_locked(data)

    def _save_action_locked(self, job, payload):
        if self.knowledge is None:
            return self._save_locked(job)
        try:
            self.knowledge.store.record_action(job, payload)
        except (RuntimeError, ValueError, TypeError):
            return False
        return self._export_job_locked(job)

    def _export_job_locked(self, data):
        try:
            path = self._job_root(data["id"]) / "job.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            temp.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temp.replace(path)
            return True
        except (OSError, TypeError, ValueError, RuntimeError):
            # DB가 기준 저장소이므로 캐시 쓰기 실패를 DB 저장 실패로 오인하지 않는다.
            return self.knowledge is not None

    @synchronized
    def knowledge_call(self, method: str, params: dict):
        if self.knowledge is None:
            raise RuntimeError("지식 저장소가 설정되지 않았습니다.")
        store = self.knowledge.store
        if method == "projects.list":
            return store.projects()
        if method in {"projects.create", "projects.assign"}:
            raise ValueError("프로젝트 생성·이동은 지원이 종료되었습니다. 대화 세션을 사용하세요.")
        if method == "knowledge.search":
            return self.knowledge.search(params.get("query"), params.get("project_id"), params.get("kind"), params.get("status"), job_id=params.get("job_id"))
        if method == "knowledge.node":
            return store.node(params.get("node_id"))
        if method == "knowledge.graph":
            allowed = {"project_id", "job_id", "kind", "status", "node_id", "depth", "limit"}
            return store.graph(**{key: value for key, value in params.items() if key in allowed})
        if method == "knowledge.document":
            return store.artifact_page(params.get("job_id"), params.get("path"), params.get("content_hash"), params.get("offset", 0))
        if method == "knowledge.retry":
            self.knowledge.schedule()
            return {"status": "queued"}
        raise ValueError("알 수 없는 지식 조회입니다.")

    def _job_root(self, ident: str) -> Path:
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            raise KeyError(ident)
        root = (self.data_dir / ident).resolve()
        try:
            root.relative_to(self.data_dir)
        except ValueError as exc:
            raise KeyError(ident) from exc
        if root.parent != self.data_dir or root.name != ident:
            raise KeyError(ident)
        return root

    def _get_locked(self, ident: str) -> dict:
        if (
            not isinstance(ident, str)
            or not _ID.fullmatch(ident)
            or ident not in self.jobs
        ):
            raise KeyError(ident)
        job = self.jobs[ident]
        if ACTOR.get() is not None and job.get('owner_id') != ACTOR.get()['id']:
            raise KeyError(ident)
        return job

    def _queue_position_locked(self, ident: str) -> int:
        active = sorted(
            (job for job in self.jobs.values() if job["status"] in _ACTIVE),
            key=lambda job: job.get("queue_order", job["order"]),
        )
        return next(
            index for index, job in enumerate(active, start=1) if job["id"] == ident
        )

    def _new_order(self) -> int:
        self._next_order += 1
        return self._next_order

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("서버가 종료 중입니다.")

    @staticmethod
    def _snapshot(job: dict) -> dict:
        return copy.deepcopy(job)

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def _validate_request(request: object, demo: object, provider: object) -> str:
        if not isinstance(request, str) or not request.strip() or len(request) > 20_000:
            raise ValueError("요청은 1~20,000자로 입력하세요.")
        if demo is not None and demo is not False:
            raise ValueError("데모 실행은 지원하지 않습니다.")
        if provider is not None and provider != "openai":
            raise ValueError("OpenAI만 지원합니다.")
        return "openai"

    @staticmethod
    def _validate_payload(action: str, payload: object, questions: list[str], forms=None) -> None:
        if action == "answer":
            if not isinstance(payload, list) or not payload or len(payload) > 20:
                raise ValueError("한 개 이상의 답변을 입력하세요.")
            seen: set[str] = set()
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("답변 형식이 올바르지 않습니다.")
                question_id, question, answer = (
                    item.get("question_id"),
                    item.get("question"),
                    item.get("answer"),
                )
                if not all(
                    isinstance(value, str) for value in (question_id, question, answer)
                ):
                    raise ValueError("질문과 답변은 텍스트로 입력하세요.")
                if (
                    not question_id.strip()
                    or not question.strip()
                    or not answer.strip()
                    or len(question_id) > 160
                    or len(question) > 10_000
                    or len(answer) > 20_000
                    or question_id in seen
                ):
                    raise ValueError("답변 내용을 확인하세요.")
                seen.add(question_id)
                if not any(
                    f"[{question_id}]" in pending or question.strip() == pending.strip()
                    for pending in questions
                ):
                    raise ValueError("대기 중인 질문에만 답변할 수 있습니다.")
            if any(any(k in item for k in ("form_version", "selected_option_ids", "custom_text")) for item in payload):
                from backend.engine import _validate_answers
                from backend.errors import InvalidStateError
                try:
                    _validate_answers(payload, questions, forms)
                except InvalidStateError as error:
                    raise ValueError(str(error)) from error
        elif action == "revise":
            if (
                not isinstance(payload, str)
                or not payload.strip()
                or len(payload) > 20_000
            ):
                raise ValueError("수정 의견은 1~20,000자로 입력하세요.")
        elif action == "approve" and payload not in (None, {}):
            raise ValueError("승인 요청 형식이 올바르지 않습니다.")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _message_for_status(status: str) -> str:
    return {
        "NEEDS_USER_INPUT": "진행에 필요한 요구사항을 확인해주세요.",
        "PASS_PENDING_USER_APPROVAL": "검토를 통과했습니다. 내용을 확인한 뒤 승인하세요.",
        "CRITICAL_BLOCKED": "자동 보완으로 명세의 결함을 해결하지 못했습니다. 보완 내역과 실패 원인을 확인하세요.",
        "FINALIZED": "최종 명세가 준비되었습니다.",
        "APPROVED": "승인이 처리되었습니다.",
    }.get(status, "작업이 완료되었습니다.")


def _legacy_graph_status(status: object) -> str:
    if status == "CRITICAL_BLOCKED":
        return "blocked"
    if status == "NEEDS_USER_INPUT":
        return "waiting"
    if status == "PASS_PENDING_USER_APPROVAL":
        return "waiting_approval"
    if status == "interrupted":
        return "interrupted"
    if status == "error":
        return "failed"
    return "completed"


def _log_job_failure(
    ident: str,
    action: str,
    provider: str,
    exc: BaseException,
    *,
    diagnostic: dict | None = None,
) -> None:
    diagnostic = diagnostic or diagnose_exception(exc)
    LOGGER.error(
        "job failed id=%s action=%s provider=%s reason=%s "
        "error_code=%s error_stage=%s exception_type=%s cause_types=%s "
        "http_status=%s failed_checks=%s frames=%s",
        ident,
        action,
        provider,
        diagnostic["reason"],
        diagnostic["error_code"],
        diagnostic["error_stage"],
        diagnostic["exception_type"],
        diagnostic["cause_types"],
        diagnostic["http_status"],
        diagnostic["failed_checks"],
        diagnostic["frames"],
    )
