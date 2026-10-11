"""Importance score of events and sujets ("À la une" order).

An event matters when many *independent* newsrooms cover it, recently, and put it on their front page:

    event = Σ over ownership groups g of   freshness(g) × weight(g) × (1 + 0.15·ln(articles of g))

    freshness(g) = 0.5 ** (hours since g's latest article / HALF_LIFE_H)
    weight(g)    = 1, ×0.5 if all of g's articles are opinion, ×0.6 if only agency copy, +0.5 if featured

Ten Québecor sites running the same piece count once; a story covered by Québecor, La Presse, Le Devoir,
Radio-Canada and CN2i scores ~5. A sujet scores its best event plus a share of its other recent events
(momentum), and sports/culture are damped on the front page (they have their own tabs).
"""

import json
import math
from collections import defaultdict
from datetime import timedelta

from sqlmodel import Session, col, select

from app.db import engine
from app.models import Article, Event, Sujet, utcnow

HALF_LIFE_H = 18.0
MOMENTUM = 0.3
FRONT_PAGE_DAMPING = {"sports": 0.55, "culture": 0.6}
RANK_DAYS = 10  # older events/sujets keep their last score


def freshness(hours: float) -> float:
    return 0.5 ** (max(hours, 0.0) / HALF_LIFE_H)


def event_score(arts: list[Article], now) -> float:
    by_group: dict[str, list[Article]] = defaultdict(list)
    for a in arts:
        by_group[a.group].append(a)
    total = 0.0
    for group_arts in by_group.values():
        newest = max(a.published_at for a in group_arts)
        w = 1.0
        if all(a.opinion for a in group_arts):
            w *= 0.5
        if all(a.wire for a in group_arts):
            w *= 0.6
        if any(a.featured for a in group_arts):
            w += 0.5
        hours = (now - newest).total_seconds() / 3600
        total += freshness(hours) * w * (1 + 0.15 * math.log(len(group_arts)))
    return round(total, 4)


def rank_all() -> int:
    now = utcnow()
    since = now - timedelta(days=RANK_DAYS)
    with Session(engine) as session:
        events = session.exec(select(Event).where(Event.last_at >= since)).all()
        arts_by_event: dict[int, list[Article]] = defaultdict(list)
        canonical = select(Article).where(
            col(Article.event_id).in_([e.id for e in events]),
            Article.dup_of == None,
        )
        for a in session.exec(canonical).all():
            arts_by_event[a.event_id].append(a)
        by_sujet: dict[int, list[Event]] = defaultdict(list)
        for ev in events:
            ev.score = event_score(arts_by_event[ev.id], now)
            session.add(ev)
            if ev.sujet_id:
                by_sujet[ev.sujet_id].append(ev)
        for sujet_id, evs in by_sujet.items():
            sujet = session.get(Sujet, sujet_id)
            if sujet is None:
                continue
            evs.sort(key=lambda e: -e.score)
            raw = evs[0].score + MOMENTUM * sum(e.score for e in evs[1:])
            sujet.score = round(raw * FRONT_PAGE_DAMPING.get(sujet.category or "", 1.0), 4)
            # the sujet's headline is that of its most important development right now
            sujet.title = evs[0].title
            session.add(sujet)
        session.commit()
    return len(events)


def verification_of(ev: Event) -> dict:
    return json.loads(ev.verification or "{}")
