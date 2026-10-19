"""원문 위치를 보존하는 제한 길이 슬라이딩 윈도우."""

import re

from backend.knowledge.config import KnowledgeError
from backend.knowledge.projection import digest


CHUNK_RULE = "semantic-window-512-overlap64-v2"


def _segments(text, count, context, limit):
    """긴 문단과 그 뒤의 짧은 문단을 분리하고 짧은 이웃 문단만 합친다."""
    boundaries, offset, fence = [], 0, None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
        elif fence is None:
            if re.match(r"^#{1,6} ", line) and offset:
                boundaries.append(offset)
            if not line.strip():
                boundaries.append(offset + len(line))
        offset += len(line)
    boundaries.append(len(text))
    pending_start = block_start = 0
    for end in sorted(set(boundaries)):
        if end <= block_start:
            continue
        if count(context + text[block_start:end]) > limit:
            if pending_start < block_start:
                yield pending_start, block_start
            yield block_start, end
            pending_start = end
        elif count(context + text[pending_start:end]) > limit:
            yield pending_start, block_start
            pending_start = block_start
        block_start = end
    if pending_start < len(text):
        yield pending_start, len(text)


def chunks(node, tokenizer, limit=512, prompt=""):
    """본문을 복호화하지 않고 원문 문자 범위로 분할한다."""
    attrs = node.get("attrs", {})
    title = str(attrs.get("title_path", attrs.get("section", "")))
    context = f"유형: {node['kind']}\n식별자: {node.get('logical_key', node['id'])}\n제목: {title}\n\n"
    count = lambda value: len(tokenizer.encode(prompt + value, add_special_tokens=True))
    # 제목이 지나치게 길어도 본문 공간을 남기고 최종 입력을 다시 검사한다.
    while count(context) > limit // 3 and context:
        context = context[:len(context) // 2]
    sequence = 0
    fields = [("body", node["body"])]
    if node["kind"] == "decision":
        fields += [(key, attrs.get(key, "")) for key in ("rationale", "conditions")]
    for field, text in fields:
        if not isinstance(text, str) or not text.strip():
            continue
        for segment_start, segment_end in _segments(text, count, context, limit):
            start, previous_end = segment_start, segment_start
            while start < segment_end:
                # 문자 수 이진 탐색 후 재검사하여 tokenizer 경계의 재인코딩 오차도 막는다.
                low, high = start + 1, segment_end
                end = start
                while low <= high:
                    middle = (low + high) // 2
                    if count(context + text[start:middle]) <= limit:
                        end, low = middle, middle + 1
                    else:
                        high = middle - 1
                if end <= start:
                    raise KnowledgeError("청크 입력을 안전하게 분할할 수 없습니다.")
                # fenced code 안의 문장·제목을 경계로 해석하지 않는다.
                fenced, boundaries = False, []
                for match in re.finditer(r"(?m)^\s*(?:```|~~~).*?$|\n\s*\n|[.!?。！？](?:\s+|$)", text[:end]):
                    if re.match(r"\s*(?:```|~~~)", match.group()):
                        fenced = not fenced
                    elif not fenced and start < match.end() <= end:
                        boundaries.append(match.end())
                if end < segment_end:
                    candidates = [b for b in boundaries if b > previous_end and b >= start + (end - start) // 2]
                    if candidates:
                        end = candidates[-1]
                if end <= previous_end:
                    start = previous_end
                    continue
                body = text[start:end]
                value = context + body
                if count(value) > limit:
                    raise KnowledgeError("청크 입력 한도를 초과했습니다.")
                hashed = digest(value)
                yield {"id": digest([node["id"], CHUNK_RULE, sequence, hashed]), "node_id": node["id"],
                       "ordinal": sequence, "title_path": title, "body": body, "input": value,
                       "input_hash": hashed, "source_ranges": [{"field": field, "start": start, "end": end}],
                       "rule": CHUNK_RULE}
                sequence += 1
                previous_end = end
                if end == segment_end:
                    break
                # 약 64토큰의 접미부. 최대 96토큰인 문장 경계를 우선한다.
                low, high = start + 1, end
                while low < high:
                    middle = (low + high) // 2
                    if len(tokenizer.encode(text[middle:end], add_special_tokens=False)) > 64:
                        low = middle + 1
                    else:
                        high = middle
                overlap = low
                candidates = [b for b in boundaries if start < b < end and
                              len(tokenizer.encode(text[b:end], add_special_tokens=False)) <= 96]
                if candidates:
                    overlap = min(candidates, key=lambda b: abs(len(tokenizer.encode(text[b:end], add_special_tokens=False)) - 64))
                # 작은 입력 한도에서도 중복만 있는 청크를 만들지 않는다.
                start = max(start + 1, overlap)
