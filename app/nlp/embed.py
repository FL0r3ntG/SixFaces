"""Local multilingual sentence embeddings (ONNX, CPU, ~120 MB). Not an LLM: it maps a headline to a vector so
that the same news in French and English lands close together."""

import threading

import numpy as np

from app.config import get_settings

_model = None
_lock = threading.Lock()
DIM = 768


def _get():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding

            s = get_settings()
            _model = TextEmbedding(s.embedding_model, cache_dir=str(s.model_cache_dir))
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """(n, DIM) float32, L2-normalized."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    vecs = np.array(list(_get().embed(texts, batch_size=64)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs


def to_bytes(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)
