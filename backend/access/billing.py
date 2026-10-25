"""실제 제공자 호출 앞의 최악 비용 예약과 불확실한 응답 보존."""

from decimal import Decimal
from backend.access.context import AccessError
from backend.access.costs import TOKEN_FIELDS, calculate_cost, usage_problem
from backend.model_policy import COST_POLICY


class Meter:
    def __init__(self, access, uid, jid, generation, prices, initial=None, *, execution_id):
        self.access, self.uid, self.jid = access, uid, jid
        self.generation, self.prices, self.initial = generation, prices, initial
        self.execution_id = execution_id

    def price(self, model):
        try:
            row = self.prices[model]
            incoming, outgoing = Decimal(str(row['input_usd_per_million'])), Decimal(str(row['output_usd_per_million']))
            context, output = row['context_tokens'], row['max_output_tokens']
            # context_tokens는 임의 요청 예산이 아닌 제공자가 보장하는 모델 전체 문맥 상한이다.
            if not row.get('context_limit_verified') or not incoming.is_finite() or not outgoing.is_finite() or incoming <= 0 or outgoing <= 0 or type(context) is not int or type(output) is not int or not 1 <= output < context:
                raise ValueError()
            return incoming, outgoing, context, output
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise AccessError('모델 단가와 검증된 문맥 상한을 설정해야 합니다.', 'configuration') from None

    def maximum(self, model):
        try:
            return self._maximum(model)
        except (AccessError, KeyError, ValueError, TypeError, ArithmeticError):
            return None

    def _maximum(self, model):
        incoming, outgoing, context, output = self.price(model)
        incoming *= Decimal(str(self.prices[model].get('cache_write_multiplier',1)))
        if not incoming.is_finite() or incoming <= 0:
            raise ValueError()
        return ((context * incoming + output * outgoing) / Decimal(1000000)).quantize(Decimal('.00000001'), rounding='ROUND_UP')

    def reserve(self, model):
        self.access.check_execution(self.uid,self.jid,self.generation,self.execution_id)
        amount = self.maximum(model)
        if self.initial is not None and self.initial[1] == model:
            ident, _ = self.initial
            self.initial = None
        else:
            ident = self.access.reserve(self.uid, self.jid, self.generation, model, amount, execution_id=self.execution_id)
        self.access.mark_called(ident, generation=self.generation, execution_id=self.execution_id)
        return ident

    def record_usage(self, ident, model, incoming, outgoing, cached, written=None, write_30m=None, write_12h=None):
        incoming = incoming if type(incoming) is int and 0 <= incoming <= 2**63-1 else None
        outgoing = outgoing if type(outgoing) is int and 0 <= outgoing <= 2**63-1 else None
        self.access.record_tokens(ident,incoming,outgoing,cached,written,write_30m,write_12h,policy=COST_POLICY, generation=self.generation, execution_id=self.execution_id)

    def settle(self, ident, model, result):
        if result is not None:
            self.record_usage(ident,model,result.input_tokens,result.output_tokens,result.cached_tokens,
                              result.cache_write_tokens,result.cache_write_30m_tokens,result.cache_write_12h_tokens)
        # 실패/타임아웃은 제공자의 실제 과금 여부를 추정하지 않는다.
        if result is None or type(result.input_tokens) is not int or type(result.output_tokens) is not int:
            self.access.settle(ident, generation=self.generation, execution_id=self.execution_id)
            return
        usage = {key: getattr(result,key) for key in TOKEN_FIELDS}
        try:
            self.price(model)
            actual = None if usage_problem(usage,self.prices[model]) else calculate_cost(usage,self.prices[model])
            if actual is not None and (not actual.is_finite() or actual < 0):
                actual = None
        except (AccessError, KeyError, ValueError, TypeError, ArithmeticError):
            actual = None
        if actual is None:
            self.access.settle(ident, generation=self.generation, execution_id=self.execution_id)
            return
        self.access.settle(ident, actual, source='calculated', policy=COST_POLICY, generation=self.generation, execution_id=self.execution_id)
