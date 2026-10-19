"""청크 순위 결합과 출처 범위 중복 제거."""

def merge_matches(row, matches):
    merged = []
    for match in matches:
        source = match["source_ranges"][0]
        previous = next((m for m in merged if m["source_ranges"][0]["field"] == source["field"] and
                         m["source_ranges"][0]["start"] <= source["end"] and
                         source["start"] <= m["source_ranges"][0]["end"]), None)
        if previous:
            span = previous["source_ranges"][0]
            span["start"], span["end"] = min(span["start"], source["start"]), max(span["end"], source["end"])
            text = row["body"] if span["field"] == "body" else row["attrs"].get(span["field"], "")
            previous["quote"] = text[span["start"]:span["end"]]
            previous["chunk_ids"].append(match["chunk_id"])
        else:
            merged.append({**match, "chunk_ids": [match["chunk_id"]], "source_ranges": [dict(source)]})
    return merged


def search(store, query, kinds, active, filters, params, vector, model_id):
    columns = "SELECT n.*,j.project_id,c.id AS chunk_id,c.body AS quote,c.source_ranges,c.title_path"
    joins = " FROM magi_nodes n JOIN magi_jobs j ON j.id=n.job_id"
    chunks = (" JOIN magi_chunks c ON c.node_id=n.id JOIN magi_chunk_vectors v ON v.chunk_id=c.id "
              "JOIN magi_models m ON m.id=v.model_id AND m.active "
              "JOIN magi_chunk_sets s ON s.node_id=n.id AND s.model_id=m.id AND s.completed")
    base = " WHERE " + active + " AND n.kind=ANY(%s) AND (n.kind NOT IN ('requirement','decision','spec') OR n.attrs->>'scope'='product')" + filters
    words = query.split()[:20]
    patterns = ["%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for word in words]
    with store.transaction(mode='read') as conn:
        lexical = conn.execute(columns + joins + chunks + base +
            " AND (to_tsvector('simple',c.input) @@ plainto_tsquery('simple',%s) OR c.input ILIKE ANY(%s) "
            "OR n.logical_key=%s OR split_part(n.logical_key,':',2)=%s) "
            "ORDER BY (n.logical_key=%s OR split_part(n.logical_key,':',2)=%s) DESC,"
            "ts_rank(to_tsvector('simple',c.input),plainto_tsquery('simple',%s)) DESC,c.id LIMIT 60",
            (kinds, *params, query, patterns, query, query, query, query, query)).fetchall()
        # 청크가 준비되지 않은 최신 원본도 검색에서 빠지지 않는다.
        fallback = conn.execute("SELECT n.*,j.project_id" + joins + base +
            " AND NOT EXISTS (SELECT 1 FROM magi_chunk_sets s JOIN magi_models m ON m.id=s.model_id "
            "WHERE s.node_id=n.id AND s.completed AND m.active) "
            "AND (to_tsvector('simple',n.body) @@ plainto_tsquery('simple',%s) OR n.body ILIKE ANY(%s) "
            "OR n.logical_key=%s OR split_part(n.logical_key,':',2)=%s) "
            "ORDER BY (n.logical_key=%s OR split_part(n.logical_key,':',2)=%s) DESC,"
            "ts_rank(to_tsvector('simple',n.body),plainto_tsquery('simple',%s)) DESC,n.id LIMIT 60",
            (kinds, *params, query, patterns, query, query, query, query, query)).fetchall()
        # 텍스트 후보 두 경로를 하나의 60개 순위로 묶는다.
        lexical = sorted(lexical + fallback, key=lambda row: (
            not (row["logical_key"] == query or row["logical_key"].split(":", 1)[-1] == query),
            -sum(word.casefold() in row.get("quote", row["body"]).casefold() for word in words),
            row.get("chunk_id", row["id"])))[:60]
        semantic = []
        if vector is not None:
            import json
            semantic = conn.execute(columns + joins + chunks + base +
                " AND m.id=%s ORDER BY v.embedding <=> %s::vector,c.id LIMIT 60",
                (kinds, *params, model_id, json.dumps(vector))).fetchall()
    scores, rows = {}, {}
    for ranking in (lexical, semantic):
        for rank, row in enumerate(ranking, 1):
            key = (row["id"], row.get("chunk_id", ""))
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            rows[key] = row
    grouped = {}
    for key in sorted(scores, key=lambda key: (-scores[key], key)):
        grouped.setdefault(key[0], []).append(key)
    result = []
    for keys in list(grouped.values())[:20]:
        row = rows[keys[0]]
        node = store._public(row)
        for field in ("chunk_id", "quote", "source_ranges", "title_path"):
            node.pop(field, None)
        matches = [{key: rows[k][key] for key in ("chunk_id", "quote", "source_ranges", "title_path")}
                   for k in keys if rows[k].get("chunk_id")][:2]
        node["matches"] = merge_matches(row, matches)
        result.append(node)
    return {"nodes": result, "mode": "hybrid" if vector is not None else "text"}
