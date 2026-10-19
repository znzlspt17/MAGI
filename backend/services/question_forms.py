"""사용자 질문 폼의 검증, 버전 및 답변 정규화."""
import hashlib
import json
from backend.models import QuestionFormSpec


def question_form(question_id, question, value=None):
    spec = QuestionFormSpec.model_validate(value or {}).model_dump()
    form = {"question_id": question_id, "question": question, **spec}
    form["form_version"] = hashlib.sha256(json.dumps(form, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return form


def selected_answer(item, form):
    if item.get("form_version") != form["form_version"]:
        raise ValueError("질문이 변경되었습니다. 최신 질문을 확인해주세요.")
    ids, custom = item.get("selected_option_ids", []), item.get("custom_text")
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("선택 항목이 올바르지 않습니다.")
    allowed = {o["id"] for o in form["options"]}
    if not set(ids) <= allowed or (form["input_type"] == "text" and ids):
        raise ValueError("현재 질문에 없는 선택 항목입니다.")
    if custom is not None and (not isinstance(custom, str) or not custom.strip()):
        raise ValueError("직접 입력 내용을 작성해주세요.")
    if form["input_type"] == "single_choice" and len(ids) + (custom is not None) != 1:
        raise ValueError("한 가지 답변을 선택해주세요.")
    ordered = [o for o in form["options"] if o["id"] in ids]
    answer = "\n".join([o["label"] for o in ordered] + ([custom] if custom is not None else []))
    if len(answer) > 20000:
        raise ValueError("답변은 20,000자 이내로 입력해주세요.")
    if not answer.strip():
        raise ValueError("답변을 선택하거나 입력해주세요.")
    return answer, {"selected_option_ids": [o["id"] for o in ordered], "custom_text": custom, "form_version": form["form_version"]}
