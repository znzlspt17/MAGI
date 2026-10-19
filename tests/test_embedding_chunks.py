"""청킹과 출처, 단일 추론, 잠금의 동작 회귀 검증."""

import subprocess
import sys

from backend.knowledge.chunking import chunks
from backend.knowledge.chunk_search import merge_matches
from backend.knowledge.embedding import LocalEmbedding
from backend.knowledge import model_lock
from test_knowledge import Tokenizer


def test_windows_preserve_all_source_text_and_overlap_without_stalling():
    body = "## 제목\n\n" + ("한국어 English 문장입니다. 다음 문장입니다!\n\n" * 60) + "```md\n## 가짜 제목\n" + "x" * 1200 + "\n```\n끝"
    node = {"id": "n", "kind": "spec", "body": body, "attrs": {"section": "설계"}}
    result = list(chunks(node, Tokenizer()))
    covered, last_end = set(), 0
    for chunk in result:
        span = chunk["source_ranges"][0]
        assert span["end"] > last_end
        assert span["start"] <= last_end
        if last_end:
            assert last_end - span["start"] <= 96
        assert chunk["body"] == body[span["start"]:span["end"]]
        assert len(Tokenizer().encode(chunk["input"], add_special_tokens=True)) <= 512
        covered.update(range(span["start"], span["end"]))
        last_end = span["end"]
    assert covered == set(range(len(body)))
    assert result == list(chunks(node, Tokenizer()))


def test_short_requirement_and_decision_fields_keep_separate_sources():
    node = {"id": "n", "kind": "requirement", "body": "짧은 요구사항", "attrs": {}}
    assert len(list(chunks(node, Tokenizer()))) == 1
    node.update(kind="decision", attrs={"rationale": "이유", "conditions": "조건"})
    result = list(chunks(node, Tokenizer()))
    assert [c["source_ranges"][0]["field"] for c in result] == ["body", "rationale", "conditions"]
    assert [c["ordinal"] for c in result] == [0, 1, 2]


def test_short_key_paragraph_after_long_paragraph_is_not_diluted():
    tail = "원본 파일을 보존하고 미리보기 후 DB로 이관한다."
    node = {"id": "n", "kind": "spec", "body": "일반적인 안내 문장. " * 100 + "\n\n" + tail, "attrs": {}}
    result = list(chunks(node, Tokenizer()))
    assert result[-1]["body"] == tail
    assert result[-1]["source_ranges"][0]["start"] == node["body"].index(tail)


def test_overlap_quotes_merge_using_original_field():
    row = {"body": "abcdefghij", "attrs": {}}
    matches = [{"chunk_id": "a", "quote": "abcdef", "source_ranges": [{"field": "body", "start": 0, "end": 6}]},
               {"chunk_id": "b", "quote": "efghij", "source_ranges": [{"field": "body", "start": 4, "end": 10}]}]
    merged = merge_matches(row, matches)
    assert len(merged) == 1 and merged[0]["quote"] == row["body"]
    assert merged[0]["chunk_ids"] == ["a", "b"]


def test_context_keeps_match_tail_instead_of_original_prefix():
    from backend.knowledge.runtime import KnowledgeService
    from test_knowledge import MemoryStore
    quote = "검색된 긴 문맥 " * 200 + "마지막핵심조건"
    record = {"id": "n", "project_id": "p", "job_id": "j", "kind": "spec", "active": True,
              "body": "관련 없는 앞부분", "attrs": {"scope": "product"}}
    class Store(MemoryStore):
        def graph(self, **kwargs): return {"nodes": [], "edges": []}
        def node_records(self, identities): return {"n": record}
    service = KnowledgeService(Store(), LocalEmbedding(None))
    service.search = lambda query, **kwargs: {"mode": "hybrid", "nodes": [{**record, "matches": [
        {"chunk_id": "c", "quote": quote, "source_ranges": [{"field": "body", "start": 9000, "end": 10000}]}]}]}
    try:
        assert service.context("마지막핵심조건")["nodes"][0]["body"] == quote
    finally:
        service.close()


def test_model_lock_excludes_other_process_and_releases(tmp_path):
    class Owner: pass
    owner = Owner()
    path = str(tmp_path / "model.lock")
    model_lock.acquire(owner, path)
    script = "from backend.knowledge import model_lock; from backend.knowledge.config import KnowledgeError\nclass Owner: pass\no=Owner()\ntry: model_lock.acquire(o)\nexcept KnowledgeError: print('busy')\nelse: model_lock.release(o); print('ready')"
    script = script.replace("model_lock.acquire(o)", "model_lock.acquire(o, " + repr(path) + ")")
    try:
        assert subprocess.check_output([sys.executable, "-c", script], text=True).strip() == "busy"
    finally:
        model_lock.release(owner)
    assert subprocess.check_output([sys.executable, "-c", script], text=True).strip() == "ready"
