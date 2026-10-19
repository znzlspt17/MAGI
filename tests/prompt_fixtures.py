"""모의 제공자도 실제 모델과 같은 짧은 출처 계약을 사용한다."""

from copy import deepcopy
import json


def model_context(messages, previous=None):
    context = previous if previous is not None else {}
    for message in messages:
        content = message['content']
        if isinstance(content, list):
            content = ''.join(block.get('text', '') for block in content)
        if content.startswith('Canonical context:\n'):
            context.update(json.loads(content.split('\n', 1)[1]))
    return context


def short_sources(value, context):
    aliases = {}
    for ref, item in context.get("sources", {}).items():
        for role in item.get("roles", [item["type"]]):
            if role == "user_answer":
                for question in item.get('questions', [item]):
                    aliases["user_answer:" + question["question_id"]] = ref
            else:
                aliases[role] = ref
    def walk(item, key=""):
        if isinstance(item, list):
            return [walk(child, key) for child in item]
        if isinstance(item, dict):
            return {name: walk(child, name) for name, child in item.items()}
        if key in {"source", "sources", "basis_refs", "conflicting_source"}:
            return aliases.get(item, item)
        return item
    return walk(deepcopy(value))
