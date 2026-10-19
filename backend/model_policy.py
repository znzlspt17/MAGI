"""MAGI의 단일 모델과 보수적인 토큰 비용 정책.

확인일: 2026-10-19 (OpenAI Standard 처리)
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/pricing
캐시 할인은 적용하지 않고 입력 전체에 캐시 쓰기 할증을 적용해 과소 산정을 피한다.
"""
from decimal import Decimal

from backend.errors import MagiError

MODEL = 'gpt-6-luna'
CONTEXT_TOKENS = 1_050_000
MAX_OUTPUT_TOKENS = 128_000
SHORT_CONTEXT_TOKENS = 272_000
SERVICE_TIER = 'default'


def require_model(model: str) -> None:
    if model != MODEL:
        raise MagiError('MAGI는 gpt-6-luna 모델만 지원합니다.')


def default_prices() -> dict:
    """호출자 변경이 전역 정책에 영향을 주지 않는 독립된 비용 자료를 반환한다."""
    return {MODEL: {
        'input_usd_per_million': Decimal('0.20'),
        'output_usd_per_million': Decimal('0.75'),
        'short_input_usd_per_million': Decimal('0.10'),
        'short_output_usd_per_million': Decimal('0.50'),
        'short_context_tokens': SHORT_CONTEXT_TOKENS,
        'cache_write_multiplier': Decimal('1.25'),
        'context_tokens': CONTEXT_TOKENS,
        'max_output_tokens': MAX_OUTPUT_TOKENS,
        'context_limit_verified': True,
    }}
