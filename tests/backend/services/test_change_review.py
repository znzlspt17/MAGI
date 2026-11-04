"""확인 제안의 폼 검증과 변경 검토 캐시 호환성을 확인한다."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.services import change_review as review
from tests.support.rubric_helpers import Documents


def judgment(**changes):
    value = {"change_id": "C", "meaning": "uncertain", "relation": "unverified",
             "summary": "버전이 미정입니다.", "rationale": "사용자 확인이 필요합니다.",
             "question": "버전을 지정할까요?", "question_form": {
                 "input_type": "single_choice", "options": [
                     {"id": "keep", "label": "미정으로 유지"}, {"id": "set", "label": "버전 지정"}]},
             "evidence": []}
    value.update(changes)
    return review.ChangeResponse.model_validate({"judgments": [value]})


def validate(value):
    return review._validate(value, [{"id": "C"}], [])


def test_choice_question_has_valid_versioned_form():
    result = validate(judgment())["C"]
    form = result["question_form"]
    assert form["question_id"] == "C" and form["question"] == result["question"]
    assert len(form["options"]) == 2 and len(form["form_version"]) == 64
    assert validate(judgment())["C"]["question_form"] == form
    changed = validate(judgment(question="버전을 미정으로 둘까요?"))["C"]["question_form"]
    assert changed["form_version"] != form["form_version"]


def test_text_question_and_no_question():
    assert validate(judgment(question_form={"input_type": "text", "options": []}))["C"]["question_form"]["input_type"] == "text"
    assert validate(judgment(meaning="wording", question="", question_form=None))["C"]["question_form"] is None


@pytest.mark.parametrize("changes", [
    {"question_form": None},
    {"meaning": "wording", "question": "", "question_form": {"input_type": "text"}},
    {"question_form": {"input_type": "single_choice", "options": [{"id": "a", "label": "유지"}]}},
    {"question_form": {"input_type": "single_choice", "options": [{"id": "a", "label": "유지"}, {"id": "a", "label": "변경"}]}},
    {"question_form": {"input_type": "single_choice", "options": [{"id": "a", "label": "유지", "impact": "English only"}, {"id": "b", "label": "변경"}]}},
])
def test_invalid_question_forms_are_rejected(changes):
    with pytest.raises((ValueError, ValidationError)):
        validate(judgment(**changes))


def snapshot(content):
    data = {"content": content, "blocks": review.document_blocks(content), "events": [],
            "requirements": {}, "sources": {}, "answers": [], "revision_history": [], "decisions": {}}
    return {**data, "id": review.digest(data)}


def test_old_cache_version_reuses_original_baseline_and_validates_new_forms(monkeypatch):
    writer = Documents()
    before, after = snapshot("## Version\nUnspecified."), snapshot("## Version\nUnity 6.")
    writer.write_json(f"candidate_snapshots/{before['id']}.json", before)
    writer.write_json(review.LATEST, {"id": after["id"]})
    writer.write_json(review.CURRENT_REVIEW, {"version": 1, "after_id": after["id"], "before_id": before["id"]})
    monkeypatch.setattr(review, "_sources", lambda *_: [])
    def complete(*args, **kwargs):
        change = next(iter(writer.data[path] for path in writer.data if path.startswith("change_reviews/")))["changes"][0]
        value = judgment()
        value.judgments[0].change_id = change["id"]
        return value
    provider = Mock(side_effect=complete)
    monkeypatch.setattr(review, "_complete_once", provider)
    context = SimpleNamespace(writer=writer, provider=None, config=SimpleNamespace(model_routing={"compiler": SimpleNamespace(model="fake")}))
    result = review._review_snapshot(context, {}, after)
    assert result["version"] == 2 and result["before_id"] == before["id"]
    assert result["status"] == "complete" and result["changes"][0]["question_form"]["form_version"]
    assert provider.call_count == 1
    writer.write_json(review.CURRENT_REVIEW, result)
    assert review._review_snapshot(context, {}, after) == result
    assert provider.call_count == 1


def test_invalid_form_marks_analysis_failed_without_raising(monkeypatch):
    writer = Documents()
    before, after = snapshot("Old."), snapshot("New.")
    writer.write_json(f"candidate_snapshots/{before['id']}.json", before)
    writer.write_json(review.LATEST, {"id": before["id"]})
    monkeypatch.setattr(review, "_sources", lambda *_: [])
    def invalid_response(*args, **kwargs):
        change = next(value for path, value in writer.data.items() if path.startswith("change_reviews/"))["changes"][0]
        value = judgment(question_form=None)
        value.judgments[0].change_id = change["id"]
        return value
    monkeypatch.setattr(review, "_complete_once", invalid_response)
    context = SimpleNamespace(writer=writer, provider=None, config=SimpleNamespace(model_routing={"compiler": SimpleNamespace(model="fake")}))
    result = review._review_snapshot(context, {}, after)
    assert result["status"] == "failed" and result["remaining"] == 1
    assert result["changes"][0]["reason"] == "analysis_failed"
