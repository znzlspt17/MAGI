"""질문 폼의 호환성, 선택 검증과 실제 파이프라인 저장을 검증한다."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from backend.engine import _validate_answers
from backend.errors import InvalidStateError
from backend.models import AnswerResponse, CompletionResult, InterviewResponse, QuestionFormSpec, MagiState, QAItem
from backend.server.job_manager import JobManager
from backend.services.question_forms import question_form
from backend.services.review_questions import collect_review_questions
from backend.services.saved_answers import saved_answers
from test_review_decisions import engine_for, read_state, korean_decision
from test_sessions import SessionProvider
from backend.models import IssuePacket


def form(kind="single_choice", ident="PRODUCT-003"):
    return question_form(ident, "저장 방식을 선택해주세요.", {"input_type": kind, "options": [{"id": "local", "label": "로컬 저장"}, {"id": "cloud", "label": "클라우드 저장"}]})


def submission(f, **changes):
    return {"question_id": f["question_id"], "question": f["question"], "answer": "화면 표시값", "selected_option_ids": ["local"], "custom_text": None, "form_version": f["form_version"], **changes}


@pytest.mark.parametrize("kind,options", [("single_choice", []), ("multiple_choice", [{"id": "x", "label": "하나"}]), ("text", [{"id": "x", "label": "하나"}]), ("single_choice", [{"id": "x", "label": "하나"}, {"id": "x", "label": "둘"}]), ("single_choice", [{"id": "x", "label": " "}, {"id": "y", "label": "둘"}])])
def test_invalid_provider_forms(kind, options):
    with pytest.raises(ValidationError): QuestionFormSpec(input_type=kind, options=options)


def test_canonical_choices_order_custom_and_saved_metadata():
    f = form("multiple_choice")
    result = _validate_answers([submission(f, selected_option_ids=["cloud", "local"], custom_text="  별도 서버  ")], ["[PRODUCT-003] 질문"], {f["question_id"]: f})[0]
    assert result.answer == "로컬 저장\n클라우드 저장\n  별도 서버  "
    restored = saved_answers({"requirement_lock_sheet": {"user_answers": [result.to_dict()]}})[0]
    assert restored.to_dict() == result.to_dict()
    assert QAItem.from_dict(result.to_dict()).to_dict() == result.to_dict()
    assert "input_type" not in AnswerResponse.model_fields


@pytest.mark.parametrize("changes", [{"selected_option_ids": ["missing"]}, {"selected_option_ids": ["local", "cloud"]}, {"selected_option_ids": ["local", "local"]}, {"form_version": "stale"}, {"custom_text": ""}, {"custom_text": "기타"}, {"selected_option_ids": []}])
def test_invalid_submission_rejected_before_queue(changes):
    f = form(); payload = [submission(f, **changes)]
    before = deepcopy(payload)
    with pytest.raises(ValueError): JobManager._validate_payload("answer", payload, ["[PRODUCT-003] 질문"], {f["question_id"]: f})
    assert payload == before


def test_review_form_stable_until_explicit_reconfirmation():
    value = korean_decision(); value["decision_form"] = {k: form()[k] for k in ("input_type", "options")}
    records, pending = collect_review_questions([IssuePacket.from_dict(value)], {}, 1)
    original = deepcopy(records[0]["form"])
    value["decision_form"] = {"input_type": "text", "options": []}
    records2, _ = collect_review_questions([IssuePacket.from_dict(value)], {"review_questions": records}, 2)
    assert records2[0]["form"] == original
    records3, _ = collect_review_questions([IssuePacket.from_dict(value)], {"review_questions": records, "revision_feedback": "다시 확인"}, 3, reconfirm_keys=[records[0]["decision_key"]])
    assert records3[-1]["form"]["input_type"] == "text"
    assert pending


def test_interview_form_persists_and_invalid_answer_does_not_change_state(tmp_path):
    class Provider(SessionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if kwargs["text_format"] is InterviewResponse and self.calls.count(InterviewResponse) == 1:
                f = form()
                parsed = InterviewResponse.model_validate({**result.parsed.model_dump(), "blocking_questions": [{k: f[k] for k in ("question_id", "question", "input_type", "options")}], "pre_answers": []})
                return CompletionResult(text="", parsed=parsed, response_id=result.response_id)
            return result
    engine = engine_for(Provider())
    assert engine.generate_from_text(text="메모를 저장해주세요", output_dir=str(tmp_path)).status == "NEEDS_USER_INPUT"
    before = read_state(tmp_path); f = next(iter(before["question_forms"].values()))
    assert MagiState.from_dict(before).to_dict()["question_forms"] == before["question_forms"]
    with pytest.raises(InvalidStateError): engine.answer(str(tmp_path), answers=[submission(f, form_version="old")])
    assert read_state(tmp_path) == before
    engine.answer(str(tmp_path), answers=[submission(f)])
    answer = next(a for a in read_state(tmp_path)["requirement_lock_sheet"]["user_answers"] if a["question_id"] == f["question_id"])
    assert answer["answer"] == "로컬 저장"
    assert answer["selection"]["selected_option_ids"] == ["local"]


def test_text_legacy_and_stale_form_versions():
    f = question_form("Q", "설명해주세요.")
    answer = _validate_answers([submission(f, selected_option_ids=[], custom_text="  사용자 원문  ")], ["[Q] 설명해주세요."], {"Q": f})[0]
    assert answer.answer == "  사용자 원문  "
    assert _validate_answers([{"question_id": "Q", "question": "설명해주세요.", "answer": "이전 답변"}], ["[Q] 설명해주세요."])[0].selection is None
    changed = question_form("Q", "질문 변경")
    assert changed["form_version"] != f["form_version"]


def test_history_keeps_question_options():
    from backend.server.execution_history import _safe_result
    f = form()
    result = _safe_result({"blocking_questions": ["[PRODUCT-003] 질문"], "question_forms": {"PRODUCT-003": f}})
    assert result["question_forms"]["PRODUCT-003"] == f
    result["question_forms"]["PRODUCT-003"]["options"].clear()
    assert len(f["options"]) == 2


@pytest.mark.parametrize("kind,ids,custom,expected", [
    ("single_choice", ["local"], None, "로컬 저장"),
    ("multiple_choice", ["cloud", "local"], "추가 조건", "로컬 저장\n클라우드 저장\n추가 조건"),
    ("text", [], "  사용자 원문  ", "  사용자 원문  "),
])
def test_review_pipeline_preserves_selected_answer(tmp_path, kind, ids, custom, expected):
    from test_review_decisions import DecisionProvider
    from backend.models import ReviewResolutionResponse
    spec = {"input_type": kind, "options": [] if kind == "text" else form()["options"]}
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if kwargs["text_format"] is ReviewResolutionResponse:
                for item in result.parsed.resolutions:
                    if item.resolution_kind == "user_decision":
                        item.decision_form = QuestionFormSpec.model_validate(spec)
            return result
    engine = engine_for(Provider([[korean_decision()], []]))
    assert engine.generate_from_text(text="메모를 저장해주세요", output_dir=str(tmp_path)).status == "NEEDS_USER_INPUT"
    before = read_state(tmp_path)
    assert before["awaiting_input_reason"] == "review"
    f = next(iter(before["question_forms"].values()))
    assert f["input_type"] == kind
    result = engine.answer(str(tmp_path), answers=[submission(f, selected_option_ids=ids, custom_text=custom)])
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    state = read_state(tmp_path)
    saved = next(a for a in state["requirement_lock_sheet"]["user_answers"] if a["question_id"] == f["question_id"])
    assert saved["answer"] == expected
    assert state["confirmed_user_sources"]["user_answer:" + f["question_id"]] == expected
