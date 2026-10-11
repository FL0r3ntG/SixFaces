"""Group articles into events, and events into sujets (the timeline of a story).

Online and incremental, so event and sujet ids stay stable between runs:
1. each new article joins the event whose recent articles it matches best (see app.nlp.similarity), or
   starts a new one;
2. an event that keeps changing is re-linked to the sujet of the closest recent event, or starts a sujet.

Decisions use the pair probabilities of app.nlp.similarity (p_event, p_story), fitted on hand-labelled pairs;
a merge pass fuses events that turn out to be the same development (articles arriving in an unlucky order
would otherwise start a second event).
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import timedelta

import numpy as np
from sqlmodel import Session, col, select

from app.db import engine
from app.models import Article, Event, Sujet, utcnow
from app.nlp.categories import CONF_SECTION
from app.nlp.embed import embed, from_bytes, to_bytes
from app.nlp.similarity import (
    Idf,
    centroid,
    doc_text,
    lexical,
    merge_vectors,
    p_event,
    p_story,
    score,
    top_terms,
)
from app.nlp.text import same_headline

log = logging.getLogger(__name__)

EVENT_WINDOW = timedelta(hours=48)  # an article can join an event whose latest article is this recent
P_EVENT = 0.6  # best match in the event must reach this probability of "same development"
ANCHOR = 1.0  # weight of "hours since the event started" (see _Pool.best_event)
MERGE_ANCHOR = 0.0  # same for the merge pass (0: the join anchor and MAX_SPAN are enough, see README)
MAX_SPAN = timedelta(hours=24)  # one development spans at most this; later coverage is a new, chained one
P_EVENT_2ND = 0.3  # ...and the second best this, when the event has several articles (no one-link chains)
P_MERGE = 0.7  # two events are fused when their best cross pairs average this
SUJET_WINDOW = timedelta(days=7)  # a story continues as long as its developments are < 7 days apart
P_SUJET = 0.7  # same story: mean of the two best cross-event article pairs
# Sports: every Canadiens game looks like the last one; only coverage of the same game is chained.
RELINK_FOR = timedelta(hours=36)  # events younger than this can still move to another sujet
COPY_WINDOW = timedelta(hours=48)  # same owner, same piece on another of its sites
SAME_PIECE_WINDOW = timedelta(hours=36)  # another owner running the same (agency) piece
T_COPY = 0.96  # embedding cosine above which two same-owner headlines+ledes are the same piece
ENRICH_GRACE = timedelta(minutes=20)  # wait this long for the page text before clustering anyway
IDF_DAYS = 14
KNN_K = 7


def process() -> dict:
    """One clustering pass over the articles not processed yet."""
    now = utcnow()
    with Session(engine) as session:
        new = session.exec(
            select(Article)
            .where(
                Article.processed == False,
                (Article.enrich_status != "pending") | (Article.fetched_at < now - ENRICH_GRACE),
            )
            .order_by(Article.published_at)
        ).all()
        if not new:
            return {"articles": 0}

        _embed_missing(session, new)
        earliest = min(a.published_at for a in new)
        window = session.exec(
            select(Article).where(
                Article.event_id != None,
                Article.dup_of == None,
                Article.published_at >= earliest - EVENT_WINDOW,
            )
        ).all()
        idf = Idf(
            doc_text(t, s)
            for t, s in session.exec(
                select(Article.title, Article.summary).where(
                    Article.published_at >= now - timedelta(days=IDF_DAYS)
                )
            )
        )
        _knn_categories(session, new)

        pool = _Pool(window, idf)
        touched: set[int] = set()
        n_copies = n_same = 0
        for a in new:
            original = pool.copy_of(a)
            if original is not None:
                a.dup_of, a.event_id, a.processed = original.id, original.event_id, True
                session.add(a)
                touched.add(original.event_id)
                n_copies += 1
                continue
            original = pool.same_piece(a)
            if original is not None:
                a.same_as, a.event_id, a.processed = original.same_as or original.id, original.event_id, True
                session.add(a)
                pool.add(a)  # still counts for its owner's coverage
                touched.add(original.event_id)
                n_same += 1
                continue
            event_id = pool.best_event(a)
            if event_id is None:
                ev = Event(first_at=a.published_at, last_at=a.published_at)
                session.add(ev)
                session.flush()
                event_id = ev.id
            a.event_id = event_id
            a.processed = True
            session.add(a)
            pool.add(a)
            touched.add(event_id)
        session.flush()

        n_merged = 0
        for absorbed, kept in pool.merges(touched):
            for art in session.exec(select(Article).where(Article.event_id == absorbed)).all():
                art.event_id = kept
                session.add(art)
            touched.discard(absorbed)
            touched.add(kept)
            old_sujet = session.get(Event, absorbed).sujet_id
            session.delete(session.get(Event, absorbed))
            if old_sujet:
                session.flush()
                refresh_sujet(session, old_sujet)
            n_merged += 1
        session.flush()

        for event_id in touched:
            refresh_event(session, session.get(Event, event_id), idf)
        session.flush()
        n_sujets = link_sujets(session, touched, idf)
        session.commit()
    log.info(
        "clustered %d articles (%d same-owner copies, %d same piece from another owner) into %d events "
        "(%d merged), %d sujets touched",
        len(new), n_copies, n_same, len(touched), n_merged, n_sujets,
    )  # fmt: skip
    return {
        "articles": len(new),
        "copies": n_copies,
        "same_piece": n_same,
        "events": len(touched),
        "merged": n_merged,
        "sujets": n_sujets,
    }


def _embed_missing(session: Session, articles: list[Article]) -> None:
    todo = [a for a in articles if a.embedding is None]
    for i in range(0, len(todo), 256):
        chunk = todo[i : i + 256]
        vecs = embed([doc_text(a.title, a.summary) for a in chunk])
        for a, v in zip(chunk, vecs, strict=True):
            a.embedding = to_bytes(v)
            session.add(a)


def _knn_categories(session: Session, articles: list[Article]) -> None:
    """Articles whose outlet gives no usable section (Québecor, Google News) get the category of their nearest
    neighbours among articles that do: a classifier without training or LLM."""
    unsure = [a for a in articles if a.category_conf < CONF_SECTION]
    if not unsure:
        return
    seeds = session.exec(
        select(Article.embedding, Article.category).where(
            Article.category_conf >= CONF_SECTION,
            Article.wire == None,
            Article.embedding != None,
            Article.published_at >= utcnow() - timedelta(days=30),
        )
    ).all()
    if len(seeds) < KNN_K * 3:
        return
    m = np.stack([from_bytes(e) for e, _ in seeds])
    cats = [c for _, c in seeds]
    for a in unsure:
        sims = m @ from_bytes(a.embedding)
        idx = np.argpartition(-sims, KNN_K)[:KNN_K]
        votes: Counter[str] = Counter()
        for i in idx:
            if sims[i] > 0.45:
                votes[cats[i]] += float(sims[i])
        if a.category_conf > 0:  # the headline-keyword guess counts as one strong vote
            votes[a.category] += 0.8
        if votes:
            a.category = votes.most_common(1)[0][0]
            session.add(a)


class _Pool:
    """Recent clustered articles, held in memory for one pass."""

    def __init__(self, articles: list[Article], idf: Idf) -> None:
        self.idf = idf
        self.arts: list[Article] = []
        self.by_title: dict[tuple[str, str], list[int]] = {}
        self.ids: list[int] = []
        self.events: list[int] = []
        self.times = []
        self.vecs: list[dict[str, float]] = []
        self.embs: list[np.ndarray] = []
        for a in articles:
            self.add(a)

    def add(self, a: Article) -> None:
        self.arts.append(a)
        self.by_title.setdefault((a.group, a.title_norm), []).append(len(self.ids))
        self.ids.append(a.id)
        self.events.append(a.event_id)
        self.times.append(a.published_at)
        self.vecs.append(self.idf.vector(doc_text(a.title, a.summary)))
        self.embs.append(from_bytes(a.embedding))
        self._m = None

    def copy_of(self, a: Article) -> Article | None:
        """The original if `a` is the same piece republished on another site of the same owner."""
        for i in self.by_title.get((a.group, a.title_norm), []):
            if abs(self.times[i] - a.published_at) <= COPY_WINDOW:
                return self.arts[i]
        if not self.ids:
            return None
        if self._m is None:
            self._m = np.stack(self.embs)
        cos = self._m @ from_bytes(a.embedding)
        for i in np.argsort(-cos)[:5]:
            if cos[i] < T_COPY:
                break
            o = self.arts[i]
            if (
                o.group == a.group
                and o.source_key != a.source_key
                and abs(o.published_at - a.published_at) <= COPY_WINDOW
            ):
                return o
        return None

    def same_piece(self, a: Article) -> Article | None:
        """The first article if `a` is the same piece already run by another owner (agency copy)."""
        if not self.ids:
            return None
        cos = self._matrix() @ from_bytes(a.embedding)
        for i in np.argsort(-cos)[:8]:
            if cos[i] < 0.8:
                break
            o = self.arts[i]
            if o.group == a.group or abs(o.published_at - a.published_at) > SAME_PIECE_WINDOW:
                continue
            if same_headline(o.title, a.title):
                return o
        return None

    def _matrix(self) -> np.ndarray:
        if self._m is None:
            self._m = np.stack(self.embs)
        return self._m

    def _event_starts(self) -> dict[int, object]:
        start: dict[int, object] = {}
        for ev, t in zip(self.events, self.times, strict=True):
            if ev not in start or t < start[ev]:
                start[ev] = t
        return start

    def best_event(self, a: Article) -> int | None:
        if not self.ids:
            return None
        cos = self._matrix() @ from_bytes(a.embedding)
        v = self.idf.vector(doc_text(a.title, a.summary))
        start = self._event_starts()
        per_event: dict[int, list[float]] = defaultdict(list)
        for i in np.nonzero(cos > 0.45)[0]:
            hours = abs((self.times[i] - a.published_at).total_seconds()) / 3600
            if hours > EVENT_WINDOW.total_seconds() / 3600:
                continue
            # time is measured from the event's start, not from its closest article: within one development
            # coverage must not drift article by article (that chaining is for stories, see _StoryPool)
            ev = self.events[i]
            if a.published_at - start[ev] > MAX_SPAN:
                continue
            anchored = max(hours, ANCHOR * abs((a.published_at - start[ev]).total_seconds()) / 3600)
            per_event[ev].append(p_event(float(cos[i]), lexical(v, self.vecs[i]), anchored))
        best, best_p = None, 0.0
        for event_id, ps in per_event.items():
            ps.sort(reverse=True)
            if ps[0] < P_EVENT or (len(ps) > 1 and ps[1] < P_EVENT_2ND):
                continue
            p = ps[0] if len(ps) == 1 else (ps[0] + ps[1]) / 2
            if p > best_p:
                best, best_p = event_id, p
        return best

    def merges(self, event_ids: set[int]) -> list[tuple[int, int]]:
        """(absorbed, kept) pairs of events that are the same development: the mean of their three best
        cross pairs reaches P_MERGE. The older event is kept, so its id (and links to it) survive."""
        members: dict[int, list[int]] = defaultdict(list)
        for i, ev in enumerate(self.events):
            members[ev].append(i)
        m = self._matrix()
        start = self._event_starts()
        out, gone = [], set()
        for ev in sorted(event_ids):
            if ev in gone or ev not in members:
                continue
            idx = members[ev]
            cos = m[idx] @ m.T  # (members, pool)
            cands: dict[int, list[float]] = defaultdict(list)
            for r, c in zip(*np.nonzero(cos > 0.5), strict=True):
                other = self.events[c]
                if other == ev or other in gone:
                    continue
                i, j = idx[r], int(c)
                hours = abs((self.times[i] - self.times[j]).total_seconds()) / 3600
                if hours > EVENT_WINDOW.total_seconds() / 3600:
                    continue
                if abs(start[ev] - start[other]) > MAX_SPAN:
                    continue
                # anchored like best_event: two developments that started a day apart are not one
                apart = MERGE_ANCHOR * abs((start[ev] - start[other]).total_seconds()) / 3600
                cands[other].append(
                    p_event(float(cos[r, c]), lexical(self.vecs[i], self.vecs[j]), max(hours, apart))
                )
            for other, ps in cands.items():
                ps.sort(reverse=True)
                if sum(ps[:3]) / min(3, len(ps)) >= P_MERGE and len(ps) >= min(
                    2, len(idx), len(members[other])
                ):
                    kept, absorbed = (
                        (other, ev)
                        if min(self.times[k] for k in members[other]) <= min(self.times[k] for k in idx)
                        else (ev, other)
                    )
                    out.append((absorbed, kept))
                    gone.add(absorbed)
                    for k in members.pop(absorbed, []):
                        self.events[k] = kept
                        members[kept].append(k)
                    if absorbed == ev:
                        break
        return out


def refresh_event(session: Session, ev: Event, idf: Idf) -> None:
    from app.verify import verify_event

    arts = session.exec(select(Article).where(Article.event_id == ev.id, Article.dup_of == None)).all()
    if not arts:
        session.delete(ev)
        return
    _reroot_shared(session, arts)
    embs = [from_bytes(a.embedding) for a in arts]
    vecs = [idf.vector(doc_text(a.title, a.summary)) for a in arts]
    ev.centroid = to_bytes(centroid(embs))
    ev.keywords = json.dumps(top_terms(merge_vectors(vecs)), ensure_ascii=False)
    ev.first_at = min(a.published_at for a in arts)
    ev.last_at = max(a.published_at for a in arts)
    ev.n_articles = sum(1 for a in arts if a.same_as is None)  # the same piece counts once
    ev.n_sources = len({a.source_key for a in arts})
    ev.n_groups = len({a.group for a in arts})
    ev.category = _vote_category(arts)
    listed = [i for i, a in enumerate(arts) if a.same_as is None]
    rep = representative([arts[i] for i in listed], [embs[i] for i in listed], [vecs[i] for i in listed])
    ev.rep_article_id, ev.title = rep.id, rep.title
    ev.verification = json.dumps(verify_event(arts), ensure_ascii=False)
    ev.updated_at = utcnow()
    session.add(ev)


def _reroot_shared(session: Session, arts: list[Article]) -> None:
    """Of a piece run by several owners, show the richest copy: full text and photo before a headline-only
    Google News item, then the earliest. The others point to it (same_as)."""
    families: dict[int, list[Article]] = defaultdict(list)
    by_id = {a.id: a for a in arts}
    for a in arts:
        root = a.same_as if a.same_as in by_id else a.id
        families[root].append(a)
    for root_id, fam in families.items():
        if len(fam) < 2:
            continue
        best = min(fam, key=lambda a: (a.headline_only, a.text is None, not a.image_url, a.published_at))
        if best.id == root_id and best.same_as is None:
            continue
        for a in fam:
            a.same_as = None if a.id == best.id else best.id
            session.add(a)


def _vote_category(arts: list[Article]) -> str:
    """One vote per ownership group (six CN2i sites filing the same wire under "affaires" count once).
    A group's vote is as strong as its best-labelled article; agency copy weighs less, since outlets file it
    in whatever section has room."""
    per_group: dict[str, Counter[str]] = defaultdict(Counter)
    strength: dict[str, float] = defaultdict(float)
    for a in arts:
        w = (0.1 + a.category_conf) * (0.4 if a.wire else 1.0)
        per_group[a.group][a.category or "societe"] += w
        strength[a.group] = max(strength[a.group], w)
    votes: Counter[str] = Counter()
    for group, counts in per_group.items():
        total = sum(counts.values())
        for cat, w in counts.items():
            votes[cat] += strength[group] * w / total
    return votes.most_common(1)[0][0]


_LIVE = re.compile(
    r"\b(première|deuxième|troisième) période\b|prolongation \||tirs de barrage \||en direct|clavardage|"
    r"liveblog|live blog|marque finale|\brelisez\b",
    re.IGNORECASE,
)


def representative(arts: list[Article], embs: list[np.ndarray], vecs: list[dict[str, float]]) -> Article:
    """The headline closest to all the others: the most "consensus" wording, not the most dramatic one.
    Opinion pieces and very short headlines are avoided when there is a choice."""
    if len(arts) == 1:
        return arts[0]
    m = np.stack(embs)
    cos = m @ m.T
    best, best_s = arts[0], -1.0
    for i, a in enumerate(arts):
        s = sum(score(float(cos[i, j]), lexical(vecs[i], vecs[j])) for j in range(len(arts)) if j != i)
        s /= len(arts) - 1
        if a.opinion:
            s -= 0.3
        if len(a.title) < 35:
            s -= 0.1
        if _LIVE.search(a.title):
            s -= 0.5  # "Première période | Red Wings 0 – Canadien 0", "Clavardage", "en direct"
        if a.lang != "fr":
            s -= 0.05  # French interface: prefer a French headline when it's a near tie
        if s > best_s:
            best, best_s = a, s
    return best


def link_sujets(session: Session, event_ids: set[int], idf: Idf) -> int:
    now = utcnow()
    recent = session.exec(
        select(Event).where(Event.last_at >= now - SUJET_WINDOW - EVENT_WINDOW, Event.centroid != None)
    ).all()
    by_id = {e.id: e for e in recent}
    story = _StoryPool(session, list(by_id), idf)
    touched_sujets: set[int] = set()
    for event_id in sorted(event_ids):
        ev = by_id.get(event_id)
        if ev is None or (ev.sujet_id is not None and now - ev.first_at > RELINK_FOR):
            if ev is not None and ev.sujet_id:
                touched_sujets.add(ev.sujet_id)
            continue
        target, follows, p = story.best_sujet(ev, by_id)
        ev.follows_id, ev.follows_p = follows, (round(p, 3) if follows else None)
        if target is None:
            if ev.sujet_id is not None and _sujet_size(session, ev.sujet_id) == 1:
                target = ev.sujet_id  # already alone in its own sujet
            else:
                s = Sujet(first_at=ev.first_at, last_at=ev.last_at)
                session.add(s)
                session.flush()
                target = s.id
        if ev.sujet_id is not None and ev.sujet_id != target:
            touched_sujets.add(ev.sujet_id)
        ev.sujet_id = target
        session.add(ev)
        touched_sujets.add(target)
    session.flush()
    for sujet_id in touched_sujets:
        refresh_sujet(session, sujet_id)
    return len(touched_sujets)


class _StoryPool:
    """Articles of the events of the last SUJET_WINDOW, to decide which story a development belongs to."""

    def __init__(self, session: Session, event_ids: list[int], idf: Idf) -> None:
        rows = session.exec(
            select(
                Article.event_id, Article.embedding, Article.title, Article.summary, Article.published_at
            ).where(col(Article.event_id).in_(event_ids), Article.dup_of == None)
        ).all()
        self.events = [r[0] for r in rows]
        self.times = [r[4] for r in rows]
        self.vecs = [idf.vector(doc_text(r[2], r[3])) for r in rows]
        self.m = np.stack([from_bytes(r[1]) for r in rows]) if rows else np.zeros((0, 1))
        self.members: dict[int, list[int]] = defaultdict(list)
        for i, ev in enumerate(self.events):
            self.members[ev].append(i)

    def best_sujet(self, ev: Event, by_id: dict[int, Event]) -> tuple[int | None, int | None, float]:
        """(sujet, the development it follows, link probability). Compared with every article of every
        development of the last SUJET_WINDOW, so a story can drift: each new development only has to be
        close to *some* recent development of the story, not to where it started."""
        idx = self.members.get(ev.id)
        if not idx:
            return None, None, 0.0
        sports = ev.category == "sports"
        cos = self.m[idx] @ self.m.T
        cands: dict[int, list[float]] = defaultdict(list)
        for r, c in zip(*np.nonzero(cos > 0.45), strict=True):
            other = by_id.get(self.events[c])
            if other is None or other.id == ev.id or other.sujet_id is None:
                continue
            if other.first_at > ev.first_at:
                continue  # a development follows from earlier ones, never from later ones
            i, j = idx[r], int(c)
            hours = abs((self.times[i] - self.times[j]).total_seconds()) / 3600
            if hours > SUJET_WINDOW.total_seconds() / 3600:
                continue
            lex = lexical(self.vecs[i], self.vecs[j])
            p = p_event(float(cos[r, c]), lex, hours) if sports else p_story(float(cos[r, c]), lex)
            cands[other.id].append(p)
        best, best_p = None, P_SUJET
        for other_id, ps in cands.items():
            ps.sort(reverse=True)
            p = ps[0] if len(ps) == 1 else (ps[0] + ps[1]) / 2
            if p >= best_p:
                best, best_p = other_id, p
        if best is None:
            return None, None, 0.0
        return by_id[best].sujet_id, best, best_p


def _sujet_size(session: Session, sujet_id: int) -> int:
    return len(session.exec(select(Event.id).where(Event.sujet_id == sujet_id)).all())


def refresh_sujet(session: Session, sujet_id: int) -> None:
    sujet = session.get(Sujet, sujet_id)
    events = session.exec(select(Event).where(Event.sujet_id == sujet_id)).all()
    if sujet is None:
        return
    if not events:
        session.delete(sujet)
        return
    arts = session.exec(
        select(Article.source_key, Article.group, Article.same_as).where(
            col(Article.event_id).in_([e.id for e in events]), Article.dup_of == None
        )
    ).all()
    sujet.first_at = min(e.first_at for e in events)
    sujet.last_at = max(e.last_at for e in events)
    sujet.n_events = len(events)
    sujet.n_articles = sum(1 for _, _, same in arts if same is None)
    sujet.n_sources = len({s for s, _, _ in arts})
    groups = Counter(g for _, g, _ in arts)
    sujet.n_groups = len(groups)
    sujet.groups = json.dumps(dict(groups))
    cats: Counter[str] = Counter()
    for e in events:
        cats[e.category or "societe"] += e.n_groups  # groups, not articles: syndicated copies count once
    sujet.category = cats.most_common(1)[0][0]
    sujet.centroid = to_bytes(centroid([from_bytes(e.centroid) for e in events if e.centroid]))
    kw: Counter[str] = Counter()
    for e in events:
        kw.update({k: e.n_articles for k in json.loads(e.keywords)})
    sujet.keywords = json.dumps([k for k, _ in kw.most_common(8)], ensure_ascii=False)
    sujet.updated_at = utcnow()
    session.add(sujet)
