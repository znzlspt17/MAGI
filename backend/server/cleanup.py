"""확인된 기록만 격리·삭제하고 중단된 정리를 먼저 복구한다."""

from functools import wraps
import re
import time
from uuid import uuid4


ID = re.compile(r"[0-9a-f]{32}\Z")


class CleanupConflict(ValueError):
    pass


from backend.application.activity import tracked as tracked


def synchronized(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return function(self, *args, **kwargs)

    return wrapped


class Cleanup:
    def __init__(self, manager):
        self.manager, self.store = manager, manager.knowledge.store

    def write(self, operation):
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO cleanup_commits(id,data) VALUES (%s,%s) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data",
                (operation["id"], self.store._json(operation)),
            )

    def load(self, ident):
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise CleanupConflict("정리 요청을 확인하세요.")
        with self.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT data FROM cleanup_commits WHERE id=%s", (ident,)
            ).fetchone()
        if not row or not row["data"]:
            raise CleanupConflict("정리 미리보기가 없습니다.")
        return row["data"]

    def catalog(self):
        with self.store.transaction(mode="read") as conn:
            jobs = [
                {**r["data"], "owner_id": r["owner_id"]}
                for r in conn.execute(
                    "SELECT data,owner_id FROM jobs ORDER BY id"
                ).fetchall()
            ]
            pending = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM cleanup_commits WHERE data->>'state'='checkpoints_pending'"
                ).fetchall()
            ]
        return {
            "jobs": jobs,
            "projects": self.store.projects(),
            "database": True,
            "pending": pending,
        }

    def preview(self, params):
        scope, ids = params.get("scope"), params.get("ids", [])
        if (
            scope not in {"jobs", "projects", "all"}
            or not isinstance(ids, list)
            or any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids)
        ):
            raise ValueError("삭제 범위를 확인하세요.")
        if scope != "all" and not ids:
            raise ValueError("삭제할 대상을 선택하세요.")
        with self.manager.lock, self.store.transaction(mode="maintenance") as conn:
            inventory = self.store.cleanup_inventory(conn, scope, ids)
            targets = [j["id"] for j in inventory["jobs"]]
            self.require_idle(targets)
            operation = {
                **{
                    k: inventory[k]
                    for k in ("counts", "external_references", "fingerprint")
                },
                "id": uuid4().hex,
                "scope": scope,
                "ids": ids,
                "targets": targets,
                "skipped": [],
                "state": "preview",
                "expires_at": time.time() + 600,
            }
            self.write(operation)
            return operation

    def require_idle(self, targets):
        if any(
            self.manager.jobs.get(j, {}).get("status") in {"queued", "running"}
            or self.manager._activities.get(j)
            for j in targets
        ):
            raise CleanupConflict("실행·저장 중인 작업은 삭제할 수 없습니다.")

    def execute(self, params):
        with self.manager.lock, self.store.transaction(mode="maintenance") as conn:
            op = self.load(params.get("id"))
            if op["state"] == "completed":
                return op
            if op["state"] == "preview":
                if op["expires_at"] < time.time() or (
                    op["scope"] == "all"
                    and params.get("confirmation") != "전체 기록 삭제"
                ):
                    raise CleanupConflict(
                        "정리 미리보기와 확인 문구를 다시 확인하세요."
                    )
                inventory = self.store.cleanup_inventory(conn, op["scope"], op["ids"])
                if inventory["fingerprint"] != op["fingerprint"]:
                    raise CleanupConflict("삭제 대상이 변경되었습니다.")
                self.require_idle(op["targets"])
                self.store.cleanup_delete(conn, inventory)
                op["state"] = "checkpoints_pending"
                self.write(op)
        return self.finish(op)

    def finish(self, operation):
        from backend.infrastructure.workflow_store import delete_workflow_threads

        delete_workflow_threads(self.store, operation["targets"])
        for ident in operation["targets"]:
            self.manager.jobs.pop(ident, None)
            self.manager._activities.pop(ident, None)
            for key in list(self.manager.workspace._document_locks):
                if key[0] == ident:
                    del self.manager.workspace._document_locks[key]
        operation["state"] = "completed"
        self.write(operation)
        return operation

    def recover(self):
        with self.store.transaction(mode="read") as conn:
            operations = conn.execute(
                "SELECT data FROM cleanup_commits WHERE data->>'state'='checkpoints_pending'"
            ).fetchall()
        for row in operations:
            self.finish(row["data"])
