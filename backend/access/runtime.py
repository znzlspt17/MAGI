"""공개 모드 초기화와 단일 백엔드 프로세스 확인."""

import os
from backend.access.google import GoogleLogin
from backend.access.service import PublicService
from backend.errors import InvalidStateError

PROCESS_LOCK=72410635


class PublicRuntime:
    def __init__(self, store):
        self.store=store
        self.connection=None

    def acquire(self, *, recover=True):
        from psycopg.rows import dict_row
        c=self.store.connect(**self.store.config.connection,row_factory=dict_row)
        try:
            role=c.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if role['rolsuper'] or role['rolbypassrls']:
                raise InvalidStateError('공개 서비스 DB 계정은 superuser/BYPASSRLS 권한을 가질 수 없습니다.')
            if not c.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(PROCESS_LOCK,)).fetchone()['acquired']:
                raise InvalidStateError('다른 공개 백엔드 프로세스가 실행 중입니다.')
            c.commit()
            self.connection=c
            if recover:
                with self.store.transaction() as tx:
                    tx.execute("UPDATE service_lease SET phase='recovery',deadline=NULL WHERE singleton=1 AND phase IN ('running','recovery')")
        except Exception:
            c.close()
            raise

    def close(self):
        if self.connection:
            self.connection.close()


def service_factory(manager):
    from protocol.web_config import login_origin
    local_login=os.environ.get('LOCAL_LOGIN','0')=='1'
    origin=login_origin(os.environ.get('PUBLIC_ORIGIN',''),local_login)
    client_id=os.environ.get('GOOGLE_OAUTH_ID','')
    client_secret=os.environ.get('GOOGLE_OAUTH_SECRET','')
    google=GoogleLogin(client_id,client_secret,origin+'/auth/google/callback',local_login=local_login)
    manager.knowledge.public_mode=True
    return PublicService(manager,google=google,pepper=os.environ.get('SUBJECT_PEPPER',''))
