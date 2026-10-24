"""CLI 대신 문서화한 관리자 지정·복구 SQL의 효과와 롤백을 검증한다."""

from decimal import Decimal
from pathlib import Path
import re

import pytest

from backend.knowledge.config import KnowledgeError


def operation_sql(action):
    document = (Path(__file__).resolve().parents[2] / "docs/PUBLIC_SERVICE.ko.md").read_text(encoding="utf-8")
    blocks = [sql for sql in re.findall(r"```sql\n(.*?)\n```", document, re.DOTALL) if f"'{action}'" in sql]
    assert len(blocks) == 1
    return blocks[0].strip().removeprefix("BEGIN;").removesuffix("COMMIT;").strip()


@pytest.mark.parametrize("exists", [True, False])
def test_first_admin_sql_validates_user_and_revokes_sessions(store, admin_transaction, exists):
    with store.transaction() as conn:
        conn.execute("INSERT INTO public.users(id,subject_hash) VALUES ('first','fake-subject')")
        conn.execute("INSERT INTO public.sessions(hash,user_id,csrf,expires_at) VALUES ('fake-session','first','fake-csrf',1)")
    sql = operation_sql("make-admin").replace("<내부사용자ID>", "first" if exists else "missing")
    if exists:
        with admin_transaction() as conn:
            conn.execute(sql)
    else:
        with pytest.raises(KnowledgeError):
            with admin_transaction() as conn:
                conn.execute(sql)
    with store.transaction(mode="read") as conn:
        assert conn.execute("SELECT role FROM public.users WHERE id='first'").fetchone()["role"] == ("admin" if exists else "user")
        assert conn.execute("SELECT revoked FROM public.sessions").fetchone()["revoked"] is exists
        assert len(conn.execute("SELECT id FROM public.admin_audit WHERE action='make-admin'").fetchall()) == int(exists)


def test_recovery_sql_keeps_reservation_and_does_not_replay_job(store, admin_transaction):
    with store.transaction() as conn:
        conn.execute("INSERT INTO public.cost_calls(id,day,user_id,job_id,model,reserved) VALUES ('c','2026-10-24','u','j','test-model',1)")
        conn.execute("INSERT INTO public.users(id,subject_hash) VALUES ('u','fake-recovery-user')")
        conn.execute("INSERT INTO public.execution_leases(execution_id,owner_id,job_id,kind,phase) VALUES ('e','u','j','workflow','recovery')")
    with admin_transaction() as conn:
        conn.execute(operation_sql("recover"))
    with store.transaction(mode="read") as conn:
        lease = conn.execute("SELECT * FROM public.execution_leases").fetchone()
        assert lease["phase"] == "interrupted" and lease["job_id"] == "j" and lease["stopping"]
        cost = conn.execute("SELECT state,reserved,actual FROM public.cost_calls").fetchone()
        assert cost["state"] == "uncertain" and Decimal(cost["reserved"]) == Decimal(1) and cost["actual"] is None
        assert conn.execute("SELECT id FROM public.admin_audit WHERE action='recover'").fetchone()
