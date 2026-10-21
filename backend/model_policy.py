"""MAGI의 단일 모델과 보수적인 토큰 비용 정책.

확인일: 2026-10-22 (OpenAI Standard 처리)
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/pricing
예약은 최악 비용으로 유지하고 정산은 관측된 입력 종류별 사용량으로 계산한다.
"""
from decimal import Decimal

from backend.errors import Error

MODEL = 'gpt-6-luna'
CONTEXT_TOKENS = 1_050_000
MAX_OUTPUT_TOKENS = 128_000
SHORT_CONTEXT_TOKENS = 272_000
SERVICE_TIER = 'default'
COST_POLICY = 'luna-standard-2026-10-22-v1'


def require_model(model: str) -> None:
    if model != MODEL:
        raise Error('MAGI는 gpt-6-luna 모델만 지원합니다.')


def default_prices() -> dict:
    """호출자 변경이 전역 정책에 영향을 주지 않는 독립된 비용 자료를 반환한다."""
    return {MODEL: {
        'input_usd_per_million': Decimal('0.20'),
        'output_usd_per_million': Decimal('0.75'),
        'short_input_usd_per_million': Decimal('0.10'),
        'short_output_usd_per_million': Decimal('0.50'),
        'cached_usd_per_million': Decimal('0.02'),
        'short_cached_usd_per_million': Decimal('0.01'),
        'short_context_tokens': SHORT_CONTEXT_TOKENS,
        'cache_write_multiplier': Decimal('1.25'),
        'context_tokens': CONTEXT_TOKENS,
        'max_output_tokens': MAX_OUTPUT_TOKENS,
        'context_limit_verified': True,
    }}
