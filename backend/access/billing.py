"""실제 제공자 호출 앞의 최악 비용 예약과 불확실한 응답 보존."""

from decimal import Decimal
from backend.access.context import AccessError


class Meter:
    def __init__(self, access, uid, jid, generation, prices, initial=None):
        self.access, self.uid, self.jid = access, uid, jid
        self.generation, self.prices, self.initial = generation, prices, initial

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
        incoming, outgoing, context, output = self.price(model)
        incoming *= Decimal(str(self.prices[model].get('cache_write_multiplier',1)))
        return ((context * incoming + output * outgoing) / Decimal(1000000)).quantize(Decimal('.00000001'), rounding='ROUND_UP')

    def reserve(self, model):
        self.access.check_execution(self.uid,self.jid,self.generation)
        amount = self.maximum(model)
        if self.initial is not None and self.initial[1] == model:
            ident, _ = self.initial
            self.initial = None
        else:
            ident = self.access.reserve(self.uid, self.jid, self.generation, model, amount)
        self.access.mark_called(ident)
        return ident

    def record_usage(self, ident, model, incoming, outgoing, cached):
        _, _, context, output = self.price(model)
        incoming = incoming if type(incoming) is int and 0 <= incoming <= context else None
        outgoing = outgoing if type(outgoing) is int and 0 <= outgoing <= output else None
        self.access.record_tokens(ident,incoming,outgoing,cached)

    def settle(self, ident, model, result):
        if result is not None:
            self.record_usage(ident,model,result.input_tokens,result.output_tokens,result.cached_tokens)
        # 실패/타임아웃은 제공자의 실제 과금 여부를 추정하지 않는다.
        if result is None or type(result.input_tokens) is not int or type(result.output_tokens) is not int:
            self.access.settle(ident)
            return
        incoming, outgoing, context, output = self.price(model)
        if not 0 <= result.input_tokens <= context or not 0 <= result.output_tokens <= output:
            self.access.settle(ident)
            raise AccessError('제공자 사용량 상한을 확인해야 합니다.', 'unavailable')
        row=self.prices[model]
        if result.input_tokens <= row.get('short_context_tokens',-1):
            incoming=Decimal(str(row['short_input_usd_per_million']))
            outgoing=Decimal(str(row['short_output_usd_per_million']))
        incoming *= Decimal(str(row.get('cache_write_multiplier',1)))
        actual = ((result.input_tokens * incoming + result.output_tokens * outgoing) / Decimal(1000000)).quantize(Decimal('.00000001'), rounding='ROUND_UP')
        self.access.settle(ident, actual, source='calculated')
