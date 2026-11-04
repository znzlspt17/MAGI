"""저장 기능 구성에서도 같은 트랜잭션 경계를 사용한다."""
from contextlib import contextmanager
from types import SimpleNamespace

from backend.knowledge.store import KnowledgeStore
from backend.knowledge.chunk_search import rank_results
from copy import deepcopy


def test_chunk_reader_uses_shared_read_transaction():
    calls = []

    class Connection:
        def execute(self, sql, params):
            calls.append(params)
            return SimpleNamespace(fetchone=lambda: {"embedding": "[0.5]"})

    @contextmanager
    def transaction(*, mode="write"):
        calls.append(mode)
        yield Connection()

    store = KnowledgeStore(SimpleNamespace(), connect=lambda: None)
    store.transaction = transaction
    assert store.chunk_vector({"input_hash": "hash", "input": "text"}, "model") == [0.5]
    assert calls == ["read", ("hash", "text", "model")]


def test_rank_results_combines_rankings_without_mutating_source_rows():
    first = {"id": "a", "body": "첫 번째", "attrs": {}}
    second = {"id": "b", "body": "두 번째", "attrs": {}}
    lexical, semantic = [first, second], [second]
    before = deepcopy([lexical, semantic])
    result = rank_results(lexical, semantic, public_node=dict, semantic_enabled=True)
    assert [node["id"] for node in result["nodes"]] == ["b", "a"]
    assert result["mode"] == "hybrid"
    result["nodes"][0]["body"] = "표시 변경"
    assert [lexical, semantic] == before
