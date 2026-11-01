"""Sentence embeddings (multilingual MiniLM via sentence-transformers, safetensors, pinned revision)."""
from __future__ import annotations

import hashlib
import logging
import threading
from typing import Protocol

import numpy as np

from app import cache

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...   # (n, d) float32, L2-normalised


class STEmbedder:
    name = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        from app.transcribe import ensure_model

        path = ensure_model("embedder")
        device = "cpu"
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001
            log.info("torch CUDA probe failed; using CPU")
        # local folder only (already pinned + hashed); safetensors weights only
        self.model = SentenceTransformer(str(path), device=device, local_files_only=True, token=False,
                                         trust_remote_code=False,
                                         model_kwargs={"use_safetensors": True})

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        v = self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


_DEFAULT: Embedder | None = None
_LOCK = threading.Lock()


def default_embedder() -> Embedder:
    global _DEFAULT
    with _LOCK:
        if _DEFAULT is None:
            _DEFAULT = STEmbedder()
        return _DEFAULT


def texts_key(texts: list[str], model: str) -> str:
    h = hashlib.sha256(model.encode())
    for t in texts:
        h.update(b"\x00" + t.encode("utf-8"))
    return h.hexdigest()[:16]


def encode_cached(embedder: Embedder, texts: list[str], file_hash: str, prefix: str) -> np.ndarray:
    """Embeddings cached as npz (no pickle) under the file hash, keyed by text content."""
    key = texts_key(texts, embedder.name)
    name = f"{prefix}_{key}"
    hit = cache.read_npz(file_hash, name)
    if hit is not None and hit.get("v") is not None and hit["v"].shape[0] == len(texts):
        return hit["v"].astype(np.float32)
    v = embedder.encode(texts)
    cache.write_npz(file_hash, name, v=v)
    return v
