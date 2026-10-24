"""웹 실행에서 실제로 사용하는 모델과 검토 한도."""

from dataclasses import dataclass, field
from backend.errors import Error
from backend.models import ModelRoute
from backend.model_policy import MODEL, require_model

AGENT_KEYS = ("planner", "interviewer", "critic", "compiler")


@dataclass(slots=True)
class Config:
    model_routing: dict[str, ModelRoute] = field(
        default_factory=lambda: {
            key: ModelRoute(provider="openai", model=MODEL) for key in AGENT_KEYS
        }
    )
    max_critic_passes: int = 3

    def validate(self):
        if set(self.model_routing) != set(AGENT_KEYS):
            raise Error("작업별 모델 설정을 확인하세요.")
        for route in self.model_routing.values():
            if route.provider != "openai":
                raise Error("지원하지 않는 모델 제공자입니다.")
            require_model(route.model)
        if not 1 <= self.max_critic_passes <= 3:
            raise Error("검토 한도는 1~3회여야 합니다.")
