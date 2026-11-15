"""트랜잭션 기반 PostgreSQL 저장소. 접속 오류의 원문은 외부에 남기지 않는다."""

import asyncio
from contextlib import asynccontextmanager, contextmanager, nullcontext
import json
from protocol.logging import get_logger
import re
import threading
from uuid import uuid4

from backend.knowledge.config import KnowledgeError
from backend.knowledge.projection import digest, project


SEARCH_KINDS = ("decision", "requirement", "spec")
logger = get_logger(__name__)
WRITE_LOCK = 72410636


from backend.knowledge.chunk_store import ChunkStore
from backend.knowledge.cleanup import CleanupStore, MAINTENANCE_LOCK
from backend.access.context import ACTOR, TRANSACTION, AccessError
ASYNC_TRANSACTION = TRANSACTION


from backend.knowledge.project_decisions import ProjectDecisionStore


class KnowledgeStore:
    def __init__(self, config, connect=None):
        self.chunks = ChunkStore(self)
        self.cleanup = CleanupStore()
        self.decisions = ProjectDecisionStore(self)
        self.config = config
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self.connect = connect
        self._connections = threading.BoundedSemaphore(2)
        # 대기 중인 쓰기가 두 연결을 모두 점유하지 않게 연결 전에 직렬화한다.
        self._writers = threading.Lock()
        self._conversation_locks = {}
        self._async_pool = None
        self._async_pool_lock = asyncio.Lock()
        self._async_writer = asyncio.Lock()

    async def open_async(self):
        """2026-11-13: 일반 저장과 checkpoint가 대여할 제한된 풀을 준비한다."""
        async with self._async_pool_lock:
            if self._async_pool is not None:
                return self._async_pool
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            async def configure(conn):
                await conn.execute("SET search_path TO workflow, public")

            pool = AsyncConnectionPool(
                conninfo="", kwargs={**self.config.connection, "autocommit": True,
                                     "row_factory": dict_row},
                min_size=0, max_size=8, open=False, configure=configure,
            )
            try:
                await pool.open(wait=True)
            except BaseException:
                await pool.close()
                raise
            self._async_pool = pool
            return pool

    async def close_async(self):
        async with self._async_pool_lock:
            pool, self._async_pool = self._async_pool, None
            if pool is not None:
                await pool.close()

    @asynccontextmanager
    async def transaction(self, *, mode="write"):
        """2026-11-13: 태스크 간 연결을 공유하지 않고 커밋 완료까지 기다린다."""
        if mode not in {"read", "write", "maintenance"}:
            raise ValueError("DB 트랜잭션 모드가 올바르지 않습니다.")
        current_task = asyncio.current_task()
        existing = ASYNC_TRANSACTION.get()
        if existing is not None and existing[3] is not current_task:
            raise KnowledgeError("다른 태스크의 트랜잭션을 상속할 수 없습니다.")
        if existing is not None and existing[0] is self and existing[3] is current_task:
            ranks = {"read": 0, "write": 1, "maintenance": 2}
            if ranks[mode] > ranks[existing[2]]:
                raise KnowledgeError("중첩 DB 트랜잭션의 잠금 모드를 승격할 수 없습니다.")
            yield existing[1]
            return

        try:
            pool = self._async_pool if self._async_pool is not None else await self.open_async()
            # 쓰기 대기자가 풀 연결을 선점하지 않도록 먼저 로컬 잠금을 얻는다.
            writer = self._async_writer if mode != "read" else nullcontext()
            async with writer:
                async with pool.connection() as conn:
                    async with conn.transaction():
                        if mode == "read":
                            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                        await conn.execute("SET LOCAL search_path TO core,public")
                        await conn.execute("SET LOCAL statement_timeout = '15s'")
                        lock = "pg_advisory_xact_lock" if mode == "maintenance" else "pg_advisory_xact_lock_shared"
                        await conn.execute(f"SELECT {lock}(%s)", (MAINTENANCE_LOCK,))
                        if mode != "read":
                            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
                        actor = ACTOR.get()
                        owners = actor.get("owner_ids", [actor["id"]]) if actor else []
                        await conn.execute(
                            "SELECT set_config('app.actor',%s,true),set_config('app.owners',%s,true),set_config('app.internal',%s,true)",
                            (actor['id'] if actor else '', json.dumps(owners), 'off' if actor else 'on'),
                        )
                        token = ASYNC_TRANSACTION.set((self, conn, mode, current_task))
                        try:
                            yield conn
                        finally:
                            ASYNC_TRANSACTION.reset(token)
        except (KeyError, ValueError, KnowledgeError, asyncio.CancelledError):
            raise
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None)
            if not isinstance(sqlstate, str) or re.fullmatch(r"[0-9A-Z]{5}", sqlstate) is None:
                sqlstate = None
            logger.error("Async DB transaction failed exception_type=%s sqlstate=%s",
                         type(exc).__name__, sqlstate)
            raise KnowledgeError("DB 작업에 실패했습니다. 연결·권한·스키마 상태를 확인하세요.") from None

    def conversation_lock(self, job_id):
        # 2026-11-13: 같은 이벤트 루프의 태스크도 원격 대화별로 직렬화한다.
        return self._conversation_locks.setdefault(job_id, asyncio.Lock())

    @staticmethod
    def _json(value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    async def projects(self):
        async with self.transaction(mode='read') as conn:
            actor = ACTOR.get()
            # 2026-11-13: 연결된 익명 소유자의 프로젝트도 대표 계정에서 조회한다.
            owners = actor.get('owner_ids', [actor['id']]) if actor else []
            return (await (await conn.execute("SELECT id,name FROM projects" + (" WHERE owner_id=ANY(%s)" if actor else "") + " ORDER BY created_at,id", (owners,) if actor else ())).fetchall())

    async def create_project(self, name, ident=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError("프로젝트 이름은 1~120자로 입력하세요.")
        ident = ident or uuid4().hex
        actor = ACTOR.get()
        async with self.transaction() as conn:
            (await conn.execute("INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s) ON CONFLICT(id) DO NOTHING", (ident, name.strip(), actor['id'] if actor else None)))
            return (await (await conn.execute("SELECT id,name FROM projects WHERE id=%s", (ident,))).fetchone())

    async def save_job(self, job, *, expected_generation=None):
        async with self.transaction() as conn:
            (await self._save_job(conn, job, expected_generation=expected_generation))

    async def _save_job(self, conn, job, *, expected_generation=None):
        if expected_generation is not None:
            lease=(await (await conn.execute("SELECT job_id,generation,phase,execution_id FROM public.execution_leases WHERE job_id=%s AND kind='workflow' AND phase='running'", (job['id'],))).fetchone())
            if not lease or lease['generation']!=expected_generation or lease['execution_id']!=job['execution_id']:
                raise AccessError('이전 작업의 저장을 차단했습니다.', 'busy')
        if (await (await conn.execute("SELECT 1 FROM deleted_jobs WHERE id=%s", (job["id"],))).fetchone()):
            raise ValueError("삭제된 작업은 다시 저장할 수 없습니다.")
        (await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job["id"],)))
        if not (await (await conn.execute("SELECT 1 FROM projects WHERE id=%s", (job["project_id"],))).fetchone()) and not (await (await conn.execute("SELECT 1 FROM jobs WHERE id=%s AND project_id=%s", (job["id"], job["project_id"]))).fetchone()):
            raise ValueError("프로젝트를 찾을 수 없습니다.")
        (await conn.execute("INSERT INTO jobs(id,project_id,data,owner_id) VALUES (%s,%s,%s,%s) "
                     "ON CONFLICT(id) DO UPDATE SET project_id=EXCLUDED.project_id,data=EXCLUDED.data",
                     (job["id"], job["project_id"], self._json(job), job.get('owner_id'))))
        from backend.infrastructure.progress_store import ProgressStore
        (await ProgressStore(self).capture(conn, job))

    async def jobs(self):
        async with self.transaction(mode='read') as conn:
            return [{**row["data"], "owner_id":row["owner_id"]} for row in (await (await conn.execute("SELECT data,owner_id FROM jobs ORDER BY id")).fetchall())]

    async def accept_job(self, job, payload):
        # 내부 프로젝트와 최초 요청을 하나의 트랜잭션으로 접수한다.
        async with self.transaction() as conn:
            if job["project_id"] == job["id"]:
                (await conn.execute("INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s)",
                             (job["id"], job["request"][:80], job.get("owner_id"))))
            else:
                (await self.require_project(conn, job["project_id"]))
            job["reused_decisions"] = (await self.freeze_decisions(job["project_id"], job.pop("_decision_selections", [])))
            (await self._save_job(conn, job))
            (await conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,%s)",
                         (job["execution_id"], job["id"], self._json(
                             {"action": job["action"], "input": payload, "status": "queued"}))))
            await self.enqueue_accepted_input(conn, job, payload)

    async def record_action(self, job, payload):
        async with self.transaction() as conn:
            (await self._save_job(conn, job))
            inserted = await (await conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,%s) "
                         "ON CONFLICT(id) DO NOTHING RETURNING id", (job["execution_id"], job["id"],
                         self._json({"action": job["action"], "input": payload, "status": "queued"})))).fetchone()
            if inserted:
                await self.enqueue_accepted_input(conn, job, payload)

    async def enqueue_accepted_input(self, conn, job, payload):
        # 2026-11-13: 접수 원문은 확인 전 입력으로만 보관하고 원본 커밋과 함께 큐에 넣는다.
        if job['action'] in {'generate', 'message', 'revise', 'continue', 'answer'}:
            await self.enqueue_stage(job, job['execution_id'], 'accepted_input',
                                     {'action': job['action'], 'execution_id': job['execution_id'], 'payload': payload},
                                     {}, connection=conn)

    async def action_records(self, job_id):
        async with self.transaction(mode='read') as conn:
            return [{"id": row["id"], **row["data"]} for row in (await (await conn.execute(
                "SELECT id,data FROM executions WHERE job_id=%s AND data ? 'action' ORDER BY sequence", (job_id,))).fetchall())]

    async def enqueue_stage(self, job, execution, stage, state, artifacts, *, connection):
        from backend.knowledge.projection_queue import enqueue_stage
        return (await enqueue_stage(self, connection, job, execution, stage, state, artifacts))

    async def process_projection(self):
        from backend.knowledge.projection_queue import process_projection
        return (await process_projection(self))

    async def projection_status(self, job_id=None, *, project_id=None):
        from backend.knowledge.projection_queue import projection_status
        return (await projection_status(self, job_id, project_id=project_id))

    async def projection_ready(self, job_id):
        from backend.knowledge.projection_queue import projection_ready
        return await projection_ready(self, job_id)

    async def commit_stage(self, job, execution, stage, state, artifacts, *, connection=None, prepared=None):
        nodes, edges = prepared if prepared is not None else (([], []) if stage == "impact_review" else project(job["id"], state, artifacts, stage))
        snapshot = digest([job["id"], execution, stage, nodes, edges])
        async with (self.transaction() if connection is None else nullcontext(connection)) as conn:
            (await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job["id"],)))
            inserted = (await (await conn.execute("INSERT INTO projection_commits(id,job_id) VALUES (%s,%s) "
                                    "ON CONFLICT DO NOTHING RETURNING id", (snapshot,job["id"]))).fetchone())
            if not inserted:
                return snapshot
            owned = {"requirement_lock": ("requirement", "decision"), "spec_compile": ("spec", "decision"),
                     "checklist_critic": ("review",), "review_resolution": ("review",),
                     "compose_candidate": ("spec", "decision", "review")}.get(stage, ())
            for kind in owned:
                current_keys = [node["logical_key"] for node in nodes if node["kind"] == kind]
                (await conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND kind=%s AND NOT(logical_key=ANY(%s))",
                             (job["id"], kind, current_keys)))
            invalidated = {"requirement_lock": ["spec", "review"], "spec_compile": ["review"]}.get(stage, [])
            if invalidated:
                (await conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND kind=ANY(%s)", (job["id"], invalidated)))
            node_ids = {}
            existing_nodes = set()
            by_content = {node["id"]: node for node in nodes}
            for node in nodes:
                previous = (await (await conn.execute("SELECT id,content_id,active FROM nodes WHERE job_id=%s AND logical_key=%s ORDER BY active DESC,sequence DESC LIMIT 1",
                                        (job["id"], node["logical_key"]))).fetchone())
                if previous and previous["active"] and previous["content_id"] == node["id"]:
                    ident = previous["id"]
                    existing_nodes.add(node["id"])
                else:
                    ident = digest([node["id"], snapshot])
                    (await conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND logical_key=%s",
                                 (job["id"], node["logical_key"])))
                    (await conn.execute("INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                 (ident, node["id"], job["id"], node["logical_key"], node["kind"], node["body"], self._json(node["attrs"]))))
                    if previous:
                        (await self._edge(conn, previous["id"], ident, "superseded"))
                node_ids[node["id"]] = ident
                if node["kind"] in SEARCH_KINDS:
                    (await conn.execute("INSERT INTO embedding_queue(node_id) VALUES (%s) ON CONFLICT DO NOTHING", (ident,)))
            for edge in edges:
                # 재사용 ID는 현재 제공한 문맥에서 검증된 것만 여기까지 도달한다.
                source_node = by_content.get(edge["source"], {})
                source_key = source_node.get("logical_key", "")
                if (edge["target"] in existing_nodes and edge["kind"] in {"evidence", "derived"}
                    and source_node.get("kind") == "input"
                    and (source_key == "user_feedback" or (source_key.startswith("user_answer:") and source_key.count(":") == 1))):
                    continue
                source = edge["source"] if edge["kind"] == "reused" else node_ids[edge["source"]]
                (await self._edge(conn, source, node_ids[edge["target"]], edge["kind"], edge["attrs"]))
        return snapshot

    def documents(self, job_id):
        from backend.knowledge.core import Documents
        return Documents(self, job_id)

    async def state(self, job_id):
        return dict((await self.documents(job_id).workflow_snapshot()).values)

    async def require_ready(self):
        from backend.knowledge.setup import require_ready

        (await require_ready(self))

    async def _edge(self, conn, source, target, kind, attrs=None):
        # 다른 작업의 생성 중 원본이 정리되면 본문은 보존하고 끊긴 재사용 연결만 생략한다.
        if kind == "reused" and (await (await conn.execute("SELECT 1 FROM deleted_nodes WHERE id=%s", (source,))).fetchone()):
            return
        (await conn.execute("INSERT INTO edges(id,source,target,kind,attrs) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (digest([source, target, kind]), source, target, kind, self._json(attrs or {}))))

    async def node(self, ident):
        async with self.transaction(mode='read') as conn:
            node = (await (await conn.execute("SELECT n.*,j.project_id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE n.id=%s", (ident,))).fetchone())
            if node is None:
                raise KeyError(ident)
            node = self._public(node, detail=True)
            node["edges"] = (await (await conn.execute("SELECT e.source,e.target,e.kind,e.attrs,left(other.body,100) AS other_body "
                "FROM edges e JOIN nodes other ON other.id=CASE WHEN e.source=%s THEN e.target ELSE e.source END "
                "WHERE e.source=%s OR e.target=%s LIMIT 200", (ident, ident, ident))).fetchall())
            path = node["attrs"].get("artifact_path")
            content_hash = node["attrs"].get("artifact_hash")
            if path and content_hash:
                doc = (await (await conn.execute("SELECT b.content FROM document_versions d JOIN document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) WHERE d.job_id=%s AND d.name=%s AND d.content_hash=%s LIMIT 1",
                                   (node["job_id"], path, content_hash))).fetchone())
                if doc:
                    # 전송 한도를 지키고 전체 문서는 별도 페이지로 제공한다.
                    node["document"] = doc["content"][:12000]
                    node["document_has_more"] = len(doc["content"]) > 12000
                    node["document_next_offset"] = len(node["document"])
            return node

    async def node_records(self, identities):
        async with self.transaction(mode='read') as conn:
            rows = (await (await conn.execute("SELECT n.*,j.project_id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE n.id=ANY(%s)",
                                (list(identities),))).fetchall())
            return {row["id"]: self._public(row, detail=True) for row in rows}

    async def artifact_page(self, job_id, path, content_hash, offset=0):
        if type(offset) is not int or offset < 0:
            raise ValueError("문서 위치가 올바르지 않습니다.")
        async with self.transaction(mode='read') as conn:
            row = (await (await conn.execute("SELECT b.content FROM document_versions d JOIN document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) WHERE d.job_id=%s AND d.name=%s AND d.content_hash=%s LIMIT 1",
                               (job_id, path, content_hash))).fetchone())
            if not row:
                raise KeyError(path)
            content = row["content"]
            chunk = content[offset:offset+12000]
            return {"content": chunk, "offset": offset, "next_offset": offset+len(chunk), "has_more": offset+len(chunk) < len(content)}

    @staticmethod
    def _public(row, detail=False):
        row = dict(row)
        row.pop("created_at", None)
        row.pop("kind_rank", None)
        if not detail:
            row["body"] = row["body"][:240]
            row["attrs"] = {key: row["attrs"][key] for key in ("actor", "status", "section", "requirement_id", "scope", "artifact_hash", "artifact_path", "title_path", "question") if key in row["attrs"]}
        return row

    async def graph(self, *, project_id=None, job_id=None, kind=None, status=None, node_id=None, depth=1, limit=100):
        if type(depth) is not int or not 0 <= depth <= 2 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("그래프 조회 범위가 올바르지 않습니다.")
        filters, params = [], []
        for column, value in (("j.project_id", project_id), ("n.job_id", job_id), ("n.kind", kind)):
            if value:
                filters.append(column + "=%s")
                params.append(value)
        if status == "superseded":
            filters.append("NOT n.active")
        elif status:
            filters.append("n.active AND n.attrs->>'status'=%s")
            params.append(status)
        elif not node_id:
            filters.append("n.active")
        base = "SELECT n.*,j.project_id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE "
        where = " AND ".join(filters) or "true"
        async with self.transaction(mode='read') as conn:
            if node_id:
                rows = (await (await conn.execute(base + where + " AND n.id=%s LIMIT %s", (*params, node_id, limit+1))).fetchall())
            else:
                # 유형별 시작점을 고르고 직접 연결을 우선 채운다.
                rows = (await (await conn.execute("SELECT * FROM (SELECT n.*,j.project_id,"
                    "row_number() OVER (PARTITION BY n.kind ORDER BY n.sequence DESC,n.id) AS kind_rank "
                    "FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE " + where +
                    ") ranked ORDER BY kind_rank,kind,sequence DESC,id LIMIT %s",
                    (*params, min(50, limit)))).fetchall())
                seeds = [row["id"] for row in rows]
                if seeds and len(rows) < limit:
                    rows += (await (await conn.execute(base + where + " AND NOT(n.id=ANY(%s)) AND n.id IN "
                        "(SELECT target FROM edges WHERE source=ANY(%s) UNION "
                        "SELECT source FROM edges WHERE target=ANY(%s)) "
                        "ORDER BY n.sequence DESC,n.id LIMIT %s",
                        (*params, seeds, seeds, seeds, limit-len(rows)))).fetchall())
                rows += (await (await conn.execute(base + where + " AND NOT(n.id=ANY(%s)) "
                    "ORDER BY n.sequence DESC,n.id LIMIT %s",
                    (*params, [row["id"] for row in rows], limit+1-len(rows)))).fetchall())
            found = {row["id"]: row for row in rows[:limit]}
            has_more = len(rows) > limit
            frontier = list(found)
            if node_id:
                for _ in range(depth):
                    if not frontier:
                        break
                    adjacent = (await (await conn.execute(base + where + " AND n.id NOT IN (SELECT unnest(%s::text[])) AND n.id IN "
                        "(SELECT target FROM edges WHERE source=ANY(%s) UNION SELECT source FROM edges WHERE target=ANY(%s)) "
                        "ORDER BY n.sequence DESC,n.id LIMIT %s", (*params, list(found), frontier, frontier, limit-len(found)+1))).fetchall())
                    has_more |= len(adjacent) > limit-len(found)
                    frontier = [row["id"] for row in adjacent[:limit-len(found)]]
                    found.update({row["id"]: row for row in adjacent if row["id"] in frontier})
            edges = (await (await conn.execute("SELECT id,source,target,kind FROM edges WHERE source=ANY(%s) AND target=ANY(%s)",
                                 (list(found), list(found)))).fetchall()) if found else []
            # 2026-11-13: 그래프와 반영 버전을 같은 읽기 스냅샷으로 반환한다.
            index = await self.projection_status(job_id, project_id=project_id)
            return {"nodes": [self._public(row) for row in found.values()], "edges": edges, "has_more": has_more, **index}

    async def search(self, query, *, project_id=None, kind=None, status=None, vector=None, model_id=None, job_id=None):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 20000:
            raise ValueError("검색어는 1~20000자로 입력하세요.")
        if kind and kind not in {"input", "decision", "requirement", "spec", "review"}:
            raise ValueError("지식 항목 유형이 올바르지 않습니다.")
        if status and status not in {"confirmed", "proposed", "assumption", "superseded"}:
            raise ValueError("지식 항목 상태가 올바르지 않습니다.")
        filters, params = "", []
        if project_id:
            filters = " AND j.project_id=%s"
            params.append(project_id)
        if job_id:
            filters += " AND n.job_id=%s"
            params.append(job_id)
        if status and status != "superseded":
            filters += " AND n.attrs->>'status'=%s"
            params.append(status)
        active = "NOT n.active" if status == "superseded" else "n.active"
        kinds = [kind] if kind else list(SEARCH_KINDS)
        base = " FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE " + active + " AND n.kind=ANY(%s)"
        from backend.knowledge.chunk_search import search
        return (await search(self, query, kinds, active, filters, params, vector, model_id))

    async def active_model(self):
        async with self.transaction(mode='read') as conn:
            return (await (await conn.execute("SELECT id,dimensions,max_length FROM models WHERE active")).fetchone())

    async def register_model(self, info):
        async with self.transaction() as conn:
            (await conn.execute("INSERT INTO models(id,dimensions,max_length) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (info["id"], info["dimensions"], info["max_length"])))
            (await conn.execute("UPDATE embedding_queue q SET status='pending',next_attempt=0 WHERE q.status='completed' AND EXISTS "
                         "(SELECT 1 FROM nodes n LEFT JOIN chunk_sets e ON e.node_id=n.id AND e.model_id=%s "
                         "WHERE n.id=q.node_id AND n.active AND n.attrs->>'scope'='product' AND (e.completed IS NULL OR NOT e.completed))", (info["id"],)))

    async def pending_embeddings(self, model_id, limit=1):
        async with self.transaction(mode='read') as conn:
            return (await (await conn.execute("SELECT n.id,n.body,n.kind,n.logical_key,n.attrs FROM nodes n JOIN embedding_queue q ON q.node_id=n.id "
                                "LEFT JOIN chunk_sets s ON s.node_id=n.id AND s.model_id=%s "
                                "WHERE n.active AND n.attrs->>'scope'='product' AND n.kind=ANY(%s) AND (s.completed IS NULL OR NOT s.completed) "
                                "AND q.status IN ('pending','failed') AND q.next_attempt<=extract(epoch from now()) "
                                "ORDER BY n.id LIMIT %s", (model_id, list(SEARCH_KINDS), limit))).fetchall())

    async def activate_model(self, model_id):
        async with self.transaction() as conn:
            if not (await (await conn.execute("SELECT id FROM models WHERE id=%s FOR UPDATE", (model_id,))).fetchone()):
                raise ValueError("등록된 임베딩 모델을 찾을 수 없습니다.")
            (await conn.execute("LOCK TABLE nodes IN SHARE MODE"))
            remaining = (await (await conn.execute("SELECT count(*) AS total FROM nodes n LEFT JOIN chunk_sets e "
                "ON e.node_id=n.id AND e.model_id=%s WHERE n.active AND n.attrs->>'scope'='product' AND n.kind=ANY(%s) AND (e.completed IS NULL OR NOT e.completed)",
                (model_id, list(SEARCH_KINDS)))).fetchone())["total"]
            if remaining:
                return False
            (await conn.execute("UPDATE models SET active=false WHERE active"))
            (await conn.execute("UPDATE models SET active=true WHERE id=%s", (model_id,)))
            return True

    async def embedding_failure(self, node_id):
        async with self.transaction() as conn:
            # 2026-11-13: 실패한 원본만 지연하고 다른 원본은 처리할 수 있게 남긴다.
            await conn.execute("UPDATE embedding_queue SET status='failed',attempts=attempts+1, "
                               "next_attempt=extract(epoch from now())+LEAST(300,power(2,LEAST(attempts+1,8))) "
                               "WHERE node_id=%s", (node_id,))
            await self.embedding_progress(conn, [node_id])

    async def embedding_progress(self, conn, node_ids):
        if not node_ids:
            return
        rows = await (await conn.execute('SELECT DISTINCT job_id FROM nodes WHERE id=ANY(%s)', (node_ids,))).fetchall()
        from backend.infrastructure.progress_store import ProgressStore
        progress = ProgressStore(self)
        for row in rows:
            await progress.capture_index(conn, row['job_id'])

    async def embedding_initialization_failure(self):
        # 2026-11-13: 모델 자체가 열리지 않으면 아직 선택되지 않은 원본도 실패로 표시하고 재시도한다.
        async with self.transaction() as conn:
            rows = await (await conn.execute("UPDATE embedding_queue SET status='failed',attempts=attempts+1, "
                               "next_attempt=extract(epoch from now())+LEAST(300,power(2,LEAST(attempts+1,8))) "
                               "WHERE status IN ('pending','failed') AND next_attempt<=extract(epoch from now()) RETURNING node_id")).fetchall()
            await self.embedding_progress(conn, [row['node_id'] for row in rows])

    async def chunk_vector(self, chunk, model_id):
        return (await self.chunks.chunk_vector(chunk, model_id))

    async def save_chunk(self, info, chunk, vector):
        return (await self.chunks.save_chunk(info, chunk, vector))

    async def complete_chunks(self, node_id, model_id, expected):
        return (await self.chunks.complete_chunks(node_id, model_id, expected))

    async def cleanup_inventory(self, conn, scope, ids):
        return (await self.cleanup.cleanup_inventory(conn, scope, ids))

    async def cleanup_delete(self, conn, inventory):
        return (await self.cleanup.cleanup_delete(conn, inventory))

    async def require_project(self, conn, ident):
        return (await self.decisions.require_project(conn, ident))

    async def registered_decisions(self, ident):
        return (await self.decisions.registered_decisions(ident))

    async def register_decision(self, ident, candidate):
        return (await self.decisions.register_decision(ident, candidate))

    async def deactivate_decision(self, ident, decision_id, version):
        return (await self.decisions.deactivate_decision(ident, decision_id, version))

    async def freeze_decisions(self, ident, selections):
        return (await self.decisions.freeze_decisions(ident, selections))
