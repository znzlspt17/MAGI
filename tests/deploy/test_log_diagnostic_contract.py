"""컨테이너 수집 경계가 안전한 검증 참조를 버리지 않는지 확인한다."""

import json
from pathlib import Path
import re

import yaml


def test_collector_preserves_rubric_diagnostic_fields_without_raw_response():
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "deploy/vector.yaml").read_text(encoding="utf-8")
    )
    transform = config["transforms"]["normalized"]["source"]
    fields = set(json.loads(re.search(r"for_each\((\[[^\n]+\])\)", transform).group(1)))
    assert {
        "validation_reason", "validation_requirement_id", "validation_rubric_id",
        "attempt", "max_attempts", "job_id", "execution_id", "error_stage",
    } <= fields
    assert not fields & {"context", "validation_details", "quote", "response", "exception_message"}
