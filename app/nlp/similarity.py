"""How likely two articles report the same event: meaning (embeddings) + shared words and names (IDF-weighted).

Embeddings alone confuse "same topic" with "same event" on short headlines; shared rare words and names
(Riyad, Pierrefonds-Roxboro, Mathieu Lacombe) are what separate them. Names also bridge French and English.
"""

import math
from collections import Counter
from collections.abc import Iterable

import numpy as np

from app.nlp.text import entity_tokens, terms

LEX_WEIGHT = 0.6  # score = cosine(embeddings) + LEX_WEIGHT * lexical overlap
NAME_BOOST = 2.0  # a shared name counts this many times more than a shared word


def doc_text(title: str, summary: str | None) -> str:
    """What we compare: the headline and the start of the lede (every source has a headline; not all a lede)."""
    lede = (summary or "").strip()
    return f"{title}. {lede[:220]}" if lede else title


class Idf:
    def __init__(self, docs: Iterable[str]) -> None:
        df: Counter[str] = Counter()
        n = 0
        for d in docs:
            n += 1
            df.update(set(terms(d)) | {f"@{e}" for e in entity_tokens(d)})
        self.n, self.df = n, df

    def __call__(self, t: str) -> float:
        return math.log((self.n + 1) / (self.df.get(t, 0) + 1)) + 1.0

    def vector(self, text: str) -> dict[str, float]:
        counts = Counter(terms(text))
        for e in entity_tokens(text):
            counts[f"@{e}"] += NAME_BOOST
        v = {t: c * self(t) for t, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}


def lexical(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def merge_vectors(vectors: Iterable[dict[str, float]]) -> dict[str, float]:
    """Normalized sum: the term profile of a group of articles."""
    acc: Counter[str] = Counter()
    for v in vectors:
        acc.update(v)
    norm = math.sqrt(sum(x * x for x in acc.values())) or 1.0
    return {t: x / norm for t, x in acc.items()}


def score(emb_cos: float, lex: float) -> float:
    return emb_cos + LEX_WEIGHT * lex


# Logistic models fitted on 312 hand-labelled cross-outlet pairs (2026-10-11, 5-fold cross-validated; see
# README "Evaluation"). Same event: F1 0.77 (old fixed threshold: 0.65). Same story: F1 0.88 (old: 0.78).
# Time matters for events (same development = hours apart) but not for stories (they run for days).
_EVENT = (-2.740, 4.625, 8.054, -1.099)  # bias, cos, lexical, ln(1 + hours apart)
_STORY = (-5.530, 7.253, 9.334)  # bias, cos, lexical


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def p_event(emb_cos: float, lex: float, hours_apart: float) -> float:
    """Probability that two articles report the same development."""
    b, wc, wl, wt = _EVENT
    return _sigmoid(b + wc * emb_cos + wl * lex + wt * math.log1p(abs(hours_apart)))


def p_story(emb_cos: float, lex: float) -> float:
    """Probability that two articles belong to the same story (same or another development)."""
    b, wc, wl = _STORY
    return _sigmoid(b + wc * emb_cos + wl * lex)


def top_terms(v: dict[str, float], k: int = 8) -> list[str]:
    return [t for t, _ in sorted(v.items(), key=lambda kv: -kv[1])[:k]]


def centroid(vecs: list[np.ndarray]) -> np.ndarray:
    c = np.mean(np.stack(vecs), axis=0)
    return c / (np.linalg.norm(c) + 1e-9)
