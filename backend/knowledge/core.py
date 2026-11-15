"""업무 데이터의 설치·문서 저장. 실행 checkpoint와 파일 사본을 만들지 않는다."""

import json
import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from uuid import uuid4

from backend.errors import ArtifactError


class DocumentStage:
    def __init__(self, store, job_id):
        self.store, self.job_id, self.task = store, job_id, asyncio.current_task()
        self.items = {}
        self.history = []

    def owns(self, documents):
        return self.store is documents.store and self.job_id == documents.job_id and self.task is asyncio.current_task()


_DOCUMENT_STAGE: ContextVar[DocumentStage | None] = ContextVar('document_stage', default=None)


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

    @contextmanager
    def stage_writes(self):
        # 2026-11-13: 모델 대기 중 연결을 잡지 않고 산출물과 색인 큐를 함께 확정한다.
        stage = DocumentStage(self.store, self.job_id)
        token = _DOCUMENT_STAGE.set(stage)
        try:
            yield stage
        finally:
            _DOCUMENT_STAGE.reset(token)

    def _stage(self):
        stage = _DOCUMENT_STAGE.get()
        return stage if stage is not None and stage.owns(self) else None

    async def flush_stage(self, stage):
        for name, item in stage.history:
            await self._write_text(name, item['content'], overwrite=item['overwrite'], ident=item['id'])

    def restore_stage(self, history):
        # 2026-11-13: 저장된 모델 결과를 재호출 없이 재생할 때도 원래 버전 ID를 유지한다.
        stage = DocumentStage(self.store, self.job_id)
        for name, item in history:
            stage.history.append((name, item))
            stage.items[name] = item
        return stage

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

    async def exists(self, name):
        stage = self._stage()
        if stage is not None and self._name(name) in stage.items:
            return True
        async with self.store.transaction(mode="read") as conn:
            return (
                (await (await conn.execute(
                    "SELECT 1 FROM document_versions WHERE job_id=%s AND name=%s LIMIT 1",
                    (self.job_id, self._name(name)),
                )).fetchone())
                is not None
            )

    async def read_text(self, name):
        stage = self._stage()
        if stage is not None and self._name(name) in stage.items:
            return stage.items[self._name(name)]['content']
        async with self.store.transaction(mode="read") as conn:
            row = (await (await conn.execute(
                "SELECT b.content FROM document_versions d JOIN document_bodies b "
                "ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
                "WHERE d.job_id=%s AND d.name=%s ORDER BY d.sequence DESC LIMIT 1",
                (self.job_id, self._name(name)),
            )).fetchone())
        if row is None:
            raise ArtifactError("문서를 찾을 수 없습니다.")
        return row["content"]

    async def read_json(self, name):
        return json.loads((await self.read_text(name)))

    async def write_text(self, name, content, *, overwrite=True):
        name = self._name(name)
        if not isinstance(content, str):
            raise TypeError("문서 본문은 문자열이어야 합니다.")
        inherited = _DOCUMENT_STAGE.get()
        if inherited is not None and inherited.store is self.store and inherited.job_id == self.job_id and inherited.task is not asyncio.current_task():
            raise ArtifactError("다른 태스크의 미확정 문서에 쓸 수 없습니다.")
        stage = self._stage()
        # state에는 외부 호출 재전송 방지와 감사 정보가 있어 즉시 확정한다.
        if stage is not None and not name.startswith('state/'):
            previous = stage.items.get(name)
            if previous and previous['content'] == content:
                return name
            if previous is None and await self.exists(name[len(self.prefix):]):
                if await self.read_text(name[len(self.prefix):]) == content:
                    return name
                if not overwrite:
                    raise ArtifactError("이미 저장된 문서를 덮어쓸 수 없습니다.")
            elif previous is not None and not overwrite:
                raise ArtifactError("이미 저장된 문서를 덮어쓸 수 없습니다.")
            item = {'content': content, 'overwrite': overwrite, 'id': uuid4().hex}
            stage.items[name] = item
            stage.history.append((name, item))
            return name
        return await self._write_text(name, content, overwrite=overwrite)

    async def _write_text(self, name, content, *, overwrite=True, ident=None):
        checksum = content_hash(content)
        async with self.store.transaction() as conn:
            meter = getattr(self.runtime, "meter", None)
            if meter is not None:
                (await meter.access.execution(conn, meter.uid, meter.jid, meter.generation, meter.execution_id))
            (await conn.execute("SELECT id FROM jobs WHERE id=%s FOR UPDATE", (self.job_id,)))
            latest = (await (await conn.execute(
                "SELECT content_hash FROM document_versions WHERE job_id=%s AND name=%s "
                "ORDER BY sequence DESC LIMIT 1",
                (self.job_id, name),
            )).fetchone())
            if latest and latest["content_hash"] == checksum and ident is None:
                return name
            if latest and not overwrite:
                raise ArtifactError("이미 저장된 문서를 덮어쓸 수 없습니다.")
            (await conn.execute(
                "INSERT INTO document_bodies(job_id,hash,content) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.job_id, checksum, content),
            ))
            ident = ident or uuid4().hex
            (await conn.execute(
                "INSERT INTO document_versions(id,job_id,name,content_hash) VALUES (%s,%s,%s,%s)",
                (ident, self.job_id, name, checksum),
            ))
        self.changed[name] = ident
        return name

    async def write_json(self, name, value, *, overwrite=True):
        return (await self.write_text(
            name,
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            overwrite=overwrite,
        ))

    async def all(self):
        async with self.store.transaction(mode="read") as conn:
            rows = (await (await conn.execute(
                "SELECT DISTINCT ON (d.name) d.name,b.content FROM document_versions d "
                "JOIN document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
                "WHERE d.job_id=%s AND starts_with(d.name,%s) ORDER BY d.name,d.sequence DESC",
                (self.job_id, self.prefix),
            )).fetchall())
        result = {r["name"][len(self.prefix) :]: r["content"] for r in rows}
        stage = self._stage()
        if stage is not None:
            result.update({name[len(self.prefix):]: item['content'] for name, item in stage.items.items() if name.startswith(self.prefix)})
        return result

    async def workflow_snapshot(self):
        from backend.pipeline.agent_workflow import AgentWorkflow

        async with self.store.transaction(mode="read") as conn:
            if not (await (await conn.execute(
                "SELECT id FROM jobs WHERE id=%s", (self.job_id,)
            )).fetchone()):
                raise KeyError(self.job_id)
        async with checkpoint_store(self.store) as saver:
            graph = AgentWorkflow(None, None, self, None).build(saver)
            return (await graph.aget_state({"configurable": {"thread_id": self.job_id}}))

    async def reference(self, name):
        stage = self._stage()
        if stage is not None and self._name(name) in stage.items:
            return stage.items[self._name(name)]['id']
        async with self.store.transaction(mode="read") as conn:
            row = (await (await conn.execute(
                "SELECT id FROM document_versions WHERE job_id=%s AND name=%s ORDER BY sequence DESC LIMIT 1",
                (self.job_id, self._name(name)),
            )).fetchone())
        return row["id"] if row else None

    async def version(self, ident):
        stage = self._stage()
        if stage is not None:
            for _, item in stage.history:
                if item['id'] == ident:
                    return item['content']
        async with self.store.transaction(mode="read") as conn:
            row = (await (await conn.execute(
                "SELECT b.content FROM document_versions d JOIN document_bodies b "
                "ON (b.job_id,b.hash)=(d.job_id,d.content_hash) WHERE d.job_id=%s AND d.id=%s",
                (self.job_id, ident),
            )).fetchone())
        return row["content"] if row else None

    async def bind_versions(self, references):
        for name, ident in references.items():
            text = (await self.version(ident))
            if text is None:
                raise ArtifactError("작업 결과가 참조하는 문서 버전이 없습니다.")
            (await self.write_text(name, text))

    async def usage(self):
        async with self.store.transaction(mode="read") as conn:
            row = (await (await conn.execute(
                "SELECT data FROM model_usage WHERE job_id=%s AND scope=%s",
                (self.job_id, self.prefix),
            )).fetchone())
        return row["data"] if row else {"attempts": [], "recording_incomplete": False}

    async def save_usage(self, value):
        async with self.store.transaction() as conn:
            (await conn.execute(
                "INSERT INTO model_usage(job_id,scope,data) VALUES (%s,%s,%s) "
                "ON CONFLICT(job_id,scope) DO UPDATE SET data=EXCLUDED.data",
                (self.job_id, self.prefix, self.store._json(value)),
            ))


@asynccontextmanager
async def checkpoint_store(store):
    """2026-11-13: 작업별 잠금은 분리하고 실제 연결은 사용할 때만 풀에서 대여한다."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from backend.knowledge.store import ASYNC_TRANSACTION
    from backend.knowledge.config import KnowledgeError

    existing = ASYNC_TRANSACTION.get()
    if existing is not None:
        if existing[3] is not asyncio.current_task():
            raise KnowledgeError("다른 태스크의 트랜잭션을 상속할 수 없습니다.")
        if existing[0] is store:
            # 2026-11-15: 접수 중 checkpoint 조회도 같은 연결을 써 풀 고갈과 교착을 막는다.
            conn = existing[1]
            await conn.execute("SET LOCAL search_path TO workflow, core, public")
            try:
                yield AsyncPostgresSaver(conn)
            except BaseException:
                try:
                    await conn.execute("SET LOCAL search_path TO core, public")
                except Exception:
                    pass  # 실패한 SQL 트랜잭션은 호출자가 롤백한다.
                raise
            else:
                await conn.execute("SET LOCAL search_path TO core, public")
            return

    pool = await store.open_async()
    yield AsyncPostgresSaver(pool)
