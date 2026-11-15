"""작업 단계 원본을 보존하는 재시작 가능한 RAG projection 큐."""

import asyncio
import time
from uuid import uuid4

from backend.knowledge.projection import digest, project


async def enqueue_stage(store, conn, job, execution, stage, state, artifacts):
    # 2026-11-13: 입력 스냅샷 자체를 큐에 넣어 이후 문서 수정과 무관하게 재생한다.
    ident = digest([job["id"], execution, stage, state, artifacts])
    inserted = await (await conn.execute(
        "INSERT INTO projection_queue(id,job_id,execution_id,stage,state,artifacts) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING id",
        (ident, job["id"], execution, stage, store._json(state), store._json(artifacts)),
    )).fetchone()
    if inserted:
        from backend.infrastructure.progress_store import ProgressStore
        await ProgressStore(store).capture_index(conn, job['id'])
    return ident


async def _claim(store, now):
    lease = uuid4().hex
    async with store.transaction() as conn:
        row = (await (await conn.execute(
            "SELECT q.* FROM projection_queue q "
            "WHERE ((q.status IN ('pending','failed') AND q.next_attempt<=%s) "
            "OR (q.status='running' AND q.lease_until<=%s)) "
            "AND NOT EXISTS (SELECT 1 FROM projection_queue prior "
            "WHERE prior.job_id=q.job_id AND prior.sequence<q.sequence AND prior.status<>'completed') "
            "ORDER BY q.sequence LIMIT 1 FOR UPDATE SKIP LOCKED", (now, now),
        )).fetchone())
        if not row:
            return None
        (await conn.execute("UPDATE projection_queue SET status='running',lease_token=%s,lease_until=%s "
                     "WHERE id=%s", (lease, now + 300, row["id"])))
        return {**row, "lease_token": lease}


async def process_projection(store):
    """2026-11-13: 순서 보장과 만료 임대 회수로 여러 작업을 독립 복구한다."""
    row = (await _claim(store, time.time()))
    if row is None:
        return False
    try:
        # 2026-11-13: 큰 projection 생성은 DB 트랜잭션과 이벤트 루프 밖에서 수행한다.
        prepared = ([], []) if row["stage"] == "impact_review" else await asyncio.to_thread(
            project, row["job_id"], row["state"], row["artifacts"], row["stage"]
        )
        async with store.transaction() as conn:
            live = (await (await conn.execute(
                "SELECT 1 FROM projection_queue q JOIN jobs j ON j.id=q.job_id "
                "WHERE q.id=%s AND q.status='running' AND q.lease_token=%s AND q.lease_until>%s "
                "AND NOT EXISTS (SELECT 1 FROM deleted_jobs d WHERE d.id=q.job_id) FOR UPDATE",
                (row["id"], row["lease_token"], time.time()),
            )).fetchone())
            if not live:
                return True
            (await store.commit_stage({"id": row["job_id"]}, row["execution_id"], row["stage"],
                               row["state"], row["artifacts"], connection=conn, prepared=prepared))
            (await conn.execute("UPDATE projection_queue SET status='completed',lease_token=NULL,lease_until=NULL "
                         "WHERE id=%s AND lease_token=%s", (row["id"], row["lease_token"])))
            from backend.infrastructure.progress_store import ProgressStore
            await ProgressStore(store).capture_index(conn, row['job_id'])
        return True
    except Exception:
        attempts = row["attempts"] + 1
        async with store.transaction() as conn:
            (await conn.execute("UPDATE projection_queue SET status='failed',attempts=%s,lease_token=NULL, "
                         "lease_until=NULL,next_attempt=%s WHERE id=%s AND lease_token=%s",
                         (attempts, time.time() + min(300, 2 ** min(attempts, 8)), row["id"], row["lease_token"])))
            from backend.infrastructure.progress_store import ProgressStore
            await ProgressStore(store).capture_index(conn, row['job_id'])
        return True


async def projection_status(store, job_id=None, *, project_id=None):
    async with store.transaction(mode="read") as conn:
        row = (await (await conn.execute(
            "SELECT COALESCE(max(q.sequence),0) AS source, "
            "COALESCE(max(q.sequence) FILTER (WHERE q.status='completed'),0) AS applied, "
            "count(*) FILTER (WHERE q.status='failed') AS failed, "
            "count(*) FILTER (WHERE q.status IN ('pending','running')) AS pending, "
            "count(*) FILTER (WHERE q.stage='accepted_input' AND q.status='completed' "
            "AND j.data->>'status' IN ('queued','running') AND j.data->>'execution_id'=q.execution_id "
            "AND NOT EXISTS (SELECT 1 FROM projection_queue normalized WHERE normalized.job_id=q.job_id "
            "AND normalized.execution_id=q.execution_id AND normalized.stage='input')) AS normalizing "
            "FROM projection_queue q JOIN jobs j ON j.id=q.job_id "
            "WHERE (%s::text IS NULL OR q.job_id=%s) AND (%s::text IS NULL OR j.project_id=%s)",
            (job_id, job_id, project_id, project_id),
        )).fetchone())
        embedding = await (await conn.execute(
            "SELECT count(*) FILTER (WHERE e.status='failed') AS failed, "
            "count(*) FILTER (WHERE e.status NOT IN ('completed','failed')) AS pending "
            "FROM embedding_queue e JOIN nodes n ON n.id=e.node_id "
            "JOIN jobs j ON j.id=n.job_id WHERE n.active AND n.attrs->>'scope'='product' "
            "AND (%s::text IS NULL OR n.job_id=%s) AND (%s::text IS NULL OR j.project_id=%s)",
            (job_id, job_id, project_id, project_id),
        )).fetchone()
    return {"index_status": "failed" if row["failed"] or embedding["failed"] else "pending" if row["pending"] or row.get("normalizing", 0) or embedding["pending"] else "ready",
            "index_source_revision": row["source"], "index_applied_revision": row["applied"]}


async def projection_ready(store, job_id):
    """2026-11-13: 벡터 지연과 무관하게 해당 작업의 모든 원본 반영 여부를 확인한다."""
    async with store.transaction(mode="read") as conn:
        row = await (await conn.execute(
            "SELECT NOT EXISTS (SELECT 1 FROM projection_queue q JOIN jobs j ON j.id=q.job_id "
            "WHERE q.job_id=%s AND (q.status<>'completed' OR (q.stage='accepted_input' "
            "AND j.data->>'status' IN ('queued','running') AND j.data->>'execution_id'=q.execution_id "
            "AND NOT EXISTS (SELECT 1 FROM projection_queue normalized WHERE normalized.job_id=q.job_id "
            "AND normalized.execution_id=q.execution_id AND normalized.stage='input')))) AS ready", (job_id,),
        )).fetchone()
    return bool(row["ready"])
