"""관측된 사용량만으로 자동 정산 기록을 검토하고 원장을 함께 보정한다."""

from collections import Counter
from datetime import date
from decimal import Decimal
from uuid import uuid4

from backend.access.context import AccessError
from backend.access.costs import calculate_cost, usage_problem
from backend.model_policy import COST_POLICY, MODEL, default_prices


def validate_scope(job_id=None, start=None, end=None):
    if not job_id and not (start and end):
        raise ValueError('작업 ID 또는 시작일·종료일을 지정하세요.')
    if job_id is not None and (not isinstance(job_id,str) or not job_id.strip() or job_id != job_id.strip() or len(job_id)>128):
        raise ValueError('작업 ID를 확인하세요.')
    if start is not None or end is not None:
        try:
            first, last = date.fromisoformat(start),date.fromisoformat(end)
            if first.isoformat()!=start or last.isoformat()!=end or first>last:
                raise ValueError()
        except (ValueError,TypeError):
            raise ValueError('시작일·종료일은 YYYY-MM-DD 순서로 함께 지정하세요.') from None


def reprice_costs(store, *, job_id=None, start=None, end=None, apply=False):
    """호출자는 운영 프로세스 잠금을 소유해야 한다. 미리보기는 읽기 전용이다."""
    validate_scope(job_id,start,end)
    with store.transaction(mode='write' if apply else 'read') as c:
        rows = c.execute("""SELECT * FROM cost_calls
            WHERE (%s::text IS NULL OR job_id=%s)
            AND (%s::text IS NULL OR COALESCE((called_at AT TIME ZONE 'Asia/Seoul')::date::text,day)>=%s)
            AND (%s::text IS NULL OR COALESCE((called_at AT TIME ZONE 'Asia/Seoul')::date::text,day)<=%s)
            ORDER BY day,user_id,id""" + (' FOR UPDATE' if apply else ''),
            (job_id,job_id,start,start,end,end)).fetchall()
        report, changes = [], []
        for row in rows:
            reason = None
            if row['state'] != 'settled':
                reason = 'not_settled'
            elif row['settlement_source'] != 'calculated':
                reason = 'not_automatic'
            elif row['model'] != MODEL or row['cost_policy'] not in (None,COST_POLICY):
                reason = 'unsupported_policy'
            else:
                reason = usage_problem(row,default_prices()[MODEL])
            item = {'id':row['id'],'status':reason}
            if reason is None:
                actual = calculate_cost(row)
                old = Decimal(str(row['actual'])) if row['actual'] is not None else None
                if old is None or not old.is_finite() or old < 0 or actual > Decimal(str(row['reserved'])):
                    item['status'] = 'invalid_amount'
                elif old == actual and row['cost_policy'] == COST_POLICY:
                    item['status'] = 'unchanged'
                else:
                    item.update(status='eligible',before=format(old,'.8f'),after=format(actual,'.8f'),
                                before_policy=row['cost_policy'],after_policy=COST_POLICY)
                    changes.append((row,actual,item))
            report.append(item)
        if apply:
            # 원장과 집계의 불일치를 숨기지 않고 처리 전체를 롤백한다.
            for day,uid in sorted({(row['day'],row['user_id']) for row,_,_ in changes}):
                daily = c.execute('SELECT spent FROM daily_usage WHERE day=%s AND user_id=%s FOR UPDATE',(day,uid)).fetchone()
                ledger = c.execute("SELECT COALESCE(sum(actual),0) AS spent FROM cost_calls WHERE day=%s AND user_id=%s AND state='settled'",(day,uid)).fetchone()
                if daily is None or Decimal(str(daily['spent'])) != Decimal(str(ledger['spent'])):
                    raise AccessError('원장과 일일 집계가 일치하지 않아 보정을 중단했습니다.','invalid')
            for row,actual,item in changes:
                c.execute('UPDATE cost_calls SET actual=%s,cost_policy=%s WHERE id=%s',(actual,COST_POLICY,row['id']))
                c.execute('UPDATE daily_usage SET spent=spent+%s WHERE day=%s AND user_id=%s',
                          (actual-Decimal(str(row['actual'])),row['day'],row['user_id']))
                c.execute("INSERT INTO admin_audit(id,actor_id,action,target_id,details) VALUES (%s,'operator','reprice-cost',%s,%s)",
                          (uuid4().hex,row['id'],store._json(item)))
        counts = dict(Counter(item['status'] for item in report))
        return {'mode':'apply' if apply else 'preview','rows':report,'counts':counts,
                'eligible':len(changes),'applied':len(changes) if apply else 0,
                'excluded':sum(n for status,n in counts.items() if status not in {'eligible','unchanged'})}
