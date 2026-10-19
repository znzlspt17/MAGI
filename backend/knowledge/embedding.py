"""다운로드 없는 로컬 모델 로딩과 단일 입력 인코딩."""

import hashlib
import json
import math
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import threading

from backend.knowledge.config import KnowledgeError
from backend.knowledge.chunking import CHUNK_RULE, chunks
from backend.knowledge import model_lock


class LocalEmbedding:
    def __init__(self, path, device="cpu", factory=None):
        self.path = Path(path) if path else None
        self.device = device
        self.factory = factory
        self.lock = threading.RLock()
        self.model = None

    def _load(self):
        if self.model is not None:
            return
        try:
            if self.path is None or not self.path.is_dir():
                raise ValueError
            if self.factory is None:
                model_lock.acquire(self)
            root = self.path.resolve()
            model_files = []
            config_names = {"config.json", "modules.json", "config_sentence_transformers.json", "sentence_bert_config.json",
                            "tokenizer_config.json", "special_tokens_map.json", "tokenizer.json", "added_tokens.json",
                            "vocab.json", "vocab.txt", "merges.txt", "adapter_config.json", "generation_config.json",
                            "preprocessor_config.json", "spiece.model", "sentencepiece.bpe.model", "tokenizer.model",
                            "sentencepiece.model", "model.safetensors.index.json", "pytorch_model.bin.index.json"}
            for file in sorted(root.rglob("*")):
                relative = file.relative_to(root)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                if file.is_symlink():
                    target = file.resolve(strict=True)
                    # HF 스냅샷의 파일 링크는 해당 저장소의 blobs 안에서만 허용한다.
                    hf_blob = (root.parent.name == "snapshots" and target.parent == root.parent.parent / "blobs"
                               and re.fullmatch(r"[0-9a-f]{40,64}", target.name))
                    if file.is_dir() or not (target.is_relative_to(root) or hf_blob):
                        raise ValueError
                weight = re.fullmatch(r"(?:model|pytorch_model|adapter_model)(?:-\d+-of-\d+)?\.(?:safetensors|bin)", file.name)
                if file.is_file() and (file.name in config_names or weight):
                    model_files.append(file)
            factory = self.factory
            if factory is None:
                from sentence_transformers import SentenceTransformer
                import torch
                torch.set_num_threads(2)
                factory = SentenceTransformer
            # 사용자 정의 Python 모듈과 보호 파일을 모델 코드로 실행하지 않는다.
            modules_path = self.path / "modules.json"
            if modules_path.is_file():
                modules = json.loads(modules_path.read_text(encoding="utf-8"))
                if any(not str(item.get("type", "")).startswith("sentence_transformers.") for item in modules):
                    raise ValueError
                if any(not (root / item.get("path", "")).resolve().is_relative_to(root) for item in modules):
                    raise ValueError
            model = factory(str(self.path), device=self.device,
                            local_files_only=True, trust_remote_code=False, token=False,
                            model_kwargs={"torch_dtype": "float32"})
            dimension = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
            if self.factory is None:
                if self.device != "cpu" or dimension() != 1024:
                    raise ValueError
                model.float()
            dim = int(dimension())
            limit = min(512, int(model.max_seq_length))
            model.max_seq_length = limit
            if dim < 1 or limit < 8 or limit > 1_000_000:
                raise ValueError
            fingerprint = hashlib.sha256()
            # 모델 자체와 전처리의 변경을 감지한다. 비밀 파일은 열지 않는다.
            for file in model_files:
                fingerprint.update(file.relative_to(root).as_posix().encode())
                with file.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        fingerprint.update(block)
            try:
                library_version = version("sentence-transformers")
            except PackageNotFoundError:
                library_version = "test-factory"
            dependencies = {}
            for package in ("torch", "transformers", "tokenizers"):
                try:
                    dependencies[package] = version(package)
                except PackageNotFoundError:
                    dependencies[package] = "unavailable"
            fingerprint.update(json.dumps({"algorithm": CHUNK_RULE, "dtype": "float32", "library_version": library_version, "prompts": model.prompts,
                "dependencies": dependencies,
                "default_prompt_name": model.default_prompt_name,
                "dimensions": dim, "max_length": limit}, sort_keys=True).encode())
            self.model_id = fingerprint.hexdigest()
            self.dimensions, self.max_length = dim, limit
            self.model = model
        except Exception:
            self.model = None
            model_lock.release(self)
            raise KnowledgeError("로컬 임베딩 모델을 로드할 수 없습니다. 경로·호환 형식·장치를 확인하세요.") from None

    def info(self):
        with self.lock:
            self._load()
            return {"id": self.model_id, "dimensions": self.dimensions, "max_length": self.max_length}

    def _prompt(self, query=False):
        prompts = self.model.prompts or {}
        name = "query" if query else next((key for key in ("document", "passage", "corpus") if key in prompts), "document")
        return prompts.get(name, prompts.get(self.model.default_prompt_name, ""))

    def chunks(self, node):
        with self.lock:
            self._load()
        yield from chunks(node, self.model.tokenizer, self.max_length, self._prompt())

    def encode(self, texts, *, query=False):
        with self.lock:
            try:
                self._load()
                result = []
                for text in texts:
                    if len(self.model.tokenizer.encode(self._prompt(query) + text, add_special_tokens=True)) > self.max_length:
                        raise KnowledgeError("임베딩 입력이 512토큰 또는 모델 입력 한도를 초과했습니다.")
                    fn = self.model.encode_query if query else self.model.encode_document
                    vectors = fn([text], batch_size=1, normalize_embeddings=True, show_progress_bar=False)
                    if len(vectors) != 1 or len(vectors[0]) != self.dimensions:
                        raise KnowledgeError("임베딩 모델의 실제 출력 차원이 선언과 일치하지 않습니다.")
                    vector = [float(v) for v in vectors[0]]
                    norm = math.sqrt(sum(v * v for v in vector))
                    if not math.isfinite(norm) or norm == 0:
                        raise ValueError
                    result.append([v / norm for v in vector])
                return result
            except KnowledgeError:
                raise
            except Exception:
                raise KnowledgeError("로컬 임베딩 생성에 실패했습니다. 텍스트 검색을 사용합니다.") from None

    def close(self):
        with self.lock:
            self.model = None
            model_lock.release(self)
