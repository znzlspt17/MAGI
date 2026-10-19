"""공개 BGE-M3 파일만 익명 다운로드한다. 앱 시작 경로에서는 호출하지 않는다."""

import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def prepare(destination):
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with urlopen("https://huggingface.co/api/models/BAAI/bge-m3", timeout=30) as response:
        revision = json.load(response)["sha"]
    from huggingface_hub import snapshot_download
    snapshot_download("BAAI/bge-m3", revision=revision, local_dir=root, token=False, max_workers=1,
                      allow_patterns=["config.json", "modules.json", "config_sentence_transformers.json",
                                      "sentence_bert_config.json", "tokenizer.json", "tokenizer_config.json",
                                      "special_tokens_map.json", "sentencepiece.bpe.model", "model.safetensors", "pytorch_model.bin",
                                      "1_Pooling/config.json", "README.md"])
    if not (root / "modules.json").is_file() or not any((root / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")):
        raise RuntimeError("BGE-M3 모델 구성 또는 가중치 파일을 준비하지 못했습니다.")
    (root / "magi_model_revision.json").write_text(json.dumps({"model": "BAAI/bge-m3", "revision": revision}), encoding="utf-8")
    return root


def main():
    parser = argparse.ArgumentParser(description="공개 BGE-M3 모델을 명시적으로 준비합니다.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(prepare(args.output))


if __name__ == "__main__":
    main()
