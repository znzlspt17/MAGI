"""개인 프로젝트와 공통 결정의 트랜잭션 저장 경계."""
from uuid import uuid4

from backend.access.context import ACTOR


class ProjectDecisionStore:
    def require_project(self, conn, ident):
        if not isinstance(ident, str):
            raise ValueError("프로젝트를 선택하세요.")
        row = conn.execute("SELECT id,name,owner_id FROM projects WHERE id=%s", (ident,)).fetchone()
        actor = ACTOR.get()
        if not row or (actor and row["owner_id"] != actor["id"]):
            raise KeyError("project")
        return row

    def registered_decisions(self, ident):
        with self.transaction(mode="read") as conn:
            self.require_project(conn, ident)
            return [{**r["data"], "id": r["id"], "version": r["version"], "active": r["active"], "source_available": r["source_job_id"] is not None}
                    for r in conn.execute("SELECT * FROM project_decisions WHERE project_id=%s ORDER BY created_at DESC,id", (ident,)).fetchall()]

    def register_decision(self, ident, candidate):
        with self.transaction() as conn:
            self.require_project(conn, ident)
            job = conn.execute("SELECT id FROM jobs WHERE id=%s AND project_id=%s", (candidate["job_id"], ident)).fetchone()
            if not job: raise KeyError("job")
            row = conn.execute("INSERT INTO project_decisions(id,project_id,source_job_id,completed_id,decision_id,data) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(project_id,completed_id,decision_id) DO UPDATE SET active=true,version=project_decisions.version+CASE WHEN project_decisions.active THEN 0 ELSE 1 END,updated_at=now() RETURNING *",
                (uuid4().hex, ident, candidate["job_id"], candidate["completed_id"], candidate["decision_id"], self._json(candidate))).fetchone()
            return {**row["data"], "id": row["id"], "version": row["version"], "active": row["active"], "source_available": True}

    def deactivate_decision(self, ident, decision_id, version):
        if type(version) is not int: raise ValueError("결정 버전을 확인하세요.")
        with self.transaction() as conn:
            self.require_project(conn, ident)
            row = conn.execute("UPDATE project_decisions SET active=false,version=version+1,updated_at=now() WHERE project_id=%s AND id=%s AND version=%s RETURNING id,version,active", (ident, decision_id, version)).fetchone()
            if not row: raise ValueError("결정이 변경되었습니다. 다시 조회하세요.")
            return row

    def freeze_decisions(self, ident, selections):
        if not isinstance(selections, list) or len(selections) > 20:
            raise ValueError("공통 결정은 최대 20개까지 선택하세요.")
        with self.transaction() as conn:
            self.require_project(conn, ident)
            result, seen = [], set()
            for selection in selections:
                if not isinstance(selection, dict) or set(selection) != {"id", "version", "source_hash"} or not isinstance(selection["id"], str) or selection["id"] in seen or type(selection["version"]) is not int:
                    raise ValueError("선택한 결정 형식을 확인하세요.")
                seen.add(selection["id"])
                row = conn.execute("SELECT * FROM project_decisions WHERE project_id=%s AND id=%s FOR UPDATE", (ident, selection["id"])).fetchone()
                if not row or not row["active"] or not row["source_job_id"] or row["version"] != selection["version"] or row["data"]["source_hash"] != selection["source_hash"]:
                    raise ValueError("선택한 결정이 변경되었거나 출처가 없습니다. 다시 확인하세요.")
                result.append({**row["data"], "id": row["id"], "version": row["version"]})
            if sum(len(r["text"]) + len(r["conditions"]) for r in result) > 12000:
                raise ValueError("선택한 결정과 적용 조건은 합계 12,000자 이하여야 합니다.")
            return result
