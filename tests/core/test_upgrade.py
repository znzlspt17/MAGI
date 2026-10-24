"""전환은 원본을 보존하고 같은 입력에 멱등이며 변경된 원본은 차단한다."""

import pytest

from backend.knowledge.projection import digest
from backend.knowledge.upgrade import migrate_business, install
from backend.knowledge.config import KnowledgeError


def test_legacy_state_validation_has_safe_cli_reason(legacy_store):
    with legacy_store.transaction() as conn:
        conn.execute("SET LOCAL search_path TO public")
        conn.execute("INSERT INTO projects(id,name) VALUES ('p','검증')")
        conn.execute("INSERT INTO jobs(id,project_id,data) VALUES ('j','p','{}')")
        conn.execute(
            "INSERT INTO snapshots(id,job_id,execution_id,stage,state) VALUES ('s','j','e','spec_compile','{}')"
        )
    with pytest.raises(KnowledgeError, match="현재 실행 형식으로 전환되지 않은 과거 상태"):
        migrate_business(legacy_store)


def test_business_upgrade_preserves_all_original_versions_and_rejects_drift(
    legacy_store,
):
    store = legacy_store
    with store.transaction() as conn:
        conn.execute("SET LOCAL search_path TO public")
        conn.execute("INSERT INTO projects(id,name) VALUES ('p','보존 프로젝트')")
        conn.execute(
            "INSERT INTO jobs(id,project_id,data) VALUES ('j','p',%s)",
            (store._json({"id": "j", "request": "원문"}),),
        )
        conn.execute(
            "INSERT INTO executions(id,job_id,data) VALUES ('e','j',%s)",
            (store._json({"action": "generate", "input": "원문"}),),
        )
        for index in range(3):
            conn.execute(
                "INSERT INTO snapshots(id,job_id,execution_id,stage,state,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    str(index),
                    "j",
                    "e",
                    "spec_compile",
                    store._json(
                        {"workflow_schema": 1, "original_user_request": "원문"}
                    ),
                    "2026-10-20T00:00:00Z",
                ),
            )
            conn.execute(
                "INSERT INTO artifacts(id,job_id,snapshot_id,path,content,content_hash,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    "a" + str(index),
                    "j",
                    str(index),
                    "draft/spec.md",
                    "변경하지 않은 문서",
                    digest("변경하지 않은 문서"),
                    "2026-10-20T00:00:00Z",
                ),
            )
    first = migrate_business(store)
    assert first["artifacts"]["count"] == 3
    assert migrate_business(store) == first
    with store.transaction() as conn:
        assert (
            conn.execute("SELECT count(*) AS total FROM document_bodies").fetchone()[
                "total"
            ]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) AS total FROM history_archive").fetchone()[
                "total"
            ]
            == 3
        )
        conn.execute(
            "UPDATE public.jobs SET data=data || %s WHERE id='j'",
            (store._json({"request": "변경된 원문"}),),
        )
    with pytest.raises(RuntimeError, match="원본 업무 데이터가 변경"):
        migrate_business(store)


def test_new_install_contains_only_current_storage_and_can_be_repeated(empty_store):
    install(empty_store)
    install(empty_store)
    with empty_store.transaction(mode="read") as conn:
        assert (
            conn.execute("SELECT to_regclass('public.jobs') AS name").fetchone()["name"]
            is None
        )
        assert (
            conn.execute("SELECT version FROM core.installation").fetchone()[
                "version"
            ]
            == 2
        )
        assert conn.execute(
            "SELECT to_regclass('core.document_versions') AS name"
        ).fetchone()["name"]


def test_official_interrupt_conversion_is_repeatable_without_model_calls(legacy_store):
    from backend.knowledge.upgrade import initialize_checkpoints, convert_checkpoints
    from backend.knowledge.core import checkpoint_store
    from backend.pipeline.agent_workflow import AgentWorkflow
    from backend.models import State

    store = legacy_store
    ident = "a" * 32
    with store.transaction() as conn:
        conn.execute("SET LOCAL search_path TO public")
        conn.execute("INSERT INTO projects(id,name) VALUES ('p','대기')")
        conn.execute(
            "INSERT INTO jobs(id,project_id,data) VALUES (%s,'p',%s)",
            (ident, store._json({"id": ident, "status": "NEEDS_USER_INPUT"})),
        )
    migrate_business(store)
    initialize_checkpoints(store)
    config = {"configurable": {"thread_id": ident}}
    state = State(
        run_id=ident,
        status="NEEDS_USER_INPUT",
        user_request="보존할 원문",
        original_user_request="보존할 원문",
    ).to_dict()
    state.update(
        allowed_actions=["answer", "message"], wait_reason="답변을 기다립니다."
    )
    # 업무 함수가 없는 그래프에서 대기 노드 이외 실행은 즉시 실패한다.
    with checkpoint_store(store) as saver:
        graph = AgentWorkflow(None, None, store.documents(ident), None).build(saver)
        graph.update_state(config, state, as_node="ask")
        graph.invoke(None, config=config, durability="sync")
    assert convert_checkpoints(store) == 1
    assert convert_checkpoints(store) == 1
    snapshot = store.documents(ident).workflow_snapshot()
    assert snapshot.next == ("wait",) and snapshot.tasks[0].interrupts
    assert snapshot.values["original_user_request"] == "보존할 원문"
