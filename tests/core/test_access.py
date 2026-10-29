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


def test_thresholds_only_observe_and_unknown_estimates_keep_result(store):
    from backend.access.billing import Meter
    from backend.models import CompletionResult
    access = AccessStore(store)
    _, user = account(access,"observe-owner")
    with store.transaction() as conn:
        conn.execute("UPDATE users SET daily_runs=0,daily_usd=0")
        conn.execute("UPDATE service_settings SET daily_usd=0")
        generation = access.acquire(conn,user["id"],"observe",execution_id="observe",kind="auxiliary",count=True,queued=False)
    call = access.reserve(user["id"],"observe",generation,"unknown",Decimal("0.2"),execution_id="observe")
    meter = Meter(access,user["id"],"observe",generation,{},execution_id="observe")
    assert meter.maximum("unknown") is None
    meter.settle(call,"unknown",CompletionResult(text="valid result",input_tokens=1,output_tokens=1))
    unknown = meter.reserve("unknown")
    meter.settle(unknown,"unknown",CompletionResult(text="valid result"))
    usage = access.usage(user["id"])
    assert usage["limit_mode"] == "observe" and usage["runs_exceeded"] and usage["limit_reached"]
    with store.transaction(mode="read") as conn:
        rows = conn.execute("SELECT state,reserved,actual FROM cost_calls ORDER BY reserved DESC").fetchall()
    assert len(rows) == 2 and all(row["state"] == "uncertain" and row["actual"] is None for row in rows)
    assert Decimal(rows[0]["reserved"]) == Decimal("0.2")


@pytest.mark.parametrize("prices_known", [False, True])
def test_provider_followup_calls_continue_over_thresholds_with_usage_observed(store, prices_known):
    import httpx2
    from chat_model_fixture import transport
    from test_models import response
    from backend.access.billing import Meter
    from backend.access.context import TRANSACTION
    from backend.model_policy import default_prices, MODEL
    from backend.providers.llm_provider import ChatModelProvider
    from backend.infrastructure.workflow_store import CURRENT_ATTEMPT, workflow_store

    access = AccessStore(store)
    _, user = account(access,"observe-provider")
    with store.transaction() as conn:
        conn.execute("UPDATE users SET daily_usd=0")
        conn.execute("UPDATE service_settings SET daily_usd=0")
        generation = access.acquire(conn,user["id"],"provider",execution_id="provider",kind="auxiliary",queued=False)
    meter = Meter(access,user["id"],"provider",generation,default_prices() if prices_known else {},execution_id="provider")
    provider = ChatModelProvider(api_key="fake-test-value",meter=meter)
    calls = []
    def handle(request):
        assert TRANSACTION.get() is None
        calls.append(True)
        return httpx2.Response(200,json=response(),request=request)
    with workflow_store(store,"provider") as (_,journal):
        journal.begin("multiple-calls")
        attempt = {"journal":journal,"task_id":"multiple-calls","call_count":0}
        token = CURRENT_ATTEMPT.set(attempt)
        try:
            with transport(handle):
                for _ in range(2):
                    assert provider.complete_result([{"role":"user","content":"test"}],model=MODEL,conversation_id="conv_test").text == "Result"
        finally:
            CURRENT_ATTEMPT.reset(token)
        assert len(calls) == attempt["call_count"] == 2
    with store.transaction(mode="read") as conn:
        rows = conn.execute("SELECT input_tokens,output_tokens,state FROM cost_calls").fetchall()
    assert len(rows) == 2 and all(row["input_tokens"] == 20 and row["output_tokens"] == 3 for row in rows)


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
    with store.transaction() as conn:
        conn.execute("UPDATE users SET daily_runs=0,daily_usd=0")
        conn.execute("UPDATE service_settings SET daily_usd=0")
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
