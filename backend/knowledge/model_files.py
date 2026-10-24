"""공개 BGE-M3 모델 파일 준비 API와 서버 시작 시 사용하는 해시 검증."""

import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen


MODEL_FILES = ("model.safetensors", "pytorch_model.bin", "config.json", "modules.json",
               "config_sentence_transformers.json", "sentence_bert_config.json", "tokenizer.json",
               "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model",
               "1_Pooling/config.json")


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_prepared_model(root):
    """고정 공개 파일명만 검증해 manifest로 임의 경로를 읽지 못하게 한다."""
    root = Path(root)
    metadata = root / 'model_revision.json'
    if metadata.is_symlink():
        raise ValueError('모델 revision 기록은 일반 파일이어야 합니다.')
    try:
        record = json.loads(metadata.read_text(encoding='utf-8'))
        hashes = record['sha256']
        if (record['model'] != 'BAAI/bge-m3' or not re.fullmatch(r'[0-9a-f]{40}', record['revision'])
                or not isinstance(hashes, dict) or not set(hashes) <= set(MODEL_FILES)
                or not {'config.json', 'modules.json', 'tokenizer.json'} <= set(hashes)
                or not {'model.safetensors', 'pytorch_model.bin'} & set(hashes)):
            raise ValueError
        for name, expected in hashes.items():
            path = root / name
            if (path.is_symlink() or path.parent.is_symlink()
                    or not re.fullmatch(r'[0-9a-f]{64}', str(expected))
                    or file_digest(path) != expected):
                raise ValueError
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError('준비된 모델의 구성·revision 기록 또는 파일 해시가 올바르지 않습니다. 빈 폴더에 모델을 다시 준비하세요.') from None


def prepare(destination, revision=None):
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision은 40자리 commit SHA여야 합니다.")
    root = Path(destination).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("기존 모델을 변경하지 않도록 빈 출력 폴더를 지정하세요.")
    root.mkdir(parents=True, exist_ok=True)
    if revision is None:
        with urlopen("https://huggingface.co/api/models/BAAI/bge-m3", timeout=30) as response:
            revision = json.load(response)["sha"]
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("확인한 모델 revision은 40자리 commit SHA여야 합니다.")
    from huggingface_hub import snapshot_download
    snapshot_download("BAAI/bge-m3", revision=revision, local_dir=root, token=False, max_workers=1,
                      allow_patterns=["config.json", "modules.json", "config_sentence_transformers.json",
                                      "sentence_bert_config.json", "tokenizer.json", "tokenizer_config.json",
                                      "special_tokens_map.json", "sentencepiece.bpe.model", "model.safetensors", "pytorch_model.bin",
                                      "1_Pooling/config.json", "README.md"])
    if not (root / "modules.json").is_file() or not any((root / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")):
        raise RuntimeError("BGE-M3 모델 구성 또는 가중치 파일을 준비하지 못했습니다.")
    # 공개 모델 구성·가중치만 해시한다. 다운로드 캐시나 임의 파일은 읽지 않는다.
    files = {}
    for pattern in MODEL_FILES:
        for path in root.glob(pattern):
            if path.is_symlink():
                raise RuntimeError("모델 준비 결과는 일반 파일이어야 합니다.")
            files[path.relative_to(root).as_posix()] = file_digest(path)
    (root / "model_revision.json").write_text(json.dumps({"model": "BAAI/bge-m3", "revision": revision,
                                                            "sha256": files}, indent=2), encoding="utf-8")
    return root
