"""How likely two articles report the same event: meaning (embeddings) + shared words and names (IDF-weighted).

Embeddings alone confuse "same topic" with "same event" on short headlines; shared rare words and names
(Riyad, Pierrefonds-Roxboro, Mathieu Lacombe) are what separate them. Names also bridge French and English.
"""

import math
import re
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


# Logistic models fitted on 510 hand-labelled cross-outlet pairs (2026-10-11: 313 sampled across the whole score
# range + 197 the previous version kept apart), 5-fold cross-validated; see README "Evaluation".
#   same event: fast-model cos, lexical, ln(1 + hours apart). Refitting with the matching model (e5) did not
#     beat it end to end at equal precision (F1 0.76 vs 0.78 at P 0.88), so events keep the first model.
#   same story: e5, lexical, and when both articles have a body: shared numbers and body vocabulary. End to
#     end: F1 0.84 -> 0.88+ with higher precision.
# Time matters for events (a development = hours) but not for stories (they run for days).
_EVENT = (-2.740, 4.625, 8.054, -1.099)  # bias, cos, lex, ln(1+h)  (fitted on the first 313 pairs)
_STORY = (-60.42, 69.86, 3.56)  # bias, e5, lex
_STORY_BODY = (-2.38, 3.07, 4.36)  # both have a body: offset, shared-number share, body lexical


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def p_event(emb_cos: float, lex: float, hours_apart: float) -> float:
    """Probability that two articles report the same development."""
    b, wc, wl, wt = _EVENT
    return _sigmoid(b + wc * emb_cos + wl * lex + wt * math.log1p(abs(hours_apart)))


def p_story(e5: float, lex: float, body: tuple[float, float] | None = None) -> float:
    """Probability that two articles belong to the same story. `body` = (shared-number share, body lexical
    overlap) when both articles have their text."""
    b, we, wl = _STORY
    x = b + we * e5 + wl * lex
    if body is not None:
        off, wn, wb = _STORY_BODY
        x += off + wn * body[0] + wb * body[1]
    return _sigmoid(x)


_NUM = re.compile(r"\b\d[\d\u00a0\u202f,.]*\d\b|\b\d{2,}\b")


def body_profile(text: str | None, idf: "Idf") -> tuple[set[str], dict[str, float]] | None:
    """Numbers and term vector of the start of an article's body, for p_story."""
    if not text:
        return None
    head = text[:2500]
    return {n for n in _NUM.findall(head) if len(n) > 1}, idf.vector(head)


def body_overlap(a, b) -> tuple[float, float] | None:
    if a is None or b is None:
        return None
    na, nb = a[0], b[0]
    shared_nums = len(na & nb) / max(1, min(len(na), len(nb))) if na and nb else 0.0
    return shared_nums, lexical(a[1], b[1])


def top_terms(v: dict[str, float], k: int = 8) -> list[str]:
    return [t for t, _ in sorted(v.items(), key=lambda kv: -kv[1])[:k]]


def centroid(vecs: list[np.ndarray]) -> np.ndarray:
    c = np.mean(np.stack(vecs), axis=0)
    return c / (np.linalg.norm(c) + 1e-9)
