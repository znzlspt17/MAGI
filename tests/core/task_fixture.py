"""가짜 제공자도 실제 작업 계획 출력 계약을 따르도록 구성한다."""


def with_tasks(value, requirements=None):
    old = value["implementation_order"][0]
    value["implementation_order"] = [
        {
            **old,
            "title": "Implement local persistence",
            "requirement_ids": requirements or ["REQ-001"],
            "depends_on": [],
            "spec_item_ids": [value["architecture"][0]["item_id"]],
            "completion_item_ids": [value["acceptance_criteria"][0]["item_id"]],
        }
    ]
    return value
