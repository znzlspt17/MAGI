"""모델 준비·검증 API는 CLI 없이 공개 모델 파일만 다룬다."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backend.knowledge.model_files import prepare, verify_prepared_model


def test_model_api_prepares_verifiable_files_without_cli(tmp_path, monkeypatch):
    def download(repository, *, local_dir, **kwargs):
        assert repository == "BAAI/bge-m3" and kwargs["token"] is False
        root = Path(local_dir)
        for name in ("config.json", "modules.json", "tokenizer.json", "model.safetensors"):
            (root / name).write_bytes(b"fake-public-model-fixture")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    root = prepare(tmp_path / "model", revision="a" * 40)
    verify_prepared_model(root)
    (root / "config.json").write_bytes(b"changed-fixture")
    with pytest.raises(ValueError, match="파일 해시"):
        verify_prepared_model(root)
