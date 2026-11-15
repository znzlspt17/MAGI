"""서버에서 검증한 계정의 물리 소유자 접근 범위."""


def owner_ids(actor):
    # 2026-11-13: 브라우저 입력이 아닌 세션 조회 결과만 범위로 사용한다.
    values = actor.get('owner_ids')
    return tuple(values) if values is not None else (actor['id'],)


def can_access(actor, owner_id):
    return bool(actor is None or owner_id in owner_ids(actor))
