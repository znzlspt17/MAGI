"""테스트 전용 DB에서 한국어 저장과 기존 검색 연산을 확인한다."""

import json
from backend.services.document_hash import source_key


def test_korean_text_json_and_search_roundtrip(store):
    original = "한국어 메모를 저장한다. API `/items` 값 10%"
    with store.transaction() as conn:
        encoding = conn.execute("SHOW server_encoding").fetchone()
        client = conn.execute("SHOW client_encoding").fetchone()
        assert next(iter(encoding.values())).upper() == "UTF8"
        assert next(iter(client.values())).upper() == "UTF8"
        conn.execute("CREATE TEMPORARY TABLE korean_storage_test (body text, payload jsonb)")
        conn.execute("INSERT INTO korean_storage_test (body, payload) VALUES (%s, %s::jsonb)",
                     (original, json.dumps({"문서": original}, ensure_ascii=False)))
        row = conn.execute("SELECT body, payload, body ILIKE %s AS substring_match, "
                           "to_tsvector('simple', body) @@ plainto_tsquery('simple', %s) AS lexical_match "
                           "FROM korean_storage_test", ("%메모%", "메모를")).fetchone()
        assert row["body"] == original
        assert row["payload"]["문서"] == original
        assert row["substring_match"] and row["lexical_match"]
        similarity = conn.execute("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector AS distance").fetchone()
        assert similarity["distance"] == 0
        conn.execute("INSERT INTO projects(id,name) VALUES (%s,%s)", ("p", "한국어 저장"))
        conn.execute("INSERT INTO jobs(id,project_id,data) VALUES (%s,%s,%s::jsonb)",
                     ("j", "p", json.dumps({"요청": original}, ensure_ascii=False)))
    documents = store.documents("j")
    documents.write_text("final/FINAL_AGENT_SPEC.md", original)
    assert documents.read_text("final/FINAL_AGENT_SPEC.md") == original
    assert source_key(documents.read_text("final/FINAL_AGENT_SPEC.md")) == source_key(original)


def test_korean_node_search_uses_existing_text_and_hybrid_paths(store):
    text = "사용자는 한국어 메모를 로컬에 저장한다."
    with store.transaction() as conn:
        conn.execute("INSERT INTO projects(id,name) VALUES (%s,%s)", ("p", "한국어 검색"))
        conn.execute("INSERT INTO jobs(id,project_id,data) VALUES (%s,%s,%s::jsonb)", ("j", "p", "{}"))
        conn.execute("INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                     ("n", "c", "j", "REQ-1", "requirement", text, '{"scope":"product","status":"confirmed"}'))
    plain = store.search("메모", project_id="p")
    assert plain["mode"] == "text"
    assert any(node["id"] == "n" and node["body"] == text for node in plain["nodes"])
    with store.transaction() as conn:
        conn.execute("INSERT INTO models(id,dimensions,max_length,active) VALUES (%s,%s,%s,true)", ("fake", 3, 512))
        conn.execute("INSERT INTO chunks(id,node_id,ordinal,rule,title_path,body,input,input_hash,source_ranges) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                     ("chunk", "n", 0, "test", "", text, text, "hash", json.dumps([{"field": "body", "start": 0, "end": len(text)}])))
        conn.execute("INSERT INTO chunk_sets(node_id,model_id,completed) VALUES (%s,%s,true)", ("n", "fake"))
        conn.execute("INSERT INTO chunk_vectors(chunk_id,model_id,embedding) VALUES (%s,%s,%s::vector)", ("chunk", "fake", "[1,0,0]"))
    hybrid = store.search("메모", project_id="p", vector=[1, 0, 0], model_id="fake")
    assert hybrid["mode"] == "hybrid"
    assert any(node["id"] == "n" and node["matches"][0]["quote"] == text for node in hybrid["nodes"])
