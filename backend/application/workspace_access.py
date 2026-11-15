"""작업 소유권과 실행 자료 접근 경계."""
from __future__ import annotations
import re
from backend.access.context import ACTOR
from backend.access.ownership import can_access
from backend.knowledge.runtime import RunKnowledge


class WorkspaceAccess:
    def __init__(self, knowledge, engine_factory):
        self.knowledge = knowledge
        self.engine_factory = engine_factory

    async def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise KeyError(ident)
        async with self.knowledge.store.transaction(mode="read") as conn:
            row = (await (await conn.execute(
                "SELECT data,owner_id FROM jobs WHERE id=%s", (ident,)
            )).fetchone())
        actor = ACTOR.get()
        if not row or not can_access(actor, row["owner_id"]):
            raise KeyError(ident)
        return {**row["data"], "owner_id": row["owner_id"]}

    async def documents(self, ident):
        (await self.get(ident))
        return self.knowledge.store.documents(ident)

    async def state(self, ident):
        return (await self.knowledge.store.state((await self.get(ident))["id"]))

    async def read_json(self, ident, name):
        docs = (await self.documents(ident))
        return (await docs.read_json(name)) if (await docs.exists(name)) else None

    async def read_text(self, ident, name):
        docs = (await self.documents(ident))
        return (await docs.read_text(name)) if (await docs.exists(name)) else None

    async def engine(self, ident, meter=None):
        docs = (await self.documents(ident))
        docs.state = (await self.state(ident))
        runtime = RunKnowledge(self.knowledge, (await self.get(ident)), docs, meter=meter)
        await runtime.initialize()
        docs.runtime = runtime
        return self.engine_factory(docs, runtime)
