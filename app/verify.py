"""How well an event is established, without judging truth: who reports it independently, and do their
figures agree. Agency copy (La Presse Canadienne, AFP...) reprinted by several outlets is ONE source."""

import re
from collections import defaultdict

from app.models import Article
from app.nlp.text import normalize

# status by number of independent ownership groups with their own (non-agency) article
CONFIRMED, CORROBORATED, SINGLE, WIRE_ONLY = "confirme", "corrobore", "source_unique", "depeche"

_NUM_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "cent": 100,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "dozen": 12, "dozens": 24,
}  # fmt: skip

# figures that should agree between outlets about the same event
_UNITS = {
    "morts": r"morts?|décès|personnes? (?:sont )?(?:mortes?|décédées?|tuées?)|tué(?:e|s|es)?|victimes? mortelles?|"
    r"dead|deaths?|killed|people killed",
    "blessés": r"blessé(?:e|s|es)?|injured|wounded|hurt",
    "disparus": r"disparu(?:e|s|es)?|missing",
    "évacués": r"évacué(?:e|s|es)?|evacuated|sinistrés?",
    "arrestations": r"arrestations?|personnes? arrêtées?|suspects? arrêtés?|arrests?",
}
_NUMBER = r"(\d{1,3}(?:[ \u00a0\u202f,.]\d{3})*|\d+|" + "|".join(_NUM_WORDS) + ")"
_FIG = {
    unit: re.compile(rf"\b{_NUMBER}\s+(?:\w+\s+){{0,2}}?(?:{pat})\b", re.IGNORECASE)
    for unit, pat in _UNITS.items()
}


def _to_int(s: str) -> int | None:
    s = s.lower()
    if s in _NUM_WORDS:
        return _NUM_WORDS[s]
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits and len(digits) < 7 else None


def figures(text: str) -> dict[str, int]:
    """Largest number given for each unit ("au moins 12 morts", "douze morts", "4 injured")."""
    out: dict[str, int] = {}
    for unit, pat in _FIG.items():
        for m in pat.finditer(text):
            n = _to_int(m.group(1))
            if n is not None and n < 100000:
                out[unit] = max(out.get(unit, 0), n)
    return out


def _wire_twins(arts: list[Article]) -> set[int]:
    """Articles whose headline is identical to one in another group: reprinted copy, even without byline."""
    by_title: dict[str, set[str]] = defaultdict(set)
    for a in arts:
        by_title[normalize(a.title)].add(a.group)
    return {a.id for a in arts if len(by_title[normalize(a.title)]) > 1}


def verify_event(arts: list[Article]) -> dict:
    twins = _wire_twins(arts)
    own: dict[str, int] = defaultdict(int)  # group -> own articles
    agency_groups: dict[str, set[str]] = defaultdict(set)
    agencies: set[str] = set()
    for a in arts:
        if a.wire or a.id in twins:
            agencies.add(a.wire or "copie")
            agency_groups[a.group].add(a.wire or "copie")
        else:
            own[a.group] += 1
    independent = sorted(own)
    if not independent:
        status = WIRE_ONLY
    elif len(independent) >= 3:
        status = CONFIRMED
    elif len(independent) == 2:
        status = CORROBORATED
    else:
        status = SINGLE
    return {
        "status": status,
        "independent": independent,
        "n_independent": len(independent),
        "wire_only_groups": sorted(g for g in agency_groups if g not in own),
        "agencies": sorted(agencies - {"copie"}) + (["copie"] if "copie" in agencies else []),
        "figures": _compare_figures(arts),
    }


def _compare_figures(arts: list[Article]) -> list[dict]:
    """Per unit, the figure each outlet gives (with time): a toll that rises over time is an update, two
    outlets giving different numbers at the same time is a divergence worth checking."""
    per_unit: dict[str, list[dict]] = defaultdict(list)
    for a in sorted(arts, key=lambda a: a.published_at):
        text = f"{a.title}. {a.summary or ''} {(a.text or '')[:1500]}"
        for unit, n in figures(text).items():
            per_unit[unit].append(
                {"value": n, "source": a.source_key, "article": a.id, "at": a.published_at.isoformat()}
            )
    out = []
    for unit, rows in per_unit.items():
        values = sorted({r["value"] for r in rows})
        if len(rows) < 2:
            continue
        out.append({"unit": unit, "values": values, "rows": rows, "divergent": len(values) > 1})
    return out
