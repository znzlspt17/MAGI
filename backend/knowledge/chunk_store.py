"""청크의 중단 복구와 원본 단위 완료 처리."""

import json


class ChunkStore:
    def chunk_vector(self, chunk, model_id):
        with self.transaction(mode='read') as conn:
            row = conn.execute("SELECT v.embedding::text AS embedding FROM chunk_vectors v "
                "JOIN chunks c ON c.id=v.chunk_id WHERE c.input_hash=%s AND c.input=%s AND v.model_id=%s LIMIT 1",
                (chunk["input_hash"], chunk["input"], model_id)).fetchone()
            return json.loads(row["embedding"]) if row else None

    def save_chunk(self, info, chunk, vector):
        import math
        from backend.knowledge.config import KnowledgeError
        if len(vector) != info["dimensions"] or not all(math.isfinite(v) for v in vector):
            raise KnowledgeError("청크 벡터 차원 또는 값이 올바르지 않습니다.")
        norm = math.sqrt(sum(v*v for v in vector))
        if not math.isclose(norm, 1.0, rel_tol=1e-5):
            raise KnowledgeError("청크 벡터가 정규화되지 않았습니다.")
        with self.transaction() as conn:
            if not conn.execute("SELECT 1 FROM nodes WHERE id=%s", (chunk["node_id"],)).fetchone():
                return False
            conn.execute("INSERT INTO chunk_sets(node_id,model_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                         (chunk["node_id"], info["id"]))
            conn.execute("INSERT INTO chunks(id,node_id,ordinal,rule,title_path,body,input,input_hash,source_ranges) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         tuple(chunk[key] for key in ("id", "node_id", "ordinal", "rule", "title_path", "body", "input", "input_hash"))
                         + (self._json(chunk["source_ranges"]),))
            conn.execute("INSERT INTO chunk_vectors(chunk_id,model_id,embedding) VALUES (%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                         (chunk["id"], info["id"], json.dumps(vector)))

    def complete_chunks(self, node_id, model_id, expected):
        from backend.knowledge.config import KnowledgeError
        with self.transaction() as conn:
            if not conn.execute("SELECT 1 FROM nodes WHERE id=%s", (node_id,)).fetchone():
                return False
            count = conn.execute("SELECT count(*) AS total FROM chunks c JOIN chunk_vectors v ON v.chunk_id=c.id "
                                 "WHERE c.node_id=%s AND v.model_id=%s", (node_id, model_id)).fetchone()["total"]
            if count != expected:
                raise KnowledgeError("미완료 청크가 있어 원본을 활성화할 수 없습니다.")
            conn.execute("INSERT INTO chunk_sets(node_id,model_id,completed) VALUES (%s,%s,true) "
                         "ON CONFLICT(node_id,model_id) DO UPDATE SET completed=true", (node_id, model_id))
            conn.execute("UPDATE embedding_queue SET status='completed' WHERE node_id=%s", (node_id,))
