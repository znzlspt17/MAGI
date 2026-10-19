import json
import tempfile
import unittest
from pathlib import Path

from backend.server.execution_history import ExecutionHistory


class WaitingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.history = ExecutionHistory(Path(self.temp.name))

    def wait_stage(self, execution):
        self.history.start_execution("generate", execution)
        self.history.stage(execution, "await_user", "started")
        self.history.stage(execution, "await_user", "completed", result={"blocking_questions": ["질문"]})
        self.history.capture(execution, "await_user", root=self.history.root)
        return self.history.graph()["nodes"][-1]

    def test_terminal_merges_and_preserves_stage(self):
        before = self.wait_stage("first")
        for _ in range(2):
            self.history.terminal("first", "NEEDS_USER_INPUT", result={"blocking_questions": ["최종 질문"]})
        nodes = self.history.graph()["nodes"]
        self.assertEqual(len(nodes), 2)
        after = nodes[-1]
        for key in ("id", "duration_ms", "started_at", "completed_at"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(self.history.detail(after["id"])["result"]["blocking_questions"], ["최종 질문"])

    def test_fallback_is_idempotent_and_executions_remain_separate(self):
        self.wait_stage("first")
        self.history.start_execution("answer", "second")
        for _ in range(2):
            self.history.terminal("second", "NEEDS_USER_INPUT", "대기", result={"blocking_questions": ["다른 질문"]})
        waiting = [n for n in self.history.graph()["nodes"] if n["status"] == "waiting"]
        self.assertEqual([n["execution_id"] for n in waiting], ["first", "second"])

    def test_legacy_projection_preserves_file_and_detail_alias(self):
        stage = self.wait_stage("first")
        data = json.loads(self.history.path.read_text(encoding="utf-8"))
        terminal = {**stage, "id": "old-terminal", "stage": "workflow", "result": {"status": "NEEDS_USER_INPUT", "blocking_questions": ["최종 질문"]}}
        data["nodes"].extend([terminal, {**terminal, "id": "repeat"}])
        self.history.path.write_text(json.dumps(data), encoding="utf-8")
        original = self.history.path.read_bytes()
        self.assertEqual(len(self.history.graph()["nodes"]), 2)
        detail = self.history.detail(stage["id"])
        self.assertEqual(detail, self.history.detail("old-terminal"))
        self.assertEqual(detail["result"]["blocking_questions"], ["최종 질문"])
        self.assertEqual(original, self.history.path.read_bytes())

    def test_other_terminal_states_are_not_merged(self):
        self.wait_stage("first")
        self.history.terminal("first", "error", "실패")
        self.assertEqual(len(self.history.graph()["nodes"]), 3)
        self.assertEqual(self.history.graph()["nodes"][-1]["status"], "failed")
