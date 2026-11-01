"""현재 입력에만 적용할 모델 지침을 구성한다."""
from hashlib import sha256
import json
from backend.infrastructure.model_policy import POLICY
from backend.infrastructure.output_language import LANGUAGE_RULES


def stage_instructions(messages: list[dict[str, str]], stage: str) -> str:
    version = sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return "\n\n".join([
        f"Current stage: {stage}. Current input version: {version}. "
        "Apply these stage instructions only to this call. Use only the current call's allowed source references; "
        "older outputs and superseded drafts are historical data. Return the current output schema only.",
        *(item["content"] for item in messages if item.get("role") in {"system", "developer"}
          and item["content"] != POLICY), LANGUAGE_RULES.get(stage, "")])
