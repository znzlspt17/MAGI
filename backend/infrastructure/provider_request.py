"""현재 입력에만 적용할 모델 지침을 구성한다."""
from hashlib import sha256
import json
from backend.infrastructure.model_policy import POLICY
from backend.infrastructure.output_language import LANGUAGE_RULES


def stage_instructions(messages: list[dict[str, str]], stage: str) -> str:
    version = sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return "\n\n".join([
        f"현재 단계: {stage}. 현재 입력 버전: {version}. "
        "이 단계 지침을 현재 호출에만 적용하고 허용된 출처 참조만 사용하세요. "
        "이전 출력과 대체된 초안은 과거 자료입니다. 현재 출력 스키마만 반환하세요.",
        *(item["content"] for item in messages if item.get("role") in {"system", "developer"}
          and item["content"] != POLICY), LANGUAGE_RULES.get(stage, "")])
