"""Fetch an article page (when the outlet allows it) and extract text, byline, lede and section."""

import logging
from dataclasses import dataclass

import httpx
import trafilatura

from app.fetch.http import Blocked, client
from app.nlp.text import clean

log = logging.getLogger(__name__)


@dataclass
class Page:
    status: str  # ok | blocked | skipped | error
    text: str | None = None
    author: str | None = None
    description: str | None = None
    section: str | None = None
    tags: list[str] | None = None
    image: str | None = None


def fetch_page(url: str) -> Page:
    c = client()
    if not c.allowed(url):
        return Page("skipped")
    try:
        r = c.get(url)
    except Blocked:
        return Page("blocked")
    except httpx.HTTPError as e:
        log.info("page fetch failed: %s (%s)", url, e)
        return Page("error")
    return parse_page(r.text, url)


def parse_page(html: str, url: str) -> Page:
    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False, favor_precision=True
    )
    meta = trafilatura.extract_metadata(html, default_url=url)
    if not text:
        return Page("error")
    return Page(
        "ok",
        text=text[:20000],
        author=clean(meta.author) or None if meta else None,
        description=clean(meta.description) or None if meta else None,
        section=", ".join(c.strip("/") for c in (meta.categories or [])) or None if meta else None,
        tags=list(meta.tags or []) if meta else None,
        image=meta.image if meta and (meta.image or "").startswith("https://") else None,
    )
