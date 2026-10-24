"""다중 사용자·중복 접수·비용과 실행 잠금의 경계를 검증한다."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from backend.access.context import ACTOR, AccessError
from backend.access.store import AccessStore
from backend.access.service import PublicService
from test_workflow import manager_for


def account(access, subject):
    sid = access.login(subject, "fake-test-pepper")
    return sid, access.session(sid)


def test_uncertain_cost_keeps_reservation_but_releases_execution(store):
    access = AccessStore(store, clock=lambda: 1800000000)
    _, user = account(access, "owner")
    with store.transaction() as conn:
        generation = access.acquire(conn, user["id"], "a" * 32, execution_id="test-execution", kind="auxiliary", queued=False)
    ident = access.reserve(
        user["id"], "a" * 32, generation, "gpt-6-luna", Decimal("0.1"), execution_id="test-execution"
    )
    access.mark_called(ident)
    access.settle(ident)
    access.finish("a" * 32, generation, "test-execution")
    with store.transaction(mode="read") as conn:
        assert (
            conn.execute("SELECT phase FROM execution_leases").fetchone()["phase"]
            == "finished"
        )
        call = conn.execute(
            "SELECT state,reserved,actual FROM cost_calls WHERE id=%s", (ident,)
        ).fetchone()
        assert (
            call["state"] == "uncertain"
            and Decimal(call["reserved"]) == Decimal("0.1")
            and call["actual"] is None
        )
    access.settle(ident, Decimal("0.02"))
    access.settle(ident, Decimal("0.02"))
    with store.transaction(mode="read") as conn:
        assert (
            Decimal(
                conn.execute(
                    "SELECT reserved FROM daily_usage WHERE user_id=%s", (user["id"],)
                ).fetchone()["reserved"]
            )
            == 0
        )


def test_duplicate_command_is_accepted_once_and_rejects_changed_input(
    store, monkeypatch
):
    manager, _ = manager_for(store, monkeypatch)
    service = PublicService(manager, google=Mock(), pepper="fake-test-pepper")
    sid, user = account(service.access, "owner")
    request = {
        "method": "job.command",
        "params": {"kind": "generate", "input": "메모를 저장해주세요"},
        "session": sid,
        "csrf": user["csrf"],
        "idempotency_key": "same-command",
    }

    def dispatch(request):
        return manager.workspace.summary(
            manager.create(request["params"]["request"])["id"]
        )

    try:
        first = service.invoke(request, dispatch)
        assert service.invoke(request, dispatch)["id"] == first["id"]
        assert len(manager.jobs) == 1
        with pytest.raises(AccessError):
            service.invoke(
                {**request, "params": {"kind": "generate", "input": "다른 입력"}},
                dispatch,
            )
    finally:
        manager.close()


def test_rls_protects_document_bodies_and_versions(store, admin_transaction):
    access = AccessStore(store)
    _, owner = account(access, "owner")
    _, other = account(access, "other")
    with admin_transaction() as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='magi_test_reader'").fetchone():
            conn.execute("CREATE ROLE magi_test_reader NOSUPERUSER NOBYPASSRLS")
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname='ci_service'").fetchone():
            conn.execute("GRANT magi_test_reader TO ci_service")
        conn.execute("GRANT USAGE ON SCHEMA core TO magi_test_reader")
        conn.execute(
            "GRANT SELECT ON ALL TABLES IN SCHEMA core TO magi_test_reader"
        )
        conn.execute(
            "INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s)",
            ("p", "project", owner["id"]),
        )
        conn.execute(
            "INSERT INTO jobs(id,project_id,owner_id,data) VALUES (%s,%s,%s,%s)",
            ("j", "p", owner["id"], store._json({})),
        )
    store.documents("j").write_text("draft/spec.md", "private content")
    token = ACTOR.set(other)
    try:
        with store.transaction(mode="read") as conn:
            conn.execute("SET LOCAL ROLE magi_test_reader")
            for table in ["jobs", "document_versions", "document_bodies"]:
                assert (
                    conn.execute(f"SELECT count(*) AS total FROM {table}").fetchone()[
                        "total"
                    ]
                    == 0
                )
    finally:
        ACTOR.reset(token)
