import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.errors import RequirementNormalizationError
from backend.models import InterviewResult
from backend.models import QAItem
from backend.models import RequirementLockSheet
from backend.services.requirement_lock_builder import RequirementLockBuilder
from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS, _assemble_locked_sections
from backend.services.checklist import run_deterministic_checks
from prompt_fixtures import short_sources


def response():
    return {"workflow_constraints": [],
        'mandatory_requirements': [{'id': 'REQ-001', 'text': 'Save notes locally.', 'source': 'user_request'}],
        'constraints': [{'id': 'CON-001', 'text': 'Use Windows.', 'source': 'user_answer:PLATFORM-001'}],
        'non_scope': [{'id': 'NS-001', 'text': 'Cloud sync is excluded.', 'source': 'user_answer:SCOPE-001'}],
        'unresolved_questions': [],
    }


class LockRepairTests(unittest.TestCase):
    def build(self, callback, state=None, answers=None):
        interview = InterviewResult('feature', [], [], pre_answers=answers if answers is not None else [
            QAItem('PLATFORM-001', 'Platform?', 'Windows'), QAItem('SCOPE-001', 'Sync?', 'No cloud')])
        actual = {"user_answer:" + item.question_id: item.answer for item in interview.pre_answers}
        return RequirementLockBuilder().build({"confirmed_user_sources": actual, **(state or {})}, {}, interview, provider_messages_fn=callback)

    def test_categories_sources_and_no_extra_call(self):
        value = response()
        value['mandatory_requirements'][0]['sources'] = ['user_answer:OTHER-001', 'user_feedback']
        callback = Mock(return_value=json.dumps(value))
        self.build(callback, {'revision_feedback': 'Local only'}, [
            QAItem('PLATFORM-001', '', ''), QAItem('SCOPE-001', '', ''), QAItem('OTHER-001', '', '')])
        self.assertEqual(callback.call_count, 1)

    def test_nonbinding_categories_do_not_cover(self):
        for key in ('recommended_requirements', 'optional_requirements'):
            with self.subTest(key=key):
                value = response()
                value[key] = value.pop('constraints')
                callback = Mock(return_value=json.dumps(value))
                with self.assertRaises(RequirementNormalizationError) as caught:
                    self.build(callback)
                self.assertEqual(caught.exception.code, 'SOURCE_COVERAGE_MISSING')
                self.assertEqual(callback.call_count, 4)

    def test_repair_contains_failure_without_duplicate_response(self):
        invalid = response()
        invalid['constraints'] = []
        callback = Mock(side_effect=[json.dumps(invalid), json.dumps(response())])
        self.build(callback)
        payload = callback.call_args.args[0]
        self.assertFalse(any(item["role"] == "assistant" for item in payload))
        self.assertIn('user_answer:PLATFORM-001', payload[-1]['content'])
        self.assertEqual(callback.call_count, 2)

    def test_error_categories_and_mandatory_id_preservation(self):
        cases = []
        bad = response(); bad['mandatory_requirements'] = 'invalid'
        cases.append((bad, {}, 'structure'))
        bad = response(); bad['constraints'][0]['text'] = '윈도우 사용'
        cases.append((bad, {}, 'english_normalization'))
        cases.append((response(), {'requirement_lock_sheet': {"workflow_constraints": [], 'mandatory_requirements': [
            {'id': 'REQ-OLD', 'text': 'Keep me.', 'source': 'user_request'}]}}, 'mandatory_ids'))
        for value, state, category in cases:
            with self.subTest(category=category):
                callback = Mock(return_value=json.dumps(value))
                with self.assertRaises(RequirementNormalizationError) as caught:
                    self.build(callback, state)
                self.assertEqual(caught.exception.category, category)
                self.assertEqual(callback.call_count, 4)

    def test_transport_error_is_not_retried(self):
        callback = Mock(side_effect=ConnectionError('offline'))
        with self.assertRaises(ConnectionError):
            self.build(callback)
        self.assertEqual(callback.call_count, 1)

    def test_logs_do_not_include_response(self):
        callback = Mock(return_value='sensitive user response')
        with self.assertLogs('backend.server', level='WARNING') as logs:
            with self.assertRaises(RequirementNormalizationError):
                self.build(callback)
        self.assertNotIn('sensitive user response', str(logs.output))
        self.assertIn('category=structure', str(logs.output))


class LockedSectionsTests(unittest.TestCase):
    def setUp(self):
        self.sheet = RequirementLockSheet.from_dict(response())
        self.candidate = '\n\n'.join(h + '\n\nOriginal content.' for h in REQUIRED_FINAL_SPEC_HEADINGS)
        self.spec = _assemble_locked_sections(self.candidate, self.sheet)

    def coverage_issues(self, spec):
        return [i for i in run_deterministic_checks(spec, self.sheet) if i.checklist_id.startswith('LOCK-COVER-')]

    def test_all_categories_are_preserved_and_assembly_is_idempotent(self):
        self.assertFalse(self.coverage_issues(self.spec))
        self.assertEqual(self.spec, _assemble_locked_sections(self.spec, self.sheet))
        self.assertIn('### Locked Constraints', self.spec)
        self.assertIn('Violating any', self.spec)
        for items in (self.sheet.mandatory_requirements, self.sheet.constraints, self.sheet.non_scope):
            for item in items:
                self.assertEqual(self.spec.count(f'- [{item.id}] {item.text}'), 1)

    def test_omission_duplication_and_change_block(self):
        for key in ('constraints', 'non_scope'):
            item = getattr(self.sheet, key)[0]
            line = f'- [{item.id}] {item.text}'
            for replacement in ('', line + '\n' + line, f'- [{item.id}] Different decision.'):
                with self.subTest(key=key, replacement=replacement):
                    issues = self.coverage_issues(self.spec.replace(line, replacement))
                    self.assertTrue(any(i.requirement_id == item.id and i.blocking for i in issues))

    def test_empty_categories_preserve_existing_content(self):
        self.sheet.constraints = []
        self.sheet.non_scope = []
        output = _assemble_locked_sections(self.candidate, self.sheet)
        self.assertIn('### 4.2 Out of Scope\n\nNo explicit product exclusions were supplied.', output)
        self.assertIn('## 10. Forbidden Behaviors\n\nOriginal content.', output)

    def test_constraints_must_be_under_forbidden_behaviors(self):
        changed = self.spec.replace('### Locked Constraints', '### Other Heading')
        changed += '\n### Locked Constraints\n- [CON-001] Use Windows.\n'
        self.assertTrue(any(i.requirement_id == 'CON-001' for i in self.coverage_issues(changed)))


class OpenAIWorkflowTests(unittest.TestCase):
    def test_answer_repair_compile_review_and_usage(self):
        from backend.config import MagiConfig
        from backend.engine import MagiSpecEngine
        from backend.providers.llm_provider import OpenAIProvider
        from backend.models import CompletionResult

        from backend.models import InterviewResponse, LockResponse, SpecDraftResponse as SpecResponse, ReviewResponse

        class ScenarioProvider(OpenAIProvider):
            def __init__(self):
                super().__init__(api_key="fake-test-value")
                self.interviews = 0
                self.locks = 0
                self.calls = []
                self.answer_id = None
                self.conversations = 0

            def create_conversation(self):
                self.conversations += 1
                return f"conv_scenario{self.conversations}"

            def complete_result(self, messages, *, model, temperature=None, **kwargs):
                schema = kwargs["text_format"]
                self.calls.append((kwargs.get("conversation_id"), schema))
                if schema is InterviewResponse:
                    self.interviews += 1
                    value = dict(request_type="feature", assumptions=[],
                        blocking_questions=[dict(question_id="PRODUCT-003", question="대상 플랫폼은 무엇인가요?")] if self.interviews == 1 else [],
                        additional_questions=[], pre_answers=[])
                    parsed = schema.model_validate(value)
                elif schema is LockResponse:
                    self.locks += 1
                    if self.locks == 2:
                        assert all(item["role"] != "assistant" for item in messages)
                        assert not any(item["content"].startswith("Canonical context:") for item in messages)
                    value = response()
                    value.update(request_summary="로컬 메모 앱", recommended_requirements=[], optional_requirements=[],
                                 assumptions=[], acceptance_criteria_seed=[], unresolved_questions=[])
                    for message in messages:
                        if message["content"].startswith("Canonical context:"):
                            canonical = json.loads(message["content"].split("\n", 1)[1])
                            self.canonical = canonical
                            self.answer_id = canonical["saved_answers"][0]["question_id"] if canonical["saved_answers"] else None
                    value["constraints"][0]["source"] = "user_answer:" + self.answer_id if self.answer_id else "user_request"
                    value["non_scope"][0]["source"] = "user_request"
                    for key in ("mandatory_requirements", "constraints", "non_scope"):
                        for item in value[key]:
                            item.update(original_text="", sources=["user_feedback"] if self.canonical.get('current_feedback') else [])
                    if self.locks == 1:
                        value["constraints"] = []
                    parsed = schema.model_validate(short_sources(value, self.canonical))
                elif schema is SpecResponse:
                    parsed = schema.model_validate({key: [dict(item_id="ITEM-" + key, text="Save notes locally. Verify local persistence on Windows.",
                        requirement_ids=["REQ-001"] if key == "architecture" else [], decision_ids=[])]
                        for key in schema.model_fields if key != "decisions"})
                else:
                    parsed = ReviewResponse(issues=[])
                return CompletionResult(text="", parsed=parsed, response_id=f"resp_scenario{len(self.calls)}")

        provider = ScenarioProvider()
        config = MagiConfig.default()
        config.web_search = 'off'
        config.project_scan = False
        engine = MagiSpecEngine(config=config, provider=provider)
        with tempfile.TemporaryDirectory() as directory:
            result = engine.generate_from_text(text='Create a local notes app.', output_dir=directory)
            self.assertEqual(result.status, 'NEEDS_USER_INPUT')
            state = json.loads((Path(directory) / 'state/magi_state.json').read_text(encoding='utf-8'))
            question_id = state['blocking_questions'][0].split(']', 1)[0][1:]
            result = engine.answer(directory, answers=[{'question_id': question_id, 'answer': 'Windows'}])
            self.assertEqual(result.status, 'PASS_PENDING_USER_APPROVAL')
            spec = Path(result.approval_candidate_path).read_text(encoding='utf-8')
            self.assertIn('- [CON-001] Use Windows.', spec)
            self.assertIn('- [NS-001] Cloud sync is excluded.', spec)
            usage = json.loads((Path(directory) / 'state/provider_usage.json').read_text(encoding='utf-8'))
            self.assertEqual(len([a for a in usage['attempts'] if a['stage'] == 'requirement_lock']), 2)
            # 새 엔진 인스턴스도 파일에 저장된 연결을 이어간다.
            feedback_path = Path(directory) / "feedback.txt"
            feedback_path.write_text("Keep local Windows persistence.", encoding="utf-8")
            restarted = MagiSpecEngine(config=config, provider=provider)
            revised = restarted.revise(output_dir=directory, feedback_path=str(feedback_path))
            self.assertEqual(revised.status, "PASS_PENDING_USER_APPROVAL")
            result = engine.approve(directory)
            self.assertEqual(result.status, 'FINALIZED')
            self.assertEqual(provider.calls[0][0], "conv_scenario1")
            self.assertEqual([call[0] for call in provider.calls[1:]],
                             ["conv_scenario1"] * (len(provider.calls) - 1))
            fresh = engine.generate_from_text(text="Create another notes app.", output_dir=directory, overwrite=True)
            self.assertEqual(fresh.status, "PASS_PENDING_USER_APPROVAL")
            self.assertEqual(provider.calls[-4][0], "conv_scenario2")



if __name__ == '__main__':
    unittest.main()

