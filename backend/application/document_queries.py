"""불변 문서 조회와 패키지 제공."""
from __future__ import annotations
from typing import Any
import re
from pathlib import Path
from backend.errors import InvalidStateError
from backend.application.execution_history import ExecutionHistory
from backend.services.document_hash import source_key
from backend.services.implementation_package import PackageCache


class DocumentQueries:
    def __init__(self, access, *, lock, activities, document_locks):
        self._document_locks = document_locks
        self._package_cache = PackageCache()
        self.documents = access.documents
        self.engine = access.engine
        self.get = access.get
        self.lock = lock
        self.state = access.state
        self._activities = activities

    def document(self, ident, step_id, *, meter=None):
        doc = self.step(ident, step_id).get("document")
        if not doc or not isinstance(doc.get("content"), str):
            raise KeyError(step_id)
        return {**doc, "language": "ko"}

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
                detail: dict[str, Any] | None = {
                    "id": step_id,
                    "stage": "completed_document",
                    "title": "보존된 완료 명세",
                    "status": "completed",
                    "document": {
                        "content": content,
                        "filename": "FINAL_AGENT_SPEC.ko.md",
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
                document["language"] = "ko"
                filename = document.get("filename", "SPEC.md")
                if not filename.endswith(".ko.md"):
                    document["filename"] = Path(filename).stem + ".ko.md"
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
            metadata, files = create_package(completed_id, archive)
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
