"""관리자 사용량 조회. 원장의 귀속과 금액 정밀도를 유지한다."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from backend.access.context import AccessError
from backend.access.store import day_at
from backend.access.costs import evidence_status


BASE = """WITH ledger AS (
 SELECT c.*, COALESCE((called_at AT TIME ZONE 'Asia/Seoul')::date::text,day) AS usage_day,
        (called_at IS NOT NULL) AS is_call,
        CASE WHEN state='settled' THEN actual ELSE 0 END AS spent,
        CASE WHEN state<>'settled' THEN reserved ELSE 0 END AS outstanding
 FROM cost_calls c
), filtered AS (
 SELECT * FROM ledger WHERE usage_day >= %s AND usage_day <= %s
 AND (%s::text IS NULL OR user_id=%s) AND (%s::text IS NULL OR job_id=%s)
) """
STATS = """count(*) AS records, count(*) FILTER (WHERE is_call) AS calls,
 count(*) FILTER (WHERE NOT is_call AND reserved_at IS NOT NULL) AS pending_calls,
 count(*) FILTER (WHERE called_at IS NULL AND reserved_at IS NULL) AS unknown_calls,
 COALESCE(sum(spent),0) AS spent, COALESCE(sum(outstanding),0) AS outstanding,
 sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens,
 sum(cached_tokens) AS cached_tokens,
 count(input_tokens) AS input_recorded, count(output_tokens) AS output_recorded,
 count(cached_tokens) AS cached_recorded,
 count(*) FILTER (WHERE (is_call OR reserved_at IS NULL) AND (input_tokens IS NULL OR output_tokens IS NULL)) AS missing_tokens,
 count(*) FILTER (WHERE called_at IS NULL AND reserved_at IS NULL) AS missing_time,
 count(*) FILTER (WHERE state='uncertain') AS uncertain,
 max(COALESCE(called_at,reserved_at)) AS latest_at, max(usage_day) AS latest_day"""


def wire(value):
    if isinstance(value, Decimal):
        return format(value, '.8f')
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [wire(item) for item in value]
    if isinstance(value, dict):
        money = {'spent','outstanding','reserved','actual','limit'}
        counts = {'records','calls','pending_calls','unknown_calls','input_tokens','output_tokens','cached_tokens',
                  'input_recorded','output_recorded','cached_recorded','missing_tokens','missing_time','uncertain'}
        return {key: (format(Decimal(str(item)),'.8f') if key in money and item is not None and not (key=='limit' and type(item) is int)
                      else int(item) if key in counts and item is not None else wire(item))
                for key,item in value.items()}
    return value


def conditions(params, clock):
    today = date.fromisoformat(day_at(clock()))
    start, end = params.get('start', (today-timedelta(days=6)).isoformat()), params.get('end',today.isoformat())
    try:
        if not isinstance(start,str) or not isinstance(end,str):
            raise ValueError()
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat()!=start or last.isoformat()!=end or first>last or (last-first).days>=366:
            raise ValueError()
    except ValueError:
        raise AccessError('조회 기간은 YYYY-MM-DD 형식으로 최대 366일을 선택하세요.', 'invalid') from None
    values = [start,end]
    for key in ('user_id','job_id'):
        value = params.get(key)
        if value == '': value = None
        if value is not None and (not isinstance(value,str) or len(value)>128 or value != value.strip()):
            raise AccessError('사용자·작업 ID를 확인하세요.', 'invalid')
        values.extend([value,value])
    return values


def usage(service, method, params):
    values = conditions(params, service.access.clock)
    with service.store.transaction(mode='read') as c:
        if method=='admin.usage':
            summary = c.execute(BASE+'SELECT '+STATS+' FROM filtered',values).fetchone()
            daily = c.execute(BASE+'SELECT usage_day AS day,'+STATS+' FROM filtered GROUP BY usage_day ORDER BY usage_day',values).fetchall()
            today = day_at(service.access.clock())
            budget = c.execute('SELECT COALESCE(sum(spent),0) AS spent,COALESCE(sum(reserved),0) AS outstanding FROM daily_usage WHERE day=%s',(today,)).fetchone()
            budget.update(day=today,limit=c.execute('SELECT daily_usd FROM service_settings WHERE singleton=1').fetchone()['daily_usd'])
            users = c.execute('SELECT id FROM users UNION SELECT user_id AS id FROM cost_calls ORDER BY id').fetchall()
            return wire({'start':values[0],'end':values[1],'summary':summary,'daily':daily,'today':budget,'users':users})
        group = params.get('group_by','job')
        sort = params.get('sort','cost')
        if not isinstance(group,str) or group not in {'user','job','call'} or not isinstance(sort,str) or sort not in {'cost','recent'}:
            raise AccessError('조회 분류와 정렬을 확인하세요.', 'invalid')
        limit, offset = params.get('limit',25), params.get('offset',0)
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<=10000000:
            raise AccessError('페이지 범위를 확인하세요.', 'invalid')
        if group=='call':
            selection = "SELECT f.*,j.data->>'request' AS request FROM filtered f LEFT JOIN jobs j ON j.id=f.job_id"
            order = 'spent DESC,outstanding DESC,usage_day DESC,id' if sort=='cost' else 'usage_day DESC,called_at DESC NULLS LAST,reserved_at DESC NULLS LAST,id'
        else:
            keys = 'user_id' if group=='user' else 'job_id,user_id'
            grouped = 'SELECT '+keys+','+STATS+' FROM filtered GROUP BY '+keys
            selection = 'SELECT g.* FROM ('+grouped+') g' if group=='user' else "SELECT g.*,j.data->>'request' AS request FROM ("+grouped+") g LEFT JOIN jobs j ON j.id=g.job_id"
            tie = 'user_id' if group=='user' else 'job_id,user_id'
            order = 'spent DESC,outstanding DESC,latest_day DESC,'+tie if sort=='cost' else 'latest_day DESC,latest_at DESC NULLS LAST,'+tie
        total = c.execute(BASE+'SELECT count(*) AS total FROM ('+selection+') results',values).fetchone()['total']
        rows = c.execute(BASE+selection+' ORDER BY '+order+' LIMIT %s OFFSET %s',values+[limit,offset]).fetchall()
        if group=='call':
            for row in rows:
                row['cost_evidence'] = evidence_status(row)
        return wire({'rows':rows,'total':int(total),'limit':limit,'offset':offset,'group_by':group})
