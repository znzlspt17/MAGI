"""업무 데이터의 설치·문서 저장. 실행 checkpoint와 파일 사본을 만들지 않는다."""

import json
from contextlib import contextmanager

from backend.errors import ArtifactError


def content_hash(text):
    from backend.knowledge.projection import digest

    return digest(text)


class Documents:
    """작업에 속한 문서 버전을 직접 읽고 쓴다. 이름은 파일 시스템 경로가 아니다."""

    def __init__(self, store, job_id, *, prefix="", runtime=None):
        self.store, self.job_id = store, job_id
        self.prefix, self.runtime = prefix, runtime
        self.state = {}
        self.changed = {}

    def scope(self, prefix):
        return Documents(
            self.store,
            self.job_id,
            prefix=self._name(prefix) + "/",
            runtime=self.runtime,
        )

    def _name(self, name):
        if (
            not isinstance(name, str)
            or not name
            or name.startswith("/")
            or "\\" in name
            or ".." in name.split("/")
        ):
            raise ArtifactError("문서 이름이 올바르지 않습니다.")
        return self.prefix + name

    def exists(self, name):
        with self.store.transaction(mode="read") as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM document_versions WHERE job_id=%s AND name=%s LIMIT 1",
                    (self.job_id, self._name(name)),
                ).fetchone()
                is not None
            )

    def read_text(self, name):
        with self.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT b.content FROM document_versions d JOIN document_bodies b "
                "ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
                "WHERE d.job_id=%s AND d.name=%s ORDER BY d.sequence DESC LIMIT 1",
                (self.job_id, self._name(name)),
            ).fetchone()
        if row is None:
            raise ArtifactError("문서를 찾을 수 없습니다.")
        return row["content"]

    def read_json(self, name):
        return json.loads(self.read_text(name))

    def write_text(self, name, content, *, overwrite=True):
        name = self._name(name)
        if not isinstance(content, str):
            raise TypeError("문서 본문은 문자열이어야 합니다.")
        checksum = content_hash(content)
        with self.store.transaction() as conn:
            meter = getattr(self.runtime, "meter", None)
            if meter is not None:
                meter.access.execution(conn, meter.uid, meter.jid, meter.generation, meter.execution_id)
            conn.execute("SELECT id FROM jobs WHERE id=%s FOR UPDATE", (self.job_id,))
            latest = conn.execute(
                "SELECT content_hash FROM document_versions WHERE job_id=%s AND name=%s "
                "ORDER BY sequence DESC LIMIT 1",
                (self.job_id, name),
            ).fetchone()
            if latest and latest["content_hash"] == checksum:
                return name
            if latest and not overwrite:
                raise ArtifactError("이미 저장된 문서를 덮어쓸 수 없습니다.")
            conn.execute(
                "INSERT INTO document_bodies(job_id,hash,content) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.job_id, checksum, content),
            )
            from uuid import uuid4

            ident = uuid4().hex
            conn.execute(
                "INSERT INTO document_versions(id,job_id,name,content_hash) VALUES (%s,%s,%s,%s)",
                (ident, self.job_id, name, checksum),
            )
        self.changed[name] = ident
        return name

    def write_json(self, name, value, *, overwrite=True):
        return self.write_text(
            name,
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            overwrite=overwrite,
        )

    def all(self):
        with self.store.transaction(mode="read") as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (d.name) d.name,b.content FROM document_versions d "
                "JOIN document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
                "WHERE d.job_id=%s AND starts_with(d.name,%s) ORDER BY d.name,d.sequence DESC",
                (self.job_id, self.prefix),
            ).fetchall()
        return {r["name"][len(self.prefix) :]: r["content"] for r in rows}

    def workflow_snapshot(self):
        from backend.pipeline.agent_workflow import AgentWorkflow

        with self.store.transaction(mode="read") as conn:
            if not conn.execute(
                "SELECT id FROM jobs WHERE id=%s", (self.job_id,)
            ).fetchone():
                raise KeyError(self.job_id)
        with checkpoint_store(self.store) as saver:
            graph = AgentWorkflow(None, None, self, None).build(saver)
            return graph.get_state({"configurable": {"thread_id": self.job_id}})

    def reference(self, name):
        with self.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT id FROM document_versions WHERE job_id=%s AND name=%s ORDER BY sequence DESC LIMIT 1",
                (self.job_id, self._name(name)),
            ).fetchone()
        return row["id"] if row else None

    def version(self, ident):
        with self.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT b.content FROM document_versions d JOIN document_bodies b "
                "ON (b.job_id,b.hash)=(d.job_id,d.content_hash) WHERE d.job_id=%s AND d.id=%s",
                (self.job_id, ident),
            ).fetchone()
        return row["content"] if row else None

    def bind_versions(self, references):
        for name, ident in references.items():
            text = self.version(ident)
            if text is None:
                raise ArtifactError("작업 결과가 참조하는 문서 버전이 없습니다.")
            self.write_text(name, text)

    def usage(self):
        with self.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT data FROM model_usage WHERE job_id=%s AND scope=%s",
                (self.job_id, self.prefix),
            ).fetchone()
        return row["data"] if row else {"attempts": [], "recording_incomplete": False}

    def save_usage(self, value):
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO model_usage(job_id,scope,data) VALUES (%s,%s,%s) "
                "ON CONFLICT(job_id,scope) DO UPDATE SET data=EXCLUDED.data",
                (self.job_id, self.prefix, self.store._json(value)),
            )


@contextmanager
def checkpoint_store(store):
    """설치 시 준비한 공식 checkpointer를 열기만 한다."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    with store.connect(
        **store.config.connection, autocommit=True, row_factory=dict_row
    ) as conn:
        conn.execute("SET search_path TO workflow, public")
        yield PostgresSaver(conn)
