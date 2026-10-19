"""모든 모델 세대와 외부 연결을 포함하는 기록 삭제 SQL."""

from backend.knowledge.projection import digest


MAINTENANCE_LOCK = 72410632


class CleanupStore:
    def cleanup_inventory(self, conn, scope, ids):
        jobs = conn.execute("SELECT id,project_id,data FROM magi_jobs ORDER BY id").fetchall()
        projects = conn.execute("SELECT id,name FROM magi_projects ORDER BY id").fetchall()
        if scope == "projects":
            if not set(ids) <= {p["id"] for p in projects}:
                raise ValueError("프로젝트를 찾을 수 없습니다.")
            jobs = [j for j in jobs if j["project_id"] in ids]
            projects = [p for p in projects if p["id"] in ids]
        elif scope == "jobs":
            jobs = [j for j in jobs if j["id"] in ids]
            projects = []
        job_ids = [j["id"] for j in jobs]
        nodes = "SELECT id FROM magi_nodes WHERE job_id=ANY(%s)"
        chunks = f"SELECT id FROM magi_chunks WHERE node_id IN ({nodes})"
        clauses = {
            "magi_chunk_vectors": (f"chunk_id IN ({chunks})", job_ids),
            "magi_chunks": (f"node_id IN ({nodes})", job_ids),
            "magi_chunk_sets": (f"node_id IN ({nodes})", job_ids),
            "magi_embeddings": (f"node_id IN ({nodes})", job_ids),
            "magi_embedding_queue": (f"node_id IN ({nodes})", job_ids),
        }
        counts = {}
        for table, (where, values) in clauses.items():
            counts[table] = conn.execute(f"SELECT count(*) AS total FROM {table} WHERE {where}", (values,)).fetchone()["total"]
        for table in ("magi_nodes", "magi_artifacts", "magi_snapshots", "magi_executions"):
            counts[table] = conn.execute(f"SELECT count(*) AS total FROM {table} WHERE job_id=ANY(%s)", (job_ids,)).fetchone()["total"]
        edges = conn.execute(f"SELECT id,source,target FROM magi_edges WHERE source IN ({nodes}) OR target IN ({nodes}) ORDER BY id", (job_ids, job_ids)).fetchall()
        owned = {r["id"] for r in conn.execute(nodes, (job_ids,)).fetchall()}
        counts.update(magi_jobs=len(jobs), magi_projects=len(projects), magi_edges=len(edges))
        return {"jobs": jobs, "projects": projects, "counts": counts,
                "external_references": sum((e["source"] in owned) != (e["target"] in owned) for e in edges),
                "fingerprint": digest([jobs, projects, counts, edges])}

    def cleanup_delete(self, conn, inventory):
        ids = [j["id"] for j in inventory["jobs"]]
        conn.execute("DELETE FROM magi_admissions WHERE result->>'id'=ANY(%s)",(ids,))
        for ident in ids:
            conn.execute("INSERT INTO magi_deleted_jobs(id) VALUES (%s) ON CONFLICT DO NOTHING", (ident,))
        nodes = "SELECT id FROM magi_nodes WHERE job_id=ANY(%s)"
        conn.execute(f"INSERT INTO magi_deleted_nodes(id) {nodes} ON CONFLICT DO NOTHING", (ids,))
        conn.execute(f"DELETE FROM magi_edges WHERE source IN ({nodes}) OR target IN ({nodes})", (ids, ids))
        conn.execute(f"DELETE FROM magi_chunk_vectors WHERE chunk_id IN (SELECT id FROM magi_chunks WHERE node_id IN ({nodes}))", (ids,))
        for table in ("magi_chunks", "magi_chunk_sets", "magi_embeddings", "magi_embedding_queue"):
            conn.execute(f"DELETE FROM {table} WHERE node_id IN ({nodes})", (ids,))
        for table in ("magi_nodes", "magi_artifacts", "magi_snapshots", "magi_executions"):
            conn.execute(f"DELETE FROM {table} WHERE job_id=ANY(%s)", (ids,))
        conn.execute("DELETE FROM magi_jobs WHERE id=ANY(%s)", (ids,))
        conn.execute("DELETE FROM magi_projects WHERE id=ANY(%s)", ([p["id"] for p in inventory["projects"]],))
