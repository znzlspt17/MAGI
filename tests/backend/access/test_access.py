"""다중 사용자·중복 접수·비용과 실행 잠금의 경계를 검증한다."""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from tests.backend.application.async_helpers import run_async

from backend.access.context import ACTOR, AccessError
from backend.access.store import AccessStore
from backend.access.service import PublicService
from tests.support.workflow_helpers import manager_for
from tests.support.access_helpers import account


@run_async
async def test_thresholds_only_observe_and_unknown_estimates_keep_result(async_store_factory):
    async with async_store_factory() as store:
        from backend.access.billing import Meter
        from backend.models import CompletionResult
        access = AccessStore(store)
        _, user = (await account(access,"observe-owner"))
        async with store.transaction() as conn:
            (await conn.execute("UPDATE users SET daily_runs=0,daily_usd=0"))
            (await conn.execute("UPDATE service_settings SET daily_usd=0"))
            generation = (await access.acquire(conn,user["id"],"observe",execution_id="observe",kind="auxiliary",count=True,queued=False))
        call = (await access.reserve(user["id"],"observe",generation,"unknown",Decimal("0.2"),execution_id="observe"))
        meter = Meter(access,user["id"],"observe",generation,{},execution_id="observe")
        assert meter.maximum("unknown") is None
        (await meter.settle(call,"unknown",CompletionResult(text="valid result",input_tokens=1,output_tokens=1)))
        unknown = (await meter.reserve("unknown"))
        (await meter.settle(unknown,"unknown",CompletionResult(text="valid result")))
        usage = (await access.usage(user["id"]))
        assert usage["limit_mode"] == "observe" and usage["runs_exceeded"] and usage["limit_reached"]
        async with store.transaction(mode="read") as conn:
            rows = (await (await conn.execute("SELECT state,reserved,actual FROM cost_calls ORDER BY reserved DESC")).fetchall())
        assert len(rows) == 2 and all(row["state"] == "uncertain" and row["actual"] is None for row in rows)
        assert Decimal(rows[0]["reserved"]) == Decimal("0.2")


@pytest.mark.parametrize("prices_known", [False, True])
@run_async
async def test_provider_followup_calls_continue_over_thresholds_with_usage_observed(async_store_factory, prices_known):
    async with async_store_factory() as store:
        import httpx2
        from tests.support.chat_model_fixture import transport
        from tests.support.model_helpers import response
        from backend.access.billing import Meter
        from backend.access.context import TRANSACTION
        from backend.model_policy import default_prices, MODEL
        from backend.providers.llm_provider import ChatModelProvider
        from backend.infrastructure.workflow_store import CURRENT_ATTEMPT, workflow_store

        access = AccessStore(store)
        _, user = (await account(access,"observe-provider"))
        async with store.transaction() as conn:
            (await conn.execute("UPDATE users SET daily_usd=0"))
            (await conn.execute("UPDATE service_settings SET daily_usd=0"))
            generation = (await access.acquire(conn,user["id"],"provider",execution_id="provider",kind="auxiliary",queued=False))
        meter = Meter(access,user["id"],"provider",generation,default_prices() if prices_known else {},execution_id="provider")
        provider = ChatModelProvider(api_key="fake-test-value",meter=meter)
        calls = []
        def handle(request):
            assert TRANSACTION.get() is None
            calls.append(True)
            return httpx2.Response(200,json=response(),request=request)
        async with workflow_store(store,"provider") as (_,journal):
            (await journal.begin("multiple-calls"))
            attempt = {"journal":journal,"task_id":"multiple-calls","call_count":0}
            token = CURRENT_ATTEMPT.set(attempt)
            try:
                with transport(handle):
                    for _ in range(2):
                        assert (await provider.complete_result([{"role":"user","content":"test"}],model=MODEL,conversation_id="conv_test")).text == "Result"
            finally:
                CURRENT_ATTEMPT.reset(token)
            assert len(calls) == attempt["call_count"] == 2
        async with store.transaction(mode="read") as conn:
            rows = (await (await conn.execute("SELECT input_tokens,output_tokens,state FROM cost_calls")).fetchall())
        assert len(rows) == 2 and all(row["input_tokens"] == 20 and row["output_tokens"] == 3 for row in rows)


@run_async
async def test_uncertain_cost_keeps_reservation_but_releases_execution(async_store_factory):
    async with async_store_factory() as store:
        access = AccessStore(store, clock=lambda: 1800000000)
        _, user = (await account(access, "owner"))
        async with store.transaction() as conn:
            generation = (await access.acquire(conn, user["id"], "a" * 32, execution_id="test-execution", kind="auxiliary", queued=False))
        ident = (await access.reserve(
            user["id"], "a" * 32, generation, "gpt-6-luna", Decimal("0.1"), execution_id="test-execution"
        ))
        (await access.mark_called(ident))
        (await access.settle(ident))
        (await access.finish("a" * 32, generation, "test-execution"))
        async with store.transaction(mode="read") as conn:
            assert (
                (await (await conn.execute("SELECT phase FROM execution_leases")).fetchone())["phase"]
                == "finished"
            )
            call = (await (await conn.execute(
                "SELECT state,reserved,actual FROM cost_calls WHERE id=%s", (ident,)
            )).fetchone())
            assert (
                call["state"] == "uncertain"
                and Decimal(call["reserved"]) == Decimal("0.1")
                and call["actual"] is None
            )
        (await access.settle(ident, Decimal("0.02")))
        (await access.settle(ident, Decimal("0.02")))
        async with store.transaction(mode="read") as conn:
            assert (
                Decimal(
                    (await (await conn.execute(
                        "SELECT reserved FROM daily_usage WHERE user_id=%s", (user["id"],)
                    )).fetchone())["reserved"]
                )
                == 0
            )


@run_async
async def test_duplicate_command_is_accepted_once_and_rejects_changed_input(
    async_store_factory, monkeypatch
):
    async with async_store_factory() as store:
        manager, _ = (await manager_for(store, monkeypatch))
        service = PublicService(manager, google=Mock(), pepper="fake-test-pepper")
        sid, user = (await account(service.access, "owner"))
        async with store.transaction() as conn:
            (await conn.execute("UPDATE users SET daily_runs=0,daily_usd=0"))
            (await conn.execute("UPDATE service_settings SET daily_usd=0"))
        request = {
            "method": "job.command",
            "params": {"kind": "generate", "input": "메모를 저장해주세요"},
            "session": sid,
            "csrf": user["csrf"],
            "idempotency_key": "same-command",
        }

        async def dispatch(request):
            return (await manager.workspace.summary(
                (await manager.create(request["params"]["request"]))["id"]
            ))

        try:
            first = (await service.invoke(request, dispatch))
            assert (await service.invoke(request, dispatch))["id"] == first["id"]
            assert len(manager.jobs) == 1
            with pytest.raises(AccessError):
                (await service.invoke(
                    {**request, "params": {"kind": "generate", "input": "다른 입력"}},
                    dispatch,
                ))
        finally:
            (await manager.close())


@run_async
async def test_document_read_does_not_reserve_cost_or_execution_lease(async_store_factory, monkeypatch):
    async with async_store_factory() as store:
        manager, _ = (await manager_for(store, monkeypatch))
        service = PublicService(manager, google=Mock(), pepper="fake-test-pepper")
        sid, user = (await account(service.access, "document-owner"))
        request = {"method": "document", "params": {"id": "job", "step_id": "step"},
                   "session": sid, "csrf": user["csrf"]}
        def reject_reservation(*args, **kwargs):
            pytest.fail("원본 문서 조회에 비용 예약이나 실행 슬롯을 사용해서는 안 됩니다")
        monkeypatch.setattr(service, "temporary", reject_reservation)
        monkeypatch.setattr(service.access, "reserve", reject_reservation)
        monkeypatch.setattr(service.access, "acquire", reject_reservation)
        async def snapshot():
            async with store.transaction(mode="read") as conn:
                return [(await (await conn.execute(f"SELECT count(*) AS total FROM {table}")).fetchone())["total"]
                        for table in ("cost_calls", "execution_leases")]
        async def dispatch(value):
            assert ACTOR.get()["id"] == user["id"]
            assert value["params"] == {"id": "job", "step_id": "step"}
            assert "_meter" not in value
            return {"content": "저장된 명세입니다.", "language": "ko", "filename": "SPEC.ko.md"}
        try:
            before = (await snapshot())
            for _ in range(2):
                result = (await service.invoke(request, dispatch))
                assert result["content"] == "저장된 명세입니다."
                assert result["language"] == "ko"
            assert (await snapshot()) == before
        finally:
            (await manager.close())


@run_async
async def test_rls_protects_document_bodies_and_versions(async_store_factory):
    async with async_store_factory() as store:
        access = AccessStore(store)
        _, owner = await account(access, "owner")
        _, other = await account(access, "other")
        async with store.test_admin_transaction() as conn:
            await conn.execute("SET LOCAL search_path TO core,public")
            if not await (await conn.execute("SELECT 1 FROM pg_roles WHERE rolname='magi_test_reader'")).fetchone():
                await conn.execute("CREATE ROLE magi_test_reader NOSUPERUSER NOBYPASSRLS")
            if await (await conn.execute("SELECT 1 FROM pg_roles WHERE rolname='ci_service'")).fetchone():
                await conn.execute("GRANT magi_test_reader TO ci_service")
            await conn.execute("GRANT USAGE ON SCHEMA core TO magi_test_reader")
            await conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA core TO magi_test_reader")
            await conn.execute("INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s)", ("p", "project", owner["id"]))
            await conn.execute("INSERT INTO jobs(id,project_id,owner_id,data) VALUES (%s,%s,%s,%s)",
                               ("j", "p", owner["id"], store._json({})))
        await store.documents("j").write_text("draft/spec.md", "private content")
        token = ACTOR.set(other)
        try:
            async with store.transaction(mode="read") as conn:
                await conn.execute("SET LOCAL ROLE magi_test_reader")
                for table in ["jobs", "document_versions", "document_bodies"]:
                    assert (await (await conn.execute(f"SELECT count(*) AS total FROM {table}")).fetchone())["total"] == 0
        finally:
            ACTOR.reset(token)
