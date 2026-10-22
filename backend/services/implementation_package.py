"""승인 자료로만 구성하는 구현 묶음과 크기가 제한된 임시 전송 캐시."""
import base64
from collections import OrderedDict
import hashlib
import json
import threading
import time

from backend.services.implementation_plan import valid_plan
from backend.services.spec_compiler import _rendered_sections

CHUNK = 48 * 1024
FILE_LIMIT = 4 * 1024 * 1024
TOTAL_LIMIT = 16 * 1024 * 1024
NAMES = {"README.ko.md", "SPEC.en.md", "SPEC.ko.md", "TASKS.md", "CONSTRAINTS.md", "VERIFICATION.md", "manifest.json"}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def create_package(completed_id, archive, korean=None):
    content = archive["content"]
    sections = _rendered_sections(content)
    plan = archive.get("implementation_plan")
    structured = valid_plan(plan, content)
    limits = [] if structured else ["작업별 의존관계·완료 조건 연결 자료 부족"]
    if not korean:
        limits.append("저장된 번역 없음 · 영어 원문 포함")
    documents = {"SPEC.en.md": [content], "TASKS.md": ["# Implementation tasks\n\n", sections.get("implementation_order", "No implementation-order section was preserved."), "\n\n"]}
    if structured:
        sources = {s["item_id"]: s for s in plan["sources"]}
        documents["TASKS.md"] = ["# Approved implementation tasks\n\nRecommended and optional work remain non-mandatory.\n\n"]
        for task in plan["tasks"]:
            documents["TASKS.md"].extend([task["rendered"], "\n\n"])
            for field, title in (("spec_item_ids", "Specification source text"), ("completion_item_ids", "Completion source text")):
                documents["TASKS.md"].extend([title + ":\n\n"])
                for ref in task[field]:
                    documents["TASKS.md"].extend([f'[{ref}] (SPEC.en.md / {sources[ref]["section"]})\n\n', sources[ref]["text"], "\n\n"])
    else:
        documents["TASKS.md"].insert(1, "작업별 의존관계·완료 조건 연결 자료 부족\n\n")
    documents["CONSTRAINTS.md"] = ["# Product constraints and exclusions\n\nSource: SPEC.en.md / 10. Forbidden Behaviors\n\n", sections.get("forbidden_behaviors", "No forbidden-behavior section was preserved."),
                                  "\n\n## Out of scope\n\nSource: SPEC.en.md / 4.2 Out of Scope\n\n", sections.get("out_of_scope", "No exclusion section was preserved.")]
    documents["VERIFICATION.md"] = ["# Verification checklist\n\n실행 전 확인 목록 · 실제 테스트 결과 미수집\n\n"]
    for key, title in (("acceptance_criteria", "Acceptance criteria"), ("test_plan", "Test plan"), ("manual_verification_checklist", "Manual verification")):
        documents["VERIFICATION.md"].extend([f"## {title}\n\n", sections.get(key, "No section was preserved."), "\n\n"])
    if structured:
        from backend.services.implementation_plan import CHECKS
        linked = {ref for task in plan["tasks"] for ref in task["completion_item_ids"]}
        unlinked = [s for s in plan["sources"] if s["section"] in CHECKS and s["item_id"] not in linked]
        if unlinked:
            documents["VERIFICATION.md"].append("## 작업에 연결되지 않은 검증 본문\n\n")
            for source in unlinked:
                documents["VERIFICATION.md"].extend([f'[{source["item_id"]}] (SPEC.en.md / {source["section"]})\n\n', source["text"], "\n\n"])
    documents["VERIFICATION.md"].append("연결되지 않은 본문도 위 원문에 포함됩니다. 문서의 통과 표현은 실제 실행 결과로 해석하지 마세요.\n")
    documents["README.ko.md"] = [f"# 구현 시작용 자료\n\n승인 완료본: {completed_id}\n\n명세 SHA-256: {sha(content.encode('utf-8'))}\n\n",
        "SPEC.en.md를 먼저 읽고 TASKS.md의 선행 관계에 따라 구현하세요. CONSTRAINTS.md의 제품 제약·비범위를 지키고 VERIFICATION.md로 구현 후 검증을 계획하세요. 권장·선택 작업은 필수가 아닙니다.\n\n",
        "영어 원문이 기준입니다. 한국어본은 같은 버전의 저장·검증된 번역이 있을 때만 포함됩니다. 문서 검토는 구현이나 테스트 실행을 뜻하지 않습니다.\n\n",
        "## 자료 범위\n\n", "\n".join("- " + v for v in limits) or "- 승인된 구조화 작업 계획 포함", "\n"]
    if korean:
        documents["SPEC.ko.md"] = [korean]
    files, entries = {}, []
    for name, parts in documents.items():
        size, checksum, data = 0, hashlib.sha256(), bytearray()
        for part in parts:
            raw = part.encode("utf-8")
            size += len(raw); checksum.update(raw)
            if size <= FILE_LIMIT:
                data.extend(raw)
        entries.append({"name": name, "size": size, "sha256": checksum.hexdigest()})
        if size <= FILE_LIMIT:
            files[name] = bytes(data)
    identity = {"format_version": 1, "completed_id": completed_id, "source_hash": sha(content.encode("utf-8")),
                "files": entries, "completeness": "complete" if structured else "limited", "korean_included": bool(korean),
                "task_count": len(plan["tasks"]) if structured else 0, "limitations": limits}
    bundle_id = sha(serialize(identity))
    manifest = {**identity, "bundle_id": bundle_id, "test_status": "not_collected"}
    files["manifest.json"] = serialize(manifest)
    total = sum(e["size"] for e in entries) + len(files["manifest.json"])
    available = all(e["size"] <= FILE_LIMIT for e in entries) and total <= TOTAL_LIMIT
    metadata = {**manifest, "available": available, "total_size": total, "file_limit": FILE_LIMIT, "total_limit": TOTAL_LIMIT,
                "filename": f"MAGI-implementation-{completed_id[:12]}-{bundle_id[:8]}.zip",
                "files": entries + [{"name": "manifest.json", "size": len(files["manifest.json"]), "sha256": sha(files["manifest.json"])}]}
    if not available:
        metadata["limitations"] = limits + ["개별 파일 4MiB 또는 전체 자료 16MiB 제한을 초과했습니다."]
        files = {}
    return metadata, files


class PackageCache:
    def __init__(self, clock=time.monotonic):
        self.clock, self.entries, self.lock = clock, OrderedDict(), threading.Lock()

    def _expire(self):
        for key, value in list(self.entries.items()):
            if self.clock() - value[0] >= 300:
                del self.entries[key]

    def put(self, key, metadata, files):
        with self.lock:
            self._expire()
            self.entries[key] = (self.clock(), metadata, files)
            self.entries.move_to_end(key)
            while sum(len(serialize(v[1])) + sum(len(b) for b in v[2].values()) for v in self.entries.values()) > 32 * 1024 * 1024:
                self.entries.popitem(last=False)

    def get(self, key):
        with self.lock:
            self._expire()
            value = self.entries.get(key)
            if value:
                self.entries.move_to_end(key)
                return value[1], value[2]


def file_chunk(metadata, files, name, offset):
    if not metadata["available"] or not isinstance(name, str) or name not in NAMES or name not in files:
        raise ValueError("묶음 파일을 확인할 수 없습니다.")
    data = files[name]
    if type(offset) is not int or offset < 0 or offset % CHUNK or offset >= len(data):
        raise ValueError("파일 조회 위치가 올바르지 않습니다.")
    raw = data[offset:offset + CHUNK]
    return {"bundle_id": metadata["bundle_id"], "name": name, "offset": offset,
            "size": len(data), "sha256": sha(data), "content": base64.b64encode(raw).decode("ascii"), "eof": offset + len(raw) == len(data)}
