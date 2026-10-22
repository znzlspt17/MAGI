"""트랜잭션 기반 PostgreSQL 저장소. 접속 오류의 원문은 외부에 남기지 않는다."""

from contextlib import contextmanager, nullcontext
import json
import logging
import re
import threading
from uuid import uuid4

from backend.knowledge.config import KnowledgeError
from backend.knowledge.projection import digest, project


SEARCH_KINDS = ("decision", "requirement", "spec")
logger = logging.getLogger(__name__)
WRITE_LOCK = 72410636


from backend.knowledge.chunk_store import ChunkStore
from backend.knowledge.cleanup import CleanupStore, MAINTENANCE_LOCK
from backend.access.context import ACTOR, TRANSACTION, METER, AccessError


from backend.knowledge.project_decisions import ProjectDecisionStore


class KnowledgeStore(ChunkStore, CleanupStore, ProjectDecisionStore):
    def __init__(self, config, connect=None):
        self.config = config
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self.connect = connect
        self._connections = threading.BoundedSemaphore(2)
        # 대기 중인 쓰기가 두 연결을 모두 점유하지 않게 연결 전에 직렬화한다.
        self._writers = threading.Lock()

    @contextmanager
    def transaction(self, *, mode="write"):
        from psycopg.rows import dict_row
        if mode not in {"read", "write", "maintenance"}:
            raise ValueError("DB 트랜잭션 모드가 올바르지 않습니다.")
        existing = TRANSACTION.get()
        if existing is not None and existing[0] is self:
            ranks = {"read": 0, "write": 1, "maintenance": 2}
            if ranks[mode] > ranks[existing[2]]:
                raise KnowledgeError("중첩 DB 트랜잭션의 잠금 모드를 승격할 수 없습니다.")
            yield existing[1]
            return
        stage = "connect"
        writer = self._writers if mode != "read" else nullcontext()
        try:
            with writer, self._connections:
                with self.connect(**self.config.connection, row_factory=dict_row) as conn:
                    if mode == "read":
                        # 여러 쿼리로 구성된 그래프·문서 조회는 같은 버전을 읽는다.
                        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    stage = "statement_timeout"
                    conn.execute("SET LOCAL statement_timeout = '15s'")
                    stage = "maintenance_lock"
                    lock = "pg_advisory_xact_lock" if mode == "maintenance" else "pg_advisory_xact_lock_shared"
                    conn.execute(f"SELECT {lock}(%s)", (MAINTENANCE_LOCK,))
                    if mode != "read":
                        stage = "write_lock"
                        conn.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
                    actor = ACTOR.get()
                    stage = "actor_context"
                    conn.execute("SELECT set_config('app.actor',%s,true),set_config('app.internal',%s,true)",
                                 (actor['id'] if actor else '', 'off' if actor else 'on'))
                    token = TRANSACTION.set((self, conn, mode))
                    try:
                        stage = "body"
                        yield conn
                        stage = "commit"
                    finally:
                        TRANSACTION.reset(token)
        except (KeyError, ValueError, KnowledgeError):
            raise
        except Exception as exc:
            # SQLSTATE는 고정 형식 코드만 허용하고 드라이버 메시지는 남기지 않는다.
            sqlstate = getattr(exc, "sqlstate", None)
            if not isinstance(sqlstate, str) or re.fullmatch(r"[0-9A-Z]{5}", sqlstate) is None:
                sqlstate = None
            logger.error(
                "DB transaction failed stage=%s exception_type=%s sqlstate=%s",
                stage, type(exc).__name__, sqlstate,
            )
            raise KnowledgeError("DB 작업에 실패했습니다. 연결·권한·스키마 상태를 확인하세요.") from None

    def migrate(self):
        from backend.knowledge.schema import migrate
        return migrate(self)

    @staticmethod
    def _json(value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    def projects(self):
        with self.transaction(mode='read') as conn:
            actor = ACTOR.get()
            return conn.execute("SELECT id,name FROM projects" + (" WHERE owner_id=%s" if actor else "") + " ORDER BY created_at,id", (actor['id'],) if actor else ()).fetchall()

    def create_project(self, name, ident=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError("프로젝트 이름은 1~120자로 입력하세요.")
        ident = ident or uuid4().hex
        with self.transaction() as conn:
            conn.execute("INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s) ON CONFLICT(id) DO NOTHING", (ident, name.strip(), ACTOR.get()['id'] if ACTOR.get() else None))
            return conn.execute("SELECT id,name FROM projects WHERE id=%s", (ident,)).fetchone()

    def save_job(self, job):
        with self.transaction() as conn:
            self._save_job(conn, job)

    def _save_job(self, conn, job):
        meter=METER.get()
        if meter is not None and job['id']==meter.jid:
            lease=conn.execute('SELECT job_id,generation,phase FROM service_lease WHERE singleton=1').fetchone()
            if lease['job_id']!=meter.jid or lease['generation']!=meter.generation or lease['phase']!='running':
                raise AccessError('이전 작업의 저장을 차단했습니다.', 'busy')
        if conn.execute("SELECT 1 FROM deleted_jobs WHERE id=%s", (job["id"],)).fetchone():
            raise ValueError("삭제된 작업은 다시 저장할 수 없습니다.")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job["id"],))
        if not conn.execute("SELECT 1 FROM projects WHERE id=%s", (job["project_id"],)).fetchone() and not conn.execute("SELECT 1 FROM jobs WHERE id=%s AND project_id=%s", (job["id"], job["project_id"])).fetchone():
            raise ValueError("프로젝트를 찾을 수 없습니다.")
        conn.execute("INSERT INTO jobs(id,project_id,data,owner_id) VALUES (%s,%s,%s,%s) "
                     "ON CONFLICT(id) DO UPDATE SET project_id=EXCLUDED.project_id,data=EXCLUDED.data",
                     (job["id"], job["project_id"], self._json(job), job.get('owner_id')))

    def jobs(self):
        with self.transaction(mode='read') as conn:
            return [row["data"] for row in conn.execute("SELECT data FROM jobs ORDER BY id").fetchall()]

    def accept_job(self, job, payload):
        # 내부 프로젝트와 최초 요청을 하나의 트랜잭션으로 접수한다.
        with self.transaction() as conn:
            if job["project_id"] == job["id"]:
                conn.execute("INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s)",
                             (job["id"], job["request"][:80], job.get("owner_id")))
            else:
                self.require_project(conn, job["project_id"])
            job["reused_decisions"] = self.freeze_decisions(job["project_id"], job.pop("_decision_selections", []))
            self._save_job(conn, job)
            conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,%s)",
                         (job["execution_id"], job["id"], self._json(
                             {"action": job["action"], "input": payload, "status": "queued"})))

    def record_action(self, job, payload):
        with self.transaction() as conn:
            self._save_job(conn, job)
            conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,%s) "
                         "ON CONFLICT(id) DO NOTHING", (job["execution_id"], job["id"],
                         self._json({"action": job["action"], "input": payload, "status": "queued"})))

    def action_records(self, job_id):
        with self.transaction(mode='read') as conn:
            return [{"id": row["id"], **row["data"]} for row in conn.execute(
                "SELECT id,data FROM executions WHERE job_id=%s AND data ? 'action' ORDER BY sequence", (job_id,)).fetchall()]

    def commit_stage(self, job, execution, stage, state, artifacts, *, connection=None):
        nodes, edges = ([], []) if stage == "impact_review" else project(job["id"], state, artifacts, stage)
        # 실행·단계·내용을 포함하므로 동일 재전송은 멱등이고 후속 버전은 보존된다.
        supplements = ("translations/", "impact_reviews/", "impact_requests/")
        identity_artifacts = artifacts if stage in {"import", "translation", "impact_review"} else {
            path: content for path, content in artifacts.items() if not path.startswith(supplements)}
        snapshot = digest([job["id"], execution, stage, state, identity_artifacts])
        with (self.transaction() if connection is None else nullcontext(connection)) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job["id"],))
            if conn.execute("SELECT id FROM snapshots WHERE id=%s", (snapshot,)).fetchone():
                return snapshot
            if stage not in {"import", "translation", "impact_review"}:
                durable = conn.execute("SELECT path,content FROM artifacts WHERE snapshot_id="
                    "(SELECT id FROM snapshots WHERE job_id=%s ORDER BY sequence DESC LIMIT 1) "
                    "AND (path LIKE 'translations/%%' OR path LIKE 'impact_reviews/%%' OR path LIKE 'impact_requests/%%')",
                    (job["id"],)).fetchall()
                artifacts = {path: content for path, content in artifacts.items() if not path.startswith(supplements)}
                artifacts.update({row["path"]: row["content"] for row in durable})
            self._save_job(conn, job)
            conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,%s) "
                         "ON CONFLICT(id) DO UPDATE SET data=executions.data || EXCLUDED.data",
                         (execution, job["id"], self._json({"stage": stage, "status": state.get("status")})))
            inserted = conn.execute("INSERT INTO snapshots(id,job_id,execution_id,stage,state) VALUES (%s,%s,%s,%s,%s) "
                                    "ON CONFLICT DO NOTHING RETURNING id", (snapshot, job["id"], execution, stage, self._json(state))).fetchone()
            if not inserted:
                return snapshot
            for path, content in artifacts.items():
                conn.execute("INSERT INTO artifacts(id,job_id,snapshot_id,path,content,content_hash) VALUES (%s,%s,%s,%s,%s,%s)",
                             (digest([snapshot, path]), job["id"], snapshot, path, content, digest(content)))
            owned = {"requirement_lock": ("requirement", "decision"), "spec_compile": ("spec", "decision"),
                     "checklist_critic": ("review",), "review_resolution": ("review",)}.get(stage, ())
            for kind in owned:
                current_keys = [node["logical_key"] for node in nodes if node["kind"] == kind]
                conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND kind=%s AND NOT(logical_key=ANY(%s))",
                             (job["id"], kind, current_keys))
            invalidated = {"requirement_lock": ["spec", "review"], "spec_compile": ["review"]}.get(stage, [])
            if invalidated:
                conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND kind=ANY(%s)", (job["id"], invalidated))
            node_ids = {}
            existing_nodes = set()
            by_content = {node["id"]: node for node in nodes}
            for node in nodes:
                previous = conn.execute("SELECT id,content_id,active FROM nodes WHERE job_id=%s AND logical_key=%s ORDER BY active DESC,sequence DESC LIMIT 1",
                                        (job["id"], node["logical_key"])).fetchone()
                if previous and previous["active"] and previous["content_id"] == node["id"]:
                    ident = previous["id"]
                    existing_nodes.add(node["id"])
                else:
                    ident = digest([node["id"], snapshot])
                    conn.execute("UPDATE nodes SET active=false WHERE job_id=%s AND logical_key=%s",
                                 (job["id"], node["logical_key"]))
                    conn.execute("INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                 (ident, node["id"], job["id"], node["logical_key"], node["kind"], node["body"], self._json(node["attrs"])))
                    if previous:
                        self._edge(conn, previous["id"], ident, "superseded")
                node_ids[node["id"]] = ident
                if node["kind"] in SEARCH_KINDS:
                    conn.execute("INSERT INTO embedding_queue(node_id) VALUES (%s) ON CONFLICT DO NOTHING", (ident,))
            for edge in edges:
                # 재사용 ID는 현재 제공한 문맥에서 검증된 것만 여기까지 도달한다.
                source_node = by_content.get(edge["source"], {})
                source_key = source_node.get("logical_key", "")
                if (edge["target"] in existing_nodes and edge["kind"] in {"evidence", "derived"}
                    and source_node.get("kind") == "input"
                    and (source_key == "user_feedback" or (source_key.startswith("user_answer:") and source_key.count(":") == 1))):
                    continue
                source = edge["source"] if edge["kind"] == "reused" else node_ids[edge["source"]]
                self._edge(conn, source, node_ids[edge["target"]], edge["kind"], edge["attrs"])
        return snapshot

    def save_prompt_references(self, job_id, content):
        """원격 호출 전에 대응표만 최신 스냅샷에 원자적으로 첨부한다."""
        self._save_supplement(job_id, {"state/prompt_references.json": content}, "prompt_references")

    def save_translation(self, job_id, translated):
        from backend.knowledge.runtime import is_artifact_path
        if not translated or any(not path.startswith("translations/") or not is_artifact_path(path) for path in translated):
            raise ValueError("번역 산출물 경로가 올바르지 않습니다.")
        self._save_supplement(job_id, translated, "translation")

    def save_impact(self, job_id, artifacts):
        from backend.knowledge.runtime import is_artifact_path
        if not artifacts or any(not path.startswith(("impact_reviews/", "impact_requests/")) or not is_artifact_path(path) for path in artifacts):
            raise ValueError("영향 분석 산출물 경로가 올바르지 않습니다.")
        self._save_supplement(job_id, artifacts, "impact_review")

    def _save_supplement(self, job_id, translated, stage):
        with self.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (job_id,))
            job = conn.execute("SELECT data FROM jobs WHERE id=%s", (job_id,)).fetchone()
            latest = conn.execute("SELECT id,state,execution_id FROM snapshots WHERE job_id=%s ORDER BY sequence DESC LIMIT 1", (job_id,)).fetchone()
            if job is None or latest is None:
                raise KeyError(job_id)
            rows = conn.execute("SELECT path,content FROM artifacts WHERE snapshot_id=%s", (latest["id"],)).fetchall()
            artifacts = {row["path"]: row["content"] for row in rows}
            artifacts.update(translated)
            # 실행 중인 작업의 최신 상태를 잠근 채 부가 산출물만 추가한다.
            self.commit_stage(job["data"], latest["execution_id"], stage, latest["state"], artifacts, connection=conn)

    def _edge(self, conn, source, target, kind, attrs=None):
        # 다른 작업의 생성 중 원본이 정리되면 본문은 보존하고 끊긴 재사용 연결만 생략한다.
        if kind == "reused" and conn.execute("SELECT 1 FROM deleted_nodes WHERE id=%s", (source,)).fetchone():
            return
        conn.execute("INSERT INTO edges(id,source,target,kind,attrs) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (digest([source, target, kind]), source, target, kind, self._json(attrs or {})))

    def restore(self, job_id):
        with self.transaction(mode='read') as conn:
            latest = conn.execute("SELECT id,state FROM snapshots WHERE job_id=%s ORDER BY sequence DESC LIMIT 1", (job_id,)).fetchone()
            if latest is None:
                return {}
            rows = conn.execute("SELECT path,content FROM artifacts WHERE snapshot_id=%s", (latest["id"],)).fetchall()
            artifacts = {row["path"]: row["content"] for row in rows}
            artifacts["state/state.json"] = json.dumps(latest["state"], ensure_ascii=False)
            return artifacts

    def node(self, ident):
        with self.transaction(mode='read') as conn:
            node = conn.execute("SELECT n.*,j.project_id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE n.id=%s", (ident,)).fetchone()
            if node is None:
                raise KeyError(ident)
            node = self._public(node, detail=True)
            node["edges"] = conn.execute("SELECT e.source,e.target,e.kind,e.attrs,left(other.body,100) AS other_body "
                "FROM edges e JOIN nodes other ON other.id=CASE WHEN e.source=%s THEN e.target ELSE e.source END "
                "WHERE e.source=%s OR e.target=%s LIMIT 200", (ident, ident, ident)).fetchall()
            path = node["attrs"].get("artifact_path")
            content_hash = node["attrs"].get("artifact_hash")
            if path and content_hash:
                doc = conn.execute("SELECT content FROM artifacts WHERE job_id=%s AND path=%s AND content_hash=%s LIMIT 1",
                                   (node["job_id"], path, content_hash)).fetchone()
                if doc:
                    # 전송 한도를 지키고 전체 문서는 별도 페이지로 제공한다.
                    node["document"] = doc["content"][:12000]
                    node["document_has_more"] = len(doc["content"]) > 12000
                    node["document_next_offset"] = len(node["document"])
            return node

    def node_records(self, identities):
        with self.transaction(mode='read') as conn:
            rows = conn.execute("SELECT n.*,j.project_id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE n.id=ANY(%s)",
                                (list(identities),)).fetchall()
            return {row["id"]: self._public(row, detail=True) for row in rows}

    def artifact_page(self, job_id, path, content_hash, offset=0):
        if type(offset) is not int or offset < 0:
            raise ValueError("문서 위치가 올바르지 않습니다.")
        with self.transaction(mode='read') as conn:
            row = conn.execute("SELECT content FROM artifacts WHERE job_id=%s AND path=%s AND content_hash=%s LIMIT 1",
                               (job_id, path, content_hash)).fetchone()
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

    def graph(self, *, project_id=None, job_id=None, kind=None, status=None, node_id=None, depth=1, limit=100):
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
        with self.transaction(mode='read') as conn:
            if node_id:
                rows = conn.execute(base + where + " AND n.id=%s LIMIT %s", (*params, node_id, limit+1)).fetchall()
            else:
                # 유형별 시작점을 고르고 직접 연결을 우선 채운다.
                rows = conn.execute("SELECT * FROM (SELECT n.*,j.project_id,"
                    "row_number() OVER (PARTITION BY n.kind ORDER BY n.sequence DESC,n.id) AS kind_rank "
                    "FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE " + where +
                    ") ranked ORDER BY kind_rank,kind,sequence DESC,id LIMIT %s",
                    (*params, min(50, limit))).fetchall()
                seeds = [row["id"] for row in rows]
                if seeds and len(rows) < limit:
                    rows += conn.execute(base + where + " AND NOT(n.id=ANY(%s)) AND n.id IN "
                        "(SELECT target FROM edges WHERE source=ANY(%s) UNION "
                        "SELECT source FROM edges WHERE target=ANY(%s)) "
                        "ORDER BY n.sequence DESC,n.id LIMIT %s",
                        (*params, seeds, seeds, seeds, limit-len(rows))).fetchall()
                rows += conn.execute(base + where + " AND NOT(n.id=ANY(%s)) "
                    "ORDER BY n.sequence DESC,n.id LIMIT %s",
                    (*params, [row["id"] for row in rows], limit+1-len(rows))).fetchall()
            found = {row["id"]: row for row in rows[:limit]}
            has_more = len(rows) > limit
            frontier = list(found)
            if node_id:
                for _ in range(depth):
                    if not frontier:
                        break
                    adjacent = conn.execute(base + where + " AND n.id NOT IN (SELECT unnest(%s::text[])) AND n.id IN "
                        "(SELECT target FROM edges WHERE source=ANY(%s) UNION SELECT source FROM edges WHERE target=ANY(%s)) "
                        "ORDER BY n.sequence DESC,n.id LIMIT %s", (*params, list(found), frontier, frontier, limit-len(found)+1)).fetchall()
                    has_more |= len(adjacent) > limit-len(found)
                    frontier = [row["id"] for row in adjacent[:limit-len(found)]]
                    found.update({row["id"]: row for row in adjacent if row["id"] in frontier})
            edges = conn.execute("SELECT id,source,target,kind FROM edges WHERE source=ANY(%s) AND target=ANY(%s)",
                                 (list(found), list(found))).fetchall() if found else []
            return {"nodes": [self._public(row) for row in found.values()], "edges": edges, "has_more": has_more}

    def search(self, query, *, project_id=None, kind=None, status=None, vector=None, model_id=None, job_id=None):
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
        return search(self, query, kinds, active, filters, params, vector, model_id)

    def active_model(self):
        with self.transaction(mode='read') as conn:
            return conn.execute("SELECT id,dimensions,max_length FROM models WHERE active").fetchone()

    def register_model(self, info):
        with self.transaction() as conn:
            conn.execute("INSERT INTO models(id,dimensions,max_length) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                         (info["id"], info["dimensions"], info["max_length"]))
            conn.execute("UPDATE embedding_queue q SET status='pending' WHERE EXISTS "
                         "(SELECT 1 FROM nodes n LEFT JOIN chunk_sets e ON e.node_id=n.id AND e.model_id=%s "
                         "WHERE n.id=q.node_id AND n.active AND n.attrs->>'scope'='product' AND (e.completed IS NULL OR NOT e.completed))", (info["id"],))

    def pending_embeddings(self, model_id, limit=1):
        with self.transaction(mode='read') as conn:
            return conn.execute("SELECT n.id,n.body,n.kind,n.logical_key,n.attrs FROM nodes n "
                                "LEFT JOIN chunk_sets s ON s.node_id=n.id AND s.model_id=%s "
                                "WHERE n.active AND n.attrs->>'scope'='product' AND n.kind=ANY(%s) AND (s.completed IS NULL OR NOT s.completed) "
                                "ORDER BY n.id LIMIT %s", (model_id, list(SEARCH_KINDS), limit)).fetchall()

    def activate_model(self, model_id):
        with self.transaction() as conn:
            if not conn.execute("SELECT id FROM models WHERE id=%s FOR UPDATE", (model_id,)).fetchone():
                raise ValueError("등록된 임베딩 모델을 찾을 수 없습니다.")
            conn.execute("LOCK TABLE nodes IN SHARE MODE")
            remaining = conn.execute("SELECT count(*) AS total FROM nodes n LEFT JOIN chunk_sets e "
                "ON e.node_id=n.id AND e.model_id=%s WHERE n.active AND n.attrs->>'scope'='product' AND n.kind=ANY(%s) AND (e.completed IS NULL OR NOT e.completed)",
                (model_id, list(SEARCH_KINDS))).fetchone()["total"]
            if remaining:
                return False
            conn.execute("UPDATE models SET active=false WHERE active")
            conn.execute("UPDATE models SET active=true WHERE id=%s", (model_id,))
            return True

    def embedding_failure(self):
        with self.transaction() as conn:
            conn.execute("UPDATE embedding_queue SET attempts=attempts+1 WHERE status='pending'")
