"""Local multilingual sentence embeddings (ONNX, CPU). Not an LLM: they map a headline to a vector so that the
same news in French and English lands close together.

Two models: a fast one (paraphrase-multilingual-mpnet, ~1 GB) to find candidates, detect copies and vote on
sections, and a stronger one (multilingual-e5-large, ~2 GB, ~0.3 s per article on CPU) for the actual
same-event / same-story decisions, where it raised story recall from 0.84 to 0.94 at equal precision."""

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


_matcher = None


def _get_matcher():
    global _matcher
    with _lock:
        if _matcher is None:
            from fastembed import TextEmbedding

            s = get_settings()
            _matcher = TextEmbedding(s.matching_model, cache_dir=str(s.model_cache_dir))
    return _matcher


def embed_match(texts: list[str]) -> np.ndarray:
    """Matching-model vectors, L2-normalized. e5 expects a "query: " prefix for short texts."""
    if not texts:
        return np.zeros((0, 1024), dtype=np.float32)
    vecs = np.array(
        list(_get_matcher().embed(["query: " + t for t in texts], batch_size=32)), dtype=np.float32
    )
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs


def to_bytes(v: np.ndarray) -> bytes:
    return v.astype(np.float32).tobytes()


def from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)
