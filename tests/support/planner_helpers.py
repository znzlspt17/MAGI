"""여러 테스트에서 공유하는 검증용 도우미."""

from backend.pipeline.planner import PlannerDecision


def decision(action):
    return PlannerDecision(goal="게임 명세 확정", tasks=[], action=action, target="조작 키 배치",
                           input_refs=[], expected_result="사용자 결정 확인", reason="키 배치 결정이 필요합니다.",
                           affected_requirement_ids=[])
