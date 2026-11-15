"""공개 인증 자료와 원자적 실행·비용 원장. 외부 제공자 원문은 저장하지 않는다."""

import hashlib
import hmac
from protocol.logging import get_logger
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from backend.access.context import AccessError
from backend.access.capacity import MAX_ADMITTED, MAX_PARALLEL
from backend.access.limits import LIMIT_MODE


LOGGER = get_logger('backend.server')
GUEST_TTL = 30 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def day_at(now):
    return datetime.fromtimestamp(now, timezone(timedelta(hours=9))).date().isoformat()


class AccessStore:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    async def guest(self, previous=None):
        """2026-11-13: 유효한 익명 세션은 연장하고 정지된 계정은 우회하지 않는다."""
        now = self.clock()
        async with self.store.transaction() as c:
            if isinstance(previous, str) and 20 <= len(previous) <= 200:
                row = (await (await c.execute(
                    'SELECT u.suspended AS own_suspended,a.suspended AS account_suspended,'
                    'a.subject_hash,s.revoked,s.expires_at FROM sessions s '
                    'JOIN users u ON u.id=s.user_id JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                    'WHERE s.hash=%s', (digest(previous),))).fetchone())
                if row and (row['own_suspended'] or row['account_suspended']):
                    raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
                if row and not row['revoked'] and row['expires_at'] > now:
                    if row['subject_hash'] is None:
                        (await c.execute('UPDATE sessions SET expires_at=%s WHERE hash=%s', (now + GUEST_TTL, digest(previous))))
                    return previous
            uid, sid, csrf = uuid4().hex, secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            (await c.execute('INSERT INTO users(id,subject_hash,account_id) VALUES (%s,NULL,%s)', (uid, uid)))
            (await c.execute('INSERT INTO sessions(hash,user_id,csrf,expires_at) VALUES (%s,%s,%s,%s)',
                      (digest(sid), uid, csrf, now + GUEST_TTL)))
            return sid

    async def login(self, subject, pepper, previous=None):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255 or not pepper:
            raise AccessError('로그인 결과를 확인할 수 없습니다.', 'unauthorized')
        hashed = hmac.new(pepper.encode(), ('google\0' + subject).encode(), hashlib.sha256).hexdigest()
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self.store.transaction() as c:
            prior = None
            if previous:
                prior = (await (await c.execute('SELECT u.*,s.revoked,s.expires_at,a.suspended AS account_suspended '
                                  'FROM sessions s JOIN users u ON u.id=s.user_id '
                                  'JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                                  'WHERE s.hash=%s FOR UPDATE', (digest(previous),))).fetchone())
                if not prior or prior['revoked'] or prior['expires_at'] <= self.clock():
                    raise AccessError('로그인 요청이 만료되었습니다.', 'unauthorized')
                if prior['suspended'] or prior['account_suspended']:
                    raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
            user = (await (await c.execute('SELECT * FROM users WHERE subject_hash=%s FOR UPDATE', (hashed,))).fetchone())
            if user and user['suspended']:
                raise AccessError('이 계정은 이용할 수 없습니다.')
            if prior and prior['subject_hash'] is None and (prior['account_id'] or prior['id']) == prior['id']:
                if user is None:
                    (await c.execute('UPDATE users SET subject_hash=%s WHERE id=%s', (hashed, prior['id'])))
                    uid = prior['id']
                else:
                    uid = user['id']
                    (await c.execute('UPDATE users SET account_id=%s WHERE id=%s', (uid, prior['id'])))
                # 다른 탭의 이전 익명 세션이 계정 전체 권한으로 승격되지 않게 한다.
                (await c.execute('UPDATE sessions SET revoked=true WHERE user_id=%s', (prior['id'],)))
            else:
                if prior and user and (prior['account_id'] or prior['id']) != user['id']:
                    raise AccessError('연결된 계정은 다른 계정으로 변경할 수 없습니다.', 'conflict')
                if prior and user is None:
                    raise AccessError('연결된 계정은 다른 계정으로 변경할 수 없습니다.', 'conflict')
                if user is None:
                    uid = uuid4().hex
                    (await c.execute('INSERT INTO users(id,subject_hash,account_id) VALUES (%s,%s,%s)', (uid, hashed, uid)))
                else:
                    uid = user['id']
                if previous:
                    (await c.execute('UPDATE sessions SET revoked=true WHERE hash=%s', (digest(previous),)))
            (await c.execute('INSERT INTO sessions(hash,user_id,csrf,expires_at) VALUES (%s,%s,%s,%s)',
                      (digest(sid), uid, csrf, self.clock() + 86400)))
        return sid

    async def session(self, sid):
        if not isinstance(sid, str) or not 20 <= len(sid) <= 200:
            raise AccessError('로그인이 필요합니다.', 'unauthorized')
        async with self.store.transaction(mode='read') as c:
            row = (await (await c.execute('SELECT a.*,s.csrf,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id '
                            'JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                            'WHERE s.hash=%s AND NOT s.revoked AND NOT u.suspended AND NOT a.suspended AND s.expires_at>%s',
                            (digest(sid), self.clock()))).fetchone())
            owners = (await (await c.execute('SELECT id FROM users WHERE COALESCE(account_id,id)=%s AND NOT suspended ORDER BY id',
                               (row['id'],))).fetchall()) if row else []
        if not row:
            raise AccessError('로그인이 필요합니다.', 'unauthorized')
        return {**dict(row), 'owner_ids': [owner['id'] for owner in owners],
                'identity_kind': 'google' if row['subject_hash'] else 'guest'}

    async def reject_suspended_sessions(self, *sessions):
        """2026-11-15: 만료된 쿠키와 정지된 쿠키를 함께 보내도 정지를 우회하지 않는다."""
        hashes = [digest(sid) for sid in sessions if isinstance(sid, str) and 20 <= len(sid) <= 200]
        if not hashes:
            return
        async with self.store.transaction(mode='read') as c:
            row = await (await c.execute(
                'SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id '
                'JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                'WHERE s.hash=ANY(%s) AND (u.suspended OR a.suspended) LIMIT 1', (hashes,))).fetchone()
        if row:
            raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')

    async def resolve_session(self, primary, alternate):
        """2026-11-15: 기존 세션을 우선하고 정지 계정은 대체 세션으로 우회하지 않는다."""
        if not primary:
            return alternate, await self.session(alternate)
        try:
            return primary, await self.session(primary)
        except AccessError:
            if not alternate or alternate == primary:
                raise
            if isinstance(primary, str) and 20 <= len(primary) <= 200:
                async with self.store.transaction(mode='read') as c:
                    row = await (await c.execute(
                        'SELECT u.suspended AS own_suspended,a.suspended AS account_suspended '
                        'FROM sessions s JOIN users u ON u.id=s.user_id '
                        'JOIN users a ON a.id=COALESCE(u.account_id,u.id) WHERE s.hash=%s',
                        (digest(primary),))).fetchone()
                if row and (row['own_suspended'] or row['account_suspended']):
                    raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
            return alternate, await self.session(alternate)

    async def logout(self, sid):
        async with self.store.transaction() as c:
            (await c.execute('UPDATE sessions SET revoked=true WHERE hash=%s', (digest(sid),)))

    async def session_for_worker(self, uid):
        async with self.store.transaction(mode='read') as c:
            row = (await (await c.execute('SELECT u.id,a.id AS account_id,a.role,u.suspended AS own_suspended,a.suspended AS account_suspended '
                            'FROM users u JOIN users a ON a.id=COALESCE(u.account_id,u.id) WHERE u.id=%s',(uid,))).fetchone())
            owners = (await (await c.execute('SELECT id FROM users WHERE COALESCE(account_id,id)=%s AND NOT suspended ORDER BY id',
                                             (row['account_id'],))).fetchall()) if row else []
        if not row or row['own_suspended'] or row['account_suspended']:
            raise AccessError('작업 소유자를 확인할 수 없습니다.', 'unauthorized')
        return {'id': uid, 'role': row['role'], 'suspended': False, 'owner_ids': [owner['id'] for owner in owners]}

    async def throttle(self, uid):
        async with self.store.transaction() as c:
            minute=int(self.clock()//60)
            (await c.execute('DELETE FROM request_windows WHERE minute<%s',(minute-1,)))
            row=(await (await c.execute('INSERT INTO request_windows(identity,minute,calls) VALUES (%s,%s,1) '
                          'ON CONFLICT(identity) DO UPDATE SET minute=EXCLUDED.minute,calls=CASE WHEN request_windows.minute=EXCLUDED.minute THEN request_windows.calls+1 ELSE 1 END RETURNING calls',
                          (uid,minute))).fetchone())
            calls=row['calls']
        if calls>180:
            raise AccessError('요청이 너무 많습니다. 잠시 후 다시 시도하세요.', 'quota')

    async def begin_login(self, sid=None):
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        async with self.store.transaction() as c:
            (await c.execute('DELETE FROM login_states WHERE expires_at<%s', (self.clock(),)))
            (await c.execute('INSERT INTO login_states(hash,browser_hash,nonce,verifier,expires_at,session_hash) VALUES (%s,%s,%s,%s,%s,%s)',
                      (digest(state), digest(browser), nonce, verifier, self.clock() + 300, digest(sid) if sid else None)))
        return state, browser, nonce, verifier

    async def consume_login(self, state, browser, sid=None):
        if not state or not browser:
            raise AccessError('로그인 요청이 만료되었습니다.', 'unauthorized')
        async with self.store.transaction() as c:
            row = (await (await c.execute('DELETE FROM login_states WHERE hash=%s AND browser_hash=%s AND expires_at>%s RETURNING nonce,verifier,session_hash',
                            (digest(state), digest(browser), self.clock()))).fetchone())
        if not row or row['session_hash'] != (digest(sid) if sid else None):
            raise AccessError('로그인 요청이 만료되었습니다.', 'unauthorized')
        return row

    async def acquire(self, c, uid, jid, *, execution_id, kind='workflow', queued=True, count=False, initial=Decimal('0')):
        if kind == 'workflow' and (await (await c.execute(
            "SELECT count(*) AS total FROM execution_leases WHERE kind='workflow' AND phase IN ('queued','running')"
        )).fetchone())['total'] >= MAX_ADMITTED:
            raise AccessError('작업 대기열이 가득 찼습니다.', 'capacity')
        if kind == 'workflow' and (await (await c.execute(
            "SELECT 1 FROM execution_leases WHERE job_id=%s AND kind='workflow' AND phase IN ('queued','running')", (jid,),
        )).fetchone()):
            raise AccessError('이 작업은 이미 실행 중입니다.', 'conflict')
        user = (await (await c.execute('SELECT u.* FROM users u JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                                       'WHERE u.id=%s AND NOT u.suspended AND NOT a.suspended', (uid,))).fetchone())
        if not user:
            raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
        day = day_at(self.clock())
        usage = (await self._usage(c, day, uid))
        if count and usage['runs'] >= user['daily_runs']:
            LOGGER.info('usage threshold exceeded kind=runs mode=%s', LIMIT_MODE)
        (await self.check_money(c, uid, initial, day))
        if count:
            (await c.execute('UPDATE daily_usage SET runs=runs+1 WHERE day=%s AND user_id=%s', (day, uid)))
        return (await (await c.execute(
            "INSERT INTO execution_leases(execution_id,owner_id,job_id,kind,phase) VALUES (%s,%s,%s,%s,%s) RETURNING generation",
            (execution_id, uid, jid, kind, 'queued' if queued else 'running'),
        )).fetchone())['generation']

    async def execution(self, c, uid, jid, generation, execution_id, *, queued=False):
        row = (await (await c.execute(
            'SELECT * FROM execution_leases WHERE execution_id=%s AND generation=%s AND owner_id=%s AND job_id=%s FOR UPDATE',
            (execution_id, generation, uid, jid),
        )).fetchone())
        phases = {'queued','running'} if queued else {'running'}
        if not row or row['phase'] not in phases or row['stopping']:
            raise AccessError('작업이 중지되었거나 이전 실행입니다.', 'busy')
        if not (await (await c.execute('SELECT u.id FROM users u JOIN users a ON a.id=COALESCE(u.account_id,u.id) '
                         'WHERE u.id=%s AND NOT u.suspended AND NOT a.suspended', (uid,))).fetchone()):
            raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
        return row

    async def start(self, uid, jid, generation, execution_id):
        async with self.store.transaction() as c:
            (await self.execution(c, uid, jid, generation, execution_id, queued=True))
            (await c.execute("UPDATE execution_leases SET phase='running' WHERE execution_id=%s AND generation=%s", (execution_id,generation)))

    async def stop(self, c, uid, jid, execution_id, *, admin=False):
        row = (await (await c.execute("SELECT * FROM execution_leases WHERE execution_id=%s AND job_id=%s AND phase IN ('queued','running') FOR UPDATE", (execution_id,jid))).fetchone())
        if not row or (not admin and row['owner_id'] != uid):
            raise AccessError('종료할 최신 실행을 확인하세요.', 'conflict')
        (await c.execute('UPDATE execution_leases SET stopping=true WHERE execution_id=%s', (execution_id,)))

    async def stop_owner(self, uid):
        async with self.store.transaction() as c:
            (await c.execute("UPDATE execution_leases SET stopping=true WHERE owner_id=%s AND phase IN ('queued','running')", (uid,)))

    async def _usage(self, c, day, uid):
        (await c.execute('INSERT INTO daily_usage(day,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (day, uid)))
        return (await (await c.execute('SELECT * FROM daily_usage WHERE day=%s AND user_id=%s FOR UPDATE', (day, uid))).fetchone())

    async def check_money(self, c, uid, amount, day):
        user = (await (await c.execute('SELECT daily_usd FROM users WHERE id=%s', (uid,))).fetchone())
        usage = (await self._usage(c, day, uid))
        total = (await (await c.execute('SELECT COALESCE(sum(spent+reserved),0) AS amount FROM daily_usage WHERE day=%s', (day,))).fetchone())['amount']
        cap = (await (await c.execute('SELECT daily_usd FROM service_settings WHERE singleton=1')).fetchone())['daily_usd']
        if Decimal(str(usage['spent'])) + Decimal(str(usage['reserved'])) + amount > Decimal(str(user['daily_usd'])) or Decimal(str(total)) + amount > Decimal(str(cap)):
            LOGGER.info('usage threshold exceeded kind=cost mode=%s', LIMIT_MODE)

    async def reserve(self, uid, jid, generation, model, amount, *, execution_id, queued=False):
        estimated = amount is not None
        amount = amount if estimated else Decimal(0)
        async with self.store.transaction() as c:
            (await self.execution(c, uid, jid, generation, execution_id, queued=queued))
            day = day_at(self.clock())
            (await self.check_money(c, uid, amount, day))
            ident = uuid4().hex
            (await c.execute('UPDATE daily_usage SET reserved=reserved+%s WHERE day=%s AND user_id=%s', (amount, day, uid)))
            (await c.execute('INSERT INTO cost_calls(id,day,user_id,job_id,model,reserved,reserved_at,execution_id,execution_generation) VALUES (%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s)',
                      (ident, day, uid, jid, model, amount, self.clock(), execution_id,generation)))
            if not estimated:
                (await c.execute("UPDATE cost_calls SET state='uncertain' WHERE id=%s", (ident,)))
        return ident

    async def check_execution(self, uid, jid, generation, execution_id):
        async with self.store.transaction() as c:
            (await self.execution(c, uid, jid, generation, execution_id))

    async def _check_call(self, c, ident, generation, execution_id):
        if generation is None:
            return  # 관리자 수동 정산은 별도의 권한 검사 후 호출한다.
        row = (await (await c.execute('SELECT * FROM cost_calls WHERE id=%s', (ident,))).fetchone())
        if not row or row['execution_id'] != execution_id or row['execution_generation'] != generation:
            raise AccessError('이전 실행의 비용 변경을 차단했습니다.', 'conflict')
        execution = (await (await c.execute('SELECT * FROM execution_leases WHERE execution_id=%s AND generation=%s', (execution_id,generation))).fetchone())
        if not execution or execution['phase'] not in {'queued','running','recovery'}:
            raise AccessError('종료된 실행의 비용 변경을 차단했습니다.', 'conflict')
        if execution['kind'] == 'workflow':
            job = (await (await c.execute('SELECT data FROM jobs WHERE id=%s', (execution['job_id'],))).fetchone())
            if not job or job['data'].get('execution_id') != execution_id:
                raise AccessError('이전 실행의 비용 변경을 차단했습니다.', 'conflict')

    async def mark_called(self, ident, *, generation=None, execution_id=None):
        async with self.store.transaction() as c:
            (await self._check_call(c,ident,generation,execution_id))
            (await c.execute('UPDATE cost_calls SET called_at=COALESCE(called_at,to_timestamp(%s)) WHERE id=%s',
                      (self.clock(),ident)))

    async def record_tokens(self, ident, incoming, outgoing, cached, written=None, write_30m=None, write_12h=None, *, policy=None, generation=None, execution_id=None):
        # 누락·잘못된 값은 0으로 채우지 않고 관측한 값만 저장한다.
        incoming = incoming if type(incoming) is int and incoming >= 0 else None
        outgoing = outgoing if type(outgoing) is int and outgoing >= 0 else None
        cached = cached if type(cached) is int and incoming is not None and 0 <= cached <= incoming else None
        # 관계가 잘못된 양수도 그대로 보존해 재산정에서 불일치를 감지한다.
        writes = [value if type(value) is int and 0 <= value <= 2**63-1 else None
                  for value in (written,write_30m,write_12h)]
        async with self.store.transaction() as c:
            (await self._check_call(c,ident,generation,execution_id))
            (await c.execute('UPDATE cost_calls SET input_tokens=%s,output_tokens=%s,cached_tokens=%s,cache_write_tokens=%s,cache_write_30m_tokens=%s,cache_write_12h_tokens=%s,cost_policy=%s WHERE id=%s',
                      (incoming,outgoing,cached,*writes,policy,ident)))

    async def settle(self, ident, actual=None, *, source='calculated', policy=None, generation=None, execution_id=None):
        async with self.store.transaction() as c:
            (await self._check_call(c,ident,generation,execution_id))
            row = (await (await c.execute('SELECT * FROM cost_calls WHERE id=%s FOR UPDATE', (ident,))).fetchone())
            if not row or row['state'] == 'settled':
                return
            if actual is None:
                (await c.execute("UPDATE cost_calls SET state='uncertain' WHERE id=%s", (ident,)))
                return
            if actual < 0 or actual > Decimal(str(row['reserved'])):
                if source == 'manual':
                    raise AccessError('비용 산정을 확인해야 합니다.', 'unavailable')
                (await c.execute("UPDATE cost_calls SET state='uncertain' WHERE id=%s", (ident,)))
                return
            (await c.execute('UPDATE daily_usage SET reserved=reserved-%s,spent=spent+%s WHERE day=%s AND user_id=%s',
                      (row['reserved'], actual, row['day'], row['user_id'])))
            (await c.execute("UPDATE cost_calls SET actual=%s,state='settled',settled_at=to_timestamp(%s),settlement_source=%s,cost_policy=%s WHERE id=%s",
                      (actual,self.clock(),source,policy,ident)))

    async def finish(self, jid, generation, execution_id):
        async with self.store.transaction() as c:
            (await c.execute("UPDATE execution_leases SET phase='finished' WHERE job_id=%s AND generation=%s AND execution_id=%s AND phase IN ('queued','running','recovery')", (jid,generation,execution_id)))

    async def status(self, uid, owners=None):
        async with self.store.transaction(mode='read') as c:
            rows = (await (await c.execute("SELECT owner_id,phase FROM execution_leases WHERE phase IN ('queued','running')")).fetchall())
        return {'ready': True, 'active_count': sum(row['phase']=='running' for row in rows),
                'queued_count': sum(row['phase']=='queued' for row in rows), 'max_parallel': MAX_PARALLEL,
                'own_active_count': sum(row['owner_id'] in (owners or [uid]) and row['phase']=='running' for row in rows)}

    async def usage(self, uid, owners=None):
        async with self.store.transaction() as c:
            rows = [(await self._usage(c, day_at(self.clock()), owner)) for owner in (owners or [uid])]
            row = {key: sum((Decimal(str(item[key])) if key != 'runs' else item[key]) for item in rows)
                   for key in ('runs', 'spent', 'reserved')}
            user = (await (await c.execute('SELECT daily_runs,daily_usd FROM users WHERE id=%s', (uid,))).fetchone())
            return {'limit_mode': LIMIT_MODE, 'runs': row['runs'], 'daily_runs': user['daily_runs'],
                    'runs_exceeded': row['runs'] >= user['daily_runs'],
                    'remaining_runs': max(0,user['daily_runs']-row['runs']),
                    'limit_reached': Decimal(str(row['spent']))+Decimal(str(row['reserved'])) >= Decimal(str(user['daily_usd'])),
                    'resets_at': (datetime.fromtimestamp(self.clock(), timezone(timedelta(hours=9))).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).isoformat()}
