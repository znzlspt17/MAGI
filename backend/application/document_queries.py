"""불변 문서 조회와 패키지 제공."""
from __future__ import annotations
from typing import Any
import re
import threading
from pathlib import Path
from backend.errors import InvalidStateError
from backend.application.activity import tracked
from backend.application.execution_history import ExecutionHistory
from backend.services.spec_translation import korean_translation, source_key
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
                detail: dict[str, Any] | None = {
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
