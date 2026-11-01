"""프로젝트 결정과 지식 조회."""
from __future__ import annotations
import copy
from backend.errors import ArtifactError, InvalidStateError


class ProjectQueries:
    def __init__(self, access):
        self.documents = access.documents
        self.get = access.get
        self.knowledge = access.knowledge
        self.state = access.state

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
