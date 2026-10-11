"""Every outlet we follow, how we discover its articles, and who owns it.

Ownership groups matter: Le Journal de Montréal, Le Journal de Québec and TVA share a newsroom pool (Québecor),
and the six CN2i papers share content. Corroboration counts *groups*, not sites.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Feed:
    kind: str  # "rss" | "sitemap" | "gnews"
    url: str  # for gnews: the search query
    featured: bool = False  # front page / "à la une": editorial importance signal
    section: str | None = None  # the feed is one section of the outlet ("sports", "politique"...)


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    group: str
    lang: str
    feeds: tuple[Feed, ...]
    # False when article pages are behind bot protection (we keep the headline + feed summary only)
    fetch_pages: bool = True
    url_include: tuple[str, ...] = ()  # keep only URLs containing one of these
    url_exclude: tuple[str, ...] = ()


GROUPS: dict[str, tuple[str, str]] = {
    # key: (label, brand colour). Brand families from the outlets themselves (site CSS / icons, 2026-10-11) and
    # the user's reading of them; groups sharing a family get distinct shades (3 reds, 3 blues) so charts stay
    # readable. Rendered through the --sN tokens in app.css (views.CHART_GROUPS gives the slot).
    "cbcrc": ("CBC/Radio-Canada", "#e3000f"),  # Radio-Canada red
    "quebecor": ("Québecor", "#008bc0"),  # Québecor / TVA blue
    "lapresse": ("La Presse", "#9b1c31"),  # La Presse red, deep shade
    "bell": ("Bell Média", "#1838c8"),  # Noovo blue
    "cn2i": ("CN2i (Coops de l'information)", "#e8604d"),  # Le Soleil red #d51d2c, coral shade
    "devoir": ("Le Devoir", "#6e6e6e"),  # grey
    "postmedia": ("Postmedia", "#0b2a5b"),  # Gazette navy
    "metro": ("Métro Média", "#2e6b5f"),  # Métro green
    "cogeco": ("Cogeco Média", "#aaa192"),  # no distinct brand colour: "Autres"
    "pivot": ("Pivot", "#aaa192"),
    "mishmash": ("Mishmash Média", "#aaa192"),
}

ARC_NEWS = "/arc/outboundfeeds/sitemap-news?outputType=xml"
CN2I_EXCLUDE = (
    "/communiques-de-presse/",
    "/partenaires/",
    "/contenu-commandite/",
    "/avis-publics/",
    "/jeux/",
    "/passe-temps/",
    "/la-vitrine/",
    "/necrologie/",
)


def _cn2i(key: str, name: str, host: str) -> Source:
    return Source(
        key, name, "cn2i", "fr",
        (Feed("sitemap", f"https://{host}{ARC_NEWS}"), Feed("rss", f"https://{host}/arc/outboundfeeds/rss/")),
        url_exclude=CN2I_EXCLUDE,
    )  # fmt: skip


def _rc(feed_id: int, section: str | None = None, featured: bool = False) -> Feed:
    return Feed("rss", f"https://ici.radio-canada.ca/rss/{feed_id}", featured, section)


def _devoir(section: str) -> Feed:
    return Feed(
        "rss", f"https://www.ledevoir.com/rss/section/{section}.xml", section=section.replace("/", " ")
    )


def _gnews(site: str) -> Feed:
    return Feed("gnews", f"site:{site} when:1d")


QUEBECOR_EXCLUDE = ("/guide-achat/", "/videos/", "/video/", "/zone-video/", "/concours/", "avis-legaux")

SOURCES: tuple[Source, ...] = (
    Source(
        "jdm", "Le Journal de Montréal", "quebecor", "fr",
        (Feed("sitemap", "https://www.journaldemontreal.com/news.xml"),
         Feed("rss", "https://www.journaldemontreal.com/rss.xml", featured=True),
         Feed("rss", "https://www.journaldemontreal.com/actualite/rss.xml"),
         Feed("rss", "https://www.journaldemontreal.com/actualite/politique/rss.xml")),
        fetch_pages=False, url_exclude=QUEBECOR_EXCLUDE,
    ),
    Source(
        "jdq", "Le Journal de Québec", "quebecor", "fr",
        (Feed("sitemap", "https://www.journaldequebec.com/news.xml"),
         Feed("rss", "https://www.journaldequebec.com/rss.xml", featured=True)),
        fetch_pages=False, url_exclude=QUEBECOR_EXCLUDE,
    ),
    Source(
        "tva", "TVA Nouvelles", "quebecor", "fr",
        (Feed("sitemap", "https://www.tvanouvelles.ca/news.xml"),
         Feed("rss", "https://www.tvanouvelles.ca/rss.xml", featured=True)),
        fetch_pages=False, url_exclude=QUEBECOR_EXCLUDE,
    ),
    Source(
        "lapresse", "La Presse", "lapresse", "fr",
        # lapresse.ca is behind an AWS WAF captcha (site and La Presse+): headlines via Google News only.
        # One query per section because a Google News feed stops at 100 items.
        tuple(_gnews(f"lapresse.ca/{s}") for s in
              ("actualites/politique", "actualites/justice-et-faits-divers", "actualites/sante",
               "actualites/education", "actualites/environnement", "actualites/grand-montreal",
               "actualites/regional", "actualites/national", "actualites", "affaires", "international",
               "sports", "arts", "societe", "debats", "contexte", "maison", "voyage", "gourmand"))
        + (_gnews("lapresse.ca"),),
        fetch_pages=False,
    ),
    Source(
        "devoir", "Le Devoir", "devoir", "fr",
        (Feed("rss", "https://www.ledevoir.com/rss/manchettes.xml", featured=True),
         _devoir("politique/quebec"), _devoir("politique/canada"), _devoir("actualites"), _devoir("economie"),
         _devoir("monde"), _devoir("culture"), _devoir("opinion"), _devoir("sports")),
    ),
    _cn2i("soleil", "Le Soleil", "www.lesoleil.com"),
    _cn2i("droit", "Le Droit", "www.ledroit.com"),
    _cn2i("tribune", "La Tribune", "www.latribune.ca"),
    _cn2i("nouvelliste", "Le Nouvelliste", "www.lenouvelliste.ca"),
    _cn2i("quotidien", "Le Quotidien", "www.lequotidien.com"),
    _cn2i("voixdelest", "La Voix de l'Est", "www.lavoixdelest.ca"),
    Source(
        "rc", "Radio-Canada", "cbcrc", "fr",
        (_rc(4159, featured=True), _rc(4163, featured=True), _rc(1000524), _rc(4175, "politique"),
         _rc(5717, "economie"), _rc(4171, "sante"), _rc(4165, "science"), _rc(4167, "arts"), _rc(4169, "techno"),
         _rc(771, "sports"), _rc(6102)),
        url_exclude=("/ohdio/", "/tele/", "/mordu/"),
    ),
    Source(
        "cbc", "CBC Montreal", "cbcrc", "en",
        (Feed("rss", "https://www.cbc.ca/webfeed/rss/rss-canada-montreal"),),
        url_exclude=("/player/",),
    ),
    Source(
        "gazette", "Montreal Gazette", "postmedia", "en",
        # robots.txt forbids the RSS feed but allows the news sitemap
        (Feed("sitemap", "https://montrealgazette.com/news-sitemap.xml"),),
        url_exclude=("/sponsored/", "/shopping-essentials/", "/feature/"),
    ),
    Source(
        "ctv", "CTV Montréal", "bell", "en",
        (Feed("sitemap", "https://www.ctvnews.ca/arc/outboundfeeds/sitemap-news/latest/"),),
        url_include=("/montreal/",),
    ),
    Source(
        "noovo", "Noovo Info", "bell", "fr",
        (Feed("sitemap", "https://www.noovo.info/arc/outboundfeeds/sitemap-news/latest/"),),
    ),
    Source(
        "985", "98.5 Montréal", "cogeco", "fr",
        (Feed("sitemap", "https://www.985fm.ca/news_sitemap.xml"),),
        url_exclude=("/audio/", "/balados/"),
    ),
    Source("metro", "Métro", "metro", "fr", (Feed("rss", "https://journalmetro.com/feed/"),)),
    Source("pivot", "Pivot", "pivot", "fr", (Feed("rss", "https://pivot.quebec/feed/"),)),
    Source(
        "lactualite", "L'actualité", "mishmash", "fr",
        (_gnews("lactualite.com"),),  # Cloudflare challenge on every page: headlines via Google News only
        fetch_pages=False,
    ),
)  # fmt: skip

BY_KEY: dict[str, Source] = {s.key: s for s in SOURCES}


def group_label(group: str) -> str:
    return GROUPS[group][0]


def group_color(group: str) -> str:
    return GROUPS[group][1]
