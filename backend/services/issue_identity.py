"""검토·보완·진단이 공유하는 결함 식별 규칙."""


def decision_key(requirement_id: str | None, topic: str) -> str:
    return (requirement_id or "structure") + ":" + topic.casefold()


def defect_key(requirement_id: str | None, topic: str, checklist_id: str) -> str:
    return decision_key(requirement_id, topic) + ":" + checklist_id.casefold()
