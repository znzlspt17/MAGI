"""모든 모델 세대와 외부 연결을 포함하는 기록 삭제 SQL."""

from backend.knowledge.projection import digest


MAINTENANCE_LOCK = 72410632


class CleanupStore:
    def cleanup_inventory(self, conn, scope, ids):
        jobs = conn.execute("SELECT id,project_id,data FROM jobs ORDER BY id").fetchall()
        projects = conn.execute("SELECT id,name FROM projects ORDER BY id").fetchall()
        if scope == "projects":
            if not set(ids) <= {p["id"] for p in projects}:
                raise ValueError("프로젝트를 찾을 수 없습니다.")
            jobs = [j for j in jobs if j["project_id"] in ids]
            projects = [p for p in projects if p["id"] in ids]
        elif scope == "jobs":
            jobs = [j for j in jobs if j["id"] in ids]
            projects = []
        job_ids = [j["id"] for j in jobs]
        nodes = "SELECT id FROM nodes WHERE job_id=ANY(%s)"
        chunks = f"SELECT id FROM chunks WHERE node_id IN ({nodes})"
        clauses = {
            "chunk_vectors": (f"chunk_id IN ({chunks})", job_ids),
            "chunks": (f"node_id IN ({nodes})", job_ids),
            "chunk_sets": (f"node_id IN ({nodes})", job_ids),
            "embedding_queue": (f"node_id IN ({nodes})", job_ids),
        }
        counts = {}
        for table, (where, values) in clauses.items():
            counts[table] = conn.execute(f"SELECT count(*) AS total FROM {table} WHERE {where}", (values,)).fetchone()["total"]
        for table in ("nodes", "document_versions", "document_bodies", "execution_events", "model_usage", "projection_commits", "executions"):
            counts[table] = conn.execute(f"SELECT count(*) AS total FROM {table} WHERE job_id=ANY(%s)", (job_ids,)).fetchone()["total"]
        edges = conn.execute(f"SELECT id,source,target FROM edges WHERE source IN ({nodes}) OR target IN ({nodes}) ORDER BY id", (job_ids, job_ids)).fetchall()
        owned = {r["id"] for r in conn.execute(nodes, (job_ids,)).fetchall()}
        project_ids = [p["id"] for p in projects]
        decisions = conn.execute("SELECT id,project_id,source_job_id,version,active FROM project_decisions WHERE source_job_id=ANY(%s) OR project_id=ANY(%s) ORDER BY id", (job_ids, project_ids)).fetchall()
        counts["project_decisions"] = len(decisions)
        counts.update(jobs=len(jobs), projects=len(projects), edges=len(edges))
        return {"jobs": jobs, "projects": projects, "counts": counts,
                "external_references": sum((e["source"] in owned) != (e["target"] in owned) for e in edges) + sum(d["source_job_id"] in job_ids and d["project_id"] not in project_ids for d in decisions),
                "fingerprint": digest([jobs, projects, counts, edges, decisions])}

    def cleanup_delete(self, conn, inventory):
        ids = [j["id"] for j in inventory["jobs"]]
        conn.execute("DELETE FROM admissions WHERE result->>'id'=ANY(%s)",(ids,))
        for ident in ids:
            conn.execute("INSERT INTO deleted_jobs(id) VALUES (%s) ON CONFLICT DO NOTHING", (ident,))
        conn.execute("UPDATE project_decisions SET active=false,version=version+1,updated_at=now() WHERE source_job_id=ANY(%s)", (ids,))
        nodes = "SELECT id FROM nodes WHERE job_id=ANY(%s)"
        conn.execute(f"INSERT INTO deleted_nodes(id) {nodes} ON CONFLICT DO NOTHING", (ids,))
        conn.execute(f"DELETE FROM edges WHERE source IN ({nodes}) OR target IN ({nodes})", (ids, ids))
        conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE node_id IN ({nodes}))", (ids,))
        for table in ("chunks", "chunk_sets", "embedding_queue"):
            conn.execute(f"DELETE FROM {table} WHERE node_id IN ({nodes})", (ids,))
        for table in ("nodes", "document_versions", "document_bodies", "execution_events", "model_usage", "projection_commits", "executions"):
            conn.execute(f"DELETE FROM {table} WHERE job_id=ANY(%s)", (ids,))
        conn.execute("DELETE FROM jobs WHERE id=ANY(%s)", (ids,))
        conn.execute("DELETE FROM projects WHERE id=ANY(%s)", ([p["id"] for p in inventory["projects"]],))
