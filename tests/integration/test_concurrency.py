"""실제 PostgreSQL 연결과 장벽으로 실행·원장 경합을 검증한다."""

import asyncio
from tests.backend.application.async_helpers import run_async
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
import os
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.access.capacity import ExecutionCapacity
from backend.access.context import ACTOR, TRANSACTION, AccessError
from backend.access.service import PublicService
from backend.access.runtime import PublicRuntime
from backend.access.store import AccessStore
from backend.knowledge.store import KnowledgeStore
from backend.server.job_manager import JobManager
from backend.model_policy import MODEL
from tests.support.access_helpers import account
from tests.support.workflow_helpers import manager_for


async def _summarize_creation(manager, request):
    job = await manager.create(request)
    return await manager.workspace.summary(job['id'])


async def _value(value):
    return value


def require_real_database():
    if os.environ.get("CI_POSTGRES") != "1" or os.environ.get("CI") != "true":
        pytest.skip("독립 연결 경합은 실제 PostgreSQL에서만 평가한다.")


@contextmanager
def as_actor(actor):
    token = ACTOR.set(actor)
    try:
        yield
    finally:
        ACTOR.reset(token)


@run_async
async def test_capacity_is_shared_and_maintenance_excludes_admission(monkeypatch):
    monkeypatch.setattr("backend.access.capacity.MAX_PARALLEL", 2)
    capacity = ExecutionCapacity()
    async with capacity.slot(blocking=False):
        async with capacity.slot(blocking=False):
            with pytest.raises(AccessError) as caught:
                async with capacity.slot(blocking=False):
                    pytest.fail("세 번째 실행 슬롯을 얻으면 안 된다.")
            assert caught.value.code == "capacity"
            with pytest.raises(AccessError):
                async with capacity.maintenance():
                    pass
    async with capacity.maintenance():
        with pytest.raises(AccessError):
            (await capacity.check_admission())
    assert capacity.active == 0


@pytest.mark.parametrize("same_user", [False, True])
@pytest.mark.parametrize("cancel_third", [False, True])
@run_async
async def test_two_workers_overlap_third_waits_and_context_is_isolated(async_store_factory, monkeypatch, same_user, cancel_third):
    require_real_database()
    async with async_store_factory() as real_store:
        monkeypatch.setattr("backend.access.capacity.MAX_PARALLEL", 2)
        manager, _ = (await manager_for(real_store, monkeypatch))
        service = PublicService(manager, google=Mock(), pepper="fake-test-pepper")
        sid, first = (await account(service.access, "first"))
        _, second = (await account(service.access, "second"))
        owners = [first, first if same_user else second, first]
        async with real_store.transaction() as conn:
            (await conn.execute("UPDATE users SET daily_runs=100,daily_usd=10000"))
            (await conn.execute("UPDATE service_settings SET daily_usd=10000"))
        manager._submit_locked = MethodType(JobManager._submit_locked, manager)
        barrier, release = asyncio.Barrier(2), asyncio.Event()
        both_started, all_done = asyncio.Event(), asyncio.Event()
        records, failures = [], []
        record_lock = asyncio.Lock()

        async def fake_model(ident, action, payload, *, meter):
            try:
                assert TRANSACTION.get() is None
                owner = ACTOR.get()["id"]
                assert owner == meter.uid
                async with manager.lock:
                    job = manager.jobs[ident]
                    job["status"] = "running"
                    (await real_store.save_job(job, expected_generation=meter.generation))
                call = (await meter.reserve(MODEL))
                async with record_lock:
                    index = len(records)
                    records.append((ident,owner))
                if index < 2:
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                    both_started.set()
                    await asyncio.wait_for(release.wait(), timeout=15)
                (await real_store.documents(ident).write_text("test/owner.txt", owner + ":" + ident))
                (await service.access.settle(call,Decimal("0.01"),generation=meter.generation,execution_id=meter.execution_id))
                async with manager.lock:
                    job["status"] = "NEEDS_USER_INPUT"
                    (await real_store.save_job(job, expected_generation=meter.generation))
                async with record_lock:
                    if len(records) == 3:
                        all_done.set()
            except Exception as exc:
                failures.append(type(exc).__name__)
                raise

        monkeypatch.setattr(manager, "_run", fake_model)

        async def admit(owner):
            with as_actor(owner):
                return (await service.admit(owner, {"method":"generate", "params":{}, "idempotency_key":uuid4().hex},
                    lambda request: _summarize_creation(manager, "병렬 실행 검증")))

        try:
            one, two = (await admit(owners[0])), (await admit(owners[1]))
            await asyncio.wait_for(both_started.wait(), timeout=15)
            assert not failures
            three = (await admit(owners[2]))
            status = (await service.access.status(first["id"]))
            assert status["active_count"] == 2 and status["queued_count"] == 1
            assert len(records) == 2
            with pytest.raises(AccessError) as caught:
                async with service.temporary(first, one["id"]):
                    pass
            assert caught.value.code == "capacity"
            for method in ("knowledge.search","knowledge.graph"):
                assert (await service.invoke({"method":method,"params":{},"session":sid},lambda request: _value({"nodes":[]}))) == {"nodes":[]}
            assert (await service.access.status(first["id"]))["active_count"] == 2
            if cancel_third:
                (await service.admin({**first,"role":"admin"},"admin.stop",{"id":three["id"],"execution_id":three["execution_id"]}))
                assert (await manager.get(three["id"]))["status"] == "interrupted"
                assert (await service.access.status(first["id"]))["queued_count"] == 0
            release.set()
            if not cancel_third:
                await asyncio.wait_for(all_done.wait(), timeout=20)
                assert not failures
        finally:
            release.set()
            (await manager.close())
        assert not failures
        expected = {one["id"],two["id"]} if cancel_third else {one["id"],two["id"],three["id"]}
        assert {ident for ident,_ in records} == expected
        for ident, owner in records:
            assert (await real_store.documents(ident).read_text("test/owner.txt")) == owner + ":" + ident
        assert (await service.access.status(first["id"]))["active_count"] == 0


@pytest.mark.parametrize("same_user", [False, True])
@run_async
async def test_observed_budget_does_not_block_reservation_and_settlement_is_once(async_store_factory, same_user):
    require_real_database()
    async with async_store_factory() as real_store:
        access = AccessStore(real_store)
        _, one = (await account(access, "budget-one"))
        _, other = (await account(access, "budget-two"))
        users = [one,one if same_user else other]
        async with real_store.transaction() as conn:
            (await conn.execute("UPDATE users SET daily_usd=100"))
            (await conn.execute("UPDATE service_settings SET daily_usd=1"))
            guards = [(uuid4().hex,uuid4().hex) for _ in users]
            generations = [(await access.acquire(conn,user["id"],jid,execution_id=eid,kind="auxiliary",queued=False)) for user,(jid,eid) in zip(users,guards)]
        peers = [AccessStore(KnowledgeStore(real_store.config)) for _ in users]
        try:
            barrier = asyncio.Barrier(2)

            async def reserve(index):
                await asyncio.wait_for(barrier.wait(), timeout=10)
                jid,eid = guards[index]
                try:
                    return (await peers[index].reserve(users[index]["id"],jid,generations[index],MODEL,Decimal("0.75"),execution_id=eid))
                except AccessError as exc:
                    assert exc.code == "quota"
                    return None

            calls = await asyncio.gather(*(reserve(index) for index in range(2)))
            assert all(calls)
            call = next(value for value in calls if value is not None)
            barrier = asyncio.Barrier(2)

            async def settle(index):
                await asyncio.wait_for(barrier.wait(), timeout=10)
                (await peers[index].settle(call,Decimal("0.02"),source="manual"))

            await asyncio.gather(*(settle(index) for index in range(2)))
            async with real_store.transaction(mode="read") as conn:
                total = (await (await conn.execute("SELECT sum(reserved) AS reserved,sum(spent) AS spent FROM daily_usage")).fetchone())
                assert Decimal(total["reserved"]) == Decimal("0.75") and Decimal(total["spent"]) == Decimal("0.02")
        finally:
            for peer in peers:
                await peer.store.close_async()


@run_async
async def test_old_generation_cannot_save_reserve_finish_or_settle_new_execution(async_store_factory):
    require_real_database()
    async with async_store_factory() as real_store:
        access = AccessStore(real_store)
        _, user = (await account(access, "stale"))
        jid, old, new = uuid4().hex,uuid4().hex,uuid4().hex
        project = (await real_store.create_project("실행 세대 검증"))
        job = {"id":jid,"project_id":project["id"],"owner_id":user["id"],"execution_id":old}
        (await real_store.save_job(job))
        async with real_store.transaction() as conn:
            first = (await access.acquire(conn,user["id"],jid,execution_id=old,queued=False))
        call = (await access.reserve(user["id"],jid,first,MODEL,Decimal("0.1"),execution_id=old))
        (await access.finish(jid,first,old))
        job["execution_id"] = new
        (await real_store.save_job(job))
        async with real_store.transaction() as conn:
            second = (await access.acquire(conn,user["id"],jid,execution_id=new,queued=False))
            with pytest.raises(AccessError):
                (await access.acquire(conn,user["id"],jid,execution_id=uuid4().hex))
        with pytest.raises(AccessError):
            (await real_store.save_job({**job,"execution_id":old},expected_generation=first))
        from backend.knowledge.core import Documents
        writer = Documents(real_store,jid,runtime=SimpleNamespace(meter=SimpleNamespace(
            access=access,uid=user["id"],jid=jid,generation=first,execution_id=old,
        )))
        with pytest.raises(AccessError):
            (await writer.write_text("test/stale.txt","이전 실행의 문서"))
        assert not (await real_store.documents(jid).exists("test/stale.txt"))
        with pytest.raises(AccessError):
            (await access.reserve(user["id"],jid,first,MODEL,Decimal("0.1"),execution_id=old))
        with pytest.raises(AccessError):
            (await access.settle(call,Decimal(0),generation=first,execution_id=old))
        (await access.finish(jid,first,old))
        (await access.check_execution(user["id"],jid,second,new))


@run_async
async def test_logout_only_stops_owner_and_waiting_does_not_hold_execution(async_store_factory):
    require_real_database()
    async with async_store_factory() as real_store:
        access = AccessStore(real_store)
        _, one = (await account(access, "logout-one"))
        _, two = (await account(access, "logout-two"))
        async with real_store.transaction() as conn:
            a = (await access.acquire(conn,one["id"],"job-one",execution_id="one",kind="auxiliary",queued=False))
            b = (await access.acquire(conn,two["id"],"job-two",execution_id="two",kind="auxiliary",queued=False))
        (await access.stop_owner(one["id"]))
        with pytest.raises(AccessError):
            (await access.check_execution(one["id"],"job-one",a,"one"))
        (await access.check_execution(two["id"],"job-two",b,"two"))
        (await access.finish("job-one",a,"one"))
        assert (await access.status(two["id"]))["active_count"] == 1


@run_async
async def test_public_workflow_uses_generation_fenced_documents_and_releases_waiting_slot(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, provider = (await manager_for(real_store, monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        sid, user = (await account(service.access,"public-workflow"))
        request = {"method":"job.command","params":{"kind":"generate","input":"메모를 저장해주세요"},
                   "session":sid,"csrf":user["csrf"],"idempotency_key":uuid4().hex}

        async def dispatch(request):
            return (await manager.workspace.summary((await manager.create(request["params"]["request"]))["id"]))

        try:
            accepted = (await service.invoke(request,dispatch))
            (await service.worker(accepted["id"],"generate","메모를 저장해주세요"))
            assert (await manager.get(accepted["id"]))["status"] == "PASS_PENDING_USER_APPROVAL"
            assert (await service.access.status(user["id"]))["active_count"] == 0
        finally:
            (await manager.close())


@run_async
async def test_duplicate_admission_race_accepts_once_and_rollback_preserves_other_job(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, _ = (await manager_for(real_store,monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        sid, user = (await account(service.access,"admission-race"))
        request = {"method":"job.command","params":{"kind":"generate","input":"중복 접수 검증"},
                   "session":sid,"csrf":user["csrf"],"idempotency_key":"same-concurrent-key"}

        async def dispatch(request):
            return (await manager.workspace.summary((await manager.create(request["params"]["request"]))["id"]))

        barrier = asyncio.Barrier(2)
        async def submit(index):
            await asyncio.wait_for(barrier.wait(), timeout=10)
            return (await service.invoke(request,dispatch))

        try:
            results = await asyncio.gather(*(submit(index) for index in range(2)))
            assert results[0]["id"] == results[1]["id"] and len(manager.jobs) == 1
            other = manager.jobs[results[0]["id"]]

            async def failing_dispatch(request):
                (await manager.create("실패할 접수"))
                other["progress"] = {"stage":"other-progress","state":"completed"}
                raise ValueError("fake-admission-failure")

            with as_actor(user), pytest.raises(ValueError):
                (await service.admit(user,{"method":"generate","params":{},"idempotency_key":"different-failed-key"},failing_dispatch))
            assert list(manager.jobs) == [other["id"]]
            assert manager.jobs[other["id"]]["progress"]["stage"] == "other-progress"
            async with real_store.transaction(mode="read") as conn:
                assert len((await (await conn.execute("SELECT id FROM jobs")).fetchall())) == 1
                assert len((await (await conn.execute("SELECT key FROM admissions")).fetchall())) == 1
        finally:
            (await manager.close())


@run_async
async def test_approve_message_race_only_accepts_one_latest_execution(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, _ = (await manager_for(real_store,monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        sid, user = (await account(service.access,"command-race"))

        async def dispatch(request):
            params = request["params"]
            if request["method"] == "generate":
                result = (await manager.create(params["request"]))
            else:
                payload = {"candidate_hash":params["candidate_hash"]} if request["method"] == "approve" else params["payload"]
                result = (await manager.action(params["id"],request["method"],payload,expected_execution_id=params["execution_id"]))
            return (await manager.workspace.summary(result["id"]))

        def packet(params,key):
            return {"method":"job.command","params":params,"session":sid,"csrf":user["csrf"],"idempotency_key":key}

        try:
            accepted = (await service.invoke(packet({"kind":"generate","input":"메모를 저장해주세요"},"race-generate"),dispatch))
            (await service.worker(accepted["id"],"generate","메모를 저장해주세요"))
            job = (await manager.get(accepted["id"]))
            assert job["status"] == "PASS_PENDING_USER_APPROVAL"
            base = {"job_id":job["id"],"execution_id":job["execution_id"]}
            requests = [packet({**base,"kind":"approve","candidate_hash":(await manager.workspace.state(job["id"]))["candidate_hash"]},"race-approve"),
                        packet({**base,"kind":"message","input":"보관 조건을 바꿔주세요"},"race-message")]
            barrier = asyncio.Barrier(2)
            async def race(index):
                await asyncio.wait_for(barrier.wait(), timeout=10)
                try:
                    return (await service.invoke(requests[index],dispatch))
                except AccessError as exc:
                    return exc.code
            outcomes = await asyncio.gather(*(race(index) for index in range(2)))
            assert sum(isinstance(value,dict) for value in outcomes) == 1
            assert "conflict" in outcomes
        finally:
            (await manager.close())


@run_async
async def test_stop_command_refunds_unused_queued_call_without_stopping_other_job(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, _ = (await manager_for(real_store,monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        sid, user = (await account(service.access,"stop-owner"))
        async def dispatch(request):
            return (await manager.workspace.summary((await manager.create(request["params"]["request"]))["id"]))
        async def create(key):
            return (await service.invoke({"method":"job.command","params":{"kind":"generate","input":"중지 검증"},
                                   "session":sid,"csrf":user["csrf"],"idempotency_key":key},dispatch))
        try:
            one, other = (await create("stop-first")), (await create("stop-second"))
            (await service.invoke({"method":"job.command","params":{"kind":"stop","job_id":one["id"],"execution_id":one["execution_id"]},
                            "session":sid,"csrf":user["csrf"],"idempotency_key":"stop-command"},dispatch))
            with pytest.raises(AccessError):
                (await service.worker(one["id"],"generate","중지 검증"))
            assert (await manager.get(one["id"]))["status"] == "interrupted"
            async with real_store.transaction(mode="read") as conn:
                leases = {row["job_id"]: row for row in (await (await conn.execute("SELECT * FROM execution_leases")).fetchall())}
                assert leases[one["id"]]["phase"] == "finished"
                assert leases[other["id"]]["phase"] == "queued" and not leases[other["id"]]["stopping"]
                cost = (await (await conn.execute("SELECT actual,state FROM cost_calls WHERE job_id=%s", (one["id"],))).fetchone())
                assert cost["state"] == "settled" and Decimal(cost["actual"]) == 0
        finally:
            (await manager.close())


@run_async
async def test_maintenance_blocks_new_execution_and_releases_gate_on_exit(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, _ = (await manager_for(real_store,monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        _, user = (await account(service.access,"maintenance-owner"))
        try:
            async with service.temporary(user,"maintenance"):
                with as_actor(user), pytest.raises(AccessError) as caught:
                    (await service.admit(user,{"method":"generate","params":{},"idempotency_key":"maintenance-rejected"},
                                  lambda request: manager.create("허용되면 안 되는 접수")))
                assert caught.value.code == "capacity"
            assert not manager.jobs
            (await service.capacity.check_admission())
        finally:
            (await manager.close())


@run_async
async def test_queue_limit_is_enforced_by_transactional_execution_records(async_store_factory):
    require_real_database()
    async with async_store_factory() as real_store:
        access = AccessStore(real_store)
        _, user = (await account(access,"queue-limit"))
        async with real_store.transaction() as conn:
            for _ in range(200):
                (await access.acquire(conn,user['id'],uuid4().hex,execution_id=uuid4().hex))
        with pytest.raises(AccessError) as caught:
            async with real_store.transaction() as conn:
                (await access.acquire(conn,user['id'],uuid4().hex,execution_id=uuid4().hex))
        assert caught.value.code == 'capacity'


@run_async
async def test_maintenance_cannot_overtake_admission_commit(async_store_factory, monkeypatch):
    require_real_database()
    async with async_store_factory() as real_store:
        manager, _ = (await manager_for(real_store,monkeypatch))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        _, user = (await account(service.access,"maintenance-race"))
        entered, release = asyncio.Event(), asyncio.Event()
        maintenance_entered = asyncio.Event()
        acquire = service.access.acquire
        maintenance_gate = service.capacity.maintenance

        @asynccontextmanager
        async def observed_maintenance():
            async with maintenance_gate():
                maintenance_entered.set()
                yield

        monkeypatch.setattr(service.capacity, "maintenance", observed_maintenance)

        async def paused_acquire(*args, **kwargs):
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=10)
            return await acquire(*args, **kwargs)

        monkeypatch.setattr(service.access,"acquire",paused_acquire)

        async def admit():
            with as_actor(user):
                return (await service.admit(user,{"method":"generate","params":{},"idempotency_key":"maintenance-race"},
                                     lambda request: _summarize_creation(manager, "접수 경합")))

        async def maintain():
            with pytest.raises(AccessError) as caught:
                async with service.temporary(user,"maintenance"):
                    pytest.fail("접수 커밋을 앞질러 유지보수에 진입하면 안 된다.")
            assert caught.value.code == "capacity"

        admission = maintenance = None
        try:
            admission = asyncio.create_task(admit())
            await asyncio.wait_for(entered.wait(), timeout=10)
            maintenance = asyncio.create_task(maintain())
            await asyncio.wait_for(maintenance_entered.wait(), timeout=5)
            release.set()
            assert (await asyncio.wait_for(admission, timeout=10))["id"]
            await asyncio.wait_for(maintenance, timeout=10)
            assert (await service.access.status(user["id"]))["queued_count"] == 1
            assert not service.capacity.maintaining
        finally:
            release.set()
            await asyncio.gather(*(task for task in (admission, maintenance) if task is not None), return_exceptions=True)
            (await manager.close())


@run_async
async def test_restart_interrupts_execution_and_preserves_uncertain_reservation(async_store_factory):
    require_real_database()
    async with async_store_factory() as real_store:
        access = AccessStore(real_store)
        _, user = (await account(access,"restart-owner"))
        async with real_store.transaction() as conn:
            generation = (await access.acquire(conn,user['id'],'aux-job',execution_id='before-restart',kind='auxiliary',queued=False))
        call = (await access.reserve(user['id'],'aux-job',generation,MODEL,Decimal('0.25'),execution_id='before-restart'))
        runtime = PublicRuntime(real_store)
        try:
            (await runtime.acquire(recover=False))
            (await runtime.recover())
        finally:
            (await runtime.close())
        async with real_store.transaction(mode='read') as conn:
            row = (await (await conn.execute('SELECT state,reserved,actual FROM cost_calls WHERE id=%s',(call,))).fetchone())
            assert row['state']=='uncertain' and Decimal(row['reserved'])==Decimal('0.25') and row['actual'] is None
            assert (await (await conn.execute('SELECT phase FROM execution_leases')).fetchone())['phase']=='interrupted'
        assert (await access.status(user['id']))['active_count']==0


@pytest.mark.parametrize("same_key", [False, True])
@run_async
async def test_pending_replay_admission_race_accepts_one_execution(async_store_factory, monkeypatch, same_key):
    require_real_database()
    async with async_store_factory() as real_store:
        from backend.errors import Error
        from backend.models import InterviewResponse
        from tests.support.fakes import DecisionProvider

        class Broken(DecisionProvider):
            async def complete_result(self, messages, **kwargs):
                if kwargs["text_format"] is InterviewResponse:
                    raise Error("test transport failure")
                return await super().complete_result(messages,**kwargs)

        manager, _ = (await manager_for(real_store,monkeypatch,Broken([[]])))
        service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
        sid, user = (await account(service.access,"replay-race"))

        async def dispatch(request):
            params = request["params"]
            job = (await manager.create(params["request"])) if request["method"] == "generate" else (await manager.action(
                params["id"],"retry",{"replay_pending":params.get("replay_pending",False)},expected_execution_id=params["execution_id"]))
            return (await manager.workspace.summary(job["id"]))

        def packet(params,key):
            return {"method":"job.command","params":params,"session":sid,"csrf":user["csrf"],"idempotency_key":key}

        try:
            job = (await service.invoke(packet({"kind":"generate","input":"메모를 저장해주세요"},"replay-generate"),dispatch))
            (await service.worker(job["id"],"generate","메모를 저장해주세요"))
            summary = (await manager.workspace.summary(job["id"]))
            assert summary["can_retry"] and summary["retry_requires_replay"]
            barrier = asyncio.Barrier(2)
            async def race(index):
                await asyncio.wait_for(barrier.wait(), timeout=10)
                try:
                    return (await service.invoke(packet({"kind":"retry","job_id":job["id"],"execution_id":job["execution_id"],"replay_pending":True},
                                                 "replay-key" if same_key else f"replay-key-{index}"),dispatch))
                except AccessError as exc:
                    return exc.code
            results = await asyncio.gather(*(race(index) for index in range(2)))
            accepted = [result for result in results if isinstance(result,dict)]
            assert len(accepted) == (2 if same_key else 1)
            assert len({result["execution_id"] for result in accepted}) == 1
            async with real_store.transaction(mode="read") as conn:
                assert (await (await conn.execute("SELECT count(*) AS n FROM execution_leases WHERE phase='queued'")).fetchone())["n"] == 1
                assert (await (await conn.execute("SELECT count(*) AS n FROM cost_calls")).fetchone())["n"] == 2
        finally:
            (await manager.close())
