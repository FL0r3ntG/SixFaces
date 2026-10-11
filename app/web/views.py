"""Queries and aggregates behind the pages (kept out of the routes)."""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import Article, Event, FetchRun, Sujet, utcnow
from app.sources import BY_KEY, GROUPS, SOURCES

# Groups with a brand colour, in stacking order: reds and blues alternate so same-family shades never touch.
# The small groups without a distinct brand colour share "Autres".
CHART_GROUPS = ["cbcrc", "quebecor", "lapresse", "bell", "cn2i", "devoir", "postmedia", "metro"]
OTHER = "autres"
MAJOR_GROUPS = ["quebecor", "lapresse", "devoir", "cn2i", "cbcrc"]  # their absence is worth flagging

MIN_GROUP_ARTICLES = 20  # below this a group's percentages are noise

PERIODS = {
    "24h": timedelta(hours=24),
    "3j": timedelta(days=3),
    "7j": timedelta(days=7),
    "30j": timedelta(days=30),
}


def canonical():
    """Same-owner copies (JdM -> JdQ, TVA...) are left out of every list and count."""
    return col(Article.dup_of).is_(None)


def listed():
    """What lists show and article counts count: one row per piece. Excludes same-owner copies AND the same
    piece run by another owner (agency copy). Group coverage uses canonical(), which keeps the latter."""
    return col(Article.dup_of).is_(None) & col(Article.same_as).is_(None)


def also_run_by(session: Session, ids: list[int]) -> dict[int, list[str]]:
    """original article id -> source keys of other owners that ran the same piece."""
    out: dict[int, list[str]] = defaultdict(list)
    if ids:
        for orig, src in session.exec(
            select(Article.same_as, Article.source_key).where(col(Article.same_as).in_(ids), canonical())
        ).all():
            if src not in out[orig]:
                out[orig].append(src)
    return out


def copies(session: Session, ids: list[int]) -> dict[int, list[str]]:
    """original article id -> source keys of its copies on the owner's other sites."""
    out: dict[int, list[str]] = defaultdict(list)
    if ids:
        for orig, src in session.exec(
            select(Article.dup_of, Article.source_key).where(col(Article.dup_of).in_(ids))
        ).all():
            if src not in out[orig]:
                out[orig].append(src)
    return out


def outlet(
    source_key: str, group: str, copy_keys: list[str] | None = None, also: list[str] | None = None
) -> dict:
    """'Le Journal de Montréal', or 'Québecor' (with its sites) when the piece runs on several of them."""
    keys = [source_key, *[k for k in copy_keys or [] if k != source_key]]
    also_names = [BY_KEY[k].name for k in also or [] if k != source_key]
    if len(keys) > 1:
        return {"name": SHORT.get(group, GROUPS[group][0]), "sites": [BY_KEY[k].name for k in keys], "multi": True,
                "slot": group_slot(group), "also": also_names}  # fmt: skip
    return {"name": BY_KEY[source_key].name, "sites": [BY_KEY[source_key].name], "multi": False,
            "slot": group_slot(group), "also": also_names}  # fmt: skip


SHORT = {"cbcrc": "Radio-Canada/CBC", "cn2i": "CN2i", "bell": "Bell (Noovo, CTV)", "postmedia": "Gazette",
         "metro": "Métro"}  # fmt: skip


def chart_group(group: str) -> str:
    return group if group in CHART_GROUPS else OTHER


def group_slot(group: str) -> int:
    """1-based categorical slot; 0 = 'Autres' (neutral)."""
    g = chart_group(group)
    return CHART_GROUPS.index(g) + 1 if g != OTHER else 0


def group_name(group: str) -> str:
    return "Autres" if group == OTHER else GROUPS[group][0]


def legend() -> list[dict]:
    others = [GROUPS[g][0] for g in GROUPS if g not in CHART_GROUPS]
    return [{"key": g, "slot": i + 1, "name": GROUPS[g][0]} for i, g in enumerate(CHART_GROUPS)] + [
        {"key": OTHER, "slot": 0, "name": "Autres", "detail": ", ".join(others)}
    ]


@dataclass
class Coverage:
    segments: list[dict]  # [{key, slot, name, n, pct}] in fixed slot order
    total: int
    absent_major: list[str]


def coverage(groups_count: dict[str, int], by_size: bool = False) -> Coverage:
    """by_size: largest share first (when the bar is read with a ranked legend), else fixed group order."""
    folded: Counter[str] = Counter()
    for g, n in groups_count.items():
        folded[chart_group(g)] += n
    total = sum(folded.values()) or 1
    order = [*CHART_GROUPS, OTHER]
    segs = [
        {
            "key": g,
            "slot": group_slot(g) if g != OTHER else 0,
            "name": group_name(g),
            "short": SHORT.get(g, group_name(g)),
            "n": folded[g],
            "pct": 100 * folded[g] / total,
        }
        for g in order
        if folded[g]
    ]
    if by_size:
        segs.sort(key=lambda seg: (seg["key"] == OTHER, -seg["n"]))  # "Autres" always last
    absent = [GROUPS[g][0] for g in MAJOR_GROUPS if g not in groups_count]
    return Coverage(segs, sum(folded.values()), absent)


def sparkline(times: list[datetime], now: datetime, hours: int = 48, buckets: int = 16) -> dict:
    """Articles per bucket over the last `hours`, as SVG polyline points (0..100 x 0..24)."""
    step = hours / buckets
    counts = [0] * buckets
    for t in times:
        age = (now - t).total_seconds() / 3600
        if 0 <= age < hours:
            counts[buckets - 1 - int(age // step)] += 1
    peak = max(counts) or 1
    pts = [(i * 100 / (buckets - 1), 22 - 20 * c / peak) for i, c in enumerate(counts)]
    return {
        "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
        "area": "0,22 " + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " 100,22",
        "last": pts[-1],
        "counts": counts,
        "step_h": step,
        "peak": peak,
    }


# --- front page -----------------------------------------------------------------------------------------


@dataclass
class SujetCard:
    sujet: Sujet
    coverage: Coverage
    spark: dict
    status: str
    n_independent: int
    top_event: Event | None
    headlines: list[dict] = field(default_factory=list)  # a few outlets' own wording
    figures_divergent: bool = False
    image: str | None = None
    image_source: str | None = None
    lede: str = ""
    n_recent: int = 0  # articles in the last 3 h


def front_page(session: Session, period: str, category: str | None, limit: int = 60) -> list[SujetCard]:
    since = utcnow() - PERIODS.get(period, PERIODS["24h"])
    q = select(Sujet).where(Sujet.last_at >= since, Sujet.n_articles >= 1)
    if category:
        q = q.where(Sujet.category == category)
    if period == "24h":
        q = q.order_by(Sujet.score.desc())
    else:  # longer periods: rank by how big the story was, not how fresh it is
        q = q.order_by(Sujet.n_groups.desc(), Sujet.n_articles.desc())
    return cards_for(session, session.exec(q.limit(limit)).all())


def cards_for(session: Session, sujets: list[Sujet]) -> list[SujetCard]:
    if not sujets:
        return []
    now = utcnow()
    ids = [s.id for s in sujets]
    events = session.exec(select(Event).where(col(Event.sujet_id).in_(ids))).all()
    ev_by_sujet: dict[int, list[Event]] = defaultdict(list)
    for e in events:
        ev_by_sujet[e.sujet_id].append(e)
    rows = session.exec(
        select(
            Article.event_id, Article.published_at, Article.source_key, Article.title, Article.url,
            Article.image_url, Article.summary, Article.wire, Article.id,
        ).where(col(Article.event_id).in_([e.id for e in events]), listed())
    ).all()  # fmt: skip
    cps = copies(session, [r[8] for r in rows])
    alr = also_run_by(session, [r[8] for r in rows])
    sujet_of_event = {e.id: e.sujet_id for e in events}
    times: dict[int, list[datetime]] = defaultdict(list)
    heads: dict[int, list] = defaultdict(list)
    for row in rows:
        sid = sujet_of_event[row[0]]
        times[sid].append(row[1])
        heads[sid].append(row)
    cards = []
    for s in sujets:
        evs = sorted(ev_by_sujet[s.id], key=lambda e: -e.score)
        top = evs[0] if evs else None
        ver = json.loads(top.verification) if top else {}
        arts = sorted(heads[s.id], key=lambda r: r[1], reverse=True)
        # one headline per group, latest first: shows how outlets word the same story
        seen, sample = set(), []
        for _ev, _at, src, title, url, _img, _sum, _wire, art_id in arts:
            g = BY_KEY[src].group
            if g in seen or title == s.title:
                continue
            seen.add(g)
            o = outlet(src, g, cps.get(art_id), alr.get(art_id))
            sample.append(
                {
                    "source": o["name"],
                    "also": o["also"],
                    "group": g,
                    "slot": group_slot(g),
                    "title": title,
                    "url": url,
                }
            )
        image, image_source = _pick_image(arts, top.id if top else None)
        lede = next(
            (_short(r[6]) for r in arts if r[0] == (top.id if top else None) and r[6] and not r[7]), ""
        )
        cards.append(
            SujetCard(
                sujet=s,
                coverage=coverage(json.loads(s.groups)),
                spark=sparkline(times[s.id], now),
                status=ver.get("status", "source_unique"),
                n_independent=ver.get("n_independent", 0),
                top_event=top,
                headlines=sample[:3],
                figures_divergent=any(
                    f["divergent"] for e in evs for f in json.loads(e.verification).get("figures", [])
                ),
                image=image,
                image_source=image_source,
                lede=lede,
                n_recent=sum(1 for t in times[s.id] if (now - t).total_seconds() < 3 * 3600),
            )
        )
    return cards


def _pick_image(arts: list, top_event_id: int | None) -> tuple[str | None, str | None]:
    """The lead photo of the current development, else the newest photo of the sujet."""
    with_img = [r for r in arts if r[5]]
    for r in with_img:
        if r[0] == top_event_id:
            return r[5], BY_KEY[r[2]].name
    return (with_img[0][5], BY_KEY[with_img[0][2]].name) if with_img else (None, None)


def _short(text: str, n: int = 220) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


# --- magazine home --------------------------------------------------------------------------------------

HOME_SECTIONS = ["politique", "international", "justice", "economie", "societe", "sante", "sports", "culture"]


def home(session: Session) -> dict:
    """Everything on the home page, built from the same ranked sujets as the list view."""
    now = utcnow()
    since = now - timedelta(hours=24)
    ranked = session.exec(
        select(Sujet).where(Sujet.last_at >= since).order_by(Sujet.score.desc()).limit(150)
    ).all()
    cards = cards_for(session, ranked)
    by_id = {c.sujet.id: c for c in cards}

    # front: the lead must have a photo if any of the top 3 has one
    top = cards[:12]
    lead = next((c for c in top[:3] if c.image), top[0] if top else None)
    seconds = [c for c in top if c is not lead][:7]  # 2 under the lead, 5 in the right column
    shown = {c.sujet.id for c in [lead, *seconds] if c}

    rising = sorted(
        (c for c in cards if c.n_recent >= 3 and c.sujet.id not in shown),
        key=lambda c: (-c.n_recent, -c.sujet.score),
    )[:5]

    sections = []
    for cat in HOME_SECTIONS:
        items = [c for c in cards if c.sujet.category == cat and c.sujet.id not in shown][:4]
        if items:
            sections.append({"key": cat, "cards": items})

    blind = next((c for c in cards[:40] if c.sujet.n_groups >= 4 and c.coverage.absent_major), None)
    return {
        "lead": lead,
        "seconds": seconds,
        "rising": rising,
        "sections": sections,
        "divides": divided_headlines(session, since),
        "blind": blind,
        "ticker": latest(session, 24),
        "fil": latest(session, 40),
        "day": day_numbers(session, since, cards),
        "by_id": by_id,
    }


def latest(session: Session, n: int) -> list[dict]:
    arts = session.exec(
        select(Article)
        .where(Article.event_id != None, listed())
        .order_by(Article.published_at.desc())
        .limit(n)
    ).all()
    sujet_of = dict(
        session.exec(
            select(Event.id, Event.sujet_id).where(col(Event.id).in_([a.event_id for a in arts]))
        ).all()
    )
    cps = copies(session, [a.id for a in arts])
    alr = also_run_by(session, [a.id for a in arts])
    return [
        {
            "a": a,
            "source": outlet(a.source_key, a.group, cps.get(a.id))["name"],
            "also": outlet(a.source_key, a.group, None, alr.get(a.id))["also"],
            "slot": group_slot(a.group),
            "sujet_id": sujet_of.get(a.event_id),
        }
        for a in arts
    ]


def divided_headlines(session: Session, since: datetime) -> dict | None:
    """The event of the day whose outlets word it most differently: lowest similarity between the headlines
    of different groups (each group's own, non-agency article)."""
    import numpy as np

    from app.nlp.embed import from_bytes

    events = session.exec(
        select(Event)
        .where(
            Event.last_at >= since, Event.n_groups >= 4, Event.category != "sports"
        )  # not pre-game vs result
        .order_by(Event.score.desc())
        .limit(25)
    ).all()
    best = None
    for ev in events:
        arts = session.exec(
            select(Article)
            .where(Article.event_id == ev.id, Article.wire == None, listed())
            .order_by(Article.published_at)
        ).all()
        per_group: dict[str, Article] = {}
        for a in arts:
            if a.embedding is not None and a.lang == "fr":
                per_group.setdefault(a.group, a)
        picks = list(per_group.values())
        if len(picks) < 3:
            continue
        m = np.stack([from_bytes(a.embedding) for a in picks])
        sims = m @ m.T
        spread = 1 - float(sims[np.triu_indices(len(picks), 1)].mean())
        if best is None or spread * (1 + 0.1 * ev.n_groups) > best["rank"]:
            best = {"rank": spread * (1 + 0.1 * ev.n_groups), "event": ev, "spread": spread, "picks": picks}
    if best is None:
        return None
    cps = copies(session, [a.id for a in best["picks"]])
    alr = also_run_by(session, [a.id for a in best["picks"]])
    best["rows"] = [
        {"title": a.title, "url": a.url, "source": outlet(a.source_key, a.group, cps.get(a.id))["name"],
         "also": outlet(a.source_key, a.group, None, alr.get(a.id))["also"],
         "group": GROUPS[a.group][0],
         "slot": group_slot(a.group), "opinion": a.opinion}
        for a in best["picks"][:4]
    ]  # fmt: skip
    return best


def day_numbers(session: Session, since: datetime, cards: list[SujetCard]) -> dict:
    n_arts = session.exec(
        select(func.count()).select_from(Article).where(Article.published_at >= since, listed())
    ).one()
    _, n_sources = session.exec(
        select(func.count(), func.count(func.distinct(Article.source_key))).where(
            Article.published_at >= since
        )
    ).one()
    by_group = dict(
        session.exec(
            select(Article.group, func.count())
            .where(Article.published_at >= since, canonical())
            .group_by(Article.group)
        ).all()
    )
    return {
        "coverage": coverage(by_group, by_size=True),
        "articles": n_arts,
        "sources": n_sources,
        "sujets": len(cards),
        "confirmed": sum(1 for c in cards if c.status == "confirme"),
        "big": sum(1 for c in cards if c.sujet.n_groups >= 5),
    }


def category_counts(session: Session, period: str) -> dict[str, int]:
    since = utcnow() - PERIODS.get(period, PERIODS["24h"])
    return dict(
        session.exec(
            select(Sujet.category, func.count()).where(Sujet.last_at >= since).group_by(Sujet.category)
        ).all()
    )


# --- sujet page -----------------------------------------------------------------------------------------


def sujet_detail(session: Session, sujet_id: int) -> dict | None:
    s = session.get(Sujet, sujet_id)
    if s is None:
        return None
    events = session.exec(
        select(Event).where(Event.sujet_id == sujet_id).order_by(Event.first_at.desc())
    ).all()
    arts = session.exec(
        select(Article)
        .where(col(Article.event_id).in_([e.id for e in events]), canonical())
        .order_by(Article.published_at)
    ).all()
    by_event: dict[int, list[Article]] = defaultdict(list)
    for a in arts:
        by_event[a.event_id].append(a)

    shared_by = also_run_by(session, [a.id for a in arts])  # piece id -> other owners' sources
    timeline = []
    for e in events:
        ev_arts = by_event[e.id]
        groups: dict[str, list[Article]] = defaultdict(list)
        shared = []  # the same piece run by several owners (agency copy): one block, every owner named
        for a in ev_arts:
            if a.same_as is not None:
                continue
            if shared_by.get(a.id):
                owners = [a.group, *(BY_KEY[k].group for k in shared_by[a.id])]
                names = list(dict.fromkeys(GROUPS[g][0] for g in owners))
                sources = [BY_KEY[a.source_key].name, *(BY_KEY[k].name for k in shared_by[a.id])]
                shared.append({"article": a, "groups": names, "sources": list(dict.fromkeys(sources)),
                               "slots": [group_slot(g) for g in dict.fromkeys(owners)]})  # fmt: skip
            else:
                groups[a.group].append(a)

        ordered = sorted(groups.items(), key=lambda kv: (group_slot(kv[0]) or 99, kv[0]))
        ver = json.loads(e.verification)
        for f in ver.get("figures", []):
            by_value: dict[int, dict] = {}
            for r in f["rows"]:
                at = datetime.fromisoformat(r["at"])
                v = by_value.setdefault(r["value"], {"value": r["value"], "sources": [], "at": at})
                if BY_KEY[r["source"]].name not in v["sources"]:
                    v["sources"].append(BY_KEY[r["source"]].name)
                v["at"] = min(v["at"], at)
            f["by_value"] = sorted(by_value.values(), key=lambda v: v["at"])
        with_img = [a for a in ev_arts if a.image_url]
        timeline.append(
            {
                "image": with_img[-1].image_url if with_img else None,
                "event": e,
                "shared": shared,
                # every owner that covered it, by real name (the chart folds small ones into "Autres")
                "who": [
                    {"name": SHORT.get(g, GROUPS[g][0]), "slot": group_slot(g)}
                    for g, _ in Counter(a.group for a in ev_arts).most_common()
                ],
                "verification": ver,
                "keywords": json.loads(e.keywords),
                "groups": [
                    {"key": g, "name": GROUPS[g][0], "slot": group_slot(g), "articles": items}
                    for g, items in ordered
                ],
                "coverage": coverage(Counter(a.group for a in ev_arts)),
                "first": ev_arts[0] if ev_arts else None,
            }
        )

    # who published first on this sujet, and how fast the others followed
    first_by_group: dict[str, datetime] = {}
    for a in arts:
        first_by_group.setdefault(a.group, a.published_at)
    t0 = min(first_by_group.values()) if first_by_group else None
    race = [
        {"name": GROUPS[g][0], "slot": group_slot(g), "at": t, "delay_h": (t - t0).total_seconds() / 3600}
        for g, t in sorted(first_by_group.items(), key=lambda kv: kv[1])
    ]
    # day-by-day evolution: day number since the story began (Quebec time), articles that day
    from app.web.fmt import local

    start_day = local(s.first_at).date()
    per_day: Counter = Counter(local(a.published_at).date() for a in arts)
    for t in timeline:
        d = local(t["event"].first_at).date()
        t["day_n"] = (d - start_day).days + 1
        t["day"] = d
    active: dict = defaultdict(set)  # day -> developments with coverage that day (not only those starting)
    for a in arts:
        active[local(a.published_at).date()].add(a.event_id)
    days = [
        {"n": (d - start_day).days + 1, "date": d, "articles": per_day[d], "events": len(active[d]),
         "new": sum(1 for t in timeline if t["day"] == d)}
        for d in sorted(per_day)
    ]  # fmt: skip
    card = cards_for(session, [s])[0]
    cps = copies(session, [a.id for a in arts])
    alr = also_run_by(session, [a.id for a in arts])
    ids_in = {t["event"].id for t in timeline}
    for t in timeline:
        f = t["event"].follows_id
        t["follows"] = next((u for u in timeline if u["event"].id == f), None) if f in ids_in else None
    n_links = sum(1 for t in timeline if t["follows"])
    return {
        "n_links": n_links,
        "days": days,
        "outlets": {a.id: outlet(a.source_key, a.group, cps.get(a.id), alr.get(a.id)) for a in arts},
        "n_same": sum(1 for a in arts if a.same_as),
        "n_copies": sum(len(v) for v in cps.values()),
        "card": card,
        "sujet": s,
        "timeline": timeline,
        "coverage": coverage(json.loads(s.groups)),
        "volume": volume_chart(arts),
        "race": race,
        "n_headline_only": sum(a.headline_only for a in arts),
        "n_wire": sum(1 for a in arts if a.wire),
        "n_opinion": sum(a.opinion for a in arts),
        "sources": sorted({BY_KEY[a.source_key].name for a in arts}),
    }


def volume_chart(arts: list[Article]) -> dict:
    """Stacked columns of articles per time bucket and group. Bucket = 3 h for short stories, 1 day otherwise."""
    if not arts:
        return {"columns": [], "max": 0}
    start, end = arts[0].published_at, arts[-1].published_at
    span_h = max((end - start).total_seconds() / 3600, 1)
    step = timedelta(hours=3) if span_h <= 72 else timedelta(days=1)
    from app.web.fmt import local

    origin = local(start).replace(minute=0, second=0, microsecond=0)
    if step == timedelta(days=1):
        origin = origin.replace(hour=0)
    else:
        origin = origin.replace(hour=origin.hour - origin.hour % 3)
    n = int((local(end) - origin) / step) + 1
    cols = [Counter() for _ in range(n)]
    for a in arts:
        cols[int((local(a.published_at) - origin) / step)][chart_group(a.group)] += 1
    order = [*CHART_GROUPS, OTHER]
    peak = max(sum(c.values()) for c in cols) or 1
    columns = []
    for i, c in enumerate(cols):
        at = origin + i * step
        segs, y = [], 0
        for g in order:
            if c[g]:
                segs.append(
                    {
                        "key": g,
                        "slot": group_slot(g) if g != OTHER else 0,
                        "name": group_name(g),
                        "n": c[g],
                        "y": y,
                    }
                )
                y += c[g]
        columns.append({"at": at, "total": y, "segments": segs})
    return {"columns": columns, "max": peak, "step_h": step.total_seconds() / 3600}


# --- coverage analytics ---------------------------------------------------------------------------------


def coverage_report(session: Session, period: str) -> dict:
    since = utcnow() - PERIODS.get(period, PERIODS["7j"])
    rows = session.exec(
        select(Article.group, Article.category, func.count())
        .where(Article.published_at >= since, Article.event_id != None, canonical())
        .group_by(Article.group, Article.category)
    ).all()
    from app.nlp.categories import CATEGORIES

    per_group: dict[str, Counter] = defaultdict(Counter)
    for g, c, n in rows:
        per_group[g][c or "societe"] += n
    small = [
        GROUPS[g][0] for g in GROUPS if 0 < sum(per_group.get(g, Counter()).values()) < MIN_GROUP_ARTICLES
    ]
    groups = [g for g in GROUPS if sum(per_group.get(g, Counter()).values()) >= MIN_GROUP_ARTICLES]
    matrix = []
    for g in groups:
        total = sum(per_group[g].values())
        matrix.append(
            {
                "group": GROUPS[g][0],
                "key": g,
                "total": total,
                "cells": [
                    {"cat": c, "n": per_group[g][c], "pct": 100 * per_group[g][c] / total if total else 0}
                    for c in CATEGORIES
                ],
            }
        )

    # Angles morts: big sujets (>= 3 groups) that a major group did not cover at all
    big = session.exec(
        select(Sujet).where(Sujet.last_at >= since, Sujet.n_groups >= 3).order_by(Sujet.n_groups.desc())
    ).all()
    blind: dict[str, list[Sujet]] = {g: [] for g in MAJOR_GROUPS}
    for s in big:
        present = json.loads(s.groups)
        for g in MAJOR_GROUPS:
            if g not in present:
                blind[g].append(s)
    blindspots = [
        {"group": GROUPS[g][0], "key": g, "sujets": blind[g][:8], "n": len(blind[g])} for g in MAJOR_GROUPS
    ]

    # Premier à publier: among events covered by >= 3 groups, who had it first
    evs = session.exec(select(Event.id).where(Event.first_at >= since, Event.n_groups >= 3)).all()
    firsts: Counter[str] = Counter()
    present_in: Counter[str] = Counter()
    if evs:
        arts = session.exec(
            select(Article.event_id, Article.group, Article.published_at).where(
                col(Article.event_id).in_(evs), canonical()
            )
        ).all()
        by_ev: dict[int, dict[str, datetime]] = defaultdict(dict)
        for e, g, t in arts:
            if g not in by_ev[e] or t < by_ev[e][g]:
                by_ev[e][g] = t
        for groups_t in by_ev.values():
            firsts[min(groups_t, key=groups_t.get)] += 1
            present_in.update(groups_t.keys())
    first_rows = [
        {
            "group": GROUPS[g][0],
            "first": firsts[g],
            "present": present_in[g],
            "rate": firsts[g] / present_in[g],
        }
        for g in sorted(present_in, key=lambda g: -firsts[g])
    ]
    return {
        "categories": CATEGORIES,
        "matrix": matrix,
        "small_groups": small,
        "blindspots": blindspots,
        "firsts": first_rows,
        "n_events_big": len(evs),
    }


# --- sources --------------------------------------------------------------------------------------------


def sources_status(session: Session) -> list[dict]:
    now = utcnow()
    counts_24h = dict(
        session.exec(
            select(Article.source_key, func.count())
            .where(Article.published_at >= now - timedelta(hours=24))
            .group_by(Article.source_key)
        ).all()
    )
    totals = dict(session.exec(select(Article.source_key, func.count()).group_by(Article.source_key)).all())
    enrich = defaultdict(Counter)
    for key, status, n in session.exec(
        select(Article.source_key, Article.enrich_status, func.count()).group_by(
            Article.source_key, Article.enrich_status
        )
    ).all():
        enrich[key][status] = n
    last_runs: dict[str, list[FetchRun]] = defaultdict(list)
    for r in session.exec(
        select(FetchRun)
        .where(FetchRun.started_at >= now - timedelta(hours=6))
        .order_by(FetchRun.started_at.desc())
    ).all():
        last_runs[r.source_key].append(r)
    out = []
    for s in SOURCES:
        runs = last_runs.get(s.key, [])
        latest_per_feed: dict[str, FetchRun] = {}
        for r in runs:
            latest_per_feed.setdefault(r.feed_url, r)
        failing = [r for r in latest_per_feed.values() if r.status != "ok"]
        out.append(
            {
                "source": s,
                "group": GROUPS[s.group][0],
                "slot": group_slot(s.group),
                "n_24h": counts_24h.get(s.key, 0),
                "n_total": totals.get(s.key, 0),
                "mode": "Texte complet" if s.fetch_pages else "Titre seulement",
                "kinds": sorted({f.kind for f in s.feeds}),
                "n_feeds": len(s.feeds),
                "last_run": runs[0].started_at if runs else None,
                "failing": failing,
                "enrich": dict(enrich.get(s.key, {})),
            }
        )
    return out


def stats(session: Session) -> dict:
    now = utcnow()
    return {
        "articles_24h": session.exec(
            select(func.count())
            .select_from(Article)
            .where(Article.published_at >= now - timedelta(hours=24), listed())
        ).one(),
        "articles": session.exec(select(func.count()).select_from(Article).where(listed())).one(),
        "sujets_24h": session.exec(
            select(func.count()).select_from(Sujet).where(Sujet.last_at >= now - timedelta(hours=24))
        ).one(),
        "pending": session.exec(
            select(func.count()).select_from(Article).where(Article.processed == False)
        ).one(),
        "first_day": session.exec(select(func.min(Article.fetched_at))).one(),
    }


def search(session: Session, q: str, limit: int = 80) -> list[dict]:
    like = f"%{q}%"
    arts = session.exec(
        select(Article)
        .where(Article.title.like(like) | Article.summary.like(like), listed())  # type: ignore[union-attr]
        .order_by(Article.published_at.desc())
        .limit(limit)
    ).all()
    sujet_of = dict(
        session.exec(
            select(Event.id, Event.sujet_id).where(
                col(Event.id).in_([a.event_id for a in arts if a.event_id])
            )
        ).all()
    )
    cps = copies(session, [a.id for a in arts])
    alr = also_run_by(session, [a.id for a in arts])
    return [
        {"article": a, "sujet_id": sujet_of.get(a.event_id), "slot": group_slot(a.group),
         "outlet": outlet(a.source_key, a.group, cps.get(a.id), alr.get(a.id))}
        for a in arts
    ]  # fmt: skip
