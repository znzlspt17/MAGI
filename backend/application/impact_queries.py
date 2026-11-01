"""변경 영향 조회와 분석 실행."""
from __future__ import annotations
import re
import threading
from backend.application.activity import tracked


class ImpactQueries:
    def __init__(self, access, *, lock, activities, document_locks):
        self._document_locks = document_locks
        self.documents = access.documents
        self.engine = access.engine
        self.get = access.get
        self.knowledge = access.knowledge
        self.lock = lock
        self.read_json = access.read_json
        self._activities = activities

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
