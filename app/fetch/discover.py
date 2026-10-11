"""Find new article URLs + headlines from RSS feeds, Google News sitemaps and Google News search feeds."""

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser
from lxml import etree

from app.fetch.http import client
from app.nlp.text import clean, clean_title
from app.sources import Feed, Source


@dataclass
class Candidate:
    url: str
    title: str
    published_at: datetime  # UTC
    summary: str = ""
    author: str | None = None
    tags: list[str] = field(default_factory=list)
    featured: bool = False
    image: str | None = None


def _utc(dt_struct) -> datetime | None:
    if not dt_struct:
        return None
    return datetime.fromtimestamp(calendar.timegm(dt_struct), tz=UTC)


def _iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:  # news sitemaps without offset: assume Quebec time
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo("America/Toronto"))
    return dt.astimezone(UTC)


_IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.IGNORECASE)


def _rss_image(e) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for m in e.get(key) or []:
            if m.get("url") and m.get("medium", "image") == "image":
                return m["url"]
    for link in e.get("links", []):
        if link.get("type", "").startswith("image/") and link.get("href"):
            return link["href"]
    m = _IMG_SRC.search(e.get("summary") or "")
    return m.group(1) if m else None


def parse_rss(content: bytes, featured: bool = False) -> list[Candidate]:
    out = []
    for e in feedparser.parse(content).entries:
        link, title = e.get("link"), clean(e.get("title"))
        when = _utc(e.get("published_parsed") or e.get("updated_parsed"))
        if not link or not title or not when:
            continue
        out.append(
            Candidate(
                url=link.split("?cmp=")[0],
                title=clean_title(title),
                published_at=when,
                summary=clean(e.get("summary"))[:1000],
                author=clean(e.get("author")) or None,
                tags=[t.term for t in e.get("tags", []) if t.get("term")],
                featured=featured,
                image=_secure(_rss_image(e)),
            )
        )
    return out


def _child(el, name: str):
    """Namespace-agnostic child lookup: outlets use both http:// and https:// sitemap namespaces."""
    for c in el:
        if isinstance(c.tag, str) and etree.QName(c).localname == name:
            return c
    return None


def _text(el, *path: str) -> str | None:
    for name in path:
        if el is None:
            return None
        el = _child(el, name)
    return el.text if el is not None else None


def _secure(url: str | None) -> str | None:
    """Only https images (the page is served over http locally, but mixed content and odd schemes are noise)."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith("https://") else None


def parse_sitemap(content: bytes) -> list[Candidate]:
    root = etree.fromstring(content, parser=etree.XMLParser(recover=True, resolve_entities=False))
    out = []
    for url in root:
        if not isinstance(url.tag, str) or etree.QName(url).localname != "url":
            continue
        loc = _text(url, "loc")
        title = _text(url, "news", "title")
        when = _iso(_text(url, "news", "publication_date"))
        keywords = _text(url, "news", "keywords") or ""
        image = _text(url, "image", "loc")
        if loc and title and when:
            out.append(
                Candidate(
                    url=loc.strip(),
                    title=clean_title(title),
                    published_at=when,
                    tags=[k.strip() for k in keywords.split(",") if k.strip()][:5],
                    image=_secure(image),
                )
            )
    return out


def parse_gnews(content: bytes, outlet_names: tuple[str, ...], section: str | None = None) -> list[Candidate]:
    """Google News RSS: the link is a Google redirect and the title ends with ' - <outlet>'."""
    out = []
    for c in parse_rss(content):
        c.title = clean_title(c.title, outlet_names).strip(" -–|")
        c.summary = ""  # Google's summary is just the headline again
        c.tags = [section] if section else []
        if len(c.title) >= 15 and c.title not in outlet_names:  # empty items come back as just " - Outlet"
            out.append(c)
    return out


def gnews_url(query: str) -> str:
    from urllib.parse import urlencode

    return "https://news.google.com/rss/search?" + urlencode(
        {"q": query, "hl": "fr-CA", "gl": "CA", "ceid": "CA:fr"}
    )


GNEWS_NAMES = {"lapresse": ("La Presse", "La Presse+"), "lactualite": ("L’actualité", "L'actualité")}


def discover(source: Source, feed: Feed) -> list[Candidate]:
    c = client()
    if feed.kind == "gnews":
        # "site:lapresse.ca/sports when:1d" -> section "sports"
        site = feed.url.split()[0].removeprefix("site:")
        section = site.split("/", 1)[1].replace("/", " ").replace("-", " ") if "/" in site else None
        names = GNEWS_NAMES.get(source.key, (source.name,))
        found = parse_gnews(c.get(gnews_url(feed.url)).content, names, section)
    elif feed.kind == "sitemap":
        found = parse_sitemap(c.get(feed.url).content)
    else:
        found = parse_rss(c.get(feed.url).content, feed.featured)
        if feed.section:
            for x in found:
                x.tags = [feed.section, *x.tags]
    return [x for x in found if keep(source, x)]


# Not news: legal notices, horoscopes, lottery results, crosswords, obituaries
_JUNK_TITLE = re.compile(
    r"^(avis\b|avis légaux|horoscope|loteries?|résultats? (de|des) loterie|mots croisés|sudoku|nécrologie|"
    r"la semaine en photos|quiz\b)",
    re.IGNORECASE,
)


def keep(source: Source, c: Candidate) -> bool:
    return keep_url(source, c.url) and not _JUNK_TITLE.match(c.title)


def keep_url(source: Source, url: str) -> bool:
    if source.url_include and not any(p in url for p in source.url_include):
        return False
    return not any(p in url for p in source.url_exclude)
