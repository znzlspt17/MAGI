"""실행 이력의 PostgreSQL 저장 경계."""
import copy
from typing import Any, TypeVar
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class EventData(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    id: str
    action: str = ""
    execution_id: str | None = None


class EventRow(BaseModel):
    model_config = ConfigDict(strict=True)
    data: EventData


class ExecutionRow(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str
    data: dict[str, Any]
    timeline: dict[str, Any] = Field(default_factory=dict)


Record = TypeVar("Record", bound=BaseModel)


def decode_rows(rows: list[dict], model: type[Record]) -> tuple[list[Record], bool]:
    accepted = []
    incomplete = False
    for row in rows:
        try:
            accepted.append(model.model_validate(row))
        except ValidationError:
            incomplete = True
    return accepted, incomplete


class HistoryRepository:
    def __init__(self, documents, user_action_result):
        self.documents = documents
        self.user_action_result = user_action_result

    def load(self):
        with self.documents.store.transaction(mode="read") as conn:
            nodes = conn.execute(
                "SELECT data FROM execution_events WHERE job_id=%s ORDER BY sequence",
                (self.documents.job_id,),
            ).fetchall()
            executions = conn.execute(
                "SELECT id,data,timeline FROM executions WHERE job_id=%s ORDER BY sequence",
                (self.documents.job_id,),
            ).fetchall()
        events, missing_events = decode_rows(nodes, EventRow)
        runs, missing_runs = decode_rows(executions, ExecutionRow)
        incomplete = missing_events or missing_runs
        records = [{**r.data, **r.timeline, "id": r.id} for r in runs]
        inputs = {
            r["id"]: self.user_action_result(r.get("action"), r.get("input"))
            for r in records
        }
        projected = []
        for event in events:
            node = event.data.model_dump(exclude_unset=True)
            if event.data.action:
                if event.data.execution_id in inputs:
                    node["result"] = inputs[event.data.execution_id]
                else:
                    # 연결할 실행이 없으면 저장된 입력만 보존하고 누락을 알린다.
                    incomplete = True
            projected.append(node)
        return {
            "version": 1,
            "nodes": projected,
            "executions": records,
            "recording_incomplete": incomplete,
        }

    def save(self, data):
        store = self.documents.store
        with store.transaction() as conn:
            for execution in data["executions"]:
                timeline = {
                    k: v
                    for k, v in execution.items()
                    if k not in {"input", "id", "action", "stage"}
                }
                conn.execute(
                    "UPDATE executions SET timeline=%s WHERE id=%s AND job_id=%s",
                    (store._json(timeline), execution["id"], self.documents.job_id),
                )
            for node in data["nodes"]:
                node = copy.deepcopy(node)
                if node.get("action"):
                    node.pop("result", None)
                conn.execute(
                    "INSERT INTO execution_events(id,job_id,execution_id,data) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data WHERE execution_events.data IS DISTINCT FROM EXCLUDED.data",
                    (
                        node["id"],
                        self.documents.job_id,
                        node["execution_id"],
                        store._json(node),
                    ),
                )

