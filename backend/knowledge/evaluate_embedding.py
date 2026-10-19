"""실제 로컬 모델의 검색 적중률·최대 RSS 측정. 사용자 DB와 보호 설정은 읽지 않는다."""

import argparse
import json
import math
import platform
from pathlib import Path
import time

from backend.knowledge.embedding import LocalEmbedding


def peak_rss_bytes():
    if platform.system() != "Windows":
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if platform.system() == "Darwin" else value * 1024)
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    handle = ctypes.windll.kernel32.GetCurrentProcess
    handle.restype = wintypes.HANDLE
    values = Counters(); values.cb = ctypes.sizeof(values)
    memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    memory_info.restype = wintypes.BOOL
    if not memory_info(handle(), ctypes.byref(values), values.cb):
        raise OSError("프로세스 메모리를 측정할 수 없습니다.")
    return values.PeakWorkingSetSize


def evaluate(model_path, corpus_path, report_path):
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    model = LocalEmbedding(model_path)
    started = time.monotonic()
    try:
        info = model.info()
        baseline, indexed, paragraph_cache = {}, {}, {}
        padding = "이 문서는 프로젝트의 공통 운영 절차와 작업 이력 및 일반적인 자료 관리에 관한 안내입니다. " * 45
        for item in corpus:
            text = padding + "\n\n" + item["body"]
            node = {"id": item["id"], "kind": "spec", "body": text, "attrs": {}}
            indexed[item["id"]] = [model.encode([chunk["input"]])[0] for chunk in model.chunks(node)]
            # 이전 paragraph-mean-v2 방식: 모델 기본 한도로 문단을 분할한 후 평균·재정규화한다.
            vectors = []
            original_limit = model.model.max_seq_length
            model.model.max_seq_length = 8192
            try:
                for paragraph in text.split("\n\n"):
                    ids = model.model.tokenizer.encode(paragraph, add_special_tokens=False)
                    for offset in range(0, len(ids), 8190):
                        part = model.model.tokenizer.decode(ids[offset:offset + 8190], skip_special_tokens=True)
                        if part not in paragraph_cache:
                            paragraph_cache[part] = model.model.encode_document([part], batch_size=1, normalize_embeddings=True, show_progress_bar=False)[0]
                        vectors.append(paragraph_cache[part])
            finally:
                model.model.max_seq_length = original_limit
            mean = [sum(float(v[i]) for v in vectors) / len(vectors) for i in range(info["dimensions"])]
            norm = math.sqrt(sum(v*v for v in mean))
            baseline[item["id"]] = [v/norm for v in mean]
        cases = []
        for item in corpus:
            query = model.encode([item["query"]], query=True)[0]
            dot = lambda vector: sum(a*b for a, b in zip(query, vector))
            old = sorted(baseline, key=lambda key: (-dot(baseline[key]), key))[:5]
            new = sorted(indexed, key=lambda key: (-max(dot(v) for v in indexed[key]), key))[:5]
            cases.append({"query": item["query"], "expected": item["id"], "baseline_top5": old, "chunks_top5": new,
                          "baseline_hit": item["id"] in old, "chunks_hit": item["id"] in new})
        peak = peak_rss_bytes()
        report = {"dataset": "synthetic MAGI Korean retrieval examples; not production accuracy",
                  "scope": "dense retrieval only; peak RSS includes both current and legacy comparison workloads",
                  "platform": platform.platform(), "machine": platform.machine(), "model": info,
                  "cases": cases, "baseline_hit_at_5": sum(c["baseline_hit"] for c in cases)/len(cases),
                  "chunks_hit_at_5": sum(c["chunks_hit"] for c in cases)/len(cases),
                  "regressions": [c["expected"] for c in cases if c["baseline_hit"] and not c["chunks_hit"]],
                  "improvements": [c["expected"] for c in cases if not c["baseline_hit"] and c["chunks_hit"]],
                  "peak_rss_bytes": peak, "below_6gb": peak < 6_000_000_000,
                  "raspberry_pi_verified": False,
                  "elapsed_seconds": round(time.monotonic()-started, 2)}
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        model.close()


def main():
    parser = argparse.ArgumentParser(description="BGE-M3 한국어 검색과 최대 메모리 검증")
    parser.add_argument("--model", required=True)
    parser.add_argument("--corpus", default="tests/fixtures/embedding_ko.json")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = evaluate(args.model, args.corpus, args.report)
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
