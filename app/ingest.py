"""Collection: discover new articles for a source, then enrich pending ones with their page text."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlmodel import Session, select

from app.db import engine
from app.fetch.discover import Candidate, discover
from app.fetch.enrich import fetch_page
from app.fetch.http import Blocked
from app.models import Article, FetchRun, utcnow
from app.nlp.categories import categorize, section_from_url
from app.nlp.text import detect_opinion, detect_wire, normalize
from app.sources import BY_KEY, Feed, Source

log = logging.getLogger(__name__)

MAX_AGE = timedelta(days=4)  # ignore older entries (98.5's sitemap goes back ~10 days)


def run_source(key: str, kinds: tuple[str, ...] = ("rss", "sitemap", "gnews")) -> int:
    source = BY_KEY[key]
    total_new = 0
    for feed in source.feeds:
        if feed.kind in kinds:
            total_new += _run_feed(source, feed)
    return total_new


def _run_feed(source: Source, feed: Feed) -> int:
    run = FetchRun(source_key=source.key, feed_url=feed.url)
    t0 = time.monotonic()
    try:
        found = discover(source, feed)
        run.n_found = len(found)
        run.n_new = store(source, found)
    except Blocked as e:
        run.status, run.error = "blocked", str(e)
    except Exception as e:  # one broken feed must not stop the others
        log.exception("%s: feed %s failed", source.key, feed.url)
        run.status, run.error = "error", f"{type(e).__name__}: {e}"[:500]
    run.duration_s = round(time.monotonic() - t0, 2)
    n_new = run.n_new
    with Session(engine) as session:
        session.add(run)
        session.commit()
    if n_new:
        log.info("%s: %d new (%s)", source.key, n_new, feed.kind)
    return n_new


def store(source: Source, found: list[Candidate]) -> int:
    cutoff = utcnow() - MAX_AGE
    new = 0
    with Session(engine) as session:
        for c in found:
            if c.published_at < cutoff:
                continue
            existing = session.exec(select(Article).where(Article.url == c.url)).first()
            if existing is None:
                # the same piece under another URL (Google News links, URL with/without slug)
                existing = session.exec(
                    select(Article).where(
                        Article.source_key == source.key,
                        Article.title_norm == normalize(c.title),
                        Article.published_at >= c.published_at - timedelta(days=2),
                    )
                ).first()
            if existing:
                _merge(existing, c)
                session.add(existing)
                continue
            session.add(_new_article(source, c))
            new += 1
        session.commit()
    return new


def _new_article(source: Source, c: Candidate) -> Article:
    section = ", ".join(c.tags) or (None if source.feeds[0].kind == "gnews" else section_from_url(c.url))
    category, conf = categorize(c.url, c.title, section, c.tags)
    return Article(
        source_key=source.key,
        group=source.group,
        url=c.url,
        title=c.title,
        title_norm=normalize(c.title),
        summary=c.summary,
        author=c.author,
        section=section,
        category=category,
        category_conf=conf,
        lang=source.lang,
        published_at=c.published_at,
        featured=c.featured,
        image_url=c.image,
        headline_only=not source.fetch_pages,
        enrich_status="pending" if source.fetch_pages else "skipped",
        wire=detect_wire(c.author, c.summary),
        opinion=detect_opinion(c.url, section, c.tags),
    )


def _merge(a: Article, c: Candidate) -> None:
    """A second feed saw the same article: keep the richest data."""
    a.featured = a.featured or c.featured
    a.image_url = a.image_url or c.image
    if c.summary and len(c.summary) > len(a.summary):
        a.summary = c.summary
    if c.author and not a.author:
        a.author = c.author
        a.wire = a.wire or detect_wire(c.author, None)
    if c.tags and not detect_opinion(a.url, a.section) and detect_opinion(a.url, None, c.tags):
        a.opinion = True


def byline_section(section: str | None, author: str | None) -> tuple[str | None, str | None]:
    """Radio-Canada signs desk pieces "Zone International" / "Zone Sports; Name": that is the section."""
    if not author or not author.startswith("Zone "):
        return section, author
    desk, _, person = author.partition(";")
    return desk.removeprefix("Zone ").strip(), person.strip() or None


def enrich_pending(limit: int, workers: int = 6) -> int:
    """Fetch page text for pending articles, newest first. Several hosts in parallel; the HTTP client keeps
    the per-host delay."""
    with Session(engine) as session:
        pending = session.exec(
            select(Article.id, Article.url)
            .where(Article.enrich_status == "pending", Article.published_at >= utcnow() - MAX_AGE)
            .order_by(Article.published_at.desc())
            .limit(limit)
        ).all()
    with ThreadPoolExecutor(workers, thread_name_prefix="enrich") as pool:
        list(pool.map(lambda row: _enrich_one(*row), pending))
    return len(pending)


def _enrich_one(article_id: int, url: str) -> None:
    page = fetch_page(url)
    with Session(engine) as session:
        a = session.get(Article, article_id)
        a.enrich_status = page.status
        if page.status == "ok":
            a.text = page.text
            a.image_url = a.image_url or page.image
            a.author = a.author or page.author
            a.section, a.author = byline_section(a.section, a.author)
            if not a.summary or len(a.summary) < 60:
                a.summary = (page.description or (page.text or "")[:400])[:1000]
            if page.section and not a.section:
                a.section = page.section
            a.wire = a.wire or detect_wire(a.author, a.text)
            a.opinion = a.opinion or detect_opinion(a.url, page.section, page.tags)
            # page tags are often the whole site's keyword list: only the section is trusted
            a.category, a.category_conf = categorize(a.url, a.title, a.section)
        session.add(a)
        session.commit()


def backfill_images(limit: int) -> int:
    """Articles read before images were collected (or whose feed has none, like Le Devoir): take the page's
    og:image. Small batches, newest first, only where pages may be fetched."""
    from app.fetch.enrich import fetch_page

    with Session(engine) as session:
        rows = session.exec(
            select(Article.id, Article.url)
            .where(
                Article.enrich_status == "ok",
                Article.image_url == None,
                Article.published_at >= utcnow() - timedelta(days=3),
            )
            .order_by(Article.published_at.desc())
            .limit(limit)
        ).all()

    def one(article_id: int, url: str) -> None:
        page = fetch_page(url)
        with Session(engine) as session:
            a = session.get(Article, article_id)
            # "" marks "looked, none found" so the article is not fetched again
            a.image_url = page.image or ""
            session.add(a)
            session.commit()

    with ThreadPoolExecutor(6, thread_name_prefix="images") as pool:
        list(pool.map(lambda row: one(*row), rows))
    return len(rows)
