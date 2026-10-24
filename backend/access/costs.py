"""실시간 정산의 사용량 검증·계산과 근거 분류."""

from decimal import Decimal, ROUND_UP

from backend.model_policy import COST_POLICY, MODEL, default_prices


TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens',
                'cache_write_30m_tokens', 'cache_write_12h_tokens')


def usage_problem(usage, prices):
    values = [usage.get(key) for key in TOKEN_FIELDS]
    if any(value is None for value in values):
        return 'missing_usage'
    if any(type(value) is not int or value < 0 for value in values):
        return 'invalid_usage'
    incoming, outgoing, cached, written, short_write, long_write = values
    if (incoming > prices['context_tokens'] or outgoing > prices['max_output_tokens']
            or cached + written > incoming or short_write + long_write != written):
        return 'invalid_usage'
    return None


def calculate_cost(usage, prices=None):
    prices = default_prices()[MODEL] if prices is None else prices
    if usage_problem(usage, prices):
        raise ValueError('정산에 필요한 사용량이 불완전합니다.')
    prefix = 'short_' if usage['input_tokens'] <= prices['short_context_tokens'] else ''
    incoming = Decimal(str(prices[prefix + 'input_usd_per_million']))
    outgoing = Decimal(str(prices[prefix + 'output_usd_per_million']))
    cached = Decimal(str(prices[prefix + 'cached_usd_per_million']))
    ordinary = usage['input_tokens'] - usage['cached_tokens'] - usage['cache_write_tokens']
    total = (ordinary * incoming + usage['cached_tokens'] * cached
             + usage['cache_write_30m_tokens'] * incoming * Decimal('1.25')
             + usage['cache_write_12h_tokens'] * incoming * Decimal('2.5')
             + usage['output_tokens'] * outgoing)
    return (total / Decimal(1000000)).quantize(Decimal('.00000001'), rounding=ROUND_UP)


def evidence_status(row):
    if row.get('settlement_source') == 'manual':
        return 'manual'
    if row.get('cost_policy') != COST_POLICY or row.get('model') != MODEL:
        return 'unknown'
    return usage_problem(row, default_prices()[MODEL]) or 'complete'
