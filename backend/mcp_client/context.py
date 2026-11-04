"""작업 문서에 저장된 MCP 결과의 모델 입력을 제한한다."""

import hashlib
import json


def bounded_results(document, limit=8000):
    # 2026-11-04: 출처 식별자를 유지하며 JSON 구조를 깨지 않고 본문만 제한한다.
    entries = document.get("results", []) if isinstance(document, dict) else []
    if not isinstance(entries, list):
        return None
    selected = []
    for item in reversed(entries):
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        metadata = {key: item[key] for key in ("connection_id", "connection_version", "tool_name", "schema_hash", "arguments_hash", "status") if key in item}
        if not all(isinstance(metadata.get(key), str) and len(metadata[key]) <= 128
                   for key in ("connection_id", "tool_name", "schema_hash", "arguments_hash")):
            continue
        text = item.get("text", "")
        if not isinstance(text, str):
            continue
        low, high, best = 0, len(text), None
        while low <= high:
            middle = (low + high) // 2
            candidate = [{**metadata, "text": text[:middle]}, *selected]
            encoded = json.dumps({"results": candidate}, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) <= limit:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            break
        selected = best
        if len(selected) >= 3:
            break
    if not selected:
        return None
    encoded = json.dumps({"results": selected}, ensure_ascii=False, separators=(",", ":"))
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
