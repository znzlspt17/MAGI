"""비밀 파일을 읽지 않는 운영 명령. 서버 중지 상태에서만 변경한다."""

import argparse
from uuid import uuid4
from backend.access.runtime import PublicRuntime
from backend.access.store import AccessStore
from backend.knowledge.config import KnowledgeConfig
from backend.knowledge.store import KnowledgeStore


def main():
    parser=argparse.ArgumentParser(description='환경을 주입한 운영 계정으로 실행하세요. 인증값을 인자로 넘기지 마세요.')
    parser.add_argument('action',choices=['users','make-admin','recover'])
    parser.add_argument('--user-id')
    parser.add_argument('--confirm-stopped',action='store_true')
    args=parser.parse_args()
    config=KnowledgeConfig.from_env()
    if config is None:
        parser.error('PostgreSQL 설정이 필요합니다.')
    store=KnowledgeStore(config)
    runtime=PublicRuntime(store)
    try:
        runtime.acquire()
        with store.transaction() as c:
            if args.action=='users':
                for row in c.execute('SELECT id,role,suspended FROM users ORDER BY id').fetchall():
                    print(row['id'],row['role'],row['suspended'])
            elif args.action=='make-admin':
                if not args.user_id or not c.execute('SELECT id FROM users WHERE id=%s',(args.user_id,)).fetchone():
                    parser.error('기존 사용자 ID를 지정하세요.')
                c.execute("UPDATE users SET role='admin' WHERE id=%s",(args.user_id,))
                c.execute('UPDATE sessions SET revoked=true WHERE user_id=%s',(args.user_id,))
                c.execute("INSERT INTO admin_audit(id,actor_id,action,target_id) VALUES (%s,'operator','make-admin',%s)",(uuid4().hex,args.user_id))
            else:
                if not args.confirm_stopped:
                    parser.error('이전 실행과 외부 호출의 종료를 확인한 뒤 --confirm-stopped를 지정하세요.')
                c.execute("UPDATE cost_calls SET state='uncertain' WHERE state='reserved'")
                AccessStore.clear(c)
                c.execute("INSERT INTO admin_audit(id,actor_id,action) VALUES (%s,'operator','recover')",(uuid4().hex,))
    finally:
        runtime.close()


if __name__=='__main__':
    main()
