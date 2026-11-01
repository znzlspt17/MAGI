"""작업 소유권과 실행 자료 접근 경계."""
from __future__ import annotations
import re
from backend.access.context import ACTOR
from backend.knowledge.runtime import RunKnowledge


class WorkspaceAccess:
    def __init__(self, knowledge, engine_factory):
        self.knowledge = knowledge
        self.engine_factory = engine_factory

    def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            raise KeyError(ident)
        with self.knowledge.store.transaction(mode="read") as conn:
            row = conn.execute(
                "SELECT data,owner_id FROM jobs WHERE id=%s", (ident,)
            ).fetchone()
        actor = ACTOR.get()
        if not row or (actor is not None and row["owner_id"] != actor["id"]):
            raise KeyError(ident)
        return {**row["data"], "owner_id": row["owner_id"]}

    def documents(self, ident):
        self.get(ident)
        return self.knowledge.store.documents(ident)

    def state(self, ident):
        return self.knowledge.store.state(self.get(ident)["id"])

    def read_json(self, ident, name):
        docs = self.documents(ident)
        return docs.read_json(name) if docs.exists(name) else None

    def read_text(self, ident, name):
        docs = self.documents(ident)
        return docs.read_text(name) if docs.exists(name) else None

    def engine(self, ident, meter=None):
        docs = self.documents(ident)
        docs.state = self.state(ident)
        runtime = RunKnowledge(self.knowledge, self.get(ident), docs, meter=meter)
        docs.runtime = runtime
        return self.engine_factory(docs, runtime)
