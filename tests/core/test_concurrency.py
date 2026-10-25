"""실제 PostgreSQL 연결과 장벽으로 실행·원장 경합을 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import os
import threading
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
from test_access import account
from test_workflow import manager_for


@pytest.fixture
def real_store(request):
    if os.environ.get("CI_POSTGRES") != "1" or os.environ.get("CI") != "true":
        pytest.skip("독립 연결 경합은 실제 PostgreSQL에서만 평가한다.")
    return request.getfixturevalue("store")


@contextmanager
def as_actor(actor):
    token = ACTOR.set(actor)
    try:
        yield
    finally:
        ACTOR.reset(token)


def test_capacity_is_shared_and_maintenance_excludes_admission():
    capacity = ExecutionCapacity()
    with capacity.slot(blocking=False):
        with capacity.slot(blocking=False):
            with pytest.raises(AccessError) as caught:
                with capacity.slot(blocking=False):
                    pytest.fail("세 번째 실행 슬롯을 얻으면 안 된다.")
            assert caught.value.code == "capacity"
            with pytest.raises(AccessError):
                with capacity.maintenance():
                    pass
    with capacity.maintenance():
        with pytest.raises(AccessError):
            capacity.check_admission()
    assert capacity.active == 0


@pytest.mark.parametrize("same_user", [False, True])
@pytest.mark.parametrize("cancel_third", [False, True])
def test_two_workers_overlap_third_waits_and_context_is_isolated(real_store, monkeypatch, same_user, cancel_third):
    manager, _ = manager_for(real_store, monkeypatch)
    service = PublicService(manager, google=Mock(), pepper="fake-test-pepper")
    sid, first = account(service.access, "first")
    _, second = account(service.access, "second")
    owners = [first, first if same_user else second, first]
    with real_store.transaction() as conn:
        conn.execute("UPDATE users SET daily_runs=100,daily_usd=10000")
        conn.execute("UPDATE service_settings SET daily_usd=10000")
    manager._submit_locked = MethodType(JobManager._submit_locked, manager)
    barrier, release = threading.Barrier(2), threading.Event()
    both_started, all_done = threading.Event(), threading.Event()
    records, failures = [], []
    record_lock = threading.Lock()

    def fake_model(ident, action, payload, *, meter):
        try:
            assert TRANSACTION.get() is None
            owner = ACTOR.get()["id"]
            assert owner == meter.uid
            with manager.lock:
                job = manager.jobs[ident]
                job["status"] = "running"
                real_store.save_job(job, expected_generation=meter.generation)
            call = meter.reserve(MODEL)
            with record_lock:
                index = len(records)
                records.append((ident,owner))
            if index < 2:
                barrier.wait(timeout=10)
                both_started.set()
                assert release.wait(15)
            real_store.documents(ident).write_text("test/owner.txt", owner + ":" + ident)
            service.access.settle(call,Decimal("0.01"),generation=meter.generation,execution_id=meter.execution_id)
            with manager.lock:
                job["status"] = "NEEDS_USER_INPUT"
                real_store.save_job(job, expected_generation=meter.generation)
            with record_lock:
                if len(records) == 3:
                    all_done.set()
        except Exception as exc:
            failures.append(type(exc).__name__)
            raise

    monkeypatch.setattr(manager, "_run", fake_model)

    def admit(owner):
        with as_actor(owner):
            return service.admit(owner, {"method":"generate", "params":{}, "idempotency_key":uuid4().hex},
                lambda request: manager.workspace.summary(manager.create("병렬 실행 검증")["id"]))

    try:
        one, two = admit(owners[0]), admit(owners[1])
        assert both_started.wait(15), failures
        three = admit(owners[2])
        status = service.access.status(first["id"])
        assert status["active_count"] == 2 and status["queued_count"] == 1
        assert len(records) == 2
        with pytest.raises(AccessError) as caught:
            with service.temporary(first, one["id"]):
                pass
        assert caught.value.code == "capacity"
        for method in ("knowledge.search","knowledge.graph"):
            assert service.invoke({"method":method,"params":{},"session":sid},lambda request: {"nodes":[]}) == {"nodes":[]}
        assert service.access.status(first["id"])["active_count"] == 2
        if cancel_third:
            service.admin({**first,"role":"admin"},"admin.stop",{"id":three["id"],"execution_id":three["execution_id"]})
            assert manager.get(three["id"])["status"] == "interrupted"
            assert service.access.status(first["id"])["queued_count"] == 0
        release.set()
        if not cancel_third:
            assert all_done.wait(20), failures
    finally:
        release.set()
        manager.close()
    assert not failures
    expected = {one["id"],two["id"]} if cancel_third else {one["id"],two["id"],three["id"]}
    assert {ident for ident,_ in records} == expected
    for ident, owner in records:
        assert real_store.documents(ident).read_text("test/owner.txt") == owner + ":" + ident
    assert service.access.status(first["id"])["active_count"] == 0


@pytest.mark.parametrize("same_user", [False, True])
def test_observed_budget_does_not_block_reservation_and_settlement_is_once(real_store, same_user):
    access = AccessStore(real_store)
    _, one = account(access, "budget-one")
    _, other = account(access, "budget-two")
    users = [one,one if same_user else other]
    with real_store.transaction() as conn:
        conn.execute("UPDATE users SET daily_usd=100")
        conn.execute("UPDATE service_settings SET daily_usd=1")
        guards = [(uuid4().hex,uuid4().hex) for _ in users]
        generations = [access.acquire(conn,user["id"],jid,execution_id=eid,kind="auxiliary",queued=False) for user,(jid,eid) in zip(users,guards)]
    peers = [AccessStore(KnowledgeStore(real_store.config)) for _ in users]
    barrier = threading.Barrier(2)

    def reserve(index):
        barrier.wait(timeout=10)
        jid,eid = guards[index]
        try:
            return peers[index].reserve(users[index]["id"],jid,generations[index],MODEL,Decimal("0.75"),execution_id=eid)
        except AccessError as exc:
            assert exc.code == "quota"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = list(pool.map(reserve,range(2)))
    assert all(calls)
    call = next(value for value in calls if value is not None)
    barrier = threading.Barrier(2)

    def settle(index):
        barrier.wait(timeout=10)
        peers[index].settle(call,Decimal("0.02"),source="manual")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(settle,range(2)))
    with real_store.transaction(mode="read") as conn:
        total = conn.execute("SELECT sum(reserved) AS reserved,sum(spent) AS spent FROM daily_usage").fetchone()
        assert Decimal(total["reserved"]) == Decimal("0.75") and Decimal(total["spent"]) == Decimal("0.02")


def test_old_generation_cannot_save_reserve_finish_or_settle_new_execution(real_store):
    access = AccessStore(real_store)
    _, user = account(access, "stale")
    jid, old, new = uuid4().hex,uuid4().hex,uuid4().hex
    project = real_store.create_project("실행 세대 검증")
    job = {"id":jid,"project_id":project["id"],"owner_id":user["id"],"execution_id":old}
    real_store.save_job(job)
    with real_store.transaction() as conn:
        first = access.acquire(conn,user["id"],jid,execution_id=old,queued=False)
    call = access.reserve(user["id"],jid,first,MODEL,Decimal("0.1"),execution_id=old)
    access.finish(jid,first,old)
    job["execution_id"] = new
    real_store.save_job(job)
    with real_store.transaction() as conn:
        second = access.acquire(conn,user["id"],jid,execution_id=new,queued=False)
        with pytest.raises(AccessError):
            access.acquire(conn,user["id"],jid,execution_id=uuid4().hex)
    with pytest.raises(AccessError):
        real_store.save_job({**job,"execution_id":old},expected_generation=first)
    from backend.knowledge.core import Documents
    writer = Documents(real_store,jid,runtime=SimpleNamespace(meter=SimpleNamespace(
        access=access,uid=user["id"],jid=jid,generation=first,execution_id=old,
    )))
    with pytest.raises(AccessError):
        writer.write_text("test/stale.txt","이전 실행의 문서")
    assert not real_store.documents(jid).exists("test/stale.txt")
    with pytest.raises(AccessError):
        access.reserve(user["id"],jid,first,MODEL,Decimal("0.1"),execution_id=old)
    with pytest.raises(AccessError):
        access.settle(call,Decimal(0),generation=first,execution_id=old)
    access.finish(jid,first,old)
    access.check_execution(user["id"],jid,second,new)


def test_logout_only_stops_owner_and_waiting_does_not_hold_execution(real_store):
    access = AccessStore(real_store)
    _, one = account(access, "logout-one")
    _, two = account(access, "logout-two")
    with real_store.transaction() as conn:
        a = access.acquire(conn,one["id"],"job-one",execution_id="one",kind="auxiliary",queued=False)
        b = access.acquire(conn,two["id"],"job-two",execution_id="two",kind="auxiliary",queued=False)
    access.stop_owner(one["id"])
    with pytest.raises(AccessError):
        access.check_execution(one["id"],"job-one",a,"one")
    access.check_execution(two["id"],"job-two",b,"two")
    access.finish("job-one",a,"one")
    assert access.status(two["id"])["active_count"] == 1


def test_public_workflow_uses_generation_fenced_documents_and_releases_waiting_slot(real_store, monkeypatch):
    manager, provider = manager_for(real_store, monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    sid, user = account(service.access,"public-workflow")
    request = {"method":"job.command","params":{"kind":"generate","input":"메모를 저장해주세요"},
               "session":sid,"csrf":user["csrf"],"idempotency_key":uuid4().hex}

    def dispatch(request):
        return manager.workspace.summary(manager.create(request["params"]["request"])["id"])

    try:
        accepted = service.invoke(request,dispatch)
        service.worker(accepted["id"],"generate","메모를 저장해주세요")
        assert manager.get(accepted["id"])["status"] == "PASS_PENDING_USER_APPROVAL"
        assert service.access.status(user["id"])["active_count"] == 0
    finally:
        manager.close()


def test_duplicate_admission_race_accepts_once_and_rollback_preserves_other_job(real_store, monkeypatch):
    manager, _ = manager_for(real_store,monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    sid, user = account(service.access,"admission-race")
    request = {"method":"job.command","params":{"kind":"generate","input":"중복 접수 검증"},
               "session":sid,"csrf":user["csrf"],"idempotency_key":"same-concurrent-key"}

    def dispatch(request):
        return manager.workspace.summary(manager.create(request["params"]["request"])["id"])

    barrier = threading.Barrier(2)
    def submit(index):
        barrier.wait(timeout=10)
        return service.invoke(request,dispatch)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit,range(2)))
        assert results[0]["id"] == results[1]["id"] and len(manager.jobs) == 1
        other = manager.jobs[results[0]["id"]]

        def failing_dispatch(request):
            manager.create("실패할 접수")
            other["progress"] = {"stage":"other-progress","state":"completed"}
            raise ValueError("fake-admission-failure")

        with as_actor(user), pytest.raises(ValueError):
            service.admit(user,{"method":"generate","params":{},"idempotency_key":"different-failed-key"},failing_dispatch)
        assert list(manager.jobs) == [other["id"]]
        assert manager.jobs[other["id"]]["progress"]["stage"] == "other-progress"
        with real_store.transaction(mode="read") as conn:
            assert len(conn.execute("SELECT id FROM jobs").fetchall()) == 1
            assert len(conn.execute("SELECT key FROM admissions").fetchall()) == 1
    finally:
        manager.close()


def test_approve_message_race_only_accepts_one_latest_execution(real_store, monkeypatch):
    manager, _ = manager_for(real_store,monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    sid, user = account(service.access,"command-race")

    def dispatch(request):
        params = request["params"]
        if request["method"] == "generate":
            result = manager.create(params["request"])
        else:
            payload = {"candidate_hash":params["candidate_hash"]} if request["method"] == "approve" else params["payload"]
            result = manager.action(params["id"],request["method"],payload,expected_execution_id=params["execution_id"])
        return manager.workspace.summary(result["id"])

    def packet(params,key):
        return {"method":"job.command","params":params,"session":sid,"csrf":user["csrf"],"idempotency_key":key}

    try:
        accepted = service.invoke(packet({"kind":"generate","input":"메모를 저장해주세요"},"race-generate"),dispatch)
        service.worker(accepted["id"],"generate","메모를 저장해주세요")
        job = manager.get(accepted["id"])
        assert job["status"] == "PASS_PENDING_USER_APPROVAL"
        base = {"job_id":job["id"],"execution_id":job["execution_id"]}
        requests = [packet({**base,"kind":"approve","candidate_hash":manager.workspace.state(job["id"])["candidate_hash"]},"race-approve"),
                    packet({**base,"kind":"message","input":"보관 조건을 바꿔주세요"},"race-message")]
        barrier = threading.Barrier(2)
        def race(index):
            barrier.wait(timeout=10)
            try:
                return service.invoke(requests[index],dispatch)
            except AccessError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(race,range(2)))
        assert sum(isinstance(value,dict) for value in outcomes) == 1
        assert "conflict" in outcomes
    finally:
        manager.close()


def test_stop_command_refunds_unused_queued_call_without_stopping_other_job(real_store, monkeypatch):
    manager, _ = manager_for(real_store,monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    sid, user = account(service.access,"stop-owner")
    def dispatch(request):
        return manager.workspace.summary(manager.create(request["params"]["request"])["id"])
    def create(key):
        return service.invoke({"method":"job.command","params":{"kind":"generate","input":"중지 검증"},
                               "session":sid,"csrf":user["csrf"],"idempotency_key":key},dispatch)
    try:
        one, other = create("stop-first"), create("stop-second")
        service.invoke({"method":"job.command","params":{"kind":"stop","job_id":one["id"],"execution_id":one["execution_id"]},
                        "session":sid,"csrf":user["csrf"],"idempotency_key":"stop-command"},dispatch)
        with pytest.raises(AccessError):
            service.worker(one["id"],"generate","중지 검증")
        assert manager.get(one["id"])["status"] == "interrupted"
        with real_store.transaction(mode="read") as conn:
            leases = {row["job_id"]: row for row in conn.execute("SELECT * FROM execution_leases").fetchall()}
            assert leases[one["id"]]["phase"] == "finished"
            assert leases[other["id"]]["phase"] == "queued" and not leases[other["id"]]["stopping"]
            cost = conn.execute("SELECT actual,state FROM cost_calls WHERE job_id=%s", (one["id"],)).fetchone()
            assert cost["state"] == "settled" and Decimal(cost["actual"]) == 0
    finally:
        manager.close()


def test_maintenance_blocks_new_execution_and_releases_gate_on_exit(real_store, monkeypatch):
    manager, _ = manager_for(real_store,monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    _, user = account(service.access,"maintenance-owner")
    try:
        with service.temporary(user,"maintenance"):
            with as_actor(user), pytest.raises(AccessError) as caught:
                service.admit(user,{"method":"generate","params":{},"idempotency_key":"maintenance-rejected"},
                              lambda request: manager.create("허용되면 안 되는 접수"))
            assert caught.value.code == "capacity"
        assert not manager.jobs
        service.capacity.check_admission()
    finally:
        manager.close()


def test_queue_limit_is_enforced_by_transactional_execution_records(real_store):
    access = AccessStore(real_store)
    _, user = account(access,"queue-limit")
    with real_store.transaction() as conn:
        for _ in range(20):
            access.acquire(conn,user['id'],uuid4().hex,execution_id=uuid4().hex)
    with pytest.raises(AccessError) as caught:
        with real_store.transaction() as conn:
            access.acquire(conn,user['id'],uuid4().hex,execution_id=uuid4().hex)
    assert caught.value.code == 'capacity'


def test_maintenance_cannot_overtake_admission_commit(real_store, monkeypatch):
    manager, _ = manager_for(real_store,monkeypatch)
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    _, user = account(service.access,"maintenance-race")
    entered, release = threading.Event(), threading.Event()
    acquire = service.access.acquire

    def paused_acquire(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return acquire(*args, **kwargs)

    monkeypatch.setattr(service.access,"acquire",paused_acquire)

    def admit():
        with as_actor(user):
            return service.admit(user,{"method":"generate","params":{},"idempotency_key":"maintenance-race"},
                                 lambda request: manager.workspace.summary(manager.create("접수 경합")["id"]))

    def maintain():
        with pytest.raises(AccessError) as caught:
            with service.temporary(user,"maintenance"):
                pytest.fail("접수 커밋을 앞질러 유지보수에 진입하면 안 된다.")
        assert caught.value.code == "capacity"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            admission = pool.submit(admit)
            assert entered.wait(10)
            maintenance = pool.submit(maintain)
            with service.capacity.condition:
                assert service.capacity.condition.wait_for(lambda: service.capacity.maintaining,timeout=5)
            release.set()
            assert admission.result(timeout=10)["id"]
            maintenance.result(timeout=10)
        assert service.access.status(user["id"])["queued_count"] == 1
        assert not service.capacity.maintaining
    finally:
        release.set()
        manager.close()


def test_restart_interrupts_execution_and_preserves_uncertain_reservation(real_store):
    access = AccessStore(real_store)
    _, user = account(access,"restart-owner")
    with real_store.transaction() as conn:
        generation = access.acquire(conn,user['id'],'aux-job',execution_id='before-restart',kind='auxiliary',queued=False)
    call = access.reserve(user['id'],'aux-job',generation,MODEL,Decimal('0.25'),execution_id='before-restart')
    runtime = PublicRuntime(real_store)
    try:
        runtime.acquire(recover=False)
        runtime.recover()
    finally:
        runtime.close()
    with real_store.transaction(mode='read') as conn:
        row = conn.execute('SELECT state,reserved,actual FROM cost_calls WHERE id=%s',(call,)).fetchone()
        assert row['state']=='uncertain' and Decimal(row['reserved'])==Decimal('0.25') and row['actual'] is None
        assert conn.execute('SELECT phase FROM execution_leases').fetchone()['phase']=='interrupted'
    assert access.status(user['id'])['active_count']==0


@pytest.mark.parametrize("same_key", [False, True])
def test_pending_replay_admission_race_accepts_one_execution(real_store, monkeypatch, same_key):
    from backend.errors import Error
    from backend.models import InterviewResponse
    from fakes import DecisionProvider

    class Broken(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            if kwargs["text_format"] is InterviewResponse:
                raise Error("test transport failure")
            return super().complete_result(messages,**kwargs)

    manager, _ = manager_for(real_store,monkeypatch,Broken([[]]))
    service = PublicService(manager,google=Mock(),pepper="fake-test-pepper")
    sid, user = account(service.access,"replay-race")

    def dispatch(request):
        params = request["params"]
        job = manager.create(params["request"]) if request["method"] == "generate" else manager.action(
            params["id"],"retry",{"replay_pending":params.get("replay_pending",False)},expected_execution_id=params["execution_id"])
        return manager.workspace.summary(job["id"])

    def packet(params,key):
        return {"method":"job.command","params":params,"session":sid,"csrf":user["csrf"],"idempotency_key":key}

    try:
        job = service.invoke(packet({"kind":"generate","input":"메모를 저장해주세요"},"replay-generate"),dispatch)
        service.worker(job["id"],"generate","메모를 저장해주세요")
        summary = manager.workspace.summary(job["id"])
        assert summary["can_retry"] and summary["retry_requires_replay"]
        barrier = threading.Barrier(2)
        def race(index):
            barrier.wait(timeout=10)
            try:
                return service.invoke(packet({"kind":"retry","job_id":job["id"],"execution_id":job["execution_id"],"replay_pending":True},
                                             "replay-key" if same_key else f"replay-key-{index}"),dispatch)
            except AccessError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(race,range(2)))
        accepted = [result for result in results if isinstance(result,dict)]
        assert len(accepted) == (2 if same_key else 1)
        assert len({result["execution_id"] for result in accepted}) == 1
        with real_store.transaction(mode="read") as conn:
            assert conn.execute("SELECT count(*) AS n FROM execution_leases WHERE phase='queued'").fetchone()["n"] == 1
            assert conn.execute("SELECT count(*) AS n FROM cost_calls").fetchone()["n"] == 2
    finally:
        manager.close()
