"""공개 인증 자료와 원자적 실행·비용 원장. 외부 제공자 원문은 저장하지 않는다."""

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from backend.access.context import AccessError


LOGGER = logging.getLogger('backend.server')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def day_at(now):
    return datetime.fromtimestamp(now, timezone(timedelta(hours=9))).date().isoformat()


class AccessStore:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def login(self, subject, pepper, previous=None):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255 or not pepper:
            raise AccessError('로그인 결과를 확인할 수 없습니다.', 'unauthorized')
        hashed = hmac.new(pepper.encode(), ('google\0' + subject).encode(), hashlib.sha256).hexdigest()
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.transaction() as c:
            c.execute('INSERT INTO users(id,subject_hash) VALUES (%s,%s) ON CONFLICT(subject_hash) DO NOTHING', (uuid4().hex, hashed))
            user = c.execute('SELECT * FROM users WHERE subject_hash=%s', (hashed,)).fetchone()
            if user['suspended']:
                raise AccessError('이 계정은 이용할 수 없습니다.')
            if previous:
                c.execute('UPDATE sessions SET revoked=true WHERE hash=%s', (digest(previous),))
            c.execute('INSERT INTO sessions(hash,user_id,csrf,expires_at) VALUES (%s,%s,%s,%s)',
                      (digest(sid), user['id'], csrf, self.clock() + 86400))
        return sid

    def session(self, sid):
        if not isinstance(sid, str) or not 20 <= len(sid) <= 200:
            raise AccessError('로그인이 필요합니다.', 'unauthorized')
        with self.store.transaction(mode='read') as c:
            row = c.execute('SELECT u.*,s.csrf,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id '
                            'WHERE s.hash=%s AND NOT s.revoked AND NOT u.suspended AND s.expires_at>%s',
                            (digest(sid), self.clock())).fetchone()
        if not row:
            raise AccessError('로그인이 필요합니다.', 'unauthorized')
        return dict(row)

    def logout(self, sid):
        with self.store.transaction() as c:
            c.execute('UPDATE sessions SET revoked=true WHERE hash=%s', (digest(sid),))

    def session_for_worker(self, uid):
        with self.store.transaction(mode='read') as c:
            row = c.execute('SELECT id,role,suspended FROM users WHERE id=%s',(uid,)).fetchone()
        if not row:
            raise AccessError('작업 소유자를 확인할 수 없습니다.', 'unauthorized')
        return dict(row)

    def throttle(self, uid):
        with self.store.transaction() as c:
            minute=int(self.clock()//60)
            c.execute('DELETE FROM request_windows WHERE minute<%s',(minute-1,))
            row=c.execute('INSERT INTO request_windows(identity,minute,calls) VALUES (%s,%s,1) '
                          'ON CONFLICT(identity) DO UPDATE SET minute=EXCLUDED.minute,calls=CASE WHEN request_windows.minute=EXCLUDED.minute THEN request_windows.calls+1 ELSE 1 END RETURNING calls',
                          (uid,minute)).fetchone()
            calls=row['calls']
        if calls>180:
            raise AccessError('요청이 너무 많습니다. 잠시 후 다시 시도하세요.', 'quota')

    def begin_login(self):
        state, browser, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        with self.store.transaction() as c:
            c.execute('DELETE FROM login_states WHERE expires_at<%s', (self.clock(),))
            c.execute('INSERT INTO login_states VALUES (%s,%s,%s,%s,%s)',
                      (digest(state), digest(browser), nonce, verifier, self.clock() + 300))
        return state, browser, nonce, verifier

    def consume_login(self, state, browser):
        if not state or not browser:
            raise AccessError('로그인 요청이 만료되었습니다.', 'unauthorized')
        with self.store.transaction() as c:
            row = c.execute('DELETE FROM login_states WHERE hash=%s AND browser_hash=%s AND expires_at>%s RETURNING nonce,verifier',
                            (digest(state), digest(browser), self.clock())).fetchone()
        if not row:
            raise AccessError('로그인 요청이 만료되었습니다.', 'unauthorized')
        return row

    def lease(self, c):
        row = dict(c.execute('SELECT * FROM service_lease WHERE singleton=1 FOR UPDATE').fetchone())
        if row['phase'] == 'waiting' and row['deadline'] <= self.clock():
            self.clear(c)
            row.update(owner_id=None, job_id=None, phase='idle', deadline=None)
        return row

    @staticmethod
    def clear(c):
        c.execute("UPDATE service_lease SET owner_id=NULL,job_id=NULL,phase='idle',deadline=NULL,stopping=false WHERE singleton=1")

    def acquire(self, c, uid, jid, *, count=False, initial=Decimal('0')):
        lease = self.lease(c)
        if lease['phase'] != 'idle' and (lease['owner_id'] != uid or lease['job_id'] != jid or lease['phase'] != 'waiting'):
            raise AccessError('다른 작업이 사용 중입니다. 잠시 후 다시 시도하세요.', 'busy')
        user = c.execute('SELECT * FROM users WHERE id=%s AND NOT suspended', (uid,)).fetchone()
        if not user:
            raise AccessError('이 계정은 이용할 수 없습니다.', 'unauthorized')
        day = day_at(self.clock())
        usage = self._usage(c, day, uid)
        if count and usage['runs'] >= user['daily_runs']:
            raise AccessError('오늘 실행 횟수를 모두 사용했습니다.', 'quota')
        self.check_money(c, uid, initial, day)
        if count:
            c.execute('UPDATE daily_usage SET runs=runs+1 WHERE day=%s AND user_id=%s', (day, uid))
        c.execute("UPDATE service_lease SET owner_id=%s,job_id=%s,phase='running',deadline=NULL,stopping=false,generation=generation+1 WHERE singleton=1",
                  (uid, jid))
        return c.execute('SELECT generation FROM service_lease WHERE singleton=1').fetchone()['generation']

    def _usage(self, c, day, uid):
        c.execute('INSERT INTO daily_usage(day,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (day, uid))
        return c.execute('SELECT * FROM daily_usage WHERE day=%s AND user_id=%s FOR UPDATE', (day, uid)).fetchone()

    def check_money(self, c, uid, amount, day):
        user = c.execute('SELECT daily_usd FROM users WHERE id=%s', (uid,)).fetchone()
        usage = self._usage(c, day, uid)
        total = c.execute('SELECT COALESCE(sum(spent+reserved),0) AS amount FROM daily_usage WHERE day=%s', (day,)).fetchone()['amount']
        cap = c.execute('SELECT daily_usd FROM service_settings WHERE singleton=1').fetchone()['daily_usd']
        if Decimal(str(usage['spent'])) + Decimal(str(usage['reserved'])) + amount > Decimal(str(user['daily_usd'])) or Decimal(str(total)) + amount > Decimal(str(cap)):
            raise AccessError('오늘 API 비용 한도에 도달했습니다.', 'quota')

    def reserve(self, uid, jid, generation, model, amount):
        with self.store.transaction() as c:
            lease = self.lease(c)
            if lease['owner_id'] != uid or lease['job_id'] != jid or lease['generation'] != generation or lease['phase'] != 'running' or lease['stopping']:
                raise AccessError('작업 사용권이 종료되었습니다.', 'busy')
            if not c.execute('SELECT id FROM users WHERE id=%s AND NOT suspended',(uid,)).fetchone():
                raise AccessError('이 계정은 이용할 수 없습니다.')
            day = day_at(self.clock())
            self.check_money(c, uid, amount, day)
            ident = uuid4().hex
            c.execute('UPDATE daily_usage SET reserved=reserved+%s WHERE day=%s AND user_id=%s', (amount, day, uid))
            c.execute('INSERT INTO cost_calls(id,day,user_id,job_id,model,reserved,reserved_at) VALUES (%s,%s,%s,%s,%s,%s,to_timestamp(%s))',
                      (ident, day, uid, jid, model, amount, self.clock()))
        return ident

    def check_execution(self, uid, jid, generation):
        with self.store.transaction() as c:
            lease=self.lease(c)
            if lease['owner_id']!=uid or lease['job_id']!=jid or lease['generation']!=generation or lease['phase']!='running' or lease['stopping']:
                raise AccessError('작업 사용권이 종료되었습니다.', 'busy')
            if not c.execute('SELECT id FROM users WHERE id=%s AND NOT suspended',(uid,)).fetchone():
                raise AccessError('이 계정은 이용할 수 없습니다.')

    def mark_called(self, ident):
        with self.store.transaction() as c:
            c.execute('UPDATE cost_calls SET called_at=COALESCE(called_at,to_timestamp(%s)) WHERE id=%s',
                      (self.clock(),ident))

    def record_tokens(self, ident, incoming, outgoing, cached, written=None, write_30m=None, write_12h=None, *, policy=None):
        # 누락·잘못된 값은 0으로 채우지 않고 관측한 값만 저장한다.
        incoming = incoming if type(incoming) is int and incoming >= 0 else None
        outgoing = outgoing if type(outgoing) is int and outgoing >= 0 else None
        cached = cached if type(cached) is int and incoming is not None and 0 <= cached <= incoming else None
        # 관계가 잘못된 양수도 그대로 보존해 재산정에서 불일치를 감지한다.
        writes = [value if type(value) is int and 0 <= value <= 2**63-1 else None
                  for value in (written,write_30m,write_12h)]
        with self.store.transaction() as c:
            c.execute('UPDATE cost_calls SET input_tokens=%s,output_tokens=%s,cached_tokens=%s,cache_write_tokens=%s,cache_write_30m_tokens=%s,cache_write_12h_tokens=%s,cost_policy=%s WHERE id=%s',
                      (incoming,outgoing,cached,*writes,policy,ident))

    def settle(self, ident, actual=None, *, source='calculated', policy=None):
        with self.store.transaction() as c:
            row = c.execute('SELECT * FROM cost_calls WHERE id=%s FOR UPDATE', (ident,)).fetchone()
            if not row or row['state'] == 'settled':
                return
            if actual is None:
                c.execute("UPDATE cost_calls SET state='uncertain' WHERE id=%s", (ident,))
                return
            if actual < 0 or actual > Decimal(str(row['reserved'])):
                c.execute("UPDATE cost_calls SET state='uncertain' WHERE id=%s", (ident,))
                raise AccessError('비용 산정을 확인해야 합니다.', 'unavailable')
            c.execute('UPDATE daily_usage SET reserved=reserved-%s,spent=spent+%s WHERE day=%s AND user_id=%s',
                      (row['reserved'], actual, row['day'], row['user_id']))
            c.execute("UPDATE cost_calls SET actual=%s,state='settled',settled_at=to_timestamp(%s),settlement_source=%s,cost_policy=%s WHERE id=%s",
                      (actual,self.clock(),source,policy,ident))

    def finish(self, jid, generation, waiting=False):
        with self.store.transaction() as c:
            row = self.lease(c)
            if row['job_id'] != jid or row['generation'] != generation:
                return
            uncertain=c.execute("SELECT count(*) AS count FROM cost_calls WHERE job_id=%s AND state='uncertain'",(jid,)).fetchone()['count']
            # 비용 예약은 유지하고, 종료가 확인된 실행의 사용권만 정상적으로 반환한다.
            if waiting and not row['stopping']:
                c.execute("UPDATE service_lease SET phase='waiting',deadline=%s WHERE singleton=1", (self.clock()+180,))
            else:
                self.clear(c)
        if uncertain:
            LOGGER.warning('billing settlement pending job_id=%s count=%s', jid, uncertain)

    def status(self, uid):
        with self.store.transaction() as c:
            row = self.lease(c)
            return {'busy': row['phase'] != 'idle', 'mine': row['owner_id'] == uid, 'phase': row['phase'],
                    'deadline': row['deadline'] if row['owner_id'] == uid else None,
                    'recovering': row['phase'] == 'recovery'}

    def usage(self, uid):
        with self.store.transaction() as c:
            row = self._usage(c, day_at(self.clock()), uid)
            user = c.execute('SELECT daily_runs,daily_usd FROM users WHERE id=%s', (uid,)).fetchone()
            return {'runs': row['runs'], 'remaining_runs': max(0,user['daily_runs']-row['runs']),
                    'limit_reached': Decimal(str(row['spent']))+Decimal(str(row['reserved'])) >= Decimal(str(user['daily_usd'])),
                    'resets_at': (datetime.fromtimestamp(self.clock(), timezone(timedelta(hours=9))).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).isoformat()}
