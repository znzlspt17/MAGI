"""확인된 기록만 격리·삭제하고 중단된 정리를 먼저 복구한다."""

from contextlib import nullcontext
from functools import wraps
import json
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

from backend.knowledge.projection import digest


ID = re.compile(r"[0-9a-f]{32}\Z")


class CleanupConflict(ValueError):
    pass


def tracked(function):
    """표시 상태가 완료로 바뀐 뒤의 저장까지 실제 활동으로 추적한다."""
    @wraps(function)
    def wrapped(self, ident, *args, **kwargs):
        with self.lock:
            self._get_locked(ident)
            self._activities[ident] = self._activities.get(ident, 0) + 1
        try:
            return function(self, ident, *args, **kwargs)
        finally:
            with self.lock:
                self._activities[ident] -= 1
    return wrapped


def synchronized(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return function(self, *args, **kwargs)
    return wrapped


class Cleanup:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.data_dir / ".cleanup"
        if self.root.is_symlink() or getattr(self.root, "is_junction", lambda: False)() or (self.root.exists() and not self.root.is_dir()):
            raise CleanupConflict("정리 기록 경로를 확인하세요.")
        self.root.mkdir(exist_ok=True)

    @property
    def store(self):
        return self.manager.knowledge.store if self.manager.knowledge else None

    def write(self, operation):
        path = self.root / (operation["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        if path.is_symlink() or temporary.is_symlink():
            raise CleanupConflict("정리 기록 경로를 확인하세요.")
        temporary.write_text(json.dumps(operation, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def load(self, ident):
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise ValueError("정리 작업 ID가 올바르지 않습니다.")
        path = self.root / (ident + ".json")
        if path.is_symlink():
            raise CleanupConflict("정리 기록 경로를 확인하세요.")
        if not path.is_file():
            raise CleanupConflict("정리 미리보기가 없습니다. 다시 확인하세요.")
        operation = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(operation, dict) or operation.get("id") != ident
            or not isinstance(operation.get("targets"), list)
            or any(not isinstance(target, str) or not ID.fullmatch(target) for target in operation["targets"])):
            raise CleanupConflict("정리 기록의 경로 정보가 올바르지 않습니다.")
        return operation

    def file_jobs(self):
        return sorted(p.name for p in self.manager.data_dir.iterdir()
                      if ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink()
                      and not getattr(p, "is_junction", lambda: False)()
                      and p.resolve().parent == self.manager.data_dir and (p / "job.json").is_file())

    def catalog(self):
        with self.manager.lock:
            jobs = {}
            if self.store:
                with self.store.transaction(mode="read") as conn:
                    # JSON에 남은 이전 소유자 대신 DB의 현재 소유권을 표시한다.
                    jobs = {row["id"]: {**row["data"], "id": row["id"], "owner_id": row["owner_id"]}
                            for row in conn.execute("SELECT id,data,owner_id FROM jobs ORDER BY id").fetchall()}
            for ident in self.file_jobs():
                if ident not in jobs:
                    path = self.manager.data_dir / ident / "job.json"
                    if path.is_symlink():
                        continue
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            jobs[ident] = {**data, "id": ident}
                    except (OSError, ValueError):
                        jobs[ident] = {"id": ident, "request": "이전 작업 기록"}
            return {"jobs": [{**{k: j.get(k) for k in ("id", "request", "project_id", "status", "created_at")},
                              "owner_id": j.get("owner_id") if isinstance(j.get("owner_id"), str) else None}
                             for j in jobs.values()],
                    "projects": self.store.projects() if self.store else [], "database": self.store is not None,
                    "pending": [p.stem for p in self.root.glob("*.json") if not p.is_symlink()
                                and self.load(p.stem)["state"] == "files_pending"]}

    def inventory(self, scope, ids, conn=None):
        db = self.store.cleanup_inventory(conn, scope, ids) if self.store else {
            "jobs": [], "projects": [], "counts": {}, "external_references": 0, "fingerprint": ""}
        targets = set(j["id"] for j in db["jobs"])
        files = self.file_jobs()
        if scope == "all":
            targets.update(files)
        elif scope == "jobs":
            targets.update(set(files) & set(ids))
            if set(ids) != targets:
                raise ValueError("삭제할 작업을 찾을 수 없습니다.")
        entries, file_count, size = [], 0, 0
        for ident in sorted(targets):
            path = self.manager.data_dir / ident
            if not ID.fullmatch(ident) or path.is_symlink() or getattr(path, "is_junction", lambda: False)() or path.resolve().parent != self.manager.data_dir:
                raise CleanupConflict("안전하지 않은 작업 경로입니다.")
            if path.exists():
                for child in sorted(path.rglob("*")):
                    if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                        raise CleanupConflict("링크가 포함된 작업은 정리하지 않습니다.")
                    stat = child.stat()
                    entries.append([ident, str(child.relative_to(path)), stat.st_size, stat.st_mtime_ns])
                    if child.is_file():
                        file_count += 1
                        size += stat.st_size
        live = [self.manager.jobs.get(ident, {}) for ident in sorted(targets)]
        for ident, job in zip(sorted(targets), live):
            if job.get("status") in {"queued", "running"} or self.manager._activities.get(ident):
                raise CleanupConflict("실행·번역·저장 중인 작업이 있습니다. 완료 후 다시 확인하세요.")
        if any(j["data"].get("status") in {"queued", "running"} for j in db["jobs"]):
            raise CleanupConflict("대기 또는 실행 중인 DB 작업이 있습니다.")
        unknown = [p.name for p in self.manager.data_dir.iterdir() if p.name != ".cleanup" and p.name not in targets
                   and (not ID.fullmatch(p.name) or p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                        or not p.is_dir() or not (p / "job.json").is_file())]
        return {"targets": sorted(targets),
                "counts": {**db["counts"], "jobs": len(targets), "files": file_count, "bytes": size},
                "external_references": db["external_references"], "skipped": unknown,
                "fingerprint": digest([db["fingerprint"], entries, live, sorted(targets)]), "db": db}

    def preview(self, params):
        scope, ids = params.get("scope"), params.get("ids", [])
        if scope not in {"jobs", "projects", "all"} or not isinstance(ids, list) or any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids):
            raise ValueError("삭제 범위가 올바르지 않습니다.")
        if scope != "all" and not ids:
            raise ValueError("삭제할 대상을 선택하세요.")
        if scope == "projects" and not self.store:
            raise ValueError("파일 전용 환경에서는 프로젝트 삭제를 사용할 수 없습니다.")
        with self.manager.lock, (self.store.transaction() if self.store else nullcontext()) as conn:
            inventory = self.inventory(scope, ids, conn)
            inventory.pop("db")
            operation = {**inventory, "id": uuid4().hex, "scope": scope, "ids": ids,
                         "expires_at": time.time() + 600, "state": "preview"}
            self.write(operation)
            return operation

    def quarantine(self, operation):
        folder = self.root / operation["id"]
        if folder.is_symlink():
            raise CleanupConflict("격리 경로를 확인하세요.")
        folder.mkdir(exist_ok=True)
        for ident in operation["targets"]:
            source = self.manager.data_dir / ident
            if source.exists():
                source.rename(folder / ident)

    def restore(self, operation):
        for ident in operation["targets"]:
            source = self.root / operation["id"] / ident
            target = self.manager.data_dir / ident
            if source.exists():
                if target.exists():
                    raise CleanupConflict("복원할 경로가 이미 있습니다. 정리 복구가 필요합니다.")
                source.rename(target)
        operation["state"] = "cancelled"
        self.write(operation)

    def finish(self, operation):
        folder = self.root / operation["id"]
        try:
            if self.store:
                from backend.infrastructure.workflow_store import delete_workflow_threads
                delete_workflow_threads(self.store, operation["targets"])
            if folder.exists():
                # 삭제 직전에도 격리 루트와 하위 링크를 재확인한다.
                if (self.root.is_symlink() or self.root.resolve().parent != self.manager.data_dir
                    or folder.is_symlink() or folder.resolve().parent != self.root.resolve()):
                    raise OSError("unsafe quarantine")
                if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in folder.rglob("*")):
                    raise OSError("unsafe quarantine entry")
                shutil.rmtree(folder)
            operation["state"] = "completed"
        except OSError:
            operation["state"] = "files_pending"
        self.write(operation)
        return operation

    def forget(self, operation):
        for ident in operation["targets"]:
            self.manager.jobs.pop(ident, None)
            self.manager._activities.pop(ident, None)
            for key in list(self.manager._document_locks):
                if key[0] == ident:
                    del self.manager._document_locks[key]

    def recover(self):
        for path in self.root.glob("*.json"):
            op = self.load(path.stem)
            if op["state"] == "prepared":
                if self.store:
                    with self.store.transaction() as conn:
                        committed = conn.execute("SELECT id FROM cleanup_commits WHERE id=%s", (op["id"],)).fetchone()
                    if not committed:
                        self.restore(op)
                        continue
                # 파일 전용은 prepared 상태가 삭제 결정의 영구 기록이다.
                op["state"] = "files_pending"
            if op["state"] == "files_pending":
                self.forget(op)
                self.quarantine(op)
                self.finish(op)

    def execute(self, params):
        with self.manager.lock:
            op = self.load(params.get("id"))
            if op["state"] == "completed":
                return op
            if op["state"] == "files_pending":
                return self.finish(op)
            if op["state"] != "preview" or op["expires_at"] < time.time():
                raise CleanupConflict("미리보기가 만료되었습니다. 다시 확인하세요.")
            if op["scope"] == "all" and params.get("confirmation") != "전체 기록 삭제":
                raise ValueError("전체 기록 삭제 문구를 입력하세요.")
            try:
                with (self.store.transaction(mode="maintenance") if self.store else nullcontext()) as conn:
                    current = self.inventory(op["scope"], op["ids"], conn)
                    if current["fingerprint"] != op["fingerprint"]:
                        raise CleanupConflict("대상이나 상태가 바뀌었습니다. 미리보기를 갱신하세요.")
                    op.update(state="prepared")
                    self.write(op)
                    self.quarantine(op)
                    if self.store:
                        self.store.cleanup_delete(conn, current["db"])
                        conn.execute("INSERT INTO cleanup_commits(id) VALUES (%s)", (op["id"],))
            except Exception:
                # commit 응답이 불확실한 경우도 DB 실재 여부로 복구한다.
                if op["state"] == "prepared":
                    if self.store:
                        self.recover()
                    else:
                        self.restore(op)
                raise
            self.forget(op)
            op["state"] = "files_pending"
            self.write(op)
            return self.finish(op)
