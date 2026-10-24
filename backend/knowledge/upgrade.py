"""중지된 서비스의 업무 자료만 전환한다. 인증 자료와 비용 원장은 읽거나 복제하지 않는다."""

import json
from importlib.resources import files

from backend.knowledge.core import content_hash
from backend.knowledge.config import KnowledgeError
from backend.knowledge.projection import digest


TABLES = (
    "projects",
    "jobs",
    "executions",
    "nodes",
    "edges",
    "models",
    "embedding_queue",
    "chunks",
    "chunk_sets",
    "chunk_vectors",
    "embeddings",
    "project_decisions",
    "deleted_jobs",
    "deleted_nodes",
    "cleanup_commits",
)


def inventory(conn):
    """정렬과 시각 표기를 고정해 업무 자료 변경을 검출한다."""
    result = {}
    for name in (*TABLES, "snapshots", "artifacts"):
        rows = conn.execute(
            f"SELECT to_jsonb(t) AS data FROM public.{name} t ORDER BY id"
            if name
            not in {"embedding_queue", "chunk_sets", "embeddings", "chunk_vectors"}
            else f"SELECT to_jsonb(t) AS data FROM public.{name} t ORDER BY to_jsonb(t)::text"
        ).fetchall()
        result[name] = {"count": len(rows), "hash": digest([r["data"] for r in rows])}
    return result


def migrate_business(store):
    """전체 복사를 한 트랜잭션으로 저장한다. 재실행은 원본 일치 여부부터 검사한다."""
    from psycopg import sql

    with store.transaction(mode="maintenance") as conn:
        if not conn.execute(
            "SELECT pg_try_advisory_xact_lock(72410635) AS acquired"
        ).fetchone()["acquired"]:
            raise KnowledgeError("서비스를 먼저 중지하세요.")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL statement_timeout=0")
        conn.execute(
            sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
                sql.SQL(",").join(
                    sql.Identifier("public", name)
                    for name in (*TABLES, "snapshots", "artifacts")
                )
            )
        )
        source = inventory(conn)
        fingerprint = digest(source)
        if conn.execute(
            "SELECT 1 FROM public.snapshots WHERE state->>'workflow_schema' IS DISTINCT FROM '1' LIMIT 1"
        ).fetchone():
            raise ValueError("현재 실행 형식으로 전환되지 않은 과거 상태가 있습니다.")
        if conn.execute(
            "SELECT to_regclass('core.installation') AS name"
        ).fetchone()["name"]:
            previous = conn.execute(
                "SELECT source_hash,verified FROM core.installation"
            ).fetchone()
            if previous["verified"]:
                raise KnowledgeError(
                    "이미 사용이 허용된 DB입니다. 전환을 다시 실행하지 마세요."
                )
            if previous["source_hash"] != fingerprint:
                raise KnowledgeError("전환 이후 원본 업무 데이터가 변경되었습니다.")
            return source
        conn.execute(
            files("backend.knowledge").joinpath("core.sql").read_text(encoding="utf-8")
        )
        for name in TABLES:
            columns = [
                r["column_name"]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                    ("public", name),
                ).fetchall()
            ]
            names = sql.SQL(",").join(map(sql.Identifier, columns))
            conn.execute(
                sql.SQL(
                    "INSERT INTO {} ({}) OVERRIDING SYSTEM VALUE SELECT {} FROM {}"
                ).format(
                    sql.Identifier("core", name),
                    names,
                    names,
                    sql.Identifier("public", name),
                )
            )
        conn.execute(
            "INSERT INTO history_archive SELECT id,job_id,execution_id,stage,state,created_at,sequence FROM public.snapshots"
        )
        rows = conn.execute(
            "SELECT a.*,s.sequence AS snapshot_sequence FROM public.artifacts a "
            "JOIN public.snapshots s ON s.id=a.snapshot_id ORDER BY s.sequence,a.path"
        ).fetchall()
        histories = {}
        for row in rows:
            checksum = content_hash(row["content"])
            if checksum != row["content_hash"]:
                raise ValueError("원본 문서 해시가 일치하지 않습니다.")
            conn.execute(
                "INSERT INTO document_bodies(job_id,hash,content) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (row["job_id"], checksum, row["content"]),
            )
            conn.execute(
                "INSERT INTO document_versions(id,job_id,name,content_hash,source_id,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    row["job_id"],
                    row["path"],
                    checksum,
                    row["snapshot_id"],
                    row["created_at"],
                ),
            )
            if row["path"].endswith("state/provider_usage.json"):
                usage = json.loads(row["content"])
                if not isinstance(usage.get("attempts"), list):
                    raise ValueError("관측 사용량 형식을 확인할 수 없습니다.")
                scope = row["path"][: -len("state/provider_usage.json")]
                conn.execute(
                    "INSERT INTO model_usage(job_id,scope,data) VALUES (%s,%s,%s) ON CONFLICT(job_id,scope) DO UPDATE SET data=EXCLUDED.data",
                    (row["job_id"], scope, store._json(usage)),
                )
            if row["path"] == "state/execution_history.json":
                histories[row["job_id"]] = json.loads(row["content"])
        for jid, history in histories.items():
            for execution in history.get("executions", []):
                timeline = {
                    k: v
                    for k, v in execution.items()
                    if k not in {"input", "id", "action", "stage"}
                }
                conn.execute(
                    "UPDATE executions SET timeline=%s WHERE id=%s AND job_id=%s",
                    (store._json(timeline), execution["id"], jid),
                )
            for node in history.get("nodes", []):
                if node.get("action"):
                    node.pop("result", None)
                document = node.get("detail", {}).get("document")
                if document and document.get("ref"):
                    version = conn.execute(
                        "SELECT id FROM document_versions WHERE job_id=%s AND name=%s ORDER BY sequence DESC LIMIT 1",
                        (jid, document.pop("ref")),
                    ).fetchone()
                    if not version:
                        raise ValueError("실행 이력의 문서 참조가 없습니다.")
                    document["version_id"] = version["id"]
                conn.execute(
                    "INSERT INTO execution_events(id,job_id,execution_id,data) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data",
                    (node["id"], jid, node["execution_id"], store._json(node)),
                )
        for name in ("executions", "nodes"):
            conn.execute(
                sql.SQL(
                    "SELECT setval(pg_get_serial_sequence(%s,'sequence'),COALESCE(max(sequence),0)+1,false) FROM {}"
                ).format(sql.Identifier("core", name)),
                ("core." + name,),
            )
        conn.execute("UPDATE installation SET source_hash=%s", (fingerprint,))
        verify_business(conn, source)
        return source


def install(store):
    """신규 DB에는 현재 규격만 설치한다. 기존 DB의 인증 자료를 덮어쓰지 않는다."""
    with store.transaction(mode="maintenance") as conn:
        if not conn.execute(
            "SELECT pg_try_advisory_xact_lock(72410635) AS acquired"
        ).fetchone()["acquired"]:
            raise KnowledgeError("서비스를 먼저 중지하세요.")
        existing = conn.execute(
            "SELECT to_regclass('core.installation') AS name"
        ).fetchone()["name"]
        if existing:
            if (
                conn.execute(
                    "SELECT source_hash FROM core.installation"
                ).fetchone()["source_hash"]
                is not None
            ):
                raise KnowledgeError("기존 자료 전환은 migrate 명령을 사용하세요.")
        else:
            if conn.execute("SELECT to_regclass('public.users') AS name").fetchone()[
                "name"
            ]:
                raise KnowledgeError("기존 DB에는 migrate 명령을 사용하세요.")
            conn.execute("SET LOCAL search_path TO public")
            conn.execute(
                files("backend.access")
                .joinpath("schema.sql")
                .read_text(encoding="utf-8")
            )
            conn.execute(
                files("backend.knowledge")
                .joinpath("core.sql")
                .read_text(encoding="utf-8")
            )
    initialize_checkpoints(store)


def verify_business(conn, expected):
    for name in TABLES:
        actual = conn.execute(
            f"SELECT count(*) AS total FROM core.{name}"
        ).fetchone()["total"]
        if actual != expected[name]["count"]:
            raise KnowledgeError("업무 데이터 전환 건수가 일치하지 않습니다.")
        from psycopg import sql

        columns = [
            r["column_name"]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                ("public", name),
            ).fetchall()
        ]
        names = sql.SQL(",").join(map(sql.Identifier, columns))
        differs = conn.execute(
            sql.SQL(
                "SELECT 1 FROM ((SELECT {} FROM {} EXCEPT ALL SELECT {} FROM {}) "
                "UNION ALL (SELECT {} FROM {} EXCEPT ALL SELECT {} FROM {})) differences LIMIT 1"
            ).format(
                names,
                sql.Identifier("public", name),
                names,
                sql.Identifier("core", name),
                names,
                sql.Identifier("core", name),
                names,
                sql.Identifier("public", name),
            )
        ).fetchone()
        if differs:
            raise KnowledgeError("업무 내용·시각·소유권·관계가 보존되지 않았습니다.")
    if conn.execute(
        "SELECT 1 FROM ((SELECT * FROM public.snapshots EXCEPT ALL SELECT * FROM core.history_archive) "
        "UNION ALL (SELECT * FROM core.history_archive EXCEPT ALL SELECT * FROM public.snapshots)) d LIMIT 1"
    ).fetchone():
        raise KnowledgeError("과거 실행 원문이 보존되지 않았습니다.")
    count = conn.execute(
        "SELECT count(*) AS total FROM core.document_versions"
    ).fetchone()["total"]
    if count < expected["artifacts"]["count"]:
        raise KnowledgeError("문서 버전 전환 건수가 일치하지 않습니다.")
    mismatch = conn.execute(
        "SELECT 1 FROM public.artifacts a LEFT JOIN core.document_versions d ON d.id=a.id "
        "LEFT JOIN core.document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
        "WHERE d.id IS NULL OR (a.job_id,a.path,a.content,a.created_at,a.content_hash) "
        "IS DISTINCT FROM (d.job_id,d.name,b.content,d.created_at,d.content_hash) LIMIT 1"
    ).fetchone()
    if mismatch:
        raise KnowledgeError("문서의 내용·소유 작업·시각이 보존되지 않았습니다.")


def initialize_checkpoints(store):
    """공식 저장소 설치는 서비스 실행과 분리한다."""
    from backend.knowledge.core import checkpoint_store

    with checkpoint_store(store) as saver:
        if not saver.conn.execute(
            "SELECT pg_try_advisory_lock(72410635) AS acquired"
        ).fetchone()["acquired"]:
            raise KnowledgeError("서비스를 먼저 중지하세요.")
        saver.conn.execute("CREATE SCHEMA IF NOT EXISTS workflow")
        saver.conn.execute("SET search_path TO workflow,public")
        saver.setup()
        saver.conn.execute(
            "CREATE TABLE IF NOT EXISTS workflow_task_results (thread_id text NOT NULL,task_id text NOT NULL,"
            "status text NOT NULL,payload text NOT NULL,PRIMARY KEY(thread_id,task_id))"
        )


def require_conversion_source(store):
    """실행 자료를 바꾸기 전에 원본과 전환 대상의 보존 여부를 확인한다."""
    with store.transaction(mode="maintenance") as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        row = conn.execute(
            "SELECT source_hash,verified FROM core.installation"
        ).fetchone()
        if row["verified"]:
            raise KnowledgeError(
                "이미 사용이 허용된 DB입니다. 전환 명령을 다시 실행하지 마세요."
            )
        if row["source_hash"] is not None:
            source = inventory(conn)
            if digest(source) != row["source_hash"]:
                raise KnowledgeError("전환 중 원본 업무 자료가 변경되었습니다.")
            verify_business(conn, source)


def convert_checkpoints(store):
    """대기 노드만 실행해 interrupt를 복원한다. 모델·검색·임베딩은 호출하지 않는다."""
    from backend.knowledge.core import checkpoint_store
    from backend.pipeline.agent_workflow import AgentWorkflow
    from backend.models import State
    from dataclasses import fields

    allowed = {f.name for f in fields(State)} | {"_interview_direction_changing"}
    with store.transaction(mode="read") as conn:
        jobs = conn.execute("SELECT id,data FROM core.jobs ORDER BY id").fetchall()
    completed = 0
    with checkpoint_store(store) as saver:
        if not saver.conn.execute(
            "SELECT pg_try_advisory_lock(72410635) AS acquired"
        ).fetchone()["acquired"]:
            raise KnowledgeError("서비스를 먼저 중지하세요.")
        require_conversion_source(store)
        for job in jobs:
            config = {"configurable": {"thread_id": job["id"]}}
            docs = store.documents(job["id"])
            graph = AgentWorkflow(None, None, docs, None).build(saver)
            snapshot = graph.get_state(config)
            if not snapshot.values or snapshot.values.get("workflow_schema") != 1:
                raise ValueError(
                    "전환할 공식 checkpoint가 없거나 실행 버전이 다릅니다."
                )
            previous = snapshot.values
            state = {k: v for k, v in previous.items() if k in allowed}
            for key, name in [
                ("approval_candidate_spec", "draft/approval_candidate_spec.en.md"),
                ("final_agent_spec", "final/FINAL_AGENT_SPEC.md"),
                ("critical_report", "critical/CRITICAL_REPORT.ko.md"),
            ]:
                if state.get(key):
                    if not docs.exists(name):
                        raise ValueError("실행 상태가 가리키는 문서가 없습니다.")
                    state[key] = name
            if state.get("status") == "FINALIZED" and not snapshot.next:
                graph.update_state(config, state, as_node="finalize")
            elif snapshot.next == ("wait",) and any(
                t.interrupts for t in snapshot.tasks
            ):
                # ask는 wait으로만 연결되므로 사용자 입력 대기 이외의 코드는 실행되지 않는다.
                graph.update_state(config, state, as_node="ask")
                graph.invoke(None, config=config, durability="sync")
                if graph.get_state(config).next != ("wait",) or not any(
                    t.interrupts for t in graph.get_state(config).tasks
                ):
                    raise ValueError("질문·승인 대기를 복원하지 못했습니다.")
            elif snapshot.next:
                # 실패한 노드는 사용자 재개까지 그대로 보존한다.
                if any(k not in allowed for k in previous):
                    raise ValueError(
                        "실패 checkpoint에 지원하지 않는 상태가 남았습니다. 별도 확인이 필요합니다."
                    )
            else:
                raise ValueError("완료·대기·실패 중 어느 상태인지 확인할 수 없습니다.")
            after = graph.get_state(config)
            for key in (
                "original_user_request",
                "requirement_lock_sheet",
                "latest_completed",
                "user_approval_status",
            ):
                if previous.get(key) != after.values.get(key):
                    raise ValueError("원문·요구사항·승인 상태가 변경되었습니다.")
            records = saver.conn.execute(
                "SELECT task_id,payload FROM workflow_task_results WHERE thread_id=%s AND status='completed'",
                (job["id"],),
            ).fetchall()
            for record in records:
                packet = json.loads(record["payload"])
                if "artifacts" not in packet:
                    continue
                references = {}
                for name, text in packet.pop("artifacts").items():
                    if name in {
                        "state/state.json",
                        "state/provider_usage.json",
                        "state/execution_history.json",
                    }:
                        continue
                    archived = docs.scope("journal_archive/" + record["task_id"])
                    archived.write_text(name, text)
                    references[name] = archived.reference(name)
                packet["documents"] = references
                packet["result"] = {
                    k: v for k, v in packet["result"].items() if k in allowed
                }
                for key, name in [
                    ("approval_candidate_spec", "draft/approval_candidate_spec.en.md"),
                    ("final_agent_spec", "final/FINAL_AGENT_SPEC.md"),
                    ("critical_report", "critical/CRITICAL_REPORT.ko.md"),
                ]:
                    if packet["result"].get(key):
                        packet["result"][key] = name
                saver.conn.execute(
                    "UPDATE workflow_task_results SET payload=%s WHERE thread_id=%s AND task_id=%s",
                    (
                        json.dumps(packet, ensure_ascii=False),
                        job["id"],
                        record["task_id"],
                    ),
                )
            completed += 1
    return completed


def verify_and_enable(store, *, application_role):
    from psycopg import sql

    count = convert_checkpoints(store)
    with store.transaction(mode="maintenance") as conn:
        if not conn.execute(
            "SELECT pg_try_advisory_xact_lock(72410635) AS acquired"
        ).fetchone()["acquired"]:
            raise KnowledgeError("서비스를 먼저 중지하세요.")
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        row = conn.execute(
            "SELECT source_hash FROM core.installation FOR UPDATE"
        ).fetchone()
        if row["source_hash"] is None:
            if conn.execute("SELECT to_regclass('public.jobs') AS name").fetchone()[
                "name"
            ]:
                raise KnowledgeError("기존 자료의 전환 기록이 없습니다.")
            source = {"snapshots": {"count": 0}}
        else:
            source = inventory(conn)
            if row["source_hash"] != digest(source):
                raise KnowledgeError("전환 중 원본 업무 자료가 변경되었습니다.")
            verify_business(conn, source)
        service = conn.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s",
            (application_role,),
        ).fetchone()
        if not service or service["rolsuper"] or service["rolbypassrls"]:
            raise ValueError("일반 서비스 DB 역할을 지정하세요.")
        role = sql.Identifier(application_role)
        conn.execute(
            sql.SQL(
                "GRANT USAGE ON SCHEMA public,core,workflow TO {}"
            ).format(role)
        )
        conn.execute(
            sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA core,workflow TO {}"
            ).format(role)
        )
        conn.execute(
            sql.SQL(
                "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA core,workflow TO {}"
            ).format(role)
        )
        accounts = (
            "users",
            "sessions",
            "login_states",
            "service_lease",
            "daily_usage",
            "cost_calls",
            "admissions",
            "admin_audit",
            "service_settings",
            "request_windows",
        )
        conn.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO {}").format(
                sql.SQL(",").join(sql.Identifier("public", t) for t in accounts), role
            )
        )
        conn.execute("UPDATE core.installation SET verified=true")
    return {
        "verified_jobs": count,
        "historical_snapshots": source["snapshots"]["count"],
    }
