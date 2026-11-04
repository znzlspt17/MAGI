"""동일 메모리 출력 대상으로 기본 로거·JSON 로거의 비용을 비교한다."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from statistics import median
from time import perf_counter_ns

from protocol.logging import _JSONFormatter, configure_logging, get_logger


def measure(logger, count=10000):
    def sample(method):
        started = perf_counter_ns()
        for _ in range(count): method("benchmark message")
        return (perf_counter_ns()-started)/count
    disabled = median(sample(logger.debug) for _ in range(3))
    active = median(sample(logger.info) for _ in range(3))
    def concurrent(_):
        started = perf_counter_ns(); logger.info("benchmark message")
        return perf_counter_ns()-started
    with ThreadPoolExecutor(max_workers=16) as pool:
        latencies = sorted(pool.map(concurrent, range(2000)))
    return {"disabled_debug_ns": round(disabled), "active_info_ns": round(active),
            "concurrent_log_call_p95_ns": latencies[int(len(latencies)*.95)]}


def main():
    results = {}
    output = io.StringIO()
    configure_logging("backend", stream=output)
    plain = logging.Logger("backend.benchmark", logging.INFO)
    handler = logging.StreamHandler(output); plain.addHandler(handler)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    results["stdlib_plain"] = measure(plain)
    output.seek(0); output.truncate()
    handler.setFormatter(_JSONFormatter())
    results["stdlib_json"] = measure(plain)
    output.seek(0); output.truncate()
    results["structlog_json"] = measure(get_logger("backend.benchmark"))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
