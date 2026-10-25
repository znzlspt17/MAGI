"""작업·문서 조회와 지식 기능. 실행 큐와 모델 작업 예약을 관리하지 않는다."""

from __future__ import annotations

import copy
import re
import threading
from pathlib import Path

from backend.access.context import ACTOR
from backend.errors import ArtifactError, InvalidStateError
from backend.knowledge.runtime import RunKnowledge
from backend.server.cleanup import tracked
from backend.server.execution_history import ExecutionHistory
from backend.services.saved_answers import saved_answer_dicts
from backend.services.spec_translation import korean_translation, source_key

_ACTIVE = {"queued", "running"}


class Workspace:
    def __init__(self, knowledge, engine_factory, lock, activities):
        self.knowledge, self.engine_factory, self.lock, self._activities = (
            knowledge,
            engine_factory,
            lock,
            activities,
        )
        self._document_locks = {}
        from backend.services.implementation_package import PackageCache

        self._package_cache = PackageCache()

    def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise KeyError(ident)
        with self.knowledge.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT data,owner_id FROM jobs WHERE id=%s", (ident,)
            ).fetchone()
        if not row or (
            ACTOR.get() is not None and row["owner_id"] != ACTOR.get()["id"]
        ):
            raise KeyError(ident)
        return {**row["data"], "owner_id": row["owner_id"]}

    def documents(self, ident):
        self.get(ident)
        return self.knowledge.store.documents(ident)

    def state(self, ident):
        return self.knowledge.store.state(self.get(ident)["id"])

    def read_json(self, ident, name):
        docs = self.documents(ident)
        return docs.read_json(name) if docs.exists(name) else None

    def read_text(self, ident, name):
        docs = self.documents(ident)
        return docs.read_text(name) if docs.exists(name) else None

    def engine(self, ident, meter=None):
        docs = self.documents(ident)
        docs.state = self.state(ident)
        runtime = RunKnowledge(self.knowledge, self.get(ident), docs, meter=meter)
        docs.runtime = runtime
        return self.engine_factory(docs, runtime)

    def allowed(self, ident):
        job = self.get(ident)
        if job["status"] in _ACTIVE:
            return []
        if job["status"] in {"error", "interrupted"}:
            from backend.infrastructure.workflow_store import retry_state
            recovery = retry_state(self.documents(ident))
            return ["message", "retry"] if recovery["can_retry"] else ["message"]
        state = self.state(ident)
        if not state:
            return []
        if state.get("status") == "FINALIZED":
            return ["message", "continue"]
        return state.get("allowed_actions", [])

    def summary(self, ident):
        job = self.get(ident)
        state = self.state(ident)
        actions = self.allowed(ident)
        recovery = {}
        if job["status"] in {"error", "interrupted"}:
            from backend.infrastructure.workflow_store import retry_state
            recovery = {k:v for k,v in retry_state(self.documents(ident)).items() if k != "task_id"}
        keys = (
            "id",
            "request",
            "status",
            "message",
            "action",
            "created_at",
            "updated_at",
            "execution_id",
            "project_id",
            "progress",
        )
        return {
            **{k: copy.deepcopy(job[k]) for k in keys if k in job},
            "can_retry": "retry" in actions,
            "can_continue": "continue" in actions,
            "read_only": not state,
            "latest_completed": state.get("latest_completed"),
            "reused_decision_count": len(job.get("reused_decisions", [])),
            **recovery,
        }

    def public(self, ident):
        job = self.summary(ident)
        state = self.state(ident)
        history = ExecutionHistory(self.documents(ident))
        keys = (
            "status",
            "blocking_questions",
            "critic_pass_count",
            "awaiting_input_reason",
            "review_questions",
            "question_forms",
            "plan",
            "wait_reason",
            "stop_reason",
            "revision",
            "candidate_hash",
            "document_versions",
            "task_results",
        )
        job["state"] = {
            **{k: state[k] for k in keys if k in state},
            "allowed_actions": self.allowed(ident),
            "saved_answers": saved_answer_dicts(state),
        }
        job["execution_graph"], job["session_events"] = (
            history.graph(),
            history.conversation(),
        )
        from backend.services.completed_specs import completed_references

        job["completed_documents"] = [
            {
                "id": Path(n).stem,
                "title": "완료 명세 · " + Path(n).stem[:8],
                "detail_available": True,
                "has_document": True,
                "stage": "completed_document",
            }
            for n in completed_references(state)
        ]
        for name, key in [
            ("draft/approval_candidate_spec.en.md", "candidate"),
            ("final/FINAL_AGENT_SPEC.md", "final"),
            ("critical/CRITICAL_REPORT.ko.md", "critical"),
        ]:
            text = self.read_text(ident, name)
            if text is not None and (key != "critical" or state.get("critical_report")):
                job[key] = text
        review = self.read_json(ident, "analysis/change_review.json")
        from backend.services.change_review import digest, normalize

        if review and review.get("after_hash") == digest(
            normalize(job.get("candidate", ""))
        ):
            job["change_review"] = review
        return job

    @tracked
    def document(self, ident, step_id, language, *, meter=None):
        if language not in {"ko", "en"}:
            raise ValueError("문서 언어를 확인하세요.")
        doc = self.step(ident, step_id).get("document")
        if not doc or not isinstance(doc.get("content"), str):
            raise KeyError(step_id)
        if language == "en":
            return {**doc, "language": "en"}
        with self.lock:
            guard = self._document_locks.setdefault(
                (ident, source_key(doc["content"])), threading.Lock()
            )
        with guard:
            engine = self.engine(ident, meter=meter)
            translated = korean_translation(
                doc["content"],
                writer=self.documents(ident).scope(
                    "translations/" + source_key(doc["content"])
                ),
                provider=engine.provider,
                model=engine.config.model_routing["compiler"].model,
            )
        return {
            **doc,
            **translated,
            "filename": Path(doc.get("filename", "SPEC.en.md")).stem.removesuffix(".en")
            + ".ko.md",
        }

    def step(self, ident: str, step_id: str) -> dict:
        """선택한 실행 노드의 저장된 상세만 돌려준다."""
        with self.lock:
            self.get(ident)
            if not isinstance(step_id, str) or len(step_id) > 64:
                raise KeyError(ident)
            history = ExecutionHistory(self.documents(ident))
            if re.fullmatch("[0-9a-f]{64}", step_id):
                from backend.services.completed_specs import (
                    completed_references,
                    load_completed,
                )

                state = self.state(ident) or {}
                if f"completed/{step_id}.json" not in completed_references(state):
                    raise KeyError(step_id)
                content = load_completed(self.documents(ident), step_id)["content"]
                detail = {
                    "id": step_id,
                    "stage": "completed_document",
                    "title": "보존된 완료 명세",
                    "status": "completed",
                    "document": {
                        "content": content,
                        "filename": "FINAL_AGENT_SPEC.en.md",
                        "kind": "final",
                        "completed_id": step_id,
                    },
                }
            else:
                detail = history.detail(step_id)
            if detail is None:
                raise KeyError(ident)
            document = detail.get("document")
            if isinstance(document, dict) and isinstance(document.get("content"), str):
                document["source_hash"] = source_key(document["content"])
                if document.get("kind") == "final":
                    from backend.services.completed_specs import (
                        completed_references,
                        load_completed,
                    )

                    state = self.state(ident) or {}
                    matches = []
                    for path in completed_references(state):
                        try:
                            if (
                                load_completed(self.documents(ident), Path(path).stem)[
                                    "content"
                                ]
                                == document["content"]
                            ):
                                matches.append(Path(path).stem)
                        except InvalidStateError:
                            continue
                    if document.get("completed_id") not in matches:
                        document.pop("completed_id", None)
                    if not document.get("completed_id") and len(matches) == 1:
                        document["completed_id"] = matches[0]
            return detail

    def implementation_package(self, ident, params, *, read_file=False):
        from backend.services.completed_specs import (
            completed_references,
            load_completed,
        )
        from backend.services.implementation_package import create_package, file_chunk
        from backend.services.spec_translation import cached_translation

        with self.lock:
            self.get(ident)
            writer = self.documents(ident)
            state = self.state(ident) or {}
            completed_id = params.get("completed_id")
            if completed_id is None:
                completed_id = (state.get("latest_completed") or {}).get("id")
            if not isinstance(completed_id, str) or not re.fullmatch(
                "[0-9a-f]{64}", completed_id
            ):
                raise KeyError(ident)
            if f"completed/{completed_id}.json" not in completed_references(state):
                raise KeyError(ident)
            archive = load_completed(writer, completed_id)
        bundle_id = params.get("bundle_id")
        if (read_file or bundle_id is not None) and (
            not isinstance(bundle_id, str)
            or not re.fullmatch("[0-9a-f]{64}", bundle_id)
        ):
            raise ValueError("묶음 식별값이 올바르지 않습니다.")
        cached = (
            self._package_cache.get((ident, completed_id, bundle_id))
            if bundle_id
            else None
        )
        if cached is None:
            doc = {"content": archive["content"], "filename": "SPEC.en.md"}
            translated = cached_translation(
                doc, writer.scope("translations/" + source_key(archive["content"]))
            )
            metadata, files = create_package(
                completed_id, archive, translated["content"] if translated else None
            )
            if bundle_id is not None and bundle_id != metadata["bundle_id"]:
                raise ValueError(
                    "묶음 자료가 변경되었습니다. 포함 자료를 다시 조회하세요."
                )
            self._package_cache.put(
                (ident, completed_id, metadata["bundle_id"]), metadata, files
            )
        else:
            metadata, files = cached
        if read_file:
            return file_chunk(
                metadata, files, params.get("file_id"), params.get("offset", 0)
            )
        return metadata

    def requirement_review(self, ident, params):
        """선택한 이력과 일치하는 불변 자료만 사용한다. 모델과 과금 경로는 호출하지 않는다."""
        from backend.services.change_review import LATEST
        from backend.services.requirement_review import build_review, load_snapshot

        with self.lock:
            job = self.get(ident)
            writer = self.documents(ident)
            step_id = params.get("step_id")
            snapshot, basis_id, review_status = (None, None, "unknown")
            if step_id:
                detail = self.step(ident, step_id)
                document = detail.get("document") or {}
                content = document.get("content", "")
                if document.get("kind") not in {"candidate", "final"}:
                    return {
                        "status": "unavailable",
                        "message": "검토 후보 또는 완료 명세에서 근거표를 확인할 수 있습니다.",
                    }
                basis_id = (detail.get("change_review") or {}).get("after_id")
                if re.fullmatch("[0-9a-f]{64}", step_id):
                    from backend.services.completed_specs import load_completed

                    archive = load_completed(writer, step_id)
                    basis_id = archive.get("review_snapshot_id")
                else:
                    basis_id = detail.get("review_snapshot_id") or basis_id
                snapshot = load_snapshot(writer, basis_id, content)
                if snapshot is None and re.fullmatch("[0-9a-f]{64}", step_id):
                    frozen_sheet = archive.get("basis", {}).get(
                        "requirement_lock_sheet"
                    )
                    links = archive.get("trace", {}).get("links", [])
                    if isinstance(frozen_sheet, dict) and links:
                        snapshot = {
                            "requirements": frozen_sheet,
                            "compiled_blocks": [
                                {**link, "text": link["quote"]} for link in links
                            ],
                        }
                        basis_id = step_id
                if snapshot:
                    review_status = (
                        "approved"
                        if document.get("kind") == "final"
                        else "pending_approval"
                    )
            else:
                if job["status"] not in {"PASS_PENDING_USER_APPROVAL", "FINALIZED"}:
                    return {
                        "status": "unavailable",
                        "message": "검토 후보가 준비되면 요구사항별 근거를 확인할 수 있습니다.",
                    }
                path = (
                    "final/FINAL_AGENT_SPEC.md"
                    if job["status"] == "FINALIZED"
                    else "draft/approval_candidate_spec.en.md"
                )
                content = self.read_text(ident, path) or ""
                basis_id = (self.read_json(ident, LATEST) or {}).get("id")
                snapshot = load_snapshot(writer, basis_id, content)
                if snapshot:
                    review_status = (
                        "approved"
                        if job["status"] == "FINALIZED"
                        else "pending_approval"
                    )
            if not content:
                return {"status": "unavailable", "message": "기준 명세가 없습니다."}
            return build_review(
                content,
                snapshot,
                basis_id=basis_id if snapshot else step_id,
                review_status=review_status,
                offset=params.get("offset", 0),
                query=params.get("query", ""),
                missing=params.get("missing", False),
                evidence_for=params.get("evidence_for"),
            )

    def impact_context(self, params):
        from backend.knowledge.impact import impact_context

        ident = params.get("job_id")
        with self.lock:
            job = self.get(ident)
            if job["status"] not in {"PASS_PENDING_USER_APPROVAL", "FINALIZED"}:
                raise ValueError(
                    "승인 후보가 준비된 작업에서 변경 영향을 검토할 수 있습니다."
                )
        node_id = params.get("node_id") or None
        if node_id is not None and (
            not isinstance(node_id, str) or not re.fullmatch("[0-9a-f]{64}", node_id)
        ):
            raise ValueError("요구사항 항목이 올바르지 않습니다.")
        return impact_context(self.knowledge.store, ident, node_id)

    def impact(self, params):
        from backend.knowledge.impact import impact_page

        return impact_page(self.impact_context(params), params.get("offset", 0))

    def cached_impact(self, params, request_key):
        from backend.knowledge.projection import digest
        from backend.services.impact_review import validate_request

        validate_request(params)
        ident = params.get("job_id")
        self.get(ident)
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("중복 방지 요청 키가 필요합니다.")
        record = self.read_json(ident, f"impact_requests/{digest(request_key)}.json")
        if not record:
            return None
        if record.get("fingerprint") != digest(params):
            raise ValueError("같은 요청 키에 다른 변경 가정을 사용할 수 없습니다.")
        key = record.get("id", "")
        if not re.fullmatch("[0-9a-f]{64}", key):
            raise ValueError("저장된 분석을 확인할 수 없습니다.")
        with self.lock:
            analysis_lock = self._document_locks.setdefault(
                (ident, "impact:" + key), threading.Lock()
            )
        if analysis_lock.locked():
            return None
        report = self.read_json(ident, f"impact_reviews/{key}/report.json")
        if report is None:
            raise ValueError(
                "접수된 분석의 결과를 확인할 수 없습니다. 자동 재전송하지 않습니다."
            )
        if report["status"] == "running":
            report = {
                **report,
                "status": "interrupted",
                "reason": "중단된 호출은 자동 재전송하지 않습니다.",
            }
        return self._impact_result(params, report)

    def _impact_result(self, params, report):
        self.get(params.get("job_id"))
        try:
            current = self.impact_context(params)["basis"]["id"]
        except ValueError:
            current = None
        return {**report, "stale": current != report.get("basis", {}).get("id")}

    @tracked
    def impact_analyse(self, ident, params, request_key, *, meter=None):
        from backend.knowledge.projection import digest

        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 128:
            raise ValueError("중복 방지 요청 키가 필요합니다.")
        with self.lock:
            request_lock = self._document_locks.setdefault(
                (ident, "impact-request:" + digest(request_key)), threading.Lock()
            )
        with request_lock:
            return self._impact_analyse(ident, params, request_key, meter=meter)

    def _impact_analyse(self, ident, params, request_key, *, meter=None):
        from backend.knowledge.projection import digest
        from backend.services.impact_review import prepare_review, run_review

        cached = self.cached_impact(params, request_key)
        if cached is not None:
            return cached
        context = self.impact_context(params)
        ranked = self.knowledge.search(
            params["proposal"], kind="spec", job_id=params["job_id"]
        )
        prepared = prepare_review(
            context, params, [node["id"] for node in ranked.get("nodes", [])]
        )
        key = prepared[0]
        if params["job_id"] != ident:
            raise ValueError("작업 범위가 일치하지 않습니다.")
        with self.lock:
            analysis_lock = self._document_locks.setdefault(
                (ident, "impact:" + key), threading.Lock()
            )
        with analysis_lock:
            writer = self.documents(ident).scope(f"impact_reviews/{key}")
            root = self.documents(ident)
            request_path = f"impact_requests/{digest(request_key)}.json"
            root.write_json(request_path, {"id": key, "fingerprint": digest(params)})

            engine = self.engine(ident, meter=meter)
            report = run_review(
                writer,
                engine.provider,
                engine.config.model_routing["compiler"].model,
                prepared,
                context["basis"],
            )
        return self._impact_result(params, report)

    def knowledge_call(self, method: str, params: dict):
        store = self.knowledge.store
        if method == "projects.list":
            return store.projects()
        if method == "projects.create":
            return store.create_project(params.get("name"))
        if method == "projects.reused_decisions":
            from backend.services.project_decisions import page

            job = self.get(params.get("job_id"))
            items = copy.deepcopy(job.get("reused_decisions", []))
            for item in items:
                item["source_available"] = False
                try:
                    self._validate_reuse_sources([item])
                    item["source_available"] = True
                except (
                    KeyError,
                    ValueError,
                    InvalidStateError,
                    ArtifactError,
                    OSError,
                ):
                    pass
            return page({"rows": items, "total": len(items)}, params.get("offset", 0))
        if method == "projects.decisions":
            return self.project_decisions(params)
        if method == "projects.decisions.register":
            with store.transaction():
                if not isinstance(params.get("completed_id"), str):
                    raise ValueError("등록할 승인본을 선택하세요.")
                with store.transaction(mode="read") as conn:
                    store.require_project(conn, params.get("project_id"))
                packet = self.decision_candidates(params.get("job_id"), params)
                candidate = next(
                    (
                        d
                        for d in packet["rows"]
                        if d["decision_id"] == params.get("decision_id")
                    ),
                    None,
                )
                if (
                    not candidate
                    or candidate["project_id"] != params.get("project_id")
                    or candidate["source_hash"] != params.get("source_hash")
                ):
                    raise ValueError("승인된 결정과 출처를 다시 확인하세요.")
                return store.register_decision(params["project_id"], candidate)
        if method == "projects.decisions.deactivate":
            return store.deactivate_decision(
                params.get("project_id"),
                params.get("decision_id"),
                params.get("version"),
            )
        if method == "projects.decision_candidates":
            from backend.services.project_decisions import page

            return page(
                self.decision_candidates(params.get("job_id"), params),
                params.get("offset", 0),
            )
        if method == "knowledge.search":
            return self.knowledge.search(
                params.get("query"),
                params.get("project_id"),
                params.get("kind"),
                params.get("status"),
                job_id=params.get("job_id"),
            )
        if method == "knowledge.node":
            return store.node(params.get("node_id"))
        if method == "knowledge.graph":
            allowed = {
                "project_id",
                "job_id",
                "kind",
                "status",
                "node_id",
                "depth",
                "limit",
            }
            return store.graph(
                **{key: value for key, value in params.items() if key in allowed}
            )
        if method == "knowledge.document":
            return store.artifact_page(
                params.get("job_id"),
                params.get("path"),
                params.get("content_hash"),
                params.get("offset", 0),
            )
        if method == "knowledge.retry":
            self.knowledge.schedule()
            return {"status": "queued"}
        raise ValueError("알 수 없는 지식 조회입니다.")

    def decision_candidates(self, ident, params):
        from backend.services.completed_specs import (
            completed_references,
            load_completed,
        )
        from backend.services.project_decisions import candidates

        job = self.get(ident)
        writer = self.documents(ident)
        state = self.state(ident) or {}
        completed_id = params.get("completed_id") or (
            state.get("latest_completed") or {}
        ).get("id")
        if not isinstance(
            completed_id, str
        ) or f"completed/{completed_id}.json" not in completed_references(state):
            raise KeyError("completed")
        archive = load_completed(writer, completed_id)
        rows = candidates(archive, completed_id, ident, job.get("project_id"))
        return {
            "rows": rows,
            "completed_id": completed_id,
            "project_id": job.get("project_id"),
            "total": len(rows),
        }

    def _validate_reuse_sources(self, items):
        for item in items:
            with self.knowledge.store.transaction(mode="read") as conn:
                if not conn.execute(
                    "SELECT 1 FROM jobs WHERE id=%s AND project_id=%s",
                    (item["job_id"], item["project_id"]),
                ).fetchone():
                    raise KeyError("source")
            try:
                packet = self.decision_candidates(
                    item["job_id"], {"completed_id": item["completed_id"]}
                )
            except (ArtifactError, InvalidStateError):
                raise ValueError(
                    "결정의 승인 출처를 읽을 수 없습니다. 다시 확인하세요."
                ) from None
            if not any(
                (
                    c["decision_id"] == item["decision_id"]
                    and all(
                        (
                            c[k] == item[k]
                            for k in (
                                "text",
                                "conditions",
                                "source_hash",
                                "actor",
                                "project_id",
                                "evidence",
                            )
                        )
                    )
                    for c in packet["rows"]
                )
            ):
                raise ValueError(
                    "결정의 승인 출처를 검증하지 못했습니다. 다시 확인하세요."
                )

    def project_decisions(self, params):
        offset = params.get("offset", 0)
        query, status = (params.get("query", ""), params.get("status", "active"))
        if (
            type(offset) is not int
            or offset < 0
            or (not isinstance(query, str))
            or (len(query) > 200)
            or (status not in {"active", "inactive", "all"})
        ):
            raise ValueError("목록 조회 형식을 확인하세요.")
        rows = self.knowledge.store.registered_decisions(params.get("project_id"))
        rows = [
            r
            for r in rows
            if (status == "all" or r["active"] == (status == "active"))
            and query.casefold() in (r["text"] + r["conditions"]).casefold()
        ]
        from backend.services.project_decisions import page

        packet = page(
            {"rows": rows, "total": len(rows), "project_id": params["project_id"]},
            offset,
        )
        rows = packet["rows"]
        for item in rows:
            item["source_available"] = False
            item["stale"] = False
            try:
                self._validate_reuse_sources([item])
                source = self.state(item["job_id"]) or {}
                item["stale"] = bool(
                    source.get("latest_completed")
                    and source["latest_completed"]["id"] != item["completed_id"]
                )
                item["source_available"] = True
            except (KeyError, ValueError, InvalidStateError, ArtifactError, OSError):
                pass
        return packet
