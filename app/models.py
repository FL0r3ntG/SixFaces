"""Three levels: Article (one outlet's piece) -> Event (one development, all outlets) -> Sujet (a story over days).

All datetimes are timezone-aware UTC.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Article(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_key: str = Field(index=True)
    group: str = Field(index=True)
    url: str = Field(unique=True)
    title: str
    title_norm: str = Field(index=True)  # for duplicate detection within a source
    summary: str = ""
    text: str | None = None
    author: str | None = None
    image_url: str | None = None  # the outlet's lead photo (hotlinked, never stored)
    section: str | None = None  # outlet's own section (from URL / feed tags)
    category: str | None = Field(default=None, index=True)
    category_conf: float = 0.0  # see app.nlp.categories
    lang: str = "fr"
    published_at: datetime = Field(index=True)
    fetched_at: datetime = Field(default_factory=utcnow)
    featured: bool = False  # seen in a front-page / "à la une" feed
    headline_only: bool = False  # no article text available (blocked pages)
    # pending -> ok | blocked | skipped | error
    enrich_status: str = Field(default="pending", index=True)
    wire: str | None = None  # "PC", "AFP", "Reuters", "AP" when the piece is agency copy
    opinion: bool = False
    embedding: bytes | None = None
    event_id: int | None = Field(default=None, index=True, foreign_key="event.id")
    # Same piece on another site of the same owner (JdM -> JdQ, TVA; Le Soleil -> 5 CN2i papers): points to the
    # first one. Copies stay in their event for the record but are left out of every count and list.
    dup_of: int | None = Field(default=None, index=True)
    # Same piece run by ANOTHER owner (agency copy: La Presse Canadienne in Noovo and L'actualité): points to
    # the first one. Shown once in every list and counted once as an article, but each owner still gets
    # credit for covering the story (it chose to run it); never an independent confirmation (app.verify).
    same_as: int | None = Field(default=None, index=True)
    processed: bool = Field(default=False, index=True)


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = ""
    rep_article_id: int | None = None
    category: str | None = Field(default=None, index=True)
    first_at: datetime = Field(index=True)
    last_at: datetime = Field(index=True)
    n_articles: int = 0
    n_sources: int = 0
    n_groups: int = 0
    score: float = Field(default=0.0, index=True)
    centroid: bytes | None = None
    keywords: str = "[]"  # json list of the event's dominant terms
    verification: str = "{}"  # json, see app.verify
    sujet_id: int | None = Field(default=None, index=True, foreign_key="sujet.id")
    # The earlier development this one was chained to (its closest predecessor in the story). A story is a chain:
    # the first and last developments may share little, each link shares a lot.
    follows_id: int | None = Field(default=None, index=True)
    follows_p: float | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class Sujet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = ""
    category: str | None = Field(default=None, index=True)
    first_at: datetime = Field(index=True)
    last_at: datetime = Field(index=True)
    n_events: int = 0
    n_articles: int = 0
    n_sources: int = 0
    n_groups: int = 0
    groups: str = "{}"  # json {group: article count}
    score: float = Field(default=0.0, index=True)
    centroid: bytes | None = None
    keywords: str = "[]"
    updated_at: datetime = Field(default_factory=utcnow)


class FetchRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source_key: str = Field(index=True)
    feed_url: str
    started_at: datetime = Field(default_factory=utcnow, index=True)
    duration_s: float = 0.0
    status: str = "ok"  # ok | error | blocked
    n_found: int = 0
    n_new: int = 0
    error: str | None = None
