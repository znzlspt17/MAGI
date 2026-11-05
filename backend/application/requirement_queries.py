"""저장된 명세의 요구사항 근거 조회."""
from __future__ import annotations
import re


class RequirementQueries:
    def __init__(self, access, *, lock, documents):
        self.documents = access.documents
        self.get = access.get
        self.lock = lock
        self.read_json = access.read_json
        self.read_text = access.read_text
        self.step = documents.step

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
                    else "draft/approval_candidate_spec.ko.md"
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
