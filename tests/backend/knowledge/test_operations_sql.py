"""CLI 대신 문서화한 관리자 지정·복구 SQL의 효과와 롤백을 검증한다."""

import asyncio
import sys
from functools import wraps
from decimal import Decimal
from pathlib import Path
import re

import pytest

from backend.knowledge.config import KnowledgeError


def async_test(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        with asyncio.Runner(loop_factory=factory) as runner:
            return runner.run(function(*args, **kwargs))
    return wrapped


def operation_sql(action):
    document = (Path(__file__).resolve().parents[3] / "docs/PUBLIC_SERVICE.ko.md").read_text(encoding="utf-8")
    blocks = [sql for sql in re.findall(r"```sql\n(.*?)\n```", document, re.DOTALL) if f"'{action}'" in sql]
    assert len(blocks) == 1
    return blocks[0].strip().removeprefix("BEGIN;").removesuffix("COMMIT;").strip()


@pytest.mark.parametrize("exists", [True, False])
@async_test
async def test_first_admin_sql_validates_user_and_revokes_sessions(async_store_factory, exists):
    async with async_store_factory() as store:
        async with store.transaction() as conn:
            (await conn.execute("INSERT INTO public.users(id,subject_hash) VALUES ('first','fake-subject')"))
            (await conn.execute("INSERT INTO public.sessions(hash,user_id,csrf,expires_at) VALUES ('fake-session','first','fake-csrf',1)"))
        sql = operation_sql("make-admin").replace("<내부사용자ID>", "first" if exists else "missing")
        if exists:
            async with store.test_admin_transaction() as conn:
                (await conn.execute(sql))
        else:
            with pytest.raises(KnowledgeError):
                async with store.test_admin_transaction() as conn:
                    (await conn.execute(sql))
        async with store.transaction(mode="read") as conn:
            assert (await (await conn.execute("SELECT role FROM public.users WHERE id='first'")).fetchone())["role"] == ("admin" if exists else "user")
            assert (await (await conn.execute("SELECT revoked FROM public.sessions")).fetchone())["revoked"] is exists
            assert len((await (await conn.execute("SELECT id FROM public.admin_audit WHERE action='make-admin'")).fetchall())) == int(exists)


@async_test
async def test_recovery_sql_keeps_reservation_and_does_not_replay_job(async_store_factory):
    async with async_store_factory() as store:
        async with store.transaction() as conn:
            (await conn.execute("INSERT INTO public.cost_calls(id,day,user_id,job_id,model,reserved) VALUES ('c','2026-10-24','u','j','test-model',1)"))
            (await conn.execute("INSERT INTO public.users(id,subject_hash) VALUES ('u','fake-recovery-user')"))
            (await conn.execute("INSERT INTO public.execution_leases(execution_id,owner_id,job_id,kind,phase) VALUES ('e','u','j','workflow','recovery')"))
        async with store.test_admin_transaction() as conn:
            (await conn.execute(operation_sql("recover")))
        async with store.transaction(mode="read") as conn:
            lease = (await (await conn.execute("SELECT * FROM public.execution_leases")).fetchone())
            assert lease["phase"] == "interrupted" and lease["job_id"] == "j" and lease["stopping"]
            cost = (await (await conn.execute("SELECT state,reserved,actual FROM public.cost_calls")).fetchone())
            assert cost["state"] == "uncertain" and Decimal(cost["reserved"]) == Decimal(1) and cost["actual"] is None
            assert (await (await conn.execute("SELECT id FROM public.admin_audit WHERE action='recover'")).fetchone())
